# Copyright (c) 2023, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _

# Define the columns for the report
def get_columns():
    return [
        _("Warehouse") + ":Link/Warehouse:250",
        _("Item Code") + ":Link/Item:600",
        _("Total QTY") + ":Int:80",
        _("Department") + ":Link/User:180",
        _("Parent Warehouse") + ":Link/Warehouse:250",
        _("Warehouse Owner") + ":Link/Warehouse:250"
    ]

# Define the data retrieval logic
def get_data(filters):
    conditions = []

    if filters.get("warehouse"):
        conditions.append(f"AND WH.name = '{filters['warehouse']}'")

    conditions_sql = " ".join(conditions)

    # SQL query to fetch data without serial_no filter
    query = f"""
        SELECT 
            Bi.warehouse, Bi.item_code,
            SUM(Bi.actual_qty) AS total_qty,
            WH.department, WH.parent_warehouse, WH.warehouse_owner
        FROM 
            tabBin Bi
        INNER JOIN 
            tabWarehouse WH ON Bi.warehouse = WH.name
        WHERE 
            WH.disabled = 0
            AND Bi.actual_qty > 0
            {conditions_sql}
        GROUP BY
            Bi.warehouse, Bi.item_code, WH.department,
            WH.parent_warehouse, WH.warehouse_owner;
    """

    data = frappe.db.sql(query, filters, as_dict=1)
    print(f"query: {query}")
    return data

# def filter_serial():

def execute(filters):
    columns = get_columns()
    # filter_serial = filter_serial()
    data = get_data(filters)
    return columns, data
