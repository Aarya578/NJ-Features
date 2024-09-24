# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def execute(filters=None):
	columns, data = [], []
	columns = [
		{"label": _("NJ Audit"), "fieldname": "name", "fieldtype": "Link", "options": "NJ Audit"},
		{"label": _("Audit Warehouse"), "fieldname": "audit_warehouse", "fieldtype": "Link", "options": "Warehouse"},
		{"label": _("Scan Rack"), "fieldname": "scan_rack", "fieldtype": "Link", "options": "Warehouse"},
		{"label": _("Serial No"), "fieldname": "serial_no", "fieldtype": "Link", "options": "Serial No"},
		{"label": _("Row"), "fieldname": "idx", "fieldtype": "Int"}
	]
	last_audit_date_query = """SELECT DATE(MAX(creation)) AS date FROM `tabNJ Audit` WHERE docstatus=1"""
	date_result = frappe.db.sql(last_audit_date_query, as_dict=1)
	date = date_result[0].get('date')
	
	query = """SELECT parent_table.name, parent_table.audit_warehouse, parent_table.scan_rack, child_table.serial_no, child_table.idx 
	FROM `tabNJ Audit` parent_table JOIN `tabNJ Audit Items` child_table ON parent_table.name = child_table.parent 
	WHERE child_table.serial_no IN (SELECT serial_no FROM `tabNJ Audit Items` WHERE DATE(creation) = %(creation_date)s 
	GROUP BY serial_no HAVING COUNT(*) > 1) AND DATE(child_table.creation) = %(creation_date)s AND parent_table.docstatus = '1'"""

	data = frappe.db.sql(query, {'creation_date': date}, as_dict=1)
	return columns, data
