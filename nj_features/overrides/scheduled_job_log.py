import frappe
from frappe.core.doctype.scheduled_job_log.scheduled_job_log import ScheduledJobLog


class CustomScheduledJobLog(ScheduledJobLog):
    def get(self, key, default=None):
        if key == "method":
            return self.method
        if key == "error":
            return self.error
        return super().get(key, default)

    @property
    def method(self):
        m = frappe.db.get_value("Scheduled Job Type", self.scheduled_job_type, "method") if self.scheduled_job_type else None
        return m or self.scheduled_job_type or ""

    @property
    def error(self):
        return self.details or frappe.get_traceback() or ""

    def on_change(self):
        if self.status == "Failed":
            self.trigger_failed_notification()

    def trigger_failed_notification(self):
        from frappe.email.doctype.notification.notification import evaluate_alert
        alerts = frappe.cache().hget("notifications", self.doctype)
        if alerts is None:
            alerts = frappe.get_all(
                "Notification",
                fields=["name", "event", "method"],
                filters={"enabled": 1, "document_type": self.doctype},
            )
            frappe.cache().hset("notifications", self.doctype, alerts)

        if not alerts:
            return

        if not hasattr(self.flags, "notifications_executed") or self.flags.notifications_executed is None:
            self.flags.notifications_executed = []

        for alert in alerts:
            if alert.name not in self.flags.notifications_executed:
                evaluate_alert(self, alert.name, alert.event)
                self.flags.notifications_executed.append(alert.name)
