"""
Generic Change Management capture / apply engine.

Registered against the "*" wildcard in hooks.py doc_events["*"]["before_save"],
so it runs on every doctype save and self-filters to only the doctypes listed
as enabled in Change Management Settings. Nothing here is specific to Quality
Procedure -- any doctype can be brought under control by ticking a row in
Change Management Settings, no code change required (per decision #1 / the
"common toggle" requirement).
"""

import json

import frappe
from frappe.desk.form.assign_to import add as add_assignment
from frappe.utils import get_url_to_form

# Doctypes that must never be captured, even if someone fat-fingers them into
# Change Management Settings -- capturing changes to the Change Management
# Request stack itself would recurse.
_EXEMPT_DOCTYPES = {
	"Change Management Request",
	"Change Management Request Detail",
	"Change Management Settings",
	"Change Management Controlled Doctype",
}

_IGNORE_FIELDTYPES = {
	"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading",
}


# ============================================================
# SETTINGS / AUTHORIZATION LOOKUPS
# ============================================================

def get_controlled_doctype_row(doctype):
	settings = frappe.get_single("Change Management Settings")
	for row in settings.controlled_doctypes:
		if row.doctype_name == doctype and row.enabled:
			return row
	return None


@frappe.whitelist()
def get_controlled_doctypes():
	"""Doctype names currently enabled in Change Management Settings.

	Used by the client-side justification popup to decide, without a
	hardcoded doctype list, whether a given form save needs to collect
	Purpose/Impact before the change control hook fires.
	"""
	settings = frappe.get_single("Change Management Settings")
	return [row.doctype_name for row in settings.controlled_doctypes if row.enabled]


def get_change_approver_role_profiles():
	"""Role Profiles flagged (Role Profile.change_management_approver) as
	eligible to approve/reject Change Management Requests. Global, not scoped by
	doctype or department -- the flag alone decides."""
	return frappe.get_all(
		"Role Profile",
		filters={"change_management_approver": 1},
		pluck="name",
	)


def is_change_management_approver(role_profile):
	if not role_profile:
		return False
	return bool(frappe.db.get_value("Role Profile", role_profile, "change_management_approver"))


def has_eligible_approver():
	role_profiles = get_change_approver_role_profiles()
	if not role_profiles:
		return False
	return bool(frappe.db.exists("User", {
		"role_profile_name": ["in", role_profiles],
		"enabled": 1,
	}))


def _resolve_department(doc):
	if doc.meta.has_field("department") and doc.get("department"):
		return doc.get("department")
	return frappe.db.get_value(
		"Employee", {"user_id": frappe.session.user, "status": "Active"}, "department"
	)


# ============================================================
# CAPTURE -- before_save hook entrypoint
# ============================================================

def capture_change(doc, method=None):
	if doc.flags.ignore_change_control:
		return
	if doc.doctype in _EXEMPT_DOCTYPES:
		return

	# Never intercept during bench-level bootstrapping -- doctypes (including
	# our own Change Management Settings) may not be synced into this site's
	# database yet mid-migrate/install/patch. This is exactly what broke a
	# fresh migrate: sync_all() writes a Default Value doc before it has
	# synced any doctype schemas, our wildcard hook fired on that write, and
	# frappe.get_single("Change Management Settings") blew up because the
	# DocType record for it didn't exist in the DB at that point.
	if (frappe.flags.in_migrate or frappe.flags.in_install
			or frappe.flags.in_patch or frappe.flags.in_setup_wizard):
		return
	if not frappe.db.exists("DocType", "Change Management Settings"):
		return

	controlled_row = get_controlled_doctype_row(doc.doctype)
	if not controlled_row:
		return

	department = _resolve_department(doc)

	# The client-side justification popup (public/js/nj_features.js) stashes
	# these as plain, non-meta keys on the submitted doc before save -- they
	# aren't real fields on the controlled doctype itself, only on Change
	# Management Request. A save that skips the popup (e.g. a raw API call)
	# is refused here rather than surfacing a confusing mandatory-field error
	# from the Change Management Request insert further down.
	purpose = (doc.get("purpose") or "").strip()
	impact = (doc.get("impact") or "").strip()
	if not purpose or not impact:
		frappe.throw(
			"Purpose and Impact are required before this change can be "
			"submitted for approval.",
			title="Justification Required",
		)

	# Open question #3 resolved as "block/warn": refuse to create a Change
	# Management Request that nothing can ever approve.
	if not has_eligible_approver():
		frappe.throw(
			f"No active approver is configured for {doc.doctype}"
			+ (f" in department {department}" if department else "")
			+ ". Ask an administrator to add an Approver Rule in Change "
			  "Management Settings before this change can be submitted."
		)

	if doc.is_new():
		# Open question #2 resolved as "new records need approval too".
		_capture_new_record(doc, department, purpose, impact, controlled_row)
		frappe.throw(
			f"This {doc.doctype} requires approval before it can be created. "
			"A Change Management Request has been raised for review and "
			"your entry was not saved directly.",
			title="Approval Required",
		)
	else:
		old_doc = frappe.get_doc(doc.doctype, doc.name)
		detail_rows = _build_update_details(old_doc, doc)
		if not detail_rows:
			return
		_create_change_request(
			doc, detail_rows, is_new_record=False, department=department,
			purpose=purpose, impact=impact, controlled_row=controlled_row,
		)
		_revert_to_old_values(doc, old_doc)
		frappe.msgprint(
			"Your changes have been submitted for approval and were not "
			"applied directly.",
			title="Pending Approval",
			indicator="orange",
		)


