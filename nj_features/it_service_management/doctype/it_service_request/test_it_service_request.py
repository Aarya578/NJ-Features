import frappe
import unittest

class TestITServiceRequest(unittest.TestCase):

    def setUp(self):
        if not frappe.db.exists("IT Service Category", "Hardware Issue"):
            frappe.get_doc({
                "doctype": "IT Service Category",
                "category_name": "Hardware Issue",
                "default_priority": "High"
            }).insert(ignore_permissions=True)

    def test_valid_creation(self):
        req = frappe.get_doc({
            "doctype": "IT Service Request",
            "subject": "Test Hardware Replacement",
            "category": "Hardware Issue",
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
            "category": "Hardware Issue",
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
            "category": "Hardware Issue",
            "priority": "Medium",
            "status": "Rejected"
        })
        self.assertRaises(frappe.ValidationError, req.insert)
