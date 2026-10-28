import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, add_to_date

class ITServiceRequest(Document):

    def validate(self):
        self.validate_required_fields()
        self.validate_task_hours()
        self.validate_rejection_reason()
        self.validate_resolution_summary()
        self.calculate_total_hours()
        self.calculate_sla_deadline()

    def validate_required_fields(self):
        if not self.category:
            frappe.throw(_("Category is mandatory for IT Service Request."))
        if not self.priority:
            frappe.throw(_("Priority is mandatory."))

    def validate_task_hours(self):
        """Enforces D3-T03 rule: Non-negative task time"""
        for row in self.get("tasks") or []:
            if (row.estimated_hours or 0) < 0:
                frappe.throw(_("Task '{0}' cannot have negative estimated hours.").format(row.task_description))
            if (row.actual_hours or 0) < 0:
                frappe.throw(_("Task '{0}' cannot have negative actual hours.").format(row.task_description))

    def validate_rejection_reason(self):
        """Enforces D3-T03 rule: Rejection Reason mandatory when rejected"""
        if self.status == "Rejected" and not (self.rejection_reason or "").strip():
            frappe.throw(_("Rejection Reason is mandatory when rejecting an IT Service Request."))

    def validate_resolution_summary(self):
        """Enforces D3-T03 rule: Resolution Summary mandatory before Resolved or Closed"""
        if self.status in ("Resolved", "Closed") and not (self.resolution_summary or "").strip():
            frappe.throw(_("Resolution Summary is mandatory before resolving or closing this request."))

    def calculate_total_hours(self):
        total = 0.0
        for row in self.get("tasks") or []:
            total += float(row.actual_hours or 0.0)
        self.total_task_hours = total

    def calculate_sla_deadline(self):
        """Calculates expected resolution date using IT Service Settings priority configuration"""
        if not self.expected_resolution_date:
            hours_map = {
                "Urgent": 4,
                "High": 24,
                "Medium": 48,
                "Low": 72
            }
            try:
                settings = frappe.get_single("IT Service Settings")
                if self.priority == "Urgent":
                    hours = settings.urgent_sla_hours or 4
                elif self.priority == "High":
                    hours = settings.high_sla_hours or 24
                elif self.priority == "Low":
                    hours = settings.low_sla_hours or 72
                else:
                    hours = settings.medium_sla_hours or 48
            except Exception:
                hours = hours_map.get(self.priority, 48)

            start = self.creation or now_datetime()
            self.expected_resolution_date = add_to_date(start, hours=hours)

    def on_submit(self):
        if self.status not in ("Resolved", "Closed"):
            self.status = "Resolved"