def _capture_new_record(doc, department, purpose, impact, controlled_row):
	detail_rows = _build_new_record_details(doc)
	cr = frappe.new_doc("Change Management Request")
	cr.reference_doctype = doc.doctype
	cr.reference_name = None
	cr.is_new_record = 1
	cr.change_summary = f"New {doc.doctype}"
	cr.purpose = purpose
	cr.impact = impact
	cr.status = "Pending Approval"
	cr.requested_by = frappe.session.user
	cr.department = department
	cr.assigned_to = controlled_row.assigned_to
	cr.pending_payload = frappe.as_json(doc.as_dict())
	for row in detail_rows:
		cr.append("change_detail", row)
	cr.insert(ignore_permissions=True)
	frappe.db.commit()
	_notify_on_creation(cr)
	return cr


def _create_change_request(doc, detail_rows, is_new_record, department, purpose, impact, controlled_row):
	cr = frappe.new_doc("Change Management Request")
	cr.reference_doctype = doc.doctype
	cr.reference_name = doc.name
	cr.is_new_record = 0
	cr.change_summary = f"Update to {doc.doctype} {doc.name}"
	cr.purpose = purpose
	cr.impact = impact
	cr.status = "Pending Approval"
	cr.requested_by = frappe.session.user
	cr.department = department
	cr.assigned_to = controlled_row.assigned_to
	for row in detail_rows:
		cr.append("change_detail", row)
	cr.insert(ignore_permissions=True)
	frappe.db.commit()
	_notify_on_creation(cr)
	return cr


# ============================================================
# NOTIFY -- requester confirmation + auto-assignee alert
# ============================================================

_PRIORITY_COLORS = {
	"Low": "#2e844a",
	"Medium": "#e9a23b",
	"High": "#d1403f",
}
_PRIORITY_DEFAULT_COLOR = "#6c7680"


def _notify_on_creation(cr):
	"""Fires once, right after a Change Management Request is first created.
	Each side effect is isolated in its own try/except -- a mail-server
	hiccup here must never surface as an unhandled exception, since
	_capture_new_record's caller throws deliberately right after this runs
	to block the original save, and that throw must not be replaced by an
	unrelated email failure."""
	try:
		_notify_requester(cr)
	except Exception:
		frappe.log_error(title="Change Management Request: requester email failed")

	if not cr.assigned_to:
		return

	try:
		add_assignment({
			"doctype": "Change Management Request",
			"name": cr.name,
			"assign_to": [cr.assigned_to],
			"description": cr.change_summary or cr.title,
		})
	except Exception:
		frappe.log_error(title="Change Management Request: auto-assignment failed")

	try:
		_notify_assignee(cr)
	except Exception:
		frappe.log_error(title="Change Management Request: assignee email failed")


def _default_outgoing_email():
	default_account = frappe.get_all(
		"Email Account", filters={"default_outgoing": 1}, fields=["email_id"], limit=1,
	)
	return default_account[0].email_id if default_account else None


def _requester_employee_id(cr):
	return frappe.db.get_value("Employee", {"user_id": cr.requested_by}, "emp_id")


