# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib

class AutoStockEntry(Document):
	pass

@frappe.whitelist()
def submit_ste(t_warehouse, serial_no):
	try:
		sn_data = frappe.db.get_value('Serial No', {'name': serial_no}, ['item_code', 'warehouse', 'status'], as_dict=1)
		if sn_data is None:
			frappe.throw(f"Serial No <b>{serial_no}</b> not found.")
		else:
			if sn_data.get('status') != 'Active':
				frappe.throw(f"Serial No <b>{serial_no}</b> is not Active.")

		material_transfer_items = []

		stock_entry_data = {
			"doctype": "Auto Stock Entry",
			"stock_entry_type": "Material Transfer",
			"material_transfer_items": material_transfer_items,
		}

		material_transfer_items.append({
			'qty': 1,
			'item_code': sn_data.get('item_code'),
			's_warehouse': sn_data.get('warehouse'),
			't_warehouse': t_warehouse,
			'serial_no': serial_no,
		})

		if material_transfer_items:
			return stock_entry_using_nj_lib(stock_entry_data)
		else:
			frappe.throw("None available in <b>Items</b> table.")

	except Exception as e:
		frappe.db.rollback()
		frappe.throw(f"Error while submitting Stock Entry: {e}")

@frappe.whitelist()
def get_work_warehouse():
	emp_data = frappe.db.get_value('Employee', {'user_id': frappe.session.user, 'status': 'Active'}, ['work_warehouse'], as_dict=1)
	if emp_data is None:
		frappe.throw("No Active Employee data found for user: {0}".format(frappe.session.user))
	if not emp_data.get('work_warehouse'):
		frappe.throw(f"Work warehouse is missing for <b>Employee: {frappe.session.user}</b>.")

	return {"work_warehouse": emp_data.get('work_warehouse')}
