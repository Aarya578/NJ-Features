import json
import math
import frappe
import traceback
from collections import defaultdict
from frappe.utils import getdate, flt
from frappe.model.document import Document
from datetime import datetime, timedelta, date

class NJProductionPlanning(Document):
    pass

@frappe.whitelist()
def get_department_details():

    all_dept = frappe.db.get_all("Department", ["name"])

    for dept in all_dept:
        dept_doc = get_department_document(dept.get("name"))

        in_model = dept_doc.get("inwarded_model") 
        in_config = dept_doc.get("inwarded_config")
        fw_model = dept_doc.get("forwarded_model") 
        fw_config = dept_doc.get("forwarded_config")

        if str(in_model) == '1' and str(fw_model) == '1':
            data = process_model_configuration(dept_doc)
            new_doc = create_production_planning(data, dept.get("name"))
            calculate_to_make(new_doc)
            suggest_to_make_serial_no(new_doc.get("nj_production_planning_child"), new_doc, department=dept.get("name"))
        elif str(in_model) == '1' and str(fw_config) == '1':
            data = process_merged_configuration(dept_doc)
            new_doc = create_production_planning(data, dept.get("name"))
            calculate_to_make(new_doc)
            suggest_to_make_serial_no(new_doc.get("nj_production_planning_child"), new_doc, department=dept.get("name"))
        elif str(in_config) == '1' and str(fw_config) == '1':
            data = process_default_configuration(dept_doc)
            new_doc = create_production_planning(data, dept.get("name"))
            calculate_to_make(new_doc)
            suggest_to_make_serial_no(new_doc.get("nj_production_planning_child"), new_doc, department=dept.get("name"))

@frappe.whitelist()
def create_production_planning(data, department):
    new_doc = frappe.new_doc("NJ Production Planning")

    for item in data:
        new_doc.department = department
        child = new_doc.append("nj_production_planning_child", {})
        child.model = item.get("model", "").upper() if item.get("model", "") else ""
        child.processor = item.get("processor_type", "").upper() if item.get("processor_type", "") else ""
        child.ram = item.get("ram_capacity", "").upper() if item.get("ram_capacity", "") else ""
        child.ssd = item.get("storage_capacity", "").upper() if item.get("storage_capacity", "") else ""
        child.sales_rate = item.get("sales_rate", 0.0)
        child.inward_inventory = item.get("inwarded_qty", 0.0)
        child.forward_inventory = item.get("forwarded_qty", 0.0)
        child.days_of_inventory = item.get("DOI", 0.0)
        child.to_make = item.get("to_make", 0.0)
        child.item_code = item.get("item_code", "")

    new_doc.insert()
    frappe.db.commit()

    return new_doc

def parse_document(doc):
    if isinstance(doc, str):
        return json.loads(doc)
    return doc

def get_department_document(department_name):
    return frappe.get_doc("Department", {"name": department_name})

def process_merged_configuration(dept_doc):
    merged_data = process_inventory_rows(dept_doc)
    days = frappe.db.get_single_value("NJ Production Planning Settings", "days")
    weight_factor = frappe.db.get_single_value("NJ Production Planning Settings", "weight_factor")
    # merged_data = get_shopify_items(merged_data)
    item_code_list = calculate_sales_order_rate_with_weights_for_model_config(merged_data, days=int(days), weight_factor=int(weight_factor))
    return calculate_doi(item_code_list)

def process_inventory_rows(dept_doc):
    merged_data = {}
    for row in dept_doc.get("inventory_details_child"):
        process_inwarded_inventory_merged(row, merged_data)
        process_forwarded_inventory_merged(row, merged_data, dept_doc)
    return merged_data

def process_inwarded_inventory_merged(row, merged_data):
    if row.get("inwarded_inventory"):
        if row.get("inwarded_warehouse_list"):
            warehouses = row.get("inwarded_warehouse_list").split(",")
        else:
            warehouses = get_warehouses(row.get("inwarded_inventory"))
        for warehouse in warehouses:
            counts = get_inwarded_counts_merged(warehouse)
            update_merged_counts(merged_data, counts, warehouse, "inwarded_count")

def process_forwarded_inventory_merged(row, merged_data, dept_doc):
    query = """
        SELECT name FROM `tabWarehouse`
        WHERE department IN (
                SELECT name FROM `tabDepartment`
                WHERE department_sequence > %s
            )
    """
    warehouses = frappe.db.sql(query, (dept_doc.get("department_sequence"),), as_dict=True)
    all_warehouse = [row.get("name") for row in warehouses]

    for warehouse in all_warehouse:
        counts = get_forwarded_counts_merged(warehouse)
        update_merged_counts(merged_data, counts, warehouse, "forwarded_count")

def get_warehouses(department):
    return frappe.db.get_all(
        "Warehouse",
        filters={"department": department},
        pluck="name"
    )

def get_inwarded_counts_merged(warehouse):
    return frappe.db.sql("""
        SELECT COUNT(sn.name) AS count, sn.model
        FROM `tabSerial No` sn
        JOIN `tabItem Group` i ON sn.item_group = i.name
        WHERE sn.warehouse = %s
        AND i.parent_item_group = "Products"
        GROUP BY sn.model
    """, (warehouse,), as_dict=True)

