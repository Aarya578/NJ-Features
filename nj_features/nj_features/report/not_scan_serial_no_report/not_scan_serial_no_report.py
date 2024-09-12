# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _

@frappe.whitelist()
def execute(filters=None):
	columns, data = [], []
	grand_child_warehouse=[]
	columns = [
		{"label": _("Serial No"), "fieldname": "name", "fieldtype": "Link", "options": "Serial No"},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse"},
		{"label": _("Audit Warehouse"), "fieldname": "audit_warehouse", "fieldtype": "Link", "options": "Warehouse"},
		{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group"},
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item"},
	]
	audit_warehouses_data = frappe.db.sql("""select distinct parent_warehouse from `tabNJ Audit Items` where docstatus='1' and DATE(creation) = (SELECT DATE(MAX(creation)) FROM `tabNJ Audit`)""",as_dict = 1)
	print('audit_warehouses_data==================',audit_warehouses_data)
	for audit_warehouse in audit_warehouses_data:
		warehouses_data = set()
		warehouses_data = set(frappe.db.get_all("Warehouse", filters={'parent_warehouse': audit_warehouse['parent_warehouse']}, pluck='name'))
		warehouses_data.add(audit_warehouse['parent_warehouse'])
		def add_child_warehouses(warehouse):
			child_warehouses = frappe.db.get_all("Warehouse", filters={'parent_warehouse': warehouse}, pluck='name')
			for child in child_warehouses:
				if child not in audit_warehouses_data:
					grand_child_warehouse.append(child)
					add_child_warehouses(child)
		for warehouse in list(warehouses_data):
			if frappe.db.get_value('Warehouse',{'name':warehouse },'is_group') == 1:
				add_child_warehouses(warehouse)
			else:
				grand_child_warehouse.append(warehouse)
		new_grand_warehouse =[]
		for xar in grand_child_warehouse:
			if (frappe.db.get_value('Warehouse',{'name':xar },'is_group')) == 0:
				new_grand_warehouse.append(xar)
		new_grand_warehouse = list(set(new_grand_warehouse))
		serial_no_data = []
		for warehouses in new_grand_warehouse:
			serial_num_data  = frappe.db.get_all("Serial No",{'warehouse' : warehouses},{'name','warehouse','item_group','item_code'})
			for serial_num in serial_num_data:
				serial_num['audit_warehouse'] = audit_warehouse.get('parent_warehouse')
			serial_no_data.extend(serial_num_data)
		serial_no_from_nj_audit = frappe.db.sql("""select serial_no from `tabNJ Audit Items` where docstatus='1' and DATE(creation) = (SELECT DATE(MAX(creation)) FROM `tabNJ Audit`)""",as_dict=1)
		serial_no_audit_set = {item['serial_no'] for item in serial_no_from_nj_audit}
		data.extend([item for item in serial_no_data if item['name'] not in serial_no_audit_set])
	print('execute function of not_scan_serial_no_report',columns,data)	
	return columns, data