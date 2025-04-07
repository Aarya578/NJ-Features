# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt
from frappe.model.document import Document

class LaptopAllocation(Document):
    pass

@frappe.whitelist()
def allocate_laptop_parts():
    
    mr_items = frappe.db.sql("""
        SELECT parent AS material_request, item_code, serial_no AS against_serial_no, stock_qty, qty AS mr_qty
        FROM `tabMaterial Request Item` 
        WHERE post_order_status IN ("Not Completed", " ") 
        AND serial_no IN (
            SELECT name 
            FROM `tabSerial No` 
            WHERE warehouse IN (
                SELECT name FROM `tabWarehouse` 
                WHERE department = "Part waiting  - NJ"
            ) 
            AND item_group = "Laptops"
        )
    """, as_dict=True)

    if not mr_items:
        frappe.msgprint("No open Material Requests found for Laptop Displays.")
        return []

    warehouses = frappe.db.get_all("Warehouse", filters={"department": "Stores - NJ"}, pluck="name")

    if not warehouses:
        frappe.msgprint("No warehouses found under 'Stores - NJ' department.")
        return []

    stock_data = {}

    stock_results = frappe.db.sql("""
        SELECT item_code, SUM(actual_qty) AS total_qty 
        FROM `tabBin` 
        WHERE warehouse IN %s 
        GROUP BY item_code
    """, (tuple(warehouses),), as_dict=True)

    for stock in stock_results:
        stock_data[stock["item_code"]] = flt(stock["total_qty"])

    allocation_results = []
    unique_serial_item_pairs = set()  

    for item in mr_items:
        serial_no = item["against_serial_no"]
        item_code = item["item_code"]
        mr_qty = flt(item["mr_qty"])
        available_stock = stock_data.get(item_code, 0)

        serial_item_key = f"{serial_no}-{item_code}"

        if serial_item_key in unique_serial_item_pairs:
            continue

        unique_serial_item_pairs.add(serial_item_key)

        if available_stock >= mr_qty:
            stock_data[item_code] -= mr_qty  
            allocated_status = "Allocated"
        else:
            allocated_status = "Not Allocated"

        status = "Available" if available_stock > 0 else "Not Available"

        allocation_results.append({
            "material_request": item["material_request"],
            "item_code": item_code,
            "against_serial_no": serial_no,
            "mr_qty": mr_qty,
            "available_stock": available_stock,  
            "status": status, 
            "allocated_status": allocated_status
        })

    allocation_results.sort(key=lambda x: (x["item_code"], -x["available_stock"]))

    print("Allocation Results ----------------------- ", allocation_results)
    return allocation_results