def get_forwarded_counts_merged(warehouse):
    
    return frappe.db.sql("""
        SELECT sn.item_code, COUNT(sn.name) AS count, sn.model
        FROM `tabSerial No` sn
        JOIN `tabItem Group` i ON sn.item_group = i.name
        WHERE sn.warehouse = %s
        AND i.parent_item_group = "Products"
        GROUP BY sn.item_code, sn.model
    """, (warehouse,), as_dict=True)

def update_merged_counts(merged_data, counts, warehouse, count_type):

    for item in counts:
        model = item.get("model")
        if not model:
            continue
            
        if model not in merged_data:
            merged_data[model] = {
                "inwarded_count": 0,
                "forwarded_count": 0,
                "warehouse": warehouse,
                "item_codes": {}
            }
        
        merged_data[model][count_type] += item.get("count", 0)
        
        if count_type == "forwarded_count":
            item_code = item.get("item_code")
            if item_code:
                merged_data[model]["item_codes"][item_code] = merged_data[model]["item_codes"].get(item_code, 0) + item.get("count", 0)

def process_model_configuration(dept_doc):
    inwarded_counts = get_model_counts(dept_doc, "inwarded_inventory")
    forwarded_counts = get_model_counts(dept_doc, "forwarded_inventory")
    item_code_list = merge_model_counts(inwarded_counts, forwarded_counts)
    days = frappe.db.get_single_value("NJ Production Planning Settings", "days") or 30
    weight_factor = frappe.db.get_single_value("NJ Production Planning Settings", "weight_factor") or 1.0
    item_code_list = calculate_sales_order_rate_with_weights_for_model(item_code_list, days=int(days), weight_factor=int(weight_factor))
    return calculate_doi(item_code_list)

def get_model_counts(dept_doc, inventory_type):
    counts = {}
    for row in dept_doc.get("inventory_details_child"):
        department = row.get(inventory_type)
        if department:
            if inventory_type == "inwarded_inventory" and row.get("inwarded_warehouse_list"):
                warehouses = row.get("inwarded_warehouse_list").split(",")
            else:
                warehouses = get_warehouses(department)
            for warehouse in warehouses:
                query = """
                    SELECT COUNT(sn.name) AS count, sn.model
                    FROM `tabSerial No` sn
                    JOIN `tabItem Group` i ON sn.item_group = i.name
                    WHERE sn.warehouse = %s
                    AND i.parent_item_group = "Products"
                    GROUP BY sn.model
                """
                results = frappe.db.sql(query, (warehouse,), as_dict=True)
                update_counts(counts, results)
    return counts

def merge_model_counts(inwarded, forwarded):
    return [{
        "model": model,
        "inwarded_qty": inwarded.get(model, 0),
        "forwarded_qty": forwarded.get(model, 0)
    } for model in set(inwarded) | set(forwarded)]

def process_default_configuration(dept_doc):
    inwarded_counts = get_item_counts(dept_doc, "inwarded_inventory")
    forwarded_counts = get_item_counts(dept_doc, "forwarded_inventory")
    item_code_list = merge_item_counts(inwarded_counts, forwarded_counts)
    item_code_list = fetch_item_attributes(item_code_list)
    days = frappe.db.get_single_value("NJ Production Planning Settings", "days")
    weight_factor = frappe.db.get_single_value("NJ Production Planning Settings", "weight_factor")
    item_code_list = calculate_sales_order_rate_with_weights(item_code_list, days=int(days), weight_factor=int(weight_factor))
    return calculate_doi(item_code_list)

def get_item_counts(dept_doc, inventory_type):
    counts = {}
    for row in dept_doc.get("inventory_details_child"):
        department = row.get(inventory_type)
        if department:
            if inventory_type == "inwarded_inventory" and row.get("inwarded_warehouse_list"):
                warehouses = row.get("inwarded_warehouse_list").split(",")
            else:
                warehouses = get_warehouses(department)
            for warehouse in warehouses:
                query = """
                    SELECT sn.item_code, COUNT(sn.name) AS count
                    FROM `tabSerial No` sn
                    JOIN `tabItem Group` i ON sn.item_group = i.name
                    WHERE sn.warehouse = %s
                    AND i.parent_item_group = "Products"
                    GROUP BY sn.item_code
                """
                results = frappe.db.sql(query, (warehouse,), as_dict=True)
                update_counts(counts, results)
    return counts

def merge_item_counts(inwarded, forwarded):
    return [{
        "item_code": code,
        "inwarded_qty": inwarded.get(code, 0),
        "forwarded_qty": forwarded.get(code, 0)
    } for code in set(inwarded) | set(forwarded)]

def fetch_item_attributes(item_list):
    item_codes = [item["item_code"] for item in item_list if item.get("item_code")]
    if not item_codes:
        return item_list
        
    try:
        placeholders = ", ".join(["%s"] * len(item_codes))
        attributes = frappe.db.sql(f"""
            SELECT 
                LOWER(iva.attribute) AS attribute,
                LOWER(iva.attribute_value) AS value,
                iva.parent AS code,
                i.item_name,
                i.item_model,
                i.item_group,
                i.variant_of
            FROM `tabItem Variant Attribute` iva
            JOIN `tabItem` i ON iva.parent = i.name
            WHERE iva.parent IN ({placeholders})
        """, tuple(item_codes), as_dict=True)
        
        attr_map = {}
        for attr in attributes:
            code = attr["code"]
            if code not in attr_map:
                attr_map[code] = {
                    "item_name": attr["item_name"],
                    "model": attr["item_model"],
                    "item_group": attr["item_group"],
                    "parent": attr["variant_of"]
                }
            attr_map[code][attr["attribute"].replace(" ", "_")] = attr["value"]
        
        for item in item_list:
            if item["item_code"] in attr_map:
                item.update(attr_map[item["item_code"]])
                
    except Exception:
        frappe.log_error(title="Attribute Fetch Error", message=traceback.format_exc())
        
    return item_list

