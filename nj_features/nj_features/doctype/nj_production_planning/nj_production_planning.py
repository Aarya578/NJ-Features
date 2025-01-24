import frappe
from frappe import _
import json
from datetime import datetime, timedelta

@frappe.whitelist()
def get_department_details(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)
    
    dept_doc = frappe.get_doc("Department", {"name": doc.get("department")})
    item_code_counts = {}
    forwarded_item_code_counts = {}

    for row in dept_doc.get("inventory_details_child"):
        # Process inwarded inventory
        if row.get("inwarded_inventory"):
            if row.get("inwarded_warehouse"):
                inwarded_warehouse = row.get("inwarded_warehouse").split(",")
            else:
                inwarded_warehouse = frappe.db.get_all(
                    "Warehouse", 
                    filters={"department": row.get("inwarded_inventory")}, 
                    pluck="name"
                )
                
            for warehouse in inwarded_warehouse:
                item_counts = frappe.db.sql("""
                    SELECT sn.item_code, COUNT(sn.name) AS count, sn.warehouse
                    FROM `tabSerial No` sn
                    JOIN `tabItem Group` i ON sn.item_group = i.name
                    WHERE sn.warehouse = %s
                    AND i.parent_item_group = "Products"
                    GROUP BY sn.item_code
                """, (warehouse,), as_dict=True)

                for item in item_counts:
                    item_code = item['item_code']
                    count = item['count']
                    
                    if item_code in item_code_counts:
                        item_code_counts[item_code] += count
                    else:
                        item_code_counts[item_code] = count

        # Process forwarded inventory
        if row.get("forwarded_inventory"): 
            if row.get("forwarded_warehouse"):
                forwarded_warehouse = row.get("forwarded_warehouse").split(",")
            else:
                forwarded_warehouse = frappe.db.get_all(
                    "Warehouse", 
                    filters={"department": row.get("forwarded_inventory")}, 
                    pluck="name"
                )
                
            for warehouse in forwarded_warehouse:
                item_counts = frappe.db.sql("""
                    SELECT sn.item_code, COUNT(sn.name) AS count, sn.warehouse
                    FROM `tabSerial No` sn
                    JOIN `tabItem Group` i ON sn.item_group = i.name
                    WHERE sn.warehouse = %s
                    AND i.parent_item_group = "Products"
                    GROUP BY sn.item_code
                """, (warehouse,), as_dict=True)

                for item in item_counts:
                    item_code = item['item_code']
                    count = item['count']
                    
                    if item_code in forwarded_item_code_counts:
                        forwarded_item_code_counts[item_code] += count
                    else:
                        forwarded_item_code_counts[item_code] = count

    # Combine inwarded and forwarded inventory counts
    item_code_list = []
    all_item_codes = set(item_code_counts.keys()).union(forwarded_item_code_counts.keys())

    for item_code in all_item_codes:
        inwarded_qty = item_code_counts.get(item_code, 0)
        forwarded_qty = forwarded_item_code_counts.get(item_code, 0)
        item_code_list.append({
            "item_code": item_code,
            "inwarded_qty": inwarded_qty,
            "forwarded_qty": forwarded_qty
        })

    item_codes = [item['item_code'] for item in item_code_list]

    if item_codes:
        placeholders = ', '.join(['%s'] * len(item_codes))
        attribute_data = frappe.db.sql(f"""
            SELECT 
                LOWER(iva.attribute) AS item_attribute, 
                LOWER(iva.attribute_value) AS attribute_value,
                iva.parent AS item_code,
                i.item_name,
                i.item_model,
                i.item_group
            FROM `tabItem Variant Attribute` iva
            INNER JOIN `tabItem` i ON iva.parent = i.name
            WHERE iva.parent IN ({placeholders})
        """, tuple(item_codes), as_dict=True)
    
        attributes_map = {}
        for row in attribute_data:
            item_code = row['item_code']
            attribute = row['item_attribute'].replace(' ', '_')
            attribute_value = row['attribute_value']
            if item_code not in attributes_map:
                attributes_map[item_code] = {}
            attributes_map[item_code][attribute] = attribute_value
            attributes_map[item_code]['item_name'] = row['item_name']
            attributes_map[item_code]['item_model'] = row['item_model']
            attributes_map[item_code]['item_group'] = row['item_group']

        for item in item_code_list:
            item_code = item['item_code']
            if item_code in attributes_map:
                item.update(attributes_map[item_code])
    
    item_code_list = calculate_sales_order_rate(item_code_list)
    
    return item_code_list

