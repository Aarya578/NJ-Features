# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from nj_features.nj_features.doctype.nj_audit.nj_audit import get_all_child_warehouses

@frappe.whitelist()
def execute(filters=None):
    columns = [
        {"label": _("Serial No"), "fieldname": "name", "fieldtype": "Link", "options": "Serial No"},
        {"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"label": _("Audit Warehouse"), "fieldname": "audit_warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group"},
        {"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item"},
    ]

    data = []
    allowed_item_group_check = []

    allowed_item_group_data = frappe.db.get_value('NJ Settings', {'parameter': 'Item Group Check'}, 'value')
    if allowed_item_group_data:
        allowed_item_group_check = allowed_item_group_data.split(",")

    last_audit_date_query = """SELECT DATE(MAX(creation)) AS date FROM `tabNJ Audit` WHERE docstatus=1"""
    date_result = frappe.db.sql(last_audit_date_query, as_dict=1)
    date = date_result[0].get('date')

    audit_warehouses_data_query = """SELECT DISTINCT parent_warehouse 
							FROM `tabNJ Audit Items` 
							WHERE docstatus=1 
							AND DATE(creation) = %s"""

    audit_warehouses_data = frappe.db.sql(audit_warehouses_data_query, date, as_dict=1)
    
    for audit_warehouse in audit_warehouses_data:
        if audit_warehouse.get('parent_warehouse') is not None:
            group_warehouses, non_group_warehouses = get_all_child_warehouses(audit_warehouse.get('parent_warehouse'))
            serial_no_data = []
            
            for warehouse in non_group_warehouses:
                filters = {'warehouse': warehouse}
                
                if allowed_item_group_check:
                    filters['item_group'] = ['in', allowed_item_group_check]
                
                serial_num_data = frappe.db.get_all("Serial No", filters=filters, 
                    fields=['name', 'warehouse', 'item_group', 'item_code']
                )
                
                for serial_num in serial_num_data:
                    serial_num['audit_warehouse'] = audit_warehouse.get('parent_warehouse')
                    
                serial_no_data.extend(serial_num_data)

            serial_no_from_nj_audit = frappe.db.sql("""SELECT serial_no 
                                        FROM `tabNJ Audit Items` 
                                        WHERE docstatus=1 
                                        AND DATE(creation) = %s""", date, as_dict=1)
            
            serial_no_audit_set = {item['serial_no'] for item in serial_no_from_nj_audit}
            data.extend([item for item in serial_no_data if item['name'] not in serial_no_audit_set])

    return columns, data