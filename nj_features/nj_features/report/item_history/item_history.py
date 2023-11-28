# Copyright (c) 2023, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _

# Define the columns for the report
def get_columns():
    return [
        _("Date") + ":Date:160",
        _("STE Number") + ":Link/Stock Entry:120",
        _("Item Code") + ":Link/Item:380",
        _("Warehouse") + ":Link/Warehouse:180",
        _("Warehouse Owner") + ":Link/User:180",
        _("Created By") + ":Link/User:180"
    ]

# Define the data retrieval logic
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

    conditions_sql = " ".join(conditions)

    # SQL query to fetch data without serial_no filter
    query = f"""
        SELECT
            concat_ws(" ", sle.posting_date, sle.posting_time) AS date,
            sle.voucher_no AS ste_number,
            sle.item_code,
            sle.warehouse,
            u2.full_name AS created_by,
            sle.serial_no,
            u1.full_name AS warehouse_owner
        FROM
            `tabStock Ledger Entry` sle
        LEFT JOIN `tabStock Entry` stock ON sle.voucher_no = stock.name
        LEFT JOIN `tabWarehouse` w ON sle.warehouse = w.name
        LEFT JOIN `tabUser` u1 on u1.email = w.warehouse_owner
        LEFT JOIN `tabUser` u2 on u2.name = stock.owner
        WHERE
            sle.company = %(company)s
            AND is_cancelled = 0
            AND MATCH(serial_no) AGAINST (%(serial_no)s)
            {conditions_sql}
        ORDER BY
            sle.posting_date desc, sle.posting_time desc, sle.creation desc
    """

    data = frappe.db.sql(query, filters, as_dict=1)
    split_serial_numbers = [entry['serial_no'].split('\n') for entry in data]
    new_data = []
    for sublist_index, serial_numbers in enumerate(split_serial_numbers):
        for serial_number in serial_numbers:
            if sublist_index < len(data):
                data[sublist_index]['serial_no'] = serial_number
                new_data.append(data[sublist_index].copy())
    if filters.get("serial_no"):
        # Filter the data in Python based on serial_no
        serial_no_filter = filters["serial_no"].upper()
        print(f"serial_no_filter: {serial_no_filter}")
        new_data = [entry for entry in new_data if serial_no_filter in entry["serial_no"]]
    data = new_data
    print(f"query: {query}")
    return data

# def filter_serial():

def execute(filters):
    columns = get_columns()
    # filter_serial = filter_serial()
    data = get_data(filters)
    return columns, data
