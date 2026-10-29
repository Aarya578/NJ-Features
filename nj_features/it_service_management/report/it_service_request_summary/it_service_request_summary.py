import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data

def get_columns():
    return [
        {
            "label": _("Request ID"),
            "fieldname": "name",
            "fieldtype": "Link",
            "options": "IT Service Request",
            "width": 170
        },
        {
            "label": _("Subject"),
            "fieldname": "subject",
            "fieldtype": "Data",
            "width": 220
        },
        {
            "label": _("Category"),
            "fieldname": "category",
            "fieldtype": "Link",
            "options": "IT Service Category",
            "width": 140
        },
        {
            "label": _("Priority"),
            "fieldname": "priority",
            "fieldtype": "Data",
            "width": 100
        },
        {
            "label": _("Status"),
            "fieldname": "status",
            "fieldtype": "Data",
            "width": 120
        },
        {
            "label": _("Department"),
            "fieldname": "department",
            "fieldtype": "Link",
            "options": "Department",
            "width": 130
        },
        {
            "label": _("Assignee"),
            "fieldname": "assigned_developer",
            "fieldtype": "Link",
            "options": "User",
            "width": 140
        },
        {
            "label": _("Age (Days)"),
            "fieldname": "age_days",
            "fieldtype": "Int",
            "width": 90
        },
        {
            "label": _("Total Hours"),
            "fieldname": "total_task_hours",
            "fieldtype": "Float",
            "width": 100
        },
        {
            "label": _("SLA Deadline"),
            "fieldname": "expected_resolution_date",
            "fieldtype": "Datetime",
            "width": 160
        },
        {
            "label": _("SLA Status"),
            "fieldname": "sla_status",
            "fieldtype": "Data",
            "width": 110
        }
    ]

def get_data(filters):
    conditions = []
    values = {}

    if filters:
        if filters.get("priority"):
            conditions.append("priority = %(priority)s")
            values["priority"] = filters["priority"]
        if filters.get("status"):
            conditions.append("status = %(status)s")
            values["status"] = filters["status"]
        if filters.get("department"):
            conditions.append("department = %(department)s")
            values["department"] = filters["department"]

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT 
            name,
            subject,
            category,
            priority,
            status,
            department,
            assigned_developer,
            total_task_hours,
            expected_resolution_date,
            creation,
            TIMESTAMPDIFF(DAY, creation, NOW()) as age_days
        FROM `tabIT Service Request`
        {where_clause}
        ORDER BY creation DESC
    """

    raw_data = frappe.db.sql(query, values, as_dict=True)
    now = now_datetime()

    for row in raw_data:
        # Compute dynamic SLA breach
        if row.get("expected_resolution_date"):
            exp_date = get_datetime(row["expected_resolution_date"])
            if row["status"] in ("Resolved", "Closed"):
                row["sla_status"] = "Completed"
            elif now > exp_date:
                row["sla_status"] = "Breached"
            elif (exp_date - now).total_seconds() <= 7200: # within 2 hours
                row["sla_status"] = "Near Breach"
            else:
                row["sla_status"] = "Within SLA"
        else:
            row["sla_status"] = "N/A"

    return raw_data