def _priority_badge(priority):
	if not priority:
		return "—"
	color = _PRIORITY_COLORS.get(priority, _PRIORITY_DEFAULT_COLOR)
	return (
		f'<span style="background-color:{color}; color:#ffffff; padding:2px 10px; '
		f'border-radius:12px; font-size:12px; font-weight:600;">{priority}</span>'
	)


def _email_row(label, value):
	return f"""
		<tr style="border-top:1px solid #e9ecef;">
			<td style="padding:8px 12px 8px 0; color:#6c7680; white-space:nowrap; vertical-align:top;">{label}</td>
			<td style="padding:8px 0; color:#1f272e;">{value}</td>
		</tr>
	"""


def _change_detail_rows_html(cr):
	"""Field-by-field diff table for the CMR's change_detail child table.
	Values come straight from user-editable doctype fields (not app-controlled
	text like Purpose/Impact above), so every cell is escaped before going
	into the HTML email -- same frappe.utils.escape_html(...) pattern already
	used server-side in this app (see stock_movement.py)."""
	if not cr.change_detail:
		return ""

	esc = frappe.utils.escape_html
	body_rows = "".join([
		f"""
			<tr style="border-top:1px solid #e9ecef;">
				<td style="padding:6px 10px 6px 0; color:#1f272e;">{esc(row.field_label or row.fieldname or "")}</td>
				<td style="padding:6px 10px; color:#6c7680;">{esc(row.parent_row or "—")}</td>
				<td style="padding:6px 10px; color:#6c7680;">{esc(row.old_value or "")}</td>
				<td style="padding:6px 0; color:#1f272e;">{esc(row.new_value or "")}</td>
			</tr>
		"""
		for row in cr.change_detail
	])

	return f"""
		<p style="color:#1f272e; font-size:14px; font-weight:600; margin:20px 0 8px;">Change Detail</p>
		<table style="width:100%; border-collapse:collapse; font-size:12px;">
			<tr>
				<th style="text-align:left; padding:6px 10px 6px 0; color:#6c7680; border-bottom:1px solid #d1d8dd;">Field</th>
				<th style="text-align:left; padding:6px 10px; color:#6c7680; border-bottom:1px solid #d1d8dd;">Row</th>
				<th style="text-align:left; padding:6px 10px; color:#6c7680; border-bottom:1px solid #d1d8dd;">Old Value</th>
				<th style="text-align:left; padding:6px 0; color:#6c7680; border-bottom:1px solid #d1d8dd;">New Value</th>
			</tr>
			{body_rows}
		</table>
	"""


def _change_request_email_body(cr, heading, intro_html):
	rows = "".join([
		_email_row("Reference", f"{cr.reference_doctype} {cr.reference_name or '(new record)'}"),
		_email_row("Summary", cr.change_summary or ""),
		_email_row("Purpose", cr.purpose or ""),
		_email_row("Impact", cr.impact or ""),
		_email_row("Priority", _priority_badge(cr.priority)),
		_email_row("Department", cr.department or ""),
		_email_row("Start Date", frappe.utils.format_date(cr.start_date) if cr.start_date else ""),
		_email_row("End Date", frappe.utils.format_date(cr.end_date) if cr.end_date else ""),
		_email_row("Requested By", cr.requested_by),
		_email_row("Employee ID", _requester_employee_id(cr) or "—"),
		_email_row("Status", cr.status),
		_email_row("Approved By", cr.approved_by) if cr.approved_by else "",
		_email_row("Approved On", frappe.utils.format_datetime(cr.approved_on)) if cr.approved_on else "",
		_email_row("Rejected By", cr.rejected_by) if cr.rejected_by else "",
		_email_row("Rejected On", frappe.utils.format_datetime(cr.rejected_on)) if cr.rejected_on else "",
		_email_row("Rejection Reason", cr.rejection_reason) if cr.rejection_reason else "",
	])

	link = get_url_to_form("Change Management Request", cr.name)

	return f"""
		<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; max-width:600px; margin:0 auto;">
			<div style="background-color:#2490ef; padding:20px 24px; border-radius:6px 6px 0 0;">
				<span style="color:#ffffff; font-size:18px; font-weight:600;">{heading}</span>
			</div>
			<div style="background-color:#ffffff; border:1px solid #d1d8dd; border-top:none; padding:24px; border-radius:0 0 6px 6px;">
				<p style="color:#1f272e; font-size:14px; margin:0 0 16px;">
					{intro_html}
				</p>
				<table style="width:100%; border-collapse:collapse; font-size:13px;">
					{rows}
				</table>
				{_change_detail_rows_html(cr)}
				<div style="margin-top:24px; text-align:center;">
					<a href="{link}" style="background-color:#2490ef; color:#ffffff; text-decoration:none; padding:10px 24px; border-radius:4px; font-size:14px; font-weight:600; display:inline-block;">
						Open {cr.name}
					</a>
				</div>
			</div>
		</div>
	"""


