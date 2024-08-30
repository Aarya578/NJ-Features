# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _

def get_columns():
    return [
        {"label": _("Date"), "fieldname": "date", "fieldtype": "Date"},
        {"label": _("STE Number"), "fieldname": "ste_number", "fieldtype": "Data"},
        {"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"label": _("Parent Warehouse"), "fieldname": "parent_warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department"},
        {"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item"},
        {"label": _("Warehouse Owner"), "fieldname": "warehouse_owner", "fieldtype": "Link", "options": "User"},
        {"label": _("Record Entry By"), "fieldname": "created_by", "fieldtype": "Link", "options": "User"},
        {"label": _("Voucher Type"), "fieldname": "voucher_type", "fieldtype": "Data"},
    ]

@frappe.whitelist()
def get_api_data():
    data = frappe.request.data
    data_json = data.decode('utf-8')
    filters = json.loads(data_json)
    response_data = get_data(filters)

    return response_data

def get_data(filters):
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

    query = f"""
    SELECT
        concat_ws(" ", sle.posting_date, sle.posting_time) AS date,
        sle.voucher_no AS ste_number,
        sle.item_code,
        sle.warehouse,
        w.parent_warehouse,
        d.name AS department,
        d.department_name,
        u2.full_name AS created_by,
        sle.serial_no,
        u1.full_name AS warehouse_owner,
        sle.voucher_type
    FROM
        `tabStock Ledger Entry` sle
    LEFT JOIN `tabStock Entry` stock ON sle.voucher_no = stock.name
    LEFT JOIN `tabWarehouse` w ON sle.warehouse = w.name
    LEFT JOIN `tabUser` u1 ON u1.email = w.warehouse_owner
    LEFT JOIN `tabUser` u2 ON u2.name = stock.owner
    LEFT JOIN `tabDepartment` d ON d.name = w.department  -- Assuming department is linked with tabWarehouse
    WHERE
        sle.is_cancelled = 0
        AND MATCH(sle.serial_no) AGAINST (%(serial_no)s)
        {conditions_sql}
    ORDER BY
        sle.posting_date DESC, sle.posting_time DESC, sle.creation DESC
    """
    data = frappe.db.sql(query, filters, as_dict=True)
    if filters.get("serial_no"):
        serial_no_filter = filters["serial_no"].upper()
        data = [entry for entry in data if any(serial_no_filter in sn for sn in entry["serial_no"].split('\n'))]

    for entry in data:
        entry["voucher_type_link"] = entry["voucher_type"].lower().replace(" ", "-")
    return data

def execute(filters): 
    columns = get_columns()
    data = get_data(filters)
    return columns, data