def update_counts(count_dict, results):
    for item in results:
        key = item.get("model") or item.get("item_code")
        if key:
            count_dict[key] = count_dict.get(key, 0) + item.get("count", 0)

def calculate_doi(items):
    for item in items:
        forwarded_qty = item.get("forwarded_qty", 0)
        sales_rate = item.get("sales_rate", 0)
        
        if forwarded_qty < 0 or sales_rate < 0:
            item["DOI"] = 0  
        elif sales_rate == 0:
            item["DOI"] = float('inf')
        else:
            item["DOI"] = forwarded_qty / sales_rate

    items = sorted(items, key=lambda x: x['DOI'])

    return items

def calculate_sales_order_rate_with_weights_for_model_config(item_code_list, days=None, weight_factor=None):

    merged_data = item_code_list

    if not item_code_list:
        item_code_list = {}

    weights = {i: (days - i) * weight_factor for i in range(days)}
    total_weight = sum(weights.values())

    sales_data = frappe.db.sql(f"""
        WITH SalesData AS (
                -- Fetch data for stock items directly from Sales Order Item
                SELECT
                    soi.item_code,
                    i.item_name,
                    i.is_stock_item,
                    DATE(so.creation) AS sale_date,
                    SUM(soi.qty) AS daily_sales
                FROM
                    `tabSales Order` so
                INNER JOIN
                    `tabSales Order Item` soi ON so.name = soi.parent
                INNER JOIN
                    `tabItem` i ON soi.item_code = i.item_code
                WHERE
                    so.creation >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
                    AND so.docstatus = 1
                    AND soi.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
                    AND i.is_stock_item = 1  -- Only take stock items
                GROUP BY
                    soi.item_code, i.item_name, i.is_stock_item, sale_date

                UNION ALL

                -- Fetch data for bundle items (is_stock_item = 0) from Packed Item table
                SELECT
                    pi.item_code,
                    i.item_name,
                    i.is_stock_item,
                    DATE(so.creation) AS sale_date,
                    SUM(pi.qty) AS daily_sales
                FROM
                    `tabSales Order` so
                INNER JOIN
                    `tabPacked Item` pi ON so.name = pi.parent
                INNER JOIN
                    `tabItem` i ON pi.item_code = i.item_code
                INNER JOIN
                    `tabSales Order Item` soi ON pi.parent_detail_docname = soi.name
                WHERE
                    so.creation >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
                    AND so.docstatus = 1
                    AND soi.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
                    AND soi.item_code IN (SELECT item_code FROM `tabItem` WHERE is_stock_item = 0)  
                    AND i.is_stock_item = 1
                    -- Only take packed items from non-stock (bundle) items
                GROUP BY
                    pi.item_code, i.item_name, i.is_stock_item, sale_date
            )
            SELECT * FROM SalesData
            ORDER BY sale_date DESC
    """, as_dict=True)

    sales_map = {}
    for sale in sales_data:
        sale_date = sale['sale_date']
        if isinstance(sale_date, str):
            sale_date = datetime.strptime(sale_date, "%Y-%m-%d").date()
        item_code = sale['item_code']
        sales_map.setdefault(item_code, {})[sale_date] = sale['daily_sales']
    
    updated_item_code_list = []
    for model_name, model_data in item_code_list.items():
        inward_qty = model_data['inwarded_count']
        
        for item_code in model_data['item_codes']:

            if item_code not in sales_map:
                continue
            
            total_sales_qty = sum(sales_map[item_code].values())

            total_weighted_sales = sum(
                        sales_map[item_code].get(datetime.today().date() - timedelta(days=day_offset), 0) * weights.get(day_offset, 0)
                        for day_offset in range(days + 1)
                    ) if item_code in sales_map else 0

            sales_rate = total_weighted_sales / total_weight if total_weight else 0

            forwarded_qty = model_data['item_codes'][item_code] 

            updated_item_code_list.append({
                'model': model_name,
                'item_code': item_code,
                'inwarded_qty': inward_qty,
                'forwarded_qty': forwarded_qty,
                'total_sales_qty': total_sales_qty,
                'sales_rate': sales_rate
            })

    item_codes = [item['item_code'] for item in updated_item_code_list]

    if item_codes:
        try:

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

            attribute_data = frappe.db.sql(query, tuple(item_codes), as_dict=True)

            attributes_map = {}
            for row in attribute_data:
                item_code = row['item_code']
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

            for item in updated_item_code_list:
                item_code = item['item_code']
                if item_code in attributes_map:
                    item.update(attributes_map[item_code])

        except Exception as e:
            print("Error fetching attributes:", str(e))

    updated_item_code_list = get_shopify_variant_item_code(merged_data, updated_item_code_list)

    return updated_item_code_list