def _notify_requester(cr):
	recipient = frappe.db.get_value("User", cr.requested_by, "email") or cr.requested_by
	message = _change_request_email_body(
		cr,
		heading="Change Management Request Submitted",
		intro_html=f"Your request <b>{cr.name}</b> has been submitted and is pending approval.",
	)
	frappe.sendmail(
		recipients=[recipient],
		sender=_default_outgoing_email(),
		subject=f"Change Management Request Submitted: {cr.title or cr.name}",
		message=message,
		now=True,
	)


def _notify_assignee(cr):
	recipient = frappe.db.get_value("User", cr.assigned_to, "email") or cr.assigned_to
	message = _change_request_email_body(
		cr,
		heading="Change Management Request Assigned",
		intro_html=f"You have been assigned <b>{cr.name}</b> for review.",
	)
	frappe.sendmail(
		recipients=[recipient],
		sender=_default_outgoing_email(),
		subject=f"Change Management Request Assigned: {cr.title or cr.name}",
		message=message,
		now=True,
	)


_DECISION_INTROS = {
	("Approved", "requester"): lambda cr: f"Your request <b>{cr.name}</b> has been approved by {cr.approved_by}.",
	("Approved", "actor"): lambda cr: f"You approved <b>{cr.name}</b>.",
	("Rejected", "requester"): lambda cr: f"Your request <b>{cr.name}</b> has been rejected by {cr.rejected_by}.",
	("Rejected", "actor"): lambda cr: f"You rejected <b>{cr.name}</b>.",
}


def _send_decision_email(cr, recipient_user, decision, audience):
	try:
		recipient = frappe.db.get_value("User", recipient_user, "email") or recipient_user
		message = _change_request_email_body(
			cr,
			heading=f"Change Management Request {decision}",
			intro_html=_DECISION_INTROS[(decision, audience)](cr),
		)
		frappe.sendmail(
			recipients=[recipient],
			sender=_default_outgoing_email(),
			subject=f"Change Management Request {decision}: {cr.title or cr.name}",
			message=message,
			now=True,
		)
	except Exception:
		frappe.log_error(title=f"Change Management Request: {audience} {decision.lower()} email failed")


def notify_approval(cr):
	_send_decision_email(cr, cr.requested_by, "Approved", "requester")
	if cr.approved_by and cr.approved_by != cr.requested_by:
		_send_decision_email(cr, cr.approved_by, "Approved", "actor")


def notify_rejection(cr):
	_send_decision_email(cr, cr.requested_by, "Rejected", "requester")
	if cr.rejected_by and cr.rejected_by != cr.requested_by:
		_send_decision_email(cr, cr.rejected_by, "Rejected", "actor")


# ============================================================
# DIFF LOGIC
# ============================================================

def _normalize(value):
	return "" if value is None else value


def _stringify(value):
	return "" if value is None else str(value)


def _build_update_details(old_doc, new_doc):
	rows = []
	for field in new_doc.meta.fields:
		if field.fieldtype in _IGNORE_FIELDTYPES:
			continue
		if field.fieldtype == "Table":
			rows.extend(_diff_table_field(old_doc, new_doc, field))
			continue
		if field.fieldtype == "Table MultiSelect":
			rows.extend(_diff_multiselect_field(old_doc, new_doc, field))
			continue
		fieldname = field.fieldname
		old_value = old_doc.get(fieldname)
		new_value = new_doc.get(fieldname)
		if _normalize(old_value) != _normalize(new_value):
			rows.append({
				"fieldname": fieldname,
				"field_label": field.label or fieldname,
				"parent_row": "",
				"old_value": _stringify(old_value),
				"new_value": _stringify(new_value),
			})
	return rows


_MULTISELECT_SKIP_FIELDS = {
	"name", "parent", "parentfield", "parenttype", "idx", "doctype",
	"creation", "modified", "modified_by", "owner", "docstatus", "amended_from",
}


