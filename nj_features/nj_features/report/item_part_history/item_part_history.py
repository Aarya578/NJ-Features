# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _

def get_columns():
    return [
        _("Creation") + ":Date:120",
        _("Machine Serial") + ":Link/Serial No:120",
        _("STE No") + ":Link/Stock Entry:120",
        _("Part Item Group") + ":Link/Item Group:120",
        _("Part Item Code") + ":Link/Item:120",
        _("s_warehouse") + ":Link/Warehouse:120",
        _("t_warehouse") + ":Link/Warehouse:120",
        _("Part Serial No") + ":Link/Serial No:120",
        _("Current Product WH") + ":Link/Warehouse:120",
        _("Product Item Code") + ":Link/Item:120"
    ]

@frappe.whitelist()
def get_api_data():
    data = frappe.request.data
    data_json = data.decode('utf-8')
    filters = json.loads(data_json)
    response_data = get_data(filters)

    return response_data

def get_data(filters):
    serial_no = filters.get('serial_no')

    query = f"""
        SELECT DISTINCT
            stock_entry_1.creation,
            stock_entry.serial_no AS 'machine_serial',
            ledger.parent AS 'ste_no',
            item.item_group AS 'part_item_group',
            ledger.item_code AS 'part_item_code',
            ledger.s_warehouse,
            ledger.t_warehouse,
            ledger.serial_no AS 'part_serial_no',
            serial_no.warehouse AS 'current_product_wh',
            serial_no.item_code AS 'product_item_code'
        FROM
            `tabStock Entry Detail` AS ledger
        INNER JOIN
            (SELECT sed.parent, sed.serial_no
            FROM `tabStock Entry Detail` sed
            WHERE
                (sed.serial_no LIKE '{serial_no}' OR 
                 sed.serial_no LIKE '{serial_no}\\n' OR 
                 sed.serial_no LIKE '\\n{serial_no}' OR 
                 sed.serial_no LIKE '\\n{serial_no}\\n')
            ) AS stock_entry
            ON stock_entry.parent = ledger.parent
        INNER JOIN
            `tabItem` AS item ON item.item_code = ledger.item_code
        INNER JOIN
            `tabStock Entry` AS stock_entry_1 ON stock_entry_1.name = stock_entry.parent
        INNER JOIN
            `tabSerial No` AS serial_no ON serial_no.serial_no = stock_entry.serial_no
        WHERE
            stock_entry_1.purpose = 'Repack' AND ledger.docstatus = 1
        ORDER BY
            stock_entry_1.creation, ledger.parent, ledger.s_warehouse DESC,
            ledger.t_warehouse, ledger.basic_rate ASC;
    """

    data = frappe.db.sql(query, as_dict=1)
    return data

def execute(filters):
    columns = get_columns()
    data = get_data(filters)
    return columns, data