def get_shopify_variant_item_code(merged_data, updated_item_code_list):
    model_list = list(merged_data.keys())
    placeholders = ', '.join(['%s'] * len(model_list))

    query = f"""
        SELECT              
            DISTINCT pbi.item_code AS item_code       
        FROM
            `tabItem` i                         
        INNER JOIN
            `tabProduct Bundle Item` pbi ON i.name = pbi.parent
        INNER JOIN
            `tabItem` ci ON pbi.item_code = ci.name  
        WHERE
            i.shopify_product_id IS NOT NULL
            AND i.shopify_product_id != ''
            AND i.item_model IN ({placeholders})
            AND ci.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes');
    """
    bundle_items = frappe.db.sql(query, tuple(model_list), as_dict=True)

    updated_item_code_map = {item['item_code']: item for item in updated_item_code_list}
    new_item_codes = [item['item_code'] for item in bundle_items if item['item_code'] not in updated_item_code_map]

    config_map = {}

    if new_item_codes:
        placeholders_new = ', '.join(['%s'] * len(new_item_codes))
        config_query = f"""
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
            WHERE iva.parent IN ({placeholders_new})
        """
        item_configs = frappe.db.sql(config_query, tuple(new_item_codes), as_dict=True)

        config_map = defaultdict(dict)
        for item in item_configs:
            item_code = item['item_code']
            config_map[item_code]['item_model'] = item['item_model']
            config_map[item_code]['item_name'] = item['item_name']
            config_map[item_code]['item_group'] = item['item_group']
            config_map[item_code]['parent'] = item['parent']
            config_map[item_code][item['item_attribute']] = item['attribute_value']

    for bundle in bundle_items:
        code = bundle['item_code']

        if code in updated_item_code_map:
            if updated_item_code_map[code].get('sales_rate', 0) == 0:
                updated_item_code_map[code]['sales_rate'] = 1
        else:
            config = config_map.get(code, {})
            new_row = {
                'model': config.get('item_model'),
                'item_code': code,
                'inwarded_qty': merged_data.get(config.get('item_model'), {}).get('inwarded_count', 0),
                'forwarded_qty': 0,
                'total_sales_qty': 0.0,
                'sales_rate': 1,
                'item_name': config.get('item_name', code),
                'item_group': config.get('item_group'),
                'parent': config.get('parent'),
                'storage_capacity': config.get('storage capacity'),
                'processor_type': config.get('processor type'),
                'ram_capacity': config.get('ram capacity')
            }
            updated_item_code_list.append(new_row)

    return updated_item_code_list

def calculate_sales_order_rate_with_weights_for_model(item_code_list, days=None, weight_factor=None):
    if not item_code_list:
        item_code_list = []

    weights = {i: (i + 1) * weight_factor for i in range(days)}
    total_weight = sum(weights.values())

    sales_data = frappe.db.sql(f"""
        WITH SalesData AS (
                -- Fetch data for stock items directly from Sales Order Item
                SELECT
                    soi.item_code,
                    i.item_name,
                    i.is_stock_item,
                    DATE(so.creation) AS sale_date,
                    SUM(soi.qty) AS daily_sales
                FROM
                    `tabSales Order` so
                INNER JOIN
                    `tabSales Order Item` soi ON so.name = soi.parent
                INNER JOIN
                    `tabItem` i ON soi.item_code = i.item_code
                WHERE
                    so.creation >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
                    AND so.docstatus = 1
                    AND soi.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
                    AND i.is_stock_item = 1  -- Only take stock items
                GROUP BY
                    soi.item_code, i.item_name, i.is_stock_item, sale_date

                UNION ALL

                -- Fetch data for bundle items (is_stock_item = 0) from Packed Item table
                SELECT
                    pi.item_code,
                    i.item_name,
                    i.is_stock_item,
                    DATE(so.creation) AS sale_date,
                    SUM(pi.qty) AS daily_sales
                FROM
                    `tabSales Order` so
                INNER JOIN
                    `tabPacked Item` pi ON so.name = pi.parent
                INNER JOIN
                    `tabItem` i ON pi.item_code = i.item_code
                INNER JOIN
                    `tabSales Order Item` soi ON pi.parent_detail_docname = soi.name
                WHERE
                    so.creation >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
                    AND so.docstatus = 1
                    AND soi.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
                    AND soi.item_code IN (SELECT item_code FROM `tabItem` WHERE is_stock_item = 0)  
                    AND i.is_stock_item = 1
                    -- Only take packed items from non-stock (bundle) items
                GROUP BY
                    pi.item_code, i.item_name, i.is_stock_item, sale_date
            )
            SELECT * FROM SalesData
            ORDER BY sale_date DESC
    """, as_dict=True)

    updated_sales_data = []

    for item in sales_data:

        get_model = frappe.db.sql(f"""
            SELECT item_model FROM `tabItem` WHERE name = '{item['item_code']}'
        """, as_dict=True)

        if get_model:
            updated_sales_data.append({
                "model": get_model[0]['item_model'],
                "sale_date": item['sale_date'],
                "daily_sales": item['daily_sales']
            })
    
    sales_map = {}
    for sale in updated_sales_data:
        sale_date = sale['sale_date']
        if isinstance(sale_date, str):
            sale_date = datetime.strptime(sale_date, "%Y-%m-%d").date()

        model = sale['model']
        sales_map.setdefault(model, {})[sale_date] = sale['daily_sales']

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

        else:
            item['total_sales_qty'] = 0
            item['sales_rate'] = 0

    return updated_item_code_list