def _multiselect_row_payload(row):
	"""Strip a Table MultiSelect child row down to its real data -- whatever
	fields the child doctype actually uses (varies per doctype, e.g. 'action_type'
	for Sub Features), excluding standard Frappe bookkeeping fields."""
	return {
		k: v for k, v in row.as_dict().items()
		if k not in _MULTISELECT_SKIP_FIELDS and v not in (None, "")
	}


def _diff_multiselect_field(old_doc, new_doc, field):
	"""Table MultiSelect fields aren't a real editable child table (no per-row
	cell edits, just add/remove whole selections) and can't be treated as a
	simple string field either (Frappe rejects a raw string for this
	fieldtype). Diff as a set of whole-row payloads; store the full new
	selection as JSON so apply-on-approve can replay it exactly via
	target.set(fieldname, parsed_list) rather than guessing a value field."""
	fieldname = field.fieldname
	old_rows = [_multiselect_row_payload(r) for r in (old_doc.get(fieldname) or [])]
	new_rows = [_multiselect_row_payload(r) for r in (new_doc.get(fieldname) or [])]

	old_key = sorted(json.dumps(r, sort_keys=True, default=str) for r in old_rows)
	new_key = sorted(json.dumps(r, sort_keys=True, default=str) for r in new_rows)
	if old_key == new_key:
		return []

	return [{
		"fieldname": fieldname,
		"field_label": field.label or fieldname,
		"parent_row": "",
		"old_value": json.dumps(old_rows, default=str),
		"new_value": json.dumps(new_rows, default=str),
	}]


def _diff_table_field(old_doc, new_doc, table_field):
	rows = []
	child_fieldname = table_field.fieldname
	old_children = {c.name: c for c in (old_doc.get(child_fieldname) or [])}
	new_rows = new_doc.get(child_fieldname) or []
	new_children = {c.name: c for c in new_rows if not c.get("__islocal")}
	new_local = [c for c in new_rows if c.get("__islocal")]

	# modified / deleted existing rows
	for name, old_child in old_children.items():
		new_child = new_children.get(name)
		if new_child is None:
			rows.append({
				"fieldname": child_fieldname,
				"field_label": table_field.label or child_fieldname,
				"parent_row": name,
				"old_value": _summarize_row(old_child),
				"new_value": "DELETED",
			})
			continue
		for cf in new_child.meta.fields:
			if cf.fieldtype in _IGNORE_FIELDTYPES or cf.fieldtype == "Table MultiSelect":
				continue
			ov, nv = old_child.get(cf.fieldname), new_child.get(cf.fieldname)
			if _normalize(ov) != _normalize(nv):
				rows.append({
					"fieldname": f"{child_fieldname}.{cf.fieldname}",
					"field_label": cf.label or cf.fieldname,
					"parent_row": name,
					"old_value": _stringify(ov),
					"new_value": _stringify(nv),
				})

	# brand-new rows -- tag by idx so every cell belonging to the same
	# appended row groups back together on apply (a bare "NEW" string can't
	# distinguish two different new rows added in the same save)
	for new_child in new_local:
		tag = f"NEW-{new_child.idx}"
		for cf in new_child.meta.fields:
			if cf.fieldtype in _IGNORE_FIELDTYPES or cf.fieldtype == "Table MultiSelect":
				continue
			nv = new_child.get(cf.fieldname)
			if nv in (None, "", 0, False):
				continue
			rows.append({
				"fieldname": f"{child_fieldname}.{cf.fieldname}",
				"field_label": cf.label or cf.fieldname,
				"parent_row": tag,
				"old_value": "",
				"new_value": _stringify(nv),
			})

	return rows


def _summarize_row(row):
	skip = {"name", "parent", "parentfield", "parenttype", "idx", "doctype",
	        "creation", "modified", "modified_by", "owner", "docstatus"}
	parts = [f"{k}={v}" for k, v in row.as_dict().items()
	         if k not in skip and v not in (None, "")]
	return "; ".join(parts)


