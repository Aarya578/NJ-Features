import frappe
from frappe.desk.form.assign_to import add as add_assignment
from frappe.model.document import Document
from frappe.utils import cint, get_url_to_form, now_datetime, nowdate

from nj_features.overrides import change_control


class ChangeManagementRequest(Document):

	def before_insert(self):
		if not self.status:
			self.status = "Draft"
		if not self.start_date:
			self.start_date = nowdate()

	def validate(self):
		self._build_title()

	def _build_title(self):
		ref = self.reference_name or "New Record"
		summary = (self.change_summary or "").strip()
		title = f"{self.reference_doctype}: {ref}"
		if summary:
			title = f"{title} — {summary}"
		self.title = title


def _current_user_role_profile():
	return frappe.db.get_value("User", frappe.session.user, "role_profile_name")


def _check_authorized(cr):
	"""Shared authorization gate for approve/reject.

	Anyone holding the Change Management Approver flag (on their Role
	Profile) can approve or reject, including their own Change Management
	Requests -- self-approval is intentionally allowed.
	"""
	user_profile = _current_user_role_profile()
	if not change_control.is_change_management_approver(user_profile):
		frappe.throw(
			"You are not authorized to act on this Change Management Request.",
			frappe.PermissionError,
		)


@frappe.whitelist()
def approve_change_request(name, reason=None):
	cr = frappe.get_doc("Change Management Request", name)

	if cr.status != "Pending Approval":
		frappe.throw(f"Cannot approve. Current status is {cr.status}.")

	_check_authorized(cr)

	change_control.apply_change_request(cr)

	cr.status = "Approved"
	cr.approved_by = frappe.session.user
	cr.approved_on = now_datetime()
	cr.end_date = nowdate()
	cr.applied = 1
	cr.flags.ignore_change_control = True
	cr.save(ignore_permissions=True)
	frappe.db.commit()

	return "Approved"


@frappe.whitelist()
def reject_change_request(name, reason=""):
	cr = frappe.get_doc("Change Management Request", name)

	if cr.status != "Pending Approval":
		frappe.throw(f"Cannot reject. Current status is {cr.status}.")

	_check_authorized(cr)

	cr.status = "Rejected"
	cr.rejection_reason = reason
	cr.flags.ignore_change_control = True
	cr.save(ignore_permissions=True)
	frappe.db.commit()

	return "Rejected"


# ============================================================
# ASSIGN TO -- page-header widget entrypoints
# ============================================================

@frappe.whitelist()
def can_assign_change_request():
	"""Whether the current session user is allowed to use the Assign
	widget at all -- same gate as approve/reject, checked again server-side
	in assign_change_request() regardless of what the client shows."""
	return bool(change_control.is_change_management_approver(_current_user_role_profile()))


@frappe.whitelist()
def get_assignable_users(doctype=None, txt="", searchfield=None, start=0, page_len=20, filters=None):
	"""Link-field query source for the Assign To dropdown. Any enabled User
	can be assigned -- the approval-access restriction applies to who can
	perform the assignment (see can_assign_change_request /
	assign_change_request), not to who can be assigned."""
	return frappe.get_all(
		"User",
		filters={
			"enabled": 1,
			"name": ["like", f"%{txt or ''}%"],
		},
		fields=["name", "full_name"],
		as_list=True,
		limit_page_length=cint(page_len) or 20,
	)


@frappe.whitelist()
def assign_change_request(name, user):
	if not user:
		frappe.throw("Select a user to assign this Change Management Request to.")

	if not change_control.is_change_management_approver(_current_user_role_profile()):
		frappe.throw(
			"Only users with approval access can assign Change Management Requests.",
			frappe.PermissionError,
		)

	cr = frappe.get_doc("Change Management Request", name)
	cr.assigned_to = user
	cr.flags.ignore_change_control = True
	cr.save(ignore_permissions=True)

	add_assignment({
		"doctype": "Change Management Request",
		"name": name,
		"assign_to": [user],
		"description": cr.change_summary or cr.title,
	})

	_notify_assignee(cr, user)
	frappe.db.commit()

	return "Assigned"


def _notify_assignee(cr, user):
	default_account = frappe.get_all(
		"Email Account", filters={"default_outgoing": 1}, fields=["email_id"], limit=1,
	)
	sender = default_account[0].email_id if default_account else None

	recipient = frappe.db.get_value("User", user, "email") or user
	link = get_url_to_form("Change Management Request", cr.name)

	def _row(label, value):
		return f"""
			<tr style="border-top:1px solid #e9ecef;">
				<td style="padding:8px 12px 8px 0; color:#6c7680; white-space:nowrap; vertical-align:top;">{label}</td>
				<td style="padding:8px 0; color:#1f272e;">{value}</td>
			</tr>
		"""

	rows = "".join([
		_row("Reference", f"{cr.reference_doctype} {cr.reference_name or '(new record)'}"),
		_row("Summary", cr.change_summary or ""),
		_row("Purpose", cr.purpose or ""),
		_row("Impact", cr.impact or ""),
		_row("Requested By", cr.requested_by),
	])

	message = f"""
		<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; max-width:600px; margin:0 auto;">
			<div style="background-color:#2490ef; padding:20px 24px; border-radius:6px 6px 0 0;">
				<span style="color:#ffffff; font-size:18px; font-weight:600;">Change Management Request Assigned</span>
			</div>
			<div style="background-color:#ffffff; border:1px solid #d1d8dd; border-top:none; padding:24px; border-radius:0 0 6px 6px;">
				<p style="color:#1f272e; font-size:14px; margin:0 0 16px;">
					You have been assigned <b>{cr.name}</b> for review.
				</p>
				<table style="width:100%; border-collapse:collapse; font-size:13px;">
					{rows}
				</table>
				<div style="margin-top:24px; text-align:center;">
					<a href="{link}" style="background-color:#2490ef; color:#ffffff; text-decoration:none; padding:10px 24px; border-radius:4px; font-size:14px; font-weight:600; display:inline-block;">
						Open {cr.name}
					</a>
				</div>
			</div>
		</div>
	"""

	frappe.sendmail(
		recipients=[recipient],
		sender=sender,
		subject=f"Change Management Request Assigned: {cr.title or cr.name}",
		message=message,
	)
