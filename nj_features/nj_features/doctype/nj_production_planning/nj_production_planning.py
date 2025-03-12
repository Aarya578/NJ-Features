import json
import frappe
import traceback
from collections import defaultdict
from frappe.utils import getdate, flt
from frappe.model.document import Document
from datetime import datetime, timedelta, date

class NJProductionPlanning(Document):
    pass

@frappe.whitelist()
def get_department_details(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)

    dept_doc = frappe.get_doc("Department", {"name": doc.get("department")})
    item_code_counts = {}
    forwarded_item_code_counts = {}

    model = '0'
    fr_config = '1'

    if model == '1' and fr_config == '1':
        merged_data = {}

        for row in dept_doc.get("inventory_details_child"):
            # Process Inwarded Inventory
            if row.get("inwarded_inventory"):
                inwarded_warehouse = frappe.db.get_all(
                    "Warehouse",
                    filters={"department": row.get("inwarded_inventory")},
                    pluck="name"
                )

                for warehouse in inwarded_warehouse:
                    inwarded_counts = frappe.db.sql("""
                        SELECT COUNT(sn.name) AS count, sn.warehouse, sn.model
                        FROM `tabSerial No` sn
                        JOIN `tabItem Group` i ON sn.item_group = i.name
                        WHERE sn.warehouse = %s
                        AND i.parent_item_group = "Products"
                        GROUP BY sn.model
                    """, (warehouse,), as_dict=True)

                    for item in inwarded_counts:
                        model_name = item["model"]
                        if model_name not in merged_data:
                            merged_data[model_name] = {
                                "inwarded_count": 0,
                                "forwarded_count": 0,
                                "warehouse": item["warehouse"],
                                "item_codes": {}  # Keeping item_codes as a dictionary
                            }
                        merged_data[model_name]["inwarded_count"] += item["count"]

            # Process Forwarded Inventory
            if row.get("forwarded_inventory"):
                forwarded_warehouse = frappe.db.get_all(
                    "Warehouse",
                    filters={"department": row.get("forwarded_inventory")},
                    pluck="name"
                )

                for warehouse in forwarded_warehouse:
                    forwarded_counts = frappe.db.sql("""
                        SELECT sn.item_code, COUNT(sn.name) AS count, sn.warehouse, sn.model
                        FROM `tabSerial No` sn
                        JOIN `tabItem Group` i ON sn.item_group = i.name
                        WHERE sn.warehouse = %s
                        AND i.parent_item_group = "Products"
                        GROUP BY sn.item_code, sn.model
                    """, (warehouse,), as_dict=True)

                    for item in forwarded_counts:
                        model_name = item["model"]
                        if model_name not in merged_data:
                            merged_data[model_name] = {
                                "inwarded_count": 0,
                                "forwarded_count": 0,
                                "warehouse": item["warehouse"],
                                "item_codes": {} 
                            }

                        merged_data[model_name]["forwarded_count"] += item["count"]

                        item_code = item["item_code"]
                        if item_code in merged_data[model_name]["item_codes"]:
                            merged_data[model_name]["item_codes"][item_code] += item["count"]
                        else:
                            merged_data[model_name]["item_codes"][item_code] = item["count"]

        print("Merged Data:", merged_data)

        item_code_list = []

        if merged_data:
            item_code_list = calculate_sales_order_rate_with_weights_for_model_config(merged_data)
        
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

    elif model == '1':

        for row in dept_doc.get("inventory_details_child"):
            if row.get("inwarded_inventory"):
                inwarded_warehouse = frappe.db.get_all(
                    "Warehouse", 
                    filters={"department": row.get("inwarded_inventory")}, 
                    pluck="name"
                )

                for warehouse in inwarded_warehouse:
                    item_counts = frappe.db.sql("""
                        SELECT COUNT(sn.name) AS count, sn.warehouse, sn.model
                        FROM `tabSerial No` sn
                        JOIN `tabItem Group` i ON sn.item_group = i.name
                        WHERE sn.warehouse = %s
                        AND i.parent_item_group = "Products"
                        GROUP BY sn.model
                    """, (warehouse,),as_dict=True)

                    for item in item_counts:
                        model = item['model']
                        count = item['count']
                        
                        if model in item_code_counts:
                            item_code_counts[model] += count
                        else:
                            item_code_counts[model] = count

            if row.get("forwarded_inventory"):

                forwarded_warehouse = frappe.db.get_all(
                    "Warehouse",
                    filters={"department": row.get("forwarded_inventory")},
                    pluck="name"
                )

                forwarded_warehouse = frappe.db.get_all(
                    "Warehouse", 
                    filters={"department": row.get("forwarded_inventory")}, 
                    pluck="name"
                )
                
                for warehouse in forwarded_warehouse:
                    item_counts = frappe.db.sql("""
                        SELECT COUNT(sn.name) AS count, sn.warehouse, sn.model
                        FROM `tabSerial No` sn
                        JOIN `tabItem Group` i ON sn.item_group = i.name
                        WHERE sn.warehouse = %s
                        AND i.parent_item_group = "Products"
                        GROUP BY sn.model
                    """, (warehouse,), as_dict=True)

                    for item in item_counts:
                        model = item['model']
                        count = item['count']

                        
                        if model in forwarded_item_code_counts:
                            forwarded_item_code_counts[model] += count
                        else:
                            forwarded_item_code_counts[model] = count

        item_code_list = []
        
        all_item_codes = set(item_code_counts.keys()).union(forwarded_item_code_counts.keys())

        print("all_item_codes ------------------------- 75", all_item_codes)

        for model in all_item_codes:
            inwarded_qty = item_code_counts.get(model, 0)
            forwarded_qty = forwarded_item_code_counts.get(model, 0)
            item_code_list.append({
                "model": model,
                "inwarded_qty": inwarded_qty,
                "forwarded_qty": forwarded_qty
            })
        
        print("item_code_list ---------------- 128", item_code_list)

        item_code_list = calculate_sales_order_rate_with_weights_for_model(item_code_list)

        print("item_code_list ------------------- ", item_code_list)
        
        for item in item_code_list:
            print('\n\nitem ----------------------- 128', item['forwarded_qty'])
            if item['sales_rate'] > 0:
                item['DOI'] = item['forwarded_qty'] / item['sales_rate']
                print('DOI ------------------- ', item['DOI'])
            else:
                print('coming to else ------------------ 132')
                item['DOI'] = 0
        
        print("item_code_list ------------------------ 134", item_code_list)

        return item_code_list

    else:

        for row in dept_doc.get("inventory_details_child"):
            if row.get("inwarded_inventory"):
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

            if row.get("forwarded_inventory"): 
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
                        i.item_group,
                        i.variant_of as parent
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
                    attributes_map[item_code]['model'] = row['item_model']
                    attributes_map[item_code]['item_group'] = row['item_group']
                    attributes_map[item_code]['parent'] = row['parent']

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


