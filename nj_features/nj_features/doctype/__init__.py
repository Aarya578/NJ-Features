import frappe

__version__ = "1.0"

@frappe.whitelist()
def get_active_emp_work_ware(email, filters=None, fields=None, exists=False):
    emp_filters = {
        'user_id': email,
        'status': 'Active'
    }

    emp_fields = ['work_warehouse', 'user_id']

    if filters:
        emp_filters.update(filters)

    if fields:
        emp_fields.extend(fields)

    if exists:
        return frappe.db.exists('Employee', emp_filters)

    emp_data = frappe.db.get_value('Employee', emp_filters, emp_fields, as_dict=True)

    return emp_data if emp_data else None
