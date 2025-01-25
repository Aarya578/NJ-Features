import json
import frappe
import traceback
from datetime import date, timedelta

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

        item_code_list = calculate_sales_order_rate_with_weights(item_code_list)
        return item_code_list

    except Exception as e:
        frappe.log_error(title="Error in get_department_details", message=traceback.format_exc())
        return {"status": "error", "message": str(e)}

def calculate_sales_order_rate_with_weights(item_code_list, days=30, weights=None):
    try:
        if not item_code_list:
            return item_code_list

        if not weights:
            weights = {i: i + 1 for i in range(days)} 
        
        item_codes = [item['item_code'] for item in item_code_list]
        if not item_codes:
            return item_code_list

        item_codes_string = ', '.join([f"'{code}'" for code in item_codes])

        inventory_warehouses = frappe.get_all(
            "Warehouse", 
            filters={"department": "Packing & Dispatch - NJ", "warehouse_type": ["!=", "Kitting"]}, 
            fields=["name"]
        )
        warehouse_names = [warehouse["name"] for warehouse in inventory_warehouses]
        warehouse_names_string = "', '".join(warehouse_names)

        inventory_data = frappe.db.sql(f"""
            SELECT
                sn.item_code,
                COUNT(sn.name) as current_inventory_qty,
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

        sales_rates = frappe.db.sql(f"""
            SELECT
                soi.item_code,
                DATE(so.creation) AS sale_date,
                SUM(soi.qty) AS total_sales
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
                soi.item_code, DATE(so.creation);
        """, as_dict=True)

        sales_map = {}
        for sale in sales_rates:
            item_code = sale['item_code']
            sale_date = sale['sale_date']
            total_sales = sale['total_sales']
            
            if item_code not in sales_map:
                sales_map[item_code] = {}
            
            sales_map[item_code][sale_date] = total_sales

        for item in item_code_list:
            item_code = item['item_code']
            item['current_inventory_qty'] = inventory_map.get(item_code, 0)

            if item_code in sales_map:
                total_sales = 0
                weighted_sales_rate = 0

                for day_offset in range(days):
                    sale_date = (frappe.utils.today() - timedelta(days=day_offset)).strftime('%Y-%m-%d')
                    day_sales = sales_map[item_code].get(sale_date, 0)
                    day_weight = weights.get(day_offset, 1) 
                    
                    total_sales += day_sales
                    weighted_sales_rate += (day_sales / day_weight)
                
                item['total_sales_qty'] = total_sales
                item['sales_rate'] = weighted_sales_rate
            else:
                item['total_sales_qty'] = 0
                item['sales_rate'] = 0

        print('Updated Item Code List with Weighted Sales:', item_code_list)

        return item_code_list

    except Exception as e:
        frappe.log_error(title="Error in calculate_sales_order_rate_with_weights", message=traceback.format_exc())
        return item_code_list