def calculate_sales_order_rate_with_weights_for_model_config(item_code_list, days=7, weight_factor=2):
    if not item_code_list:
        item_code_list = {}

    weights = {i: (i + 1) * weight_factor for i in range(days)}
    total_weight = sum(weights.values())

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
            so.creation >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
            AND so.docstatus = 1
            AND soi.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
        GROUP BY
            soi.item_code, sale_date
        ORDER BY
            sale_date DESC
    """, as_dict=True)

    print("sales_data ------------------  211", sales_data)

    sales_map = {}
    for sale in sales_data:
        sale_date = sale['sale_date']
        if isinstance(sale_date, str):
            sale_date = datetime.strptime(sale_date, "%Y-%m-%d").date()
        item_code = sale['item_code']
        sales_map.setdefault(item_code, {})[sale_date] = sale['daily_sales']
    
    print("sales_map ------------------ ", sales_map)
    
    updated_item_code_list = []
    for model_name, model_data in item_code_list.items():
        inward_qty = model_data['inwarded_count']
        
        for item_code in model_data['item_codes']:

            if item_code not in sales_map:
                updated_item_code_list.append({
                    'model': model_name,
                    'item_code': item_code,
                    'inwarded_qty': inward_qty,
                    'forwarded_qty': model_data['item_codes'][item_code],
                    'total_sales_qty': 0,
                    'sales_rate': 0
                })
                continue
            
            print("item_code in sales_map ----------------- 391", item_code)
            
            total_sales_qty = sum(sales_map[item_code].values())  # Sum of all sales

            # Compute weighted sales if data exists
            total_weighted_sales = sum(
                sales_map[item_code].get(datetime.today().date() - timedelta(days=day_offset), 0) * weights.get(day_offset, 1)
                for day_offset in range(days)
            ) if item_code in sales_map else 0

            sales_rate = total_weighted_sales / total_weight if total_weight else 0

            forwarded_qty = model_data['item_codes'][item_code]  # Get forwarded qty for this item

            updated_item_code_list.append({
                'model': model_name,
                'item_code': item_code,
                'inwarded_qty': inward_qty,
                'forwarded_qty': forwarded_qty,
                'total_sales_qty': total_sales_qty,
                'sales_rate': sales_rate
            })

    # Extract only relevant item_codes from updated_item_code_list
    item_codes = [item['item_code'] for item in updated_item_code_list]

    if item_codes:
        try:
            # Construct query with placeholders
            placeholders = ', '.join(['%s'] * len(item_codes))
            query = f"""
                SELECT 
                    LOWER(iva.attribute) AS item_attribute, 
                    LOWER(iva.attribute_value) AS attribute_value,
                    iva.parent AS item_code,
                    i.item_name,
                    i.item_model,
                    i.item_group,
                    i.variant_of as parent
                FROM `tabItem Variant Attribute` iva
                INNER JOIN `tabItem` i ON iva.parent = i.name
                WHERE iva.parent IN ({placeholders})
            """

            # Fetch data from Frappe database
            attribute_data = frappe.db.sql(query, tuple(item_codes), as_dict=True)

            # Create an attribute mapping dictionary
            attributes_map = {}
            for row in attribute_data:
                item_code = row['item_code']
                attribute = row['item_attribute'].replace(' ', '_')  # Normalize key format
                attribute_value = row['attribute_value']

                if item_code not in attributes_map:
                    attributes_map[item_code] = {
                        'item_name': row['item_name'],
                        'model': row['item_model'],
                        'item_group': row['item_group'],
                        'parent': row['parent']
                    }

                attributes_map[item_code][attribute] = attribute_value

            # Update the existing updated_item_code_list with attribute details
            for item in updated_item_code_list:
                item_code = item['item_code']
                if item_code in attributes_map:
                    item.update(attributes_map[item_code])

            print("Final updated_item_code_list with attributes:", updated_item_code_list)

        except Exception as e:
            print("Error fetching attributes:", str(e))
    

    return updated_item_code_list

def calculate_sales_order_rate_with_weights_for_model(item_code_list, days=7, weight_factor=2):
    if not item_code_list:
        item_code_list = []

    weights = {i: (i + 1) * weight_factor for i in range(days)}
    total_weight = sum(weights.values())

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
            so.creation >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
            AND so.docstatus = 1
            AND soi.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
        GROUP BY
            soi.item_code, sale_date
        ORDER BY
            sale_date DESC
    """, explain=1, debug=1, as_dict=True)

    print("sales_data ------------------  211", sales_data)
    updated_sales_data = []

    for item in sales_data:

        get_model = frappe.db.sql(f"""
            SELECT item_model FROM `tabItem` WHERE name = '{item['item_code']}'
        """, explain=1, debug=1, as_dict=True)

        if get_model:
            updated_sales_data.append({
                "model": get_model[0]['item_model'],
                "sale_date": item['sale_date'],
                "daily_sales": item['daily_sales']
            })
    
    print("updated_sales_data ------------------ 219", updated_sales_data)

    sales_map = {}
    for sale in updated_sales_data:
        sale_date = sale['sale_date']
        if isinstance(sale_date, str):
            sale_date = datetime.strptime(sale_date, "%Y-%m-%d").date()

        model = sale['model']
        sales_map.setdefault(model, {})[sale_date] = sale['daily_sales']
    
    print("sales_map ------------------ 228", sales_map)
    print("item_code_list ------------------ 229", item_code_list)

    updated_item_code_list = []

    for item in item_code_list:
        
        model = item['model']

        if model in sales_map:
            total_sales_qty = sum(sales_map[model].values())
            total_weighted_sales = sum(
                sales_map[model].get(datetime.today().date() - timedelta(days=day_offset), 0) * weights.get(day_offset, 1)
                for day_offset in range(days)
            )
            total_weight = sum(weights.get(day_offset, 1) for day_offset in range(days))
            item['total_sales_qty'] = total_sales_qty
            item['sales_rate'] = total_weighted_sales / total_weight if total_weight else 0  
            updated_item_code_list.append(item)

            print("sales_rate ----------- 242", item['sales_rate'])
        else:
            item['total_sales_qty'] = 0
            item['sales_rate'] = 0

        print(f"Item: {item['model']} | Total Sales: {item['total_sales_qty']} | Weighted Sales Rate: {item['sales_rate']}")

    print("updated_item_code_list ------------------ 246", updated_item_code_list)

    return updated_item_code_list


