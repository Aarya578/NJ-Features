import frappe
from frappe.desk.form.assign_to import add as add_assignment
from frappe.model.document import Document
from frappe.utils import cint, get_url_to_form, now_datetime

from nj_features.overrides import change_control


class ChangeManagementRequest(Document):

	def before_insert(self):
		if not self.status:
			self.status = "Draft"

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
	"""Link-field query source for the Assign To dropdown -- only Users
	whose Role Profile carries the Change Management Approver flag are
	eligible to be assigned a Change Management Request."""
	role_profiles = change_control.get_change_approver_role_profiles()
	if not role_profiles:
		return []
	return frappe.get_all(
		"User",
		filters={
			"role_profile_name": ["in", role_profiles],
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

	assignee_role_profile = frappe.db.get_value("User", user, "role_profile_name")
	if not change_control.is_change_management_approver(assignee_role_profile):
		frappe.throw(f"{user} does not have Change Management approval access.")

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

	message = f"""
		<p>You have been assigned a Change Management Request for review.</p>
		<p><b>Reference:</b> {cr.reference_doctype} {cr.reference_name or "(new record)"}</p>
		<p><b>Summary:</b> {cr.change_summary or ""}</p>
		<p><b>Purpose:</b> {cr.purpose or ""}</p>
		<p><b>Impact:</b> {cr.impact or ""}</p>
		<p><b>Requested By:</b> {cr.requested_by}</p>
		<p><a href="{link}">Open Change Management Request {cr.name}</a></p>
	"""

	frappe.sendmail(
		recipients=[recipient],
		sender=sender,
		subject=f"Change Management Request Assigned: {cr.title or cr.name}",
		message=message,
	)
