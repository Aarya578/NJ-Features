# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class NJAudit(Document):
	pass

def get_stock_ledger_entries(warehouse):

	return frappe.db.sql(
		"""
		select
			sle.item_code, warehouse, sle.actual_qty, sle.valuation_rate,
			sle.voucher_type, sle.qty_after_transaction, sle.voucher_no
		from
			`tabStock Ledger Entry` sle
		where sle.docstatus < 2 and warehouse = %s
		and is_cancelled = 0
		order by sle.posting_date, sle.posting_time, sle.creation, sle.actual_qty"""
		,(warehouse), as_dict=1)
 
@frappe.whitelist()
def get_work_and_audit_warehouse():
    emp_data = frappe.db.get_value('Employee', {'user_id': frappe.session.user}, ['work_warehouse', 'department'], as_dict=1)
    
    if emp_data is None:
        frappe.throw("Employee data not found. Please ensure that the user is correctly associated with an employee record.")
    
    if not emp_data.get('department'):
        frappe.throw("Department is missing for Employee: .")
    if not emp_data.get('work_warehouse'):
        frappe.throw("Work warehouse is missing for the employee.")
    
    audit_warehouse = frappe.db.get_value('Department', {'name': emp_data.get('department')}, 'linked_warehouse')
    
    audit_interval = frappe.db.get_value('NJ Settings', {'parameter': 'audit_interval'}, 'value')
    
    return {
        'work_warehouse': emp_data.get('work_warehouse'),
        'audit_warehouse': audit_warehouse,
        'audit_interval': audit_interval
    }

@frappe.whitelist()
def get_scanned_serial_no_data(serial_no):
    is_serial_no_exists = frappe.db.exists('Serial No', serial_no)
    
    if is_serial_no_exists:
        serial_no_data = frappe.db.get_value('Serial No', {'name': serial_no}, ['name', 'warehouse', 'item_code', 'purchase_rate'], as_dict=1)
        parent_warehouse = frappe.db.get_value('Warehouse', {'name': serial_no_data.get('warehouse')}, 'parent_warehouse')
        
        return [{
            'parent_warehouse': parent_warehouse,
            'serial_no': serial_no_data.get('name'),
            'item_code': serial_no_data.get('item_code'),
            'warehouse': serial_no_data.get('warehouse'),
            'purchase_rate': serial_no_data.get('purchase_rate')
        }]
        
    return None