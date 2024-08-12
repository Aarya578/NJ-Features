import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, add_days

@frappe.whitelist()
def fetch_data_imports():
    # Fetch the current user
    user = frappe.session.user
    # Calculate the date for yesterday
    yesterday = add_days(nowdate(), -1)
    # today = nowdate()

    data_imports = frappe.get_all('Data Import',
        filters={
            'creation': ['between', [yesterday + " 00:00:00", yesterday + " 23:59:59"]],
            # 'creation': ['between', [today + " 00:00:00", today + " 23:59:59"]],
            'owner': user
        },
        fields=['name', 'status']
    )
    
   
    return data_imports

@frappe.whitelist()
def get_stock_data():
    user = frappe.session.user
  
    today = nowdate()
    work_warehouse = frappe.db.get_value('Employee', {'user_id': frappe.session.user}, 'work_warehouse')
    print("work_warehouse--------110",work_warehouse)
    stock_ledger_data = frappe.get_all('Stock Ledger Entry',
        filters={
        'warehouse':work_warehouse,
        'creation': ['between', [today + " 00:00:00", today + " 23:59:59"]],

        },
        fields=['item_code', 'serial_no']
    )
    return stock_ledger_data
