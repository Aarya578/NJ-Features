# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _

def get_columns():
    return [
        {"label": _("Serial No"), "fieldname": "serial_no", "fieldtype": "Data"},
        {"label": _("Stock Entry Id"), "fieldname": "parent", "fieldtype": "Data", "options": "Parent"},
        {"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group"},
        {"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item"},
        {"label": _("Purchase Rate"), "fieldname": "purchase_rate", "fieldtype": "Data", "options": "Warehouse"},
        {"label": _("Source Warehouse"), "fieldname": "s_warehouse", "fieldtype": "Data", "options": "Warehouse"},
        {"label": _("Target Warehouse"), "fieldname": "t_warehouse", "fieldtype": "Data", "options": "Warehouse"},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data"},       
        {"label": _("Part Current Warehouse"), "fieldname": "part_current_warehouse", "fieldtype": "Data", "options": "Warehouse"},
        {"label": _("Part Current Item Code"), "fieldname": "part_item_code", "fieldtype": "Data"},
    ]


def get_data(filters):

    print(f'\nFILTERS FROM DJANGO ==========37=========== {filters}\n')

    conditions = []

    if filters.get("item_group"):
        conditions.append(f"AND sle.item_group = '{filters['item_group']}'")
    if filters.get("brand"):
        conditions.append(f"AND sle.brand = '{filters['brand']}'")
    if filters.get("warehouse"):
        conditions.append(f"AND sle.warehouse = '{filters['warehouse']}'")
    if filters.get("item"):
        conditions.append(f"AND sle.item_code = '{filters['item']}'")
    if filters.get("Doctype"):
        conditions.append(f"AND sle.voucher_type = '{filters['Doctype']}'")
    if filters.get("department"):
        conditions.append(f"AND d.name = '{filters['department']}'")

    conditions_sql = " ".join(conditions)

    serial_no = filters.get("serial_no", '')

    query = f"""
        SELECT sed.*,
            sn.warehouse AS part_current_warehouse,
            sn.item_code AS part_item_code,
            sn.purchase_rate AS purchase_rate
        FROM `tabStock Entry Detail` sed
        LEFT JOIN `tabSerial No` sn ON sed.serial_no = sn.name
        WHERE sed.parent IN (
            SELECT name
            FROM `tabStock Entry`
            WHERE name IN (
                SELECT parent
                FROM `tabStock Entry Detail`
                WHERE serial_no = '{serial_no}'
            )
        )
        ORDER BY sed.modified ASC, sed.idx ASC
        {conditions_sql}
        """
    data = frappe.db.sql(query, filters, as_dict=True)
    
    return data


def execute(filters): 
    print(f'\nFILTERS ==========97=========== {filters}\n')
    columns = get_columns()
    print(f'COLUMNS =============102============== {columns}')
    data = get_data(filters)
    return columns, data
