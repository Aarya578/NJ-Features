import frappe
from frappe import _
from frappe.model.document import Document

from ...resource_allocation import service


class ResourceReallocationLine(Document):
    def validate(self):
        if self.flags.from_engine:
            return
        if frappe.db.get_value("Resource Reallocation", self.reallocation, "docstatus") != 0:
            frappe.throw(_("This reallocation is already submitted."))
        before = self.get_doc_before_save()
        if before and before.recommended_department != self.recommended_department:
            if not self.present:
                frappe.throw(_("{0} is absent for this plan and cannot be reassigned.").format(self.employee_name))
            self.is_override = 1
            self.move_type = "Manual override"
            self.flags.dept_changed = True

    def on_update(self):
        if self.flags.dept_changed:
            # refresh figures on every line + department summary
            service.recompute(frappe.get_doc("Resource Reallocation", self.reallocation))
