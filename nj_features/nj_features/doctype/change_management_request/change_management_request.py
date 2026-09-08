import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, nowdate

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