def calculate_sales_order_rate_with_weights(item_code_list, days=None, weight_factor=None):
    if not item_code_list:
        item_code_list = []

    weights = {i: (i + 1) * weight_factor for i in range(days)}
    total_weight = sum(weights.values())

    item_codes = [item['item_code'] for item in item_code_list]
    item_codes_string = ', '.join([f"'{code}'" for code in item_codes]) if item_codes else "''"

    inventory_warehouses = frappe.get_all(
        "Warehouse", 
        filters={"department": "Packing & Dispatch - NJ"}, 
        fields=["name"]
    )

    sales_data = frappe.db.sql(f"""
        WITH SalesData AS (
                -- Fetch data for stock items directly from Sales Order Item
                SELECT
                    soi.item_code,
                    i.item_name,
                    i.is_stock_item,
                    DATE(so.creation) AS sale_date,
                    SUM(soi.qty) AS daily_sales
                FROM
                    `tabSales Order` so
                INNER JOIN
                    `tabSales Order Item` soi ON so.name = soi.parent
                INNER JOIN
                    `tabItem` i ON soi.item_code = i.item_code
                WHERE
                    so.creation >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
                    AND so.docstatus = 1
                    AND soi.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
                    AND i.is_stock_item = 1  -- Only take stock items
                GROUP BY
                    soi.item_code, i.item_name, i.is_stock_item, sale_date

                UNION ALL

                -- Fetch data for bundle items (is_stock_item = 0) from Packed Item table
                SELECT
                    pi.item_code,
                    i.item_name,
                    i.is_stock_item,
                    DATE(so.creation) AS sale_date,
                    SUM(pi.qty) AS daily_sales
                FROM
                    `tabSales Order` so
                INNER JOIN
                    `tabPacked Item` pi ON so.name = pi.parent
                INNER JOIN
                    `tabItem` i ON pi.item_code = i.item_code
                INNER JOIN
                    `tabSales Order Item` soi ON pi.parent_detail_docname = soi.name
                WHERE
                    so.creation >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
                    AND so.docstatus = 1
                    AND soi.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
                    AND soi.item_code IN (SELECT item_code FROM `tabItem` WHERE is_stock_item = 0)  
                    AND i.is_stock_item = 1
                    -- Only take packed items from non-stock (bundle) items
                GROUP BY
                    pi.item_code, i.item_name, i.is_stock_item, sale_date
            )
            SELECT * FROM SalesData
            ORDER BY sale_date DESC

    """, as_dict=True) 

    sales_map = {}
    for sale in sales_data:
        sale_date = sale['sale_date']
        if isinstance(sale_date, str):
            sale_date = datetime.strptime(sale_date, "%Y-%m-%d").date()

        item_code = sale['item_code']
        sales_map.setdefault(item_code, {})[sale_date] = sale['daily_sales']

        if item_code not in item_codes:

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

    return updated_item_code_list

def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def sort_by_multiple_keys(configs, keys):
    def sort_key(cfg):
        key_values = []
        for key in keys:
            reverse = key.startswith("-")
            actual_key = key.lstrip("-")
            value = cfg.get(actual_key, 0)
            key_values.append(-value if reverse else value)
        return tuple(key_values)
    return sorted(configs, key=sort_key)

def calculate_to_make(doc):
    if isinstance(doc, dict):
        doc = frappe.get_doc(doc)
    
    print("doc --------------- ", doc.as_dict())

    # Reset all to_make values to 0 before calculation
    for child in doc.get("nj_production_planning_child", []):
        child.to_make = 0

    # Create working copies with only needed fields
    temp_config = []
    for child in doc.get("nj_production_planning_child", []):
        temp_config.append({
            "item_code": child.get("item_code"),
            "sales_rate": child.get("sales_rate", 0),
            "inward_inventory": child.get("inward_inventory", 0),
            "forward_inventory": child.get("forward_inventory", 0),
            "days_of_inventory": child.get("days_of_inventory", 0),
            "to_make": 0,  # Start fresh calculation
            "model": child.get("model", ""),
            "processor": child.get("processor", ""),
            "ram": child.get("ram", ""),
            "ssd": child.get("ssd", "")
        })
    
    # Create mapping to original child items
    child_map = {child.get("item_code"): child for child in doc.get("nj_production_planning_child", [])}
    
    # Sort by DOI ascending
    temp_config = sorted(temp_config, key=lambda x: x.get("days_of_inventory", 0))
    
    rank = 0
    allocated_in_pass = True

    # Allocation algorithm
    while allocated_in_pass and any(c.get("inward_inventory", 0) > 0 for c in temp_config):
        allocated_in_pass = False
        temp_config = sorted(temp_config, key=lambda x: x.get("days_of_inventory", 0))
        
        for i in range(len(temp_config) - 1):
            current = temp_config[i]
            next_cfg = temp_config[i + 1]

            if current.get("inward_inventory", 0) <= 0:
                continue

            # Calculate gap between current and next DOI
            current_doi = current.get("days_of_inventory", 0)
            next_doi = next_cfg.get("days_of_inventory", 0)
            doi_gap = max(0, next_doi - current_doi)

            # Calculate needed units
            sales_rate = current.get("sales_rate", 0)
            needed_units = math.ceil((doi_gap + 1) * sales_rate)
            make_units = min(needed_units, current.get("inward_inventory", 0))

            if make_units > 0:
                # Update temporary config
                current["to_make"] += make_units
                current["inward_inventory"] -= make_units
                current["forward_inventory"] += make_units
                
                # Update DOI (only in temp for calculation)
                if sales_rate > 0:
                    current["days_of_inventory"] = current["forward_inventory"] / sales_rate
                else:
                    current["days_of_inventory"] = 0

                # Update ONLY to_make in main child table
                original_child = child_map.get(current["item_code"])

                if original_child:
                    original_child.to_make = current["to_make"]

                # Add to final_config table with full details
                child_row = doc.append("final_config", {})
                child_row.sales_rate = sales_rate
                child_row.date = datetime.now()
                child_row.inward_inventory = current["inward_inventory"]
                child_row.forward_inventory = current["forward_inventory"]
                child_row.days_of_inventory = current["days_of_inventory"]
                child_row.to_make = current["to_make"]
                child_row.item_code = current["item_code"]
                child_row.model = current.get("model")
                child_row.processor = current.get("processor")
                child_row.ram = current.get("ram")
                child_row.ssd = current.get("ssd")
                
                rank += 1
                child_row.rank = rank
                allocated_in_pass = True

    # Save document to persist changes
    doc.save()
    return doc.get("nj_production_planning_child", [])


