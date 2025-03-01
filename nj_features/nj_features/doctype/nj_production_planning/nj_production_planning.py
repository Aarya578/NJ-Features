import json
import frappe
import traceback
from datetime import datetime, timedelta, date
from frappe.utils import getdate

@frappe.whitelist()
def get_department_details(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)

    dept_doc = frappe.get_doc("Department", {"name": doc.get("department")})
    item_code_counts = {}
    forwarded_item_code_counts = {}

    for row in dept_doc.get("inventory_details_child"):
        if row.get("inwarded_inventory"):
            inwarded_warehouse = row.get("inwarded_warehouse").split(",") if row.get("inwarded_warehouse") else frappe.db.get_all(
                "Warehouse", 
                filters={"department": row.get("inwarded_inventory")}, 
                pluck="name"
            )

            print('inwarded_warehouse', inwarded_warehouse)
            
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

        if row.get("forwarded_inventory"): 
            forwarded_warehouse = row.get("forwarded_warehouse").split(",") if row.get("forwarded_warehouse") else frappe.db.get_all(
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

    item_code_list = []
    all_item_codes = set(item_code_counts.keys()).union(forwarded_item_code_counts.keys())

    print("all_item_codes ------------- 75", all_item_codes)

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

    print("item_code_list ------------- ", item_code_list)
    item_code_list = calculate_sales_order_rate_with_weights(item_code_list)

    print("item_code_list ------------------- ", item_code_list)
    
    for item in item_code_list:
        print('\n\nitem ----------------------- 128', item)
        if item['sales_rate'] > 0:
            item['DOI'] = item['forwarded_qty'] / item['sales_rate']
            print('DOI ------------------- ', item['DOI'])
        else:
            print('coming to else ------------------ 132')
            item['DOI'] = 0
    
    print("item_code_list ------------------------ 134", item_code_list)

    return item_code_list

def calculate_sales_order_rate_with_weights(item_code_list, days=10, weight_factor=2):
    if not item_code_list:
        return item_code_list

    # Assign weights to days
    weights = {i: (i + 1) * weight_factor for i in range(days)}
    total_weight = sum(weights.values())  # Sum of all weights for normalization

    print('total_weight -------------------- 148', total_weight)

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
            sle.qty_after_transaction AS daily_sales, 
            sle.item_code, 
            DATE(sle.creation) AS sale_date
        FROM 
            `tabStock Ledger Entry` sle
        WHERE 
            sle.item_code IN ({item_codes_string})
            AND sle.warehouse IN ('{warehouse_names_string}')
            AND sle.creation >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
        GROUP BY 
            sle.item_code, sale_date
        ORDER BY 
            sale_date ASC
    """, explain=1, debug=1, as_dict=True)

    print('inventory_data -----------------', inventory_data)

    sales_data = frappe.db.sql(f"""
        SELECT
            soi.item_code,
            DATE(so.creation) AS sale_date,
            SUM(soi.qty) AS daily_sales
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
            soi.item_code, sale_date
        ORDER BY
            sale_date DESC
    """, explain=1, debug=1, as_dict=True)

    print("sales_data ----------- ", sales_data)

    sales_map = {}
    for sale in sales_data:
        sale_date = sale['sale_date']
        if isinstance(sale_date, str):
            sale_date = datetime.strptime(sale_date, "%Y-%m-%d").date()

        item_code = sale['item_code']
        sales_map.setdefault(item_code, {})[sale_date] = sale['daily_sales']

    print("sales_map ----------- ", sales_map)

    for item in item_code_list:
        item_code = item['item_code']

        if item_code in sales_map:
            total_sales_qty = sum(sales_map[item_code].values())
            total_weighted_sales = 0

            for day_offset in range(days):
                sales_date = datetime.today().date() - timedelta(days=day_offset)
                daily_sales = sales_map[item_code].get(sales_date, 0)
                weight = weights.get(day_offset, 1)
                total_weighted_sales += daily_sales * weight

            # **Final Weighted Sales Rate Calculation**
            item['total_sales_qty'] = total_sales_qty
            item['sales_rate'] = total_weighted_sales / total_weight if total_weight else 0  
        else:
            item['total_sales_qty'] = 0
            item['sales_rate'] = 0

        print(f"Item: {item_code} | Total Sales: {item['total_sales_qty']} | Weighted Sales Rate: {item['sales_rate']}")

    return item_code_list