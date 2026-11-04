import frappe
from frappe import _
from frappe.model.document import Document

from ...resource_allocation import service


class ResourceReallocation(Document):
    def validate(self):
        if self.docstatus == 0 and self.status == "Applied":
            self.status = "Computed"

    @frappe.whitelist()
    def compute(self):
        self._check_draft()
        service.compute(self)

    @frappe.whitelist()
    def recompute(self):
        self._check_draft(computed=True)
        service.recompute(self)

    @frappe.whitelist()
    def reoptimise(self):
        self._check_draft(computed=True)
        service.reoptimise(self)

    def before_submit(self):
        if not self.snapshot_json:
            frappe.throw(_("Compute the reallocation before submitting."))

    def on_submit(self):
        service.apply(self)

    def on_cancel(self):
        self.db_set("status", "Computed")
        self.add_comment("Info", _("Cancelled. Employee departments were NOT reverted."))

    def on_trash(self):
        frappe.db.sql("delete from `tabResource Reallocation Line` where reallocation = %s", self.name)

    def _check_draft(self, computed=False):
        if self.docstatus != 0:
            frappe.throw(_("Only a draft reallocation can be changed."))
        if computed and not self.snapshot_json:
            frappe.throw(_("Run Compute first."))