def suggest_to_make_serial_no(nj_pro_child, doc, department=None):
    if not nj_pro_child or not department:
        return []

    try:
        dept_doc = frappe.get_doc("Department", department)
    except frappe.DoesNotExistError:
        return []

    inw_inventory = []
    for item in dept_doc.get("inventory_details_child", []):
        inw_inventory_data = frappe.db.get_all(
            "Warehouse",
            filters={"department": item.get("inwarded_inventory")},
            pluck="name"
        )
        inw_inventory.extend(inw_inventory_data)

    if not inw_inventory:
        return []

    raw_data = frappe.db.sql("""
        SELECT 
            Sr.name AS serial_no,
            Sr.item_code,
            Sr.warehouse,
            Sr.Model,
            IVA.Attribute,
            IVA.attribute_value
        FROM
            `tabSerial No` Sr
                INNER JOIN
            `tabItem` I ON Sr.item_code = I.item_code
                INNER JOIN
            `tabItem Variant Attribute` IVA ON IVA.parent = I.name
        WHERE
            Sr.warehouse IN %s
            AND Sr.item_group IN ('Laptops')
        ORDER BY Sr.creation DESC
    """, (tuple(inw_inventory),), as_dict=True)

    grouped_data = {}

    for row in raw_data:
        key = row["serial_no"]
        if key not in grouped_data:
            grouped_data[key] = {
                "name": row["serial_no"],
                "item_code": row["item_code"],
                "warehouse": row["warehouse"],
                "Model": row["Model"],
            }
        grouped_data[key][row["Attribute"]] = row["attribute_value"]

    get_serial_no_config = list(grouped_data.values())

    return get_serial_no_data(nj_pro_child, get_serial_no_config, inw_inventory, doc)

def get_serial_no_data(nj_pro_child, serial_no_list, inw_inventory, doc):
    suggested_serial_no_data = []
    added_serial_no = set()
    rank = 0 

    # Normalize keys in serial_no_list for easier matching (case-insensitive keys)
    normalized_serials = []
    for s in serial_no_list:
        normalized_serials.append({
            "name": s.get("name"),
            "item_code": s.get("item_code"),
            "warehouse": s.get("warehouse"),
            "model": (s.get("Model") or "").strip().lower(),
            "processor_type": (s.get("Processor Type") or "").strip().lower(),
            "ram_capacity": (s.get("RAM Capacity") or "").strip().lower(),
            "storage_capacity": (s.get("Storage Capacity") or "").strip().lower(),
        })

    for child in doc.get("nj_production_planning_child", []):
        if child.get("to_make", 0) > 0:
            needed = int(child.get("to_make"))
            model = (child.get("model") or "").strip().lower()
            processor = (child.get("processor") or "").strip().lower()
            ram = (child.get("ram") or "").strip().lower()
            ssd = (child.get("ssd") or "").strip().lower()

            matched_serials = []

            # First pass: exact matches by all specs and available in inw_inventory warehouses
            for serial in normalized_serials:
                if needed <= 0:
                    break

                if serial["name"] in added_serial_no:
                    continue

                if serial["warehouse"] not in inw_inventory:
                    continue

                if (serial["model"] == model and
                    serial["processor_type"] == processor and
                    serial["ram_capacity"] == ram and
                    serial["storage_capacity"] == ssd):

                    matched_serials.append(serial["name"])
                    added_serial_no.add(serial["name"])
                    needed -= 1

            # Second pass: if still needed, try matching just model + processor and exclude item_code already matched (relax criteria)
            if needed > 0:
                for serial in normalized_serials:
                    if needed <= 0:
                        break

                    if serial["name"] in added_serial_no:
                        continue

                    if serial["warehouse"] not in inw_inventory:
                        continue

                    # relaxed matching (same model + processor, but different item_code)
                    if (serial["model"] == model and
                        serial["processor_type"] == processor and
                        serial["item_code"] != child.get("item_code")):

                        matched_serials.append(serial["name"])
                        added_serial_no.add(serial["name"])
                        needed -= 1

            for serial_no in matched_serials:
                rank += 1
                suggested_serial_no_data.append({
                    "model": child.get("model", "").strip().upper(),
                    "processor": child.get("processor", "").strip().upper(),
                    "ram": child.get("ram", "").strip().upper(),
                    "ssd": child.get("ssd", "").strip().upper(),
                    "suggested_serial_no": serial_no,
                    "item_code": child.get("item_code"),
                    "rank": rank
                })

    doc.update({"suggested_serial_no": suggested_serial_no_data})

    allocated_lap = allocate_laptop_parts(doc)
    doc.update({"laptop_allocation": allocated_lap})

    doc.save()
    frappe.db.commit()
    # update_to_make_for_serial(doc)