def calculate_sales_order_rate_with_weights(item_code_list, days=20, weight_factor=2):
    if not item_code_list:
        item_code_list = []

    weights = {i: (i + 1) * weight_factor for i in range(days)}
    total_weight = sum(weights.values())

    print('total_weight -------------------- 148', total_weight)

    item_codes = [item['item_code'] for item in item_code_list]
    item_codes_string = ', '.join([f"'{code}'" for code in item_codes]) if item_codes else "''"

    inventory_warehouses = frappe.get_all(
        "Warehouse", 
        filters={"department": "Packing & Dispatch - NJ"}, 
        fields=["name"]
    )

    warehouse_names = [warehouse["name"] for warehouse in inventory_warehouses]
    warehouse_names_string = "', '".join(warehouse_names) if warehouse_names else "''"

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
            so.creation >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
            AND so.docstatus = 1
            AND soi.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
        GROUP BY
            soi.item_code, sale_date
        ORDER BY
            sale_date DESC
    """, explain=1, debug=1, as_dict=True)

    print("sales_data ------------------  211", sales_data)

    sales_map = {}
    for sale in sales_data:
        sale_date = sale['sale_date']
        if isinstance(sale_date, str):
            sale_date = datetime.strptime(sale_date, "%Y-%m-%d").date()

        item_code = sale['item_code']
        sales_map.setdefault(item_code, {})[sale_date] = sale['daily_sales']

        if item_code not in item_codes:
            # Generate placeholders dynamically

            attribute_data = frappe.db.sql("""
                SELECT 
                    LOWER(iva.attribute) AS item_attribute, 
                    LOWER(iva.attribute_value) AS attribute_value,
                    iva.parent AS item_code,
                    i.item_name,
                    i.item_model,
                    i.item_group,
                    i.variant_of as parent
                FROM `tabItem Variant Attribute` iva
                INNER JOIN `tabItem` i ON iva.parent = i.name
                WHERE iva.parent = %s
            """, (item_code,), as_dict=True)

            print("attribute_data ----------------- 241", attribute_data)
        
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
                attributes_map[item_code]['parent'] = row['parent']
            
            print("attribute_data ----------------- 241", attributes_map)
            
            item_code_list.append({
                "item_code": item_code,
                "forwarded_qty": 0,
                "inventory_qty": 0, 
                "total_sales_qty": 0, 
                "sales_rate": 0,
                "item_model": attributes_map[item_code].get("item_model"),
                "processor_type": attributes_map[item_code].get("processor_type"),
                "storage_capacity": attributes_map[item_code].get("storage_capacity"), 
                "ram_capacity": attributes_map[item_code].get("ram_capacity")
                })

    print("sales_map ----------- ", sales_map)

    updated_item_code_list = []

    for item in item_code_list:
        item_code = item['item_code']

        if item_code in sales_map:
            total_sales_qty = sum(sales_map[item_code].values())
            total_weighted_sales = sum(
                sales_map[item_code].get(datetime.today().date() - timedelta(days=day_offset), 0) * weights.get(day_offset, 1)
                for day_offset in range(days)
            )
            item['total_sales_qty'] = total_sales_qty
            item['sales_rate'] = total_weighted_sales / total_weight if total_weight else 0  
            updated_item_code_list.append(item)
        else:
            item['total_sales_qty'] = 0
            item['sales_rate'] = 0

        print(f"Item: {item_code} | Total Sales: {item['total_sales_qty']} | Weighted Sales Rate: {item['sales_rate']}")

    return updated_item_code_list


@frappe.whitelist()
def calculate_to_make(doc, DOI_threshold=10):

    if isinstance(doc, str):
        doc = frappe.parse_json(doc)

    for item in doc.get("nj_production_planning_child", []):
        sales_rate = flt(item.get("sales_rate", 0)) 
        forwarded_qty = flt(item.get("forwarded_qty", 0)) 
        inwarded_qty = flt(item.get("inwarded_qty", 0)) 

        to_make = (forwarded_qty - inwarded_qty) + (sales_rate * DOI_threshold)
        to_make = max(0, round(to_make))
        
        item["to_make"] = to_make
    
    suggested_serial_no = suggest_to_make_serial_no(doc.get("nj_production_planning_child", []), doc.get("department"))

    return {
        "to_make": doc.get("nj_production_planning_child", []), 
        "suggested_serial": suggested_serial_no
    }

def suggest_to_make_serial_no(nj_pro_child, department=None):

    print("nj_pro_child -------------------------- ", nj_pro_child)

    if not nj_pro_child:
        return []

    if not department:
        return [] 

    try:
        dept_doc = frappe.get_doc("Department", department)
    except frappe.DoesNotExistError:
        return [] 

    frw_inventory = []

    for item in dept_doc.get("inventory_details_child", []):
        frw_inventory_data = frappe.db.get_all(
            "Warehouse",
            filters={"department": item.get("forwarded_inventory")},
            pluck="name"
        )
        frw_inventory.extend(frw_inventory_data)

    print("frw_inventory ---------------- ", frw_inventory)

    if not frw_inventory:
        return []

    get_serial_no_config = frappe.db.sql("""
        SELECT model, item_code, COUNT(*) AS count
        FROM `tabSerial No`
        WHERE model IS NOT NULL AND warehouse IN %(warehouses)s
        GROUP BY model, item_code
    """, {"warehouses": tuple(frw_inventory)}, as_dict=True)

    print("get_serial_no ---------------- ", get_serial_no_config)

    if get_serial_no_config:

        item_codes = list(set(item["item_code"].strip() for item in get_serial_no_config))

        if item_codes:
            placeholders = ", ".join(["%s"] * len(item_codes))  
            query = f"""
                SELECT 
                    LOWER(iva.attribute) AS item_attribute, 
                    LOWER(iva.attribute_value) AS attribute_value,
                    iva.parent AS item_code,
                    i.item_name,
                    i.item_model,
                    i.item_group,
                    i.variant_of AS parent
                FROM `tabItem Variant Attribute` iva
                INNER JOIN `tabItem` i ON iva.parent = i.name
                WHERE iva.parent IN ({placeholders})
            """

            attribute_data = frappe.db.sql(query, tuple(item_codes), as_dict=True)

            attributes_map = {}
            for row in attribute_data:
                item_code = row['item_code'].strip().lower()  
                attribute = row['item_attribute'].replace(' ', '_')  
                attribute_value = row['attribute_value']

                if item_code not in attributes_map:
                    attributes_map[item_code] = {
                        'item_name': row['item_name'],
                        'model': row['item_model'],
                        'item_group': row['item_group'],
                        'parent': row['parent']
                    }

                attributes_map[item_code][attribute] = attribute_value

            for item in get_serial_no_config:
                item_code = item['item_code'].strip().lower()  
                if item_code in attributes_map:
                    item.update(attributes_map[item_code])
    

    return get_serial_no_data(nj_pro_child, get_serial_no_config, frw_inventory)

def get_serial_no_data(nj_pro_child, get_serial_no_config, frw_inventory):

    for child in nj_pro_child:

        if child.get("to_make", 0) > 0:

            for item in get_serial_no_config:

                if (
                    child.get("model", "").strip().lower() == item.get("model", "").strip().lower() and
                    child.get("processor", "").strip().lower() == item.get("processor_type", "").strip().lower() and
                    child.get("ram", "").strip().lower() == item.get("ram_capacity", "").strip().lower() and
                    child.get("ssd", "").strip().lower() == item.get("storage_capacity", "").strip().lower()
                ):

                    get_suggested_serial_no = frappe.db.sql("""
                        SELECT name FROM `tabSerial No`
                        WHERE warehouse IN %s AND item_code = %s
                        LIMIT %s
                    """, (tuple(frw_inventory), item.get("item_code"), child.get("to_make")), as_dict=True)
                    
                    suggest_serial_no = [row.get("name") for row in get_suggested_serial_no]

                    item["suggested_serial_no"] = suggest_serial_no
    
    return get_serial_no_config