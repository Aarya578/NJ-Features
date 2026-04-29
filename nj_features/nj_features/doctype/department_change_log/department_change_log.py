# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt
import frappe
from frappe.model.document import Document
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error

class DepartmentChangeLog(Document):
    pass

def update_department_change_logs():
    """
    This function creates new Department Change Log entries for each employee every day
    Each execution creates new records to track historical changes.
    """
    try:
        employees = frappe.get_all(
            "Employee",
            filters={"status": "Active"},
            fields=["user_id", "emp_id", "department", "role_profile", "ramp_level", "target", "skill_level_ramp", "skill_level_target"]
        )

        for employee in employees:
            # existing_log_name = frappe.db.get_value(
            #     "Department Change Log",
            #     filters={
            #         "user_name": employee.user_id,
            #         "current_department": employee.department,
            #         "employee_id": employee.emp_id,
            #         "role_profile": employee.role_profile
            #     },
            #     fieldname="name"
            # )

            # if existing_log_name:
            #     doc = frappe.get_doc("Department Change Log", existing_log_name)
            #     doc.ramp_level = employee.ramp_level
            #     doc.target = employee.target
            #     doc.log_datetime = frappe.utils.now()
            #     doc.save(ignore_permissions=True)
            # else:
            doc = frappe.get_doc({
                "doctype": "Department Change Log",
                "user_name": employee.user_id,
                "current_department": employee.department,
                "employee_id": employee.emp_id,
                "role_profile": employee.role_profile,
                "ramp_level": employee.ramp_level,
                "target": employee.target,
                "skill_level_ramp": employee.skill_level_ramp,
                "skill_level_target": employee.skill_level_target,
                "log_datetime": frappe.utils.now()
            })
            doc.insert(ignore_permissions=True)
    
    except Exception:
        log_error(frappe.traceback(), "Department Change Log Update Error")