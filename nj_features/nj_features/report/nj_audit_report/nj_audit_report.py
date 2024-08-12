# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	columns, data = [], []
	columns = [
		{"label": _("NJ Audit"), "fieldname": "name", "fieldtype": "Link", "options": "NJ Audit"},
		{"label": _("Audit Warehouse"), "fieldname": "audit_warehouse", "fieldtype": "Link", "options": "Warehouse"},
		{"label": _("Serial No"), "fieldname": "serial_no", "fieldtype": "Link", "options": "Serial No"}
	]
	last_audit_date = """SELECT DATE(MAX(creation)) FROM `tabNJ Audit`"""
	date_result = frappe.db.sql(last_audit_date, as_dict=1)
	date = date_result[0].get('DATE(MAX(creation))')

	query = """SELECT parent_table.name, parent_table.audit_warehouse, child_table.serial_no 
	FROM `tabNJ Audit` parent_table JOIN `tabNJ Audit Items` child_table ON parent_table.name = child_table.parent 
	WHERE child_table.serial_no IN (SELECT serial_no FROM `tabNJ Audit Items` WHERE DATE(creation) = %(creation_date)s 
	GROUP BY serial_no HAVING COUNT(*) > 1) AND DATE(child_table.creation) = %(creation_date)s AND parent_table.docstatus = '1'"""

	data = frappe.db.sql(query, {'creation_date': date}, as_dict=1)
	return columns, data
