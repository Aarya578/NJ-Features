# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe

import frappe

# getting the data from the table serial no components to fill into the table.
@frappe.whitelist()
def get_serial_no_data(serial_no):
    query = """
        SELECT * FROM `tabSerial No Component`
        WHERE parent = %s
    """
    result = frappe.db.sql(query, (serial_no,), as_dict=True)
    frappe.logger().info(f"Serial No Component data: {result}")
    return result



# getting the sell price form doctype item
@frappe.whitelist()
def get_valuation_rate(part):
    query = """
        SELECT valuation_rate FROM `tabItem`
        WHERE name= %s
        """
    result=frappe.db.sql(query,(part,),as_dict=True)
    frappe.logger().info(f'valuation_rate: {result}')
    return result


# calculating the total cost price
@frappe.whitelist()
def get_total_cost(items):
    import json
    if isinstance(items, str):
        items = json.loads(items)
    total_cost = 0
    for item in items:
        price = frappe.db.get_value("Item Group", {"name": item}, "default_item_group_price") or 0
        total_cost += price
    return total_cost




