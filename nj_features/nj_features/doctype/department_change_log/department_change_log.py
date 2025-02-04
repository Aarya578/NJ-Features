# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt
import frappe
from frappe.model.document import Document

class DepartmentChangeLog(Document):
    pass

def update_department_change_logs():
    """
    This function creates new Department Change Log entries for each employee every 5 minutes.
    Each execution creates new records to track historical changes.
    """
    try:
        employees = frappe.get_all(
            "Employee",
            filters={"status": "Active"},
            fields=["user_id", "emp_id", "department", "role_profile", "ramp_level", "target"]
        )

        for employee in employees:
            doc = frappe.get_doc({
                "doctype": "Department Change Log",
                "user_name": employee.user_id,
                "current_department": employee.department,
                "employee_id": employee.emp_id,
                "role_profile": employee.role_profile,
                "ramp_level": employee.ramp_level,
                "target": employee.target,
                "log_datetime": frappe.utils.now()  # Add timestamp for each entry
            })
            doc.insert()

        frappe.db.commit()
        
    except Exception as e:
        frappe.log_error(f"Failed to update department change logs: {str(e)}", 
                        "Department Change Log Update Error")