def calculate_sales_order_rate(item_code_list, days=30):
    """
    Calculate sales order rates for given item codes and include current inventory qty.
    """
    if not item_code_list:
        return item_code_list
    
    item_codes = [item['item_code'] for item in item_code_list]
    if not item_codes:
        return item_code_list
    
    # Fetch current inventory qty for all item codes belonging to the "Packing & Dispatch - NJ" department
    item_codes_string = ', '.join([f"'{code}'" for code in item_codes])  # Hardcode the item codes as strings
    inventory_warehouse = frappe.db.get_value("Warehouse", {"department": "Packing & Dispatch - NJ"}, "name")
    # print('inventory_data', inventory_warehouse)

    for item in item_code_list:
        item['item_name'] = frappe.db.get_value("Item", item['item_code'], "item_name")
        item['item_model'] = frappe.db.get_value("Item", item['item_code'], "item_model")
        item['item_group'] = frappe.db.get_value("Item", item['item_code'], "item_group")
    
    inventory_data = frappe.db.sql(f"""
        SELECT
            sn.item_code,
            count(sn.name) as current_inventory_qty,
            sn.warehouse
        FROM
            `tabSerial No` sn
        WHERE
            sn.item_code IN ({item_codes_string})
            AND sn.warehouse = '{inventory_warehouse}'
        GROUP BY
            sn.item_code
    """, as_dict=True)
    
    # Map inventory data to a dictionary for quick lookup
    inventory_map = {inv['item_code']: inv['current_inventory_qty'] for inv in inventory_data}
    
    # Fetch sales data for the past `days`
    sales_rates = frappe.db.sql(f"""
        SELECT
            soi.item_code,
            COUNT(DISTINCT so.name) AS total_orders,
            SUM(soi.qty) AS total_quantity,
            SUM(soi.qty) / {days} AS daily_sales_rate,
            MIN(so.creation) AS first_recorded_date,
            MAX(so.creation) AS last_recorded_date
        FROM
            `tabSales Order` so
        INNER JOIN
            `tabSales Order Item` soi ON so.name = soi.parent
        WHERE
            soi.item_code IN ({item_codes_string})
            AND so.creation >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
            AND so.docstatus = 1
            AND soi.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
        GROUP BY
            soi.item_code;

    """, as_dict=True)

    print('sales_rates --------------------- 187', sales_rates)
    
    # Map sales rates to a dictionary for quick lookup
    sales_rates_dict = {rate['item_code']: rate for rate in sales_rates}
    
    # Update the item_code_list with sales rate and inventory data
    for item in item_code_list:
        item_code = item['item_code']
        # Add inventory qty
        item['current_inventory_qty'] = inventory_map.get(item_code, 0)
        # Add sales data
        if item_code in sales_rates_dict:
            rate_info = sales_rates_dict[item_code]
            item['total_orders'] = rate_info['total_orders']
            item['total_sales_qty'] = rate_info['total_quantity']
            item['daily_sales_rate'] = rate_info['daily_sales_rate']
            item['first_sale_date'] = rate_info['first_sale_date']
            item['last_sale_date'] = rate_info['last_sale_date']
        else:
            item['total_orders'] = 0
            item['total_sales_qty'] = 0
            item['daily_sales_rate'] = 0
            item['first_sale_date'] = None
            item['last_sale_date'] = None

    # print('item_code_list ---------------- 209', item_code_list)
    
    return item_code_list
