# Copyright (c) 2023, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _

# Define the columns for the report
def get_columns():
    return [
        _("Serial No") + ":Link/Serial No:250",
        _("Item Code") + ":Link/Item:600",
        _("Item Group") + ":Link/Item Group:180",
        _("Department") + ":Link/User:180",
        _("Warehouse") + ":Link/Warehouse:250"
    ]

# Define the data retrieval logic
def get_data(filters):
    conditions = []
    if filters.get("warehouse_owner"):
        conditions.append(f"where WH.warehouse_owner = '{filters['warehouse_owner']}'")

    conditions_sql = " ".join(conditions)
    # SQL query to fetch data without serial_no filter
    # query = f"""
    #     SELECT 
    #         Bi.warehouse, Bi.item_code,
    #         SUM(Bi.actual_qty) AS total_qty,
    #         WH.department, WH.parent_warehouse, WH.warehouse_owner
    #     FROM 
    #         tabBin Bi
    #     INNER JOIN 
    #         tabWarehouse WH ON Bi.warehouse = WH.name
    #     WHERE 
    #         WH.disabled = 0
    #         AND Bi.actual_qty > 0
    #         {conditions_sql}
    #     GROUP BY
    #         Bi.warehouse, Bi.item_code, WH.department,
    #         WH.parent_warehouse, WH.warehouse_owner;
    # """
    query1 = f"""
        select Sr.serial_no,Sr.item_code,Sr.item_group,WH.department,Sr.warehouse
        from `tabSerial No` Sr
        inner join `tabWarehouse` WH on Sr.warehouse = WH.name
        {conditions_sql}

    """

    data = frappe.db.sql(query1, filters, as_dict=1)
    print(f"query: {query1}")
    return data

# def filter_serial():

def execute(filters):
    columns = get_columns()
    # filter_serial = filter_serial()
    data = get_data(filters)
    return columns, data