def allocate_laptop_parts(doc):

    serial_list = []
    serial_no_rank = {row.get("suggested_serial_no"): row.get("rank") for row in doc.get("suggested_serial_no", [])}
    for row in doc.get("suggested_serial_no"):
        if row.suggested_serial_no:
            serial_list.extend([s.strip() for s in row.suggested_serial_no.split(",") if s.strip()])

    if not serial_list:
        frappe.msgprint("No suggested serial numbers found in the latest production planning.")
        return []

    mr_items = frappe.db.sql("""
        SELECT parent AS material_request, item_code, serial_no AS against_serial_no, 
               stock_qty, qty AS mr_qty, item_group
        FROM `tabMaterial Request Item` 
        WHERE post_order_status IN ("Not Completed", " ") 
        AND serial_no IN %(serial_list)s
    """, {"serial_list": tuple(serial_list)}, as_dict=True)

    if not mr_items:
        frappe.msgprint("No Material Requests found for the suggested serial numbers.")
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

    virtual_stock_data = stock_data.copy()

    grouped_by_serial = {}

    planned_allocation = {}

    for item in mr_items:
        serial_no = item["against_serial_no"]
        item_code = item["item_code"]
        mr_qty = flt(item["mr_qty"])

        available_stock = virtual_stock_data.get(item_code, 0) - planned_allocation.get(item_code, 0)

        if available_stock >= mr_qty:
            allocated_status = "Allocated"
            status = "Available" if available_stock > 0 else "Not Available"

            row = {
                "mreq_no": item["material_request"],
                "item": item_code,
                "item_group": item["item_group"],
                "serial_no": serial_no,
                "mr_qty": mr_qty,
                "sb_qty": available_stock,
                "status": status,
                "allocated_qty": mr_qty,
                "allocated_status": allocated_status,
                "rank": serial_no_rank.get(serial_no, 0)
            }

            grouped_by_serial.setdefault(serial_no, []).append(row)

            planned_allocation[item_code] = planned_allocation.get(item_code, 0) + mr_qty

        else:
            res_item = allocated_other_part(item)

            if res_item:
                item_code_res = res_item.get("item_code")
                against_item_code = res_item.get("against_item_code")
                stock_qty_res = flt(res_item.get("stock_qty", 0))

                available_stock_res = stock_qty_res - planned_allocation.get(item_code_res, 0)

                if available_stock_res >= mr_qty:
                    allocated_status = "Allocated"
                    planned_allocation[item_code_res] = planned_allocation.get(item_code_res, 0) + mr_qty
                else:
                    allocated_status = "Not Allocated"
            else:
                allocated_status = "Not Allocated"
                item_code_res = item_code
                against_item_code = ""
                available_stock_res = 0

            status = "Available" if available_stock_res > 0 else "Not Available"

            row = {
                "mreq_no": item["material_request"],
                "item": item_code_res,
                "item_group": item["item_group"],
                "serial_no": serial_no,
                "mr_qty": mr_qty,
                "sb_qty": available_stock_res,
                "status": status,
                "allocated_qty": mr_qty,
                "allocated_status": allocated_status,
                "against_item_code": against_item_code,
                "rank": serial_no_rank.get(serial_no, 0)
            }

            grouped_by_serial.setdefault(serial_no, []).append(row)

    for serial, items in grouped_by_serial.items():
        grouped_by_serial[serial] = sorted(items, key=lambda x: x['rank'])

    sorted_serials = sorted(
        grouped_by_serial.items(),
        key=lambda x: x[1][0]['rank'] if x[1] else float('inf')
    )

    grouped_by_serial = dict(sorted_serials)

    for item_code, qty in planned_allocation.items():
        if item_code in virtual_stock_data:
            virtual_stock_data[item_code] -= qty

    final_result = []

    if not grouped_by_serial:
        return final_result

    for serial_no, items in grouped_by_serial.items():
        if all(item["allocated_status"] == "Allocated" for item in items):
            final_result.extend(items)

    from operator import itemgetter
    final_result.sort(key=itemgetter("rank"))

    unique_final_result = []
    seen_serial_item_codes = {}

    for item in final_result:
        sn = item["serial_no"]
        ic = item["item"]
        if sn not in seen_serial_item_codes:
            seen_serial_item_codes[sn] = set()
        if ic not in seen_serial_item_codes[sn]:
            unique_final_result.append(item)
            seen_serial_item_codes[sn].add(ic)

    final_results = allocate_serial_no_for_battery(unique_final_result)

    return unique_final_result

