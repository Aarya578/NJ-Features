import frappe
from frappe.utils import nowdate, add_days
from frappe.model.document import Document

class DailyIndividualReport(Document):
    pass

@frappe.whitelist()
def fetch_data_imports():
    user = frappe.session.user
    yesterday = add_days(nowdate(), -1)
    today = nowdate()

    data_imports = frappe.get_all('Data Import',
        filters={
            'creation': ['between', [yesterday + " 00:00:00", today + " 23:59:59"]],
            'owner': user
        },
        fields=['name', 'status']
    )

    sort_order = {
        'error': 1,
        'pending': 2,
        'partial success': 3,
        'success': 4
    }

    data_imports.sort(key=lambda x: sort_order.get(x['status'].lower(), 4))
    return data_imports


@frappe.whitelist()
def get_serial_no_data():
    user = frappe.session.user
    today = nowdate()
    work_warehouse = frappe.db.get_value('Employee', {'user_id': frappe.session.user}, 'work_warehouse')
    serial_no_data = frappe.get_all('Serial No',
        filters={
            'warehouse': work_warehouse,
        },
        fields=['item_code', 'serial_no']
    )
    return serial_no_data