def _build_new_record_details(doc):
	"""Human-readable audit rows for a brand-new record. Apply-on-approve
	does NOT reconstruct from these -- it uses pending_payload -- these
	exist purely so an approver can review what's being created."""
	rows = []
	for field in doc.meta.fields:
		if field.fieldtype in _IGNORE_FIELDTYPES or field.fieldtype in ("Table", "Table MultiSelect"):
			continue
		value = doc.get(field.fieldname)
		if value in (None, "", 0, False):
			continue
		rows.append({
			"fieldname": field.fieldname,
			"field_label": field.label or field.fieldname,
			"parent_row": "NEW",
			"old_value": "",
			"new_value": _stringify(value),
		})
	for field in doc.meta.fields:
		if field.fieldtype != "Table":
			continue
		for child in (doc.get(field.fieldname) or []):
			tag = f"NEW-{child.idx}"
			for cf in child.meta.fields:
				if cf.fieldtype in _IGNORE_FIELDTYPES or cf.fieldtype == "Table MultiSelect":
					continue
				value = child.get(cf.fieldname)
				if value in (None, "", 0, False):
					continue
				rows.append({
					"fieldname": f"{field.fieldname}.{cf.fieldname}",
					"field_label": cf.label or cf.fieldname,
					"parent_row": tag,
					"old_value": "",
					"new_value": _stringify(value),
				})
	return rows


def _revert_to_old_values(doc, old_doc):
	"""So the caller's original save doesn't apply the change directly --
	the in-memory doc gets reset to DB values right before Frappe writes it."""
	for field in doc.meta.fields:
		if field.fieldtype in _IGNORE_FIELDTYPES:
			continue
		if field.fieldtype in ("Table", "Table MultiSelect"):
			doc.set(field.fieldname, [
				d.as_dict() for d in (old_doc.get(field.fieldname) or [])
			])
		else:
			doc.set(field.fieldname, old_doc.get(field.fieldname))


# ============================================================
# APPLY-ON-APPROVE
# ============================================================

def apply_change_request(cr):
	if cr.is_new_record:
		return _apply_new_record(cr)
	return _apply_update(cr)


def _apply_new_record(cr):
	payload = frappe.parse_json(cr.pending_payload)
	payload.pop("name", None)
	new_doc = frappe.get_doc(payload)
	new_doc.flags.ignore_change_control = True
	new_doc.insert(ignore_permissions=True)
	cr.reference_name = new_doc.name
	return new_doc


def _cast_value(doc, fieldname, value):
	field = doc.meta.get_field(fieldname)
	if not field:
		return value
	if value == "":
		return None
	if field.fieldtype in ("Int", "Check"):
		return int(value)
	if field.fieldtype in ("Float", "Currency", "Percent"):
		return float(value)
	return value


def _apply_update(cr):
	target = frappe.get_doc(cr.reference_doctype, cr.reference_name)
	table_fieldnames = {f.fieldname for f in target.meta.fields if f.fieldtype == "Table"}

	deletions = []            # (table_fieldname, row_name)
	new_row_cells = {}        # (table_fieldname, tag) -> [(cell_fieldname, new_value)]
	modified_row_cells = {}   # (table_fieldname, row_name) -> [(cell_fieldname, new_value)]

	for row in cr.change_detail:
		if row.fieldname in table_fieldnames and row.new_value == "DELETED":
			deletions.append((row.fieldname, row.parent_row))
			continue
		if "." in row.fieldname:
			table_fieldname, cell_fieldname = row.fieldname.split(".", 1)
			bucket = new_row_cells if row.parent_row.startswith("NEW") else modified_row_cells
			bucket.setdefault((table_fieldname, row.parent_row), []).append(
				(cell_fieldname, row.new_value)
			)
			continue
		field_meta = target.meta.get_field(row.fieldname)
		if field_meta and field_meta.fieldtype == "Table MultiSelect":
			target.set(row.fieldname, json.loads(row.new_value))
			continue
		target.set(row.fieldname, _cast_value(target, row.fieldname, row.new_value))

	for table_fieldname, row_name in deletions:
		children = target.get(table_fieldname) or []
		target.set(table_fieldname, [c for c in children if c.name != row_name])

	for (table_fieldname, row_name), cells in modified_row_cells.items():
		existing = next(
			(c for c in (target.get(table_fieldname) or []) if c.name == row_name), None
		)
		if not existing:
			continue
		for cell_fieldname, new_value in cells:
			existing.set(cell_fieldname, _cast_value(existing, cell_fieldname, new_value))

	for (table_fieldname, _tag), cells in new_row_cells.items():
		new_row = target.append(table_fieldname, {})
		for cell_fieldname, new_value in cells:
			new_row.set(cell_fieldname, _cast_value(new_row, cell_fieldname, new_value))

	target.flags.ignore_change_control = True
	target.save(ignore_permissions=True)
	return target
