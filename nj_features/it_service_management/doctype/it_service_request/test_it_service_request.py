import frappe
import unittest
from frappe.utils import now_datetime, add_to_date

class TestITServiceRequest(unittest.TestCase):

    def setUp(self):
        if not frappe.db.exists("IT Service Category", "Hardware Support"):
            frappe.get_doc({
                "doctype": "IT Service Category",
                "category_name": "Hardware Support",
                "default_priority": "High"
            }).insert(ignore_permissions=True)

    def test_valid_creation(self):
        req = frappe.get_doc({
            "doctype": "IT Service Request",
            "subject": "Test Hardware Diagnostic",
            "category": "Hardware Support",
            "priority": "High",
            "status": "Draft",
            "tasks": [
                {
                    "doctype": "IT Service Request Task",
                    "task_description": "Diagnose RAM issue",
                    "estimated_hours": 2.0,
                    "actual_hours": 1.5
                }
            ]
        }).insert(ignore_permissions=True)
        self.assertTrue(req.name)
        self.assertEqual(req.total_task_hours, 1.5)

    def test_negative_task_hours_validation(self):
        req = frappe.get_doc({
            "doctype": "IT Service Request",
            "subject": "Test Negative Hours",
            "category": "Hardware Support",
            "priority": "Medium",
            "status": "Draft",
            "tasks": [
                {
                    "doctype": "IT Service Request Task",
                    "task_description": "Invalid negative task",
                    "actual_hours": -3.0
                }
            ]
        })
        self.assertRaises(frappe.ValidationError, req.insert)

    def test_rejection_reason_mandatory_when_rejected(self):
        req = frappe.get_doc({
            "doctype": "IT Service Request",
            "subject": "Test Missing Rejection Reason",
            "category": "Hardware Support",
            "priority": "Medium",
            "status": "Rejected"
        })
        self.assertRaises(frappe.ValidationError, req.insert)

    def test_sla_boundary_calculation(self):
        # D4-T01: Test Urgent priority SLA boundary (4 hours)
        urgent_req = frappe.get_doc({
            "doctype": "IT Service Request",
            "subject": "Server Down Urgent Test",
            "category": "Hardware Support",
            "priority": "Urgent",
            "status": "Draft"
        }).insert(ignore_permissions=True)
        self.assertTrue(urgent_req.expected_resolution_date)

    def test_closed_ticket_retroactive_modification(self):
        # D4-T06: Prevent editing tasks on closed requests
        req = frappe.get_doc({
            "doctype": "IT Service Request",
            "subject": "Closed Request Test",
            "category": "Hardware Support",
            "priority": "Low",
            "status": "Draft",
            "resolution_summary": "Issue resolved successfully."
        }).insert(ignore_permissions=True)

        frappe.db.set_value("IT Service Request", req.name, "status", "Resolved")
        req.reload()
        
        req.append("tasks", {
            "doctype": "IT Service Request Task",
            "task_description": "Retroactive task",
            "actual_hours": 1.0
        })
        self.assertRaises(frappe.ValidationError, req.save)
