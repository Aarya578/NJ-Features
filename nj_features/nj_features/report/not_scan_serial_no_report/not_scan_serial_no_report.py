# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	columns, data = [], []
	grand_child_warehouse=[]
	columns = [
		{"label": _("Serial No"), "fieldname": "name", "fieldtype": "Link", "options": "Serial No"},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse"},
		{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group"},
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item"},




	]
	audit_warehouse = frappe.db.sql("""select audit_warehouse from `tabNJ Audit` where creation = (select MAX(creation) FROM `tabNJ Audit`)""",as_dict = 1)
	parent_warehouse = audit_warehouse[0]['audit_warehouse']
	restricted_warehouses = set(frappe.db.get_all("Warehouse", filters={'parent_warehouse': parent_warehouse}, pluck='name'))
	restricted_warehouses.add(parent_warehouse)
	def add_child_warehouses(warehouse):
		child_warehouses = frappe.db.get_all("Warehouse", filters={'parent_warehouse': warehouse}, pluck='name')
		for child in child_warehouses:
			if child not in restricted_warehouses and (frappe.db.get_value('Warehouse',{'name':child },'is_group')) == 0:
				grand_child_warehouse.append(child)
				add_child_warehouses(child)
	for warehouse in list(restricted_warehouses):
		add_child_warehouses(warehouse)
	
	serial_no_data = []
	for warehouses in grand_child_warehouse:
		serial_num_data  = frappe.db.get_all("Serial No",{'warehouse' : warehouses},{'name','warehouse','item_group','item_code'})
		serial_no_data.extend(serial_num_data)
	serial_no_from_nj_audit = frappe.db.sql("""select serial_no from `tabNJ Audit Items` where docstatus='1' and DATE(creation) = (SELECT DATE(MAX(creation)) FROM `tabNJ Audit`)""",as_dict=1)
	serial_no_audit_set = {item['serial_no'] for item in serial_no_from_nj_audit}

	data = [item for item in serial_no_data if item['name'] not in serial_no_audit_set]


	return columns, data