def allocated_other_part(item):

    item_code = item.get("item_code")
    if not item_code:
        frappe.throw("Item Code is missing.")

    item_codes = [item_code]
    placeholders = ', '.join(['%s'] * len(item_codes))

    query = f"""SELECT 
                    LOWER(iva.attribute) AS item_attribute, 
                    LOWER(iva.attribute_value) AS attribute_value,
                    iva.parent AS item_code,
                    i.item_name,
                    i.item_model,
                    i.item_group,
                    i.variant_of AS parent
                FROM `tabItem Variant Attribute` iva
                INNER JOIN `tabItem` i ON iva.parent = i.name
                WHERE iva.parent IN ({placeholders})"""

    attribute_data = frappe.db.sql(query, tuple(item_codes), as_dict=True)
    attribute_data_info = {item['item_attribute']: item['attribute_value'] for item in attribute_data}

    item_wizard_name = frappe.db.get_value("Serial No", {'name': item.get("against_serial_no")}, 'item_wizard')
    if not item_wizard_name:
        return []

    item_wizard_doc = frappe.get_doc("Item Wizards", item_wizard_name)

    for row in item_wizard_doc.get("items_attribute"):
            for attr in attribute_data:
                if row.get("item_group", "").lower() in [attr.get("item_group", "").lower()] and row.get("item_attribute", "").lower() != "grade":
                    if attr.get("item_attribute", "").lower() == row.get("item_attribute", "").lower() and \
                            attr.get("attribute_value", "").lower() != row.get("attribute_value", "").lower():

                        attribute_data_info.update({
                            row.get("item_attribute", "").lower(): row.get("attribute_value", "").lower()
                        })

                        conditions = " OR ".join([
                        f"(LOWER(iva.attribute) = '{key.lower()}' AND LOWER(iva.attribute_value) = '{value.lower()}')"
                                    for key, value in attribute_data_info.items()
                                ])

                        query = f"""
                                    SELECT
                                        iva.parent AS item_code
                                    FROM
                                        `tabItem Variant Attribute` iva
                                    WHERE
                                        {conditions}
                                    GROUP BY
                                        iva.parent
                                    HAVING
                                        COUNT(*) = {len(attribute_data_info)}
                                """
                            
                        item_codes = frappe.db.sql(query, as_dict=True)

                        stock_data = {}

                        for items in item_codes:

                            warehouses = frappe.db.get_all("Warehouse", filters={"department": "Stores - NJ"}, pluck="name")
                            stock_results = frappe.db.sql("""
                                SELECT item_code, SUM(actual_qty) AS total_qty 
                                FROM `tabBin` 
                                WHERE warehouse IN %(warehouses)s
                                AND item_code = %(item_code)s
                                """, {
                                    "warehouses": tuple(warehouses),
                                    "item_code": items["item_code"]
                                }, as_dict=True)

                            for stock in stock_results:
                                stock_data[stock["item_code"]] = flt(stock["total_qty"])
                            
                            available_stock = stock_data.get(items.get("item_code"), 0)

                            if available_stock > 0:
                                item.update(
                                    {
                                        "item_code": items["item_code"],
                                        "against_item_code": item.get("item_code"),
                                        "stock_qty": available_stock
                                    })
                                    
                                return item

def update_to_make_for_serial(doc):

    for child in doc.get("suggested_serial_no", []):
        if child.get("suggested_serial_no"):
            serial_no_info = child.get("suggested_serial_no").split(", ")
            for serial_no in serial_no_info:
                serial_no_doc = frappe.get_doc("Serial No", serial_no)
                serial_no_doc.to_make = child.get("item_code")
                serial_no_doc.save()
                frappe.db.commit()

def allocate_serial_no_for_battery(final_result):

    for row in final_result:
        
        if not row:
            continue

        if row.get("item_group", "") == None:
            continue

        if row.get("item_group", "").lower() == "battery":
            item_code = row.get("item")
            mreq_no = row.get("mreq_no")
            item_group = row.get("item_group")

            valid_serials = []

            nj_warehouses = frappe.get_all(
                "Warehouse", 
                filters={"department": "Stores - NJ"},
                pluck="name"
            )

            if not nj_warehouses:
                continue

            serials = frappe.get_all(
                "Serial No", 
                filters={
                    "item_code": item_code,
                    "warehouse": ["in", nj_warehouses]
                },
                fields=["name", "full_charge_capacity", "battery_average_discharge_rate"]
            )

            for serial in serials:
                try:
                    if not serial.get("full_charge_capacity") or not serial.get("battery_average_discharge_rate"):
                        continue

                    full = float(serial.get("full_charge_capacity") or 0)
                    avg = float(serial.get("battery_average_discharge_rate") or 0)

                    if avg != 0:
                        battery_life = full / avg
                        if battery_life > 2:
                            valid_serials.append(serial.get("name"))
                except Exception as e:
                    print(f"Error calculating battery life for serial {serial.get('name')}: {e}")

            if valid_serials:
                try:
                    frappe.db.set_value(
                        "Material Request Item",
                        {
                            "parent": mreq_no,
                            "item_code": item_code,
                            "item_group": item_group
                        },
                        "allocated_serial_no",
                        ", ".join(valid_serials)
                    )
                except Exception as e:
                    print(f"Failed to set allocated_serial_no for {item_code}: {e}")