import frappe
import json
import traceback

@frappe.whitelist()
def get_department_details(doc):
    try:
        if isinstance(doc, str):
            doc = json.loads(doc)

        dept_doc = frappe.get_doc("Department", {"name": doc.get("department")})
        item_code_counts = {}
        forwarded_item_code_counts = {}

        for row in dept_doc.get("inventory_details_child"):
            # Process inwarded inventory
            try:
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
            except Exception as e:
                frappe.log_error(title="Error Processing Inwarded Inventory", message=traceback.format_exc())
                continue

            # Process forwarded inventory
            try:
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
            except Exception as e:
                frappe.log_error(title="Error Processing Forwarded Inventory", message=traceback.format_exc())
                continue

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
            try:
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
            except Exception as e:
                frappe.log_error(title="Error Fetching Item Attributes", message=traceback.format_exc())

        item_code_list = calculate_sales_order_rate(item_code_list)
        return item_code_list

    except Exception as e:
        frappe.log_error(title="Error in get_department_details", message=traceback.format_exc())
        return {"status": "error", "message": str(e)}

def calculate_sales_order_rate(item_code_list, days=30):
    try:
        # Add calculation logic with error handling
        if not item_code_list:
            return item_code_list
        
        item_codes = [item['item_code'] for item in item_code_list]
        if not item_codes:
            return item_code_list
        
        item_codes_string = ', '.join([f"'{code}'" for code in item_codes])
        inventory_warehouses = frappe.get_all(
            "Warehouse", 
            filters={"department": "Packing & Dispatch - NJ"}, 
            fields=["name"]
        )

        warehouse_names = [warehouse["name"] for warehouse in inventory_warehouses]

        warehouse_names_string = "', '".join(warehouse_names)

        inventory_data = frappe.db.sql(f"""
            SELECT
                sn.item_code,
                count(sn.name) as current_inventory_qty,
                sn.warehouse
            FROM
                `tabSerial No` sn
            WHERE
                sn.item_code IN ({item_codes_string})
                AND sn.warehouse IN ('{warehouse_names_string}')
            GROUP BY
                sn.item_code, sn.warehouse
        """, as_dict=True)

        
        inventory_map = {inv['item_code']: inv['current_inventory_qty'] for inv in inventory_data}

        print('inventory_map ------- 170', inventory_map)
        
        sales_rates = frappe.db.sql(f"""
            SELECT
                soi.item_code,
                COUNT(DISTINCT so.name) AS total_orders,
                SUM(soi.qty) AS total_quantity,
                SUM(soi.qty) / {days} AS daily_sales_rate,
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

        sales_rates_dict = {rate['item_code']: rate for rate in sales_rates}

        print('sales_rate_dict', sales_rates_dict)
        
        for item in item_code_list:
            item_code = item['item_code']
            item['current_inventory_qty'] = inventory_map.get(item_code, 0)
            if item_code in sales_rates_dict:
                print('item_code', item_code)
                rate_info = sales_rates_dict[item_code]
                item['total_orders'] = rate_info['total_orders']
                item['total_sales_qty'] = rate_info['total_quantity']
                item['daily_sales_rate'] = rate_info['daily_sales_rate']
            else:
                item['total_orders'] = 0
                item['total_sales_qty'] = 0
                item['daily_sales_rate'] = 0
                item['first_sale_date'] = None
                item['last_sale_date'] = None
        
        return item_code_list
    except Exception as e:
        frappe.log_error(title="Error in calculate_sales_order_rate", message=traceback.format_exc())
        return item_code_list
