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
def get_department_details():
    print("triggerring from the scheduler event")

    
    # doc = parse_document(doc)
    all_dept = frappe.db.get_all("Department", ["name"])

    # print("all_dept", all_dept)

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
        print("\n\n\n\nitem", item)
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

# Merged Configuration Processing (model=1 and fr_config=1)
def process_merged_configuration(dept_doc):
    merged_data = process_inventory_rows(dept_doc)
    days = frappe.db.get_single_value("NJ Production Planning Settings", "days")
    weight_factor = frappe.db.get_single_value("NJ Production Planning Settings", "weight_factor")
    item_code_list = calculate_sales_order_rate_with_weights_for_model_config(merged_data, days=int(days), weight_factor=int(weight_factor))
    return calculate_doi(item_code_list)

def process_inventory_rows(dept_doc):
    merged_data = {}
    for row in dept_doc.get("inventory_details_child"):
        process_inwarded_inventory_merged(row, merged_data)
        process_forwarded_inventory_merged(row, merged_data)
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

def process_forwarded_inventory_merged(row, merged_data):
    if row.get("forwarded_inventory"):
        warehouses = get_warehouses(row.get("forwarded_inventory"))
        for warehouse in warehouses:
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

# Model Configuration Processing (model=1)
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

# Default Configuration Processing
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

# Common Utilities
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
    return items


def calculate_sales_order_rate_with_weights_for_model_config(item_code_list, days=None, weight_factor=None):
    if not item_code_list:
        item_code_list = {}

    weights = {i: (days - i) * weight_factor for i in range(days)}
    total_weight = sum(weights.values())

    print("weights", weights)
    print("total_weight", total_weight)

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

    print("sales_data ----------- ", sales_data)

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
                updated_item_code_list.append({
                    'model': model_name,
                    'item_code': item_code,
                    'inwarded_qty': inward_qty,
                    'forwarded_qty': model_data['item_codes'][item_code],
                    'total_sales_qty': 0,
                    'sales_rate': 0
                })
                continue
            
            total_sales_qty = sum(sales_map[item_code].values())  # Sum of all sales

            print("toal_sales_qty", total_sales_qty)

            # Compute weighted sales if data exists
            total_weighted_sales = sum(
                        sales_map[item_code].get(datetime.today().date() - timedelta(days=day_offset), 0) * weights.get(day_offset, 0)
                        for day_offset in range(days + 1)  # Loop from 0 to days (inclusive)
                    ) if item_code in sales_map else 0

            sales_rate = total_weighted_sales / total_weight if total_weight else 0

            print("sales_rate ------------- ", sales_rate)

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

        except Exception as e:
            print("Error fetching attributes:", str(e))
    
    updated_item_code_list = sorted(updated_item_code_list, key=lambda x: x['sales_rate'], reverse=True)

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
    """, explain=1, debug=1, as_dict=True)

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

            # print("sales_rate ----------- 242", item['sales_rate'])
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

    """, explain=1, debug=1, as_dict=True)

    # print("sales_data ------------------- ", sales_data)    

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
    
    # print(updated_item_code_list)

    return updated_item_code_list

import math

def calculate_to_make(doc, conversion_factor=1, minimum_stock=5):
    if conversion_factor == 0:
        frappe.throw("Conversion Factor cannot be zero.")  # Handle division by zero
    
    for item in doc.get("nj_production_planning_child", []):
        try:
            if item.get("sales_rate", 0) == 0:
                item.to_make = 0
                continue

            # Ensure non-negative values
            sales_rate = max(flt(item.get("sales_rate", 0)), 0)
            forwarded_qty = max(flt(item.get("forward_inventory", 0)), 0)
            inwarded_qty = max(flt(item.get("inward_inventory", 0)), 0)
            days_of_inventory = max(flt(item.get("days_of_inventory", 0)), 0)

            # Calculate desired inventory (ceil to handle fractional sales rates)
            desired_from_doi = sales_rate * days_of_inventory
            desired_inventory = max(math.ceil(desired_from_doi), minimum_stock)
            
            # Inventory shortfall (ensure integer)
            inventory_shortfall = max(0, desired_inventory - forwarded_qty)
            
            # Material constraint (integer division)
            material_constraint = inwarded_qty // conversion_factor
            
            # Determine to_make (integer)
            item.to_make = int(min(inventory_shortfall, material_constraint))
            
        except Exception as e:
            item.to_make = 0
            frappe.log_error(f"Error calculating to_make: {str(e)}")

    # Rest of your logic (suggest_serial_no, etc.)
    suggested_serial_no = suggest_to_make_serial_no(...)
    
    doc.save()
    
    return doc.get("nj_production_planning_child", [])

def suggest_to_make_serial_no(nj_pro_child, doc, department=None):
    suggested_serial_no = suggest_to_make_serial_no(doc.get("nj_production_planning_child", []), doc, doc.get("department"))

    if not nj_pro_child:
        return []

    if not department:
        return [] 

    try:
        dept_doc = frappe.get_doc("Department", department)
    except frappe.DoesNotExistError:
        return [] 
    
    model = "1"

    frw_inventory = []

    for item in dept_doc.get("inventory_details_child", []):
        frw_inventory_data = frappe.db.get_all(
            "Warehouse",
            filters={"department": item.get("forwarded_inventory")},
            pluck="name"
        )
        frw_inventory.extend(frw_inventory_data)

    if not frw_inventory:
        return []

    get_serial_no_config = frappe.db.sql("""
        SELECT model, item_code, COUNT(*) AS count
        FROM `tabSerial No`
        WHERE model IS NOT NULL AND warehouse IN %(warehouses)s
        GROUP BY model, item_code
    """, {"warehouses": tuple(frw_inventory)}, as_dict=True)

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
    
    return get_serial_no_data(nj_pro_child, get_serial_no_config, frw_inventory,doc)

def get_serial_no_data(nj_pro_child, get_serial_no_config, frw_inventory, doc):

    suggested_serial_no = []
    ref_get_serial_no_config = get_serial_no_config
    suggested_serial_no_data = []
    added_serial_no = set()
    dept_doc = frappe.get_doc("Department", doc.get("department"))
    fw_model = dept_doc.get("forwarded_model") 
    fw_config = dept_doc.get("forwarded_config")

    if fw_model == "1":
        for child in nj_pro_child:

            if child.get("to_make", 0) > 0:
                for item in get_serial_no_config:
                    if child.get("model", "").strip().lower() == item.get("model", "").strip().lower():
                        
                        get_suggested_serial_no = frappe.db.sql("""
                                SELECT name FROM `tabSerial No`
                                WHERE warehouse IN %s AND model = %s
                                LIMIT %s
                            """, (tuple(frw_inventory), item.get("model"), child.get("to_make")), explain=1, debug=1, as_dict=True)
                        
                        
                        suggest_serial_no = [
                            row.get("name") for row in get_suggested_serial_no if row.get("name") not in added_serial_no
                        ]
                        
                        added_serial_no.update(suggest_serial_no)

                        # print("suggested_serial_no ---------------------- ", suggest_serial_no)
                        
                        if suggest_serial_no:
                            suggested_serial_no_data.append({
                                "model": item.get("model").upper(),
                                "suggested_serial_no": ", ".join(suggest_serial_no)
                            })
                        break

    else:

        for child in doc.get("nj_production_planning_child", []):
            # print("child -------------- ", child.as_dict())
            if child.get("to_make", 0) > 0:
                matched_serials = []
                remaining_needed = int(child.get("to_make"))

                for item in get_serial_no_config:
                    # print("item ----------------- ",item)
                    if (
                        (child.get("model") or "").strip().lower() == (item.get("model") or "").strip().lower() and
                        (child.get("processor") or "").strip().lower() == (item.get("processor_type") or "").strip().lower() and
                        (child.get("ram") or "").strip().lower() == (item.get("ram_capacity") or "").strip().lower() and
                        (child.get("ssd") or "").strip().lower() == (item.get("storage_capacity") or "").strip().lower()
                        ):

                        print("warehouse ------------------ ", frw_inventory)
                        print("item_code ------------------ ", item.get("item_code"))
                        print("remaining_needed ------------------ ", remaining_needed)

                        exact_serials = frappe.db.sql("""
                            SELECT name FROM `tabSerial No`
                            WHERE warehouse IN %s AND item_code = %s
                            LIMIT %s
                        """, (tuple(frw_inventory), item.get("item_code"), remaining_needed), as_dict=True)

                        for row in exact_serials:
                            serial_no = row.get("name")
                            if serial_no not in added_serial_no:
                                matched_serials.append(serial_no)
                                added_serial_no.add(serial_no) 
                                remaining_needed -= 1
                                if remaining_needed <= 0:
                                    break

                if remaining_needed > 0:
                    for alt_item in ref_get_serial_no_config:
                        if (
                            (child.get("model") or "").strip().lower() == (alt_item.get("model") or "").strip().lower() and
                            (child.get("processor") or "").strip().lower() == (alt_item.get("processor_type") or "").strip().lower() and
                            alt_item.get("item_code") != item.get("item_code")
                            ):

                            extra_serials = frappe.db.sql("""
                                SELECT name FROM `tabSerial No`
                                WHERE warehouse IN %s AND item_code = %s
                                LIMIT %s
                            """, (tuple(frw_inventory), alt_item.get("item_code"), remaining_needed), as_dict=True)

                            for row in extra_serials:
                                serial_no = row.get("name")
                                if serial_no not in added_serial_no:
                                    matched_serials.append(serial_no)
                                    added_serial_no.add(serial_no)
                                    remaining_needed -= 1
                                    if remaining_needed <= 0:
                                        break  

                suggested_serial_no_data.append({
                    "model": child.get("model", "").strip().upper(),
                    "processor": child.get("processor", "").strip().upper(),
                    "ram": child.get("ram", "").strip().upper(),
                    "ssd": child.get("ssd", "").strip().upper(),
                    "suggested_serial_no": ", ".join(matched_serials),
                    "item_code": child.get("item_code") if matched_serials else None,
                })

    doc.update({"suggested_serial_no": suggested_serial_no_data})
    allocated_lap = allocate_laptop_parts(doc)
    # print("\n\n\nallocated_lap", allocated_lap)
    doc.update({"laptop_allocation": allocated_lap})
    doc.save()
    frappe.db.commit()

    update_to_make_for_serial(doc)

def allocate_laptop_parts(doc):

    serial_list = []
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

    # print("mr_items ------------------ ", mr_items)

    if not mr_items:
        frappe.msgprint("No Material Requests found for the suggested serial numbers.")
        return []

    warehouses = frappe.db.get_all("Warehouse", filters={"department": "Stores - NJ"}, pluck="name")
    if not warehouses:
        frappe.msgprint("No warehouses found under 'Stores - NJ' department.")
        return []

    # Fetch actual stock per item
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

    for item in mr_items:
        serial_no = item["against_serial_no"]
        item_code = item["item_code"]
        mr_qty = flt(item["mr_qty"])
        available_stock = virtual_stock_data.get(item_code, 0)

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
                "allocated_status": allocated_status
            }

            grouped_by_serial.setdefault(serial_no, []).append(row)

            virtual_stock_data[item_code] -= mr_qty

        else:
            res_item = allocated_other_part(item)

            if res_item:
                item_code_res = res_item.get("item_code")
                against_item_code = res_item.get("against_item_code")
                available_stock = flt(res_item.get("stock_qty", 0))

                if available_stock >= mr_qty:
                    allocated_status = "Allocated"
                else:
                    allocated_status = "Not Allocated"
            else:
                allocated_status = "Not Allocated"
                item_code_res = item_code
                against_item_code = ""
                available_stock = 0

            status = "Available" if available_stock > 0 else "Not Available"

            row = {
                "mreq_no": item["material_request"],
                "item": item_code_res,
                "item_group": item["item_group"],
                "serial_no": serial_no,
                "mr_qty": mr_qty,
                "sb_qty": available_stock,
                "status": status,
                "allocated_qty": mr_qty,
                "allocated_status": allocated_status,
                "against_item_code": against_item_code
            }

            grouped_by_serial.setdefault(serial_no, []).append(row)

            if res_item:
                if item_code_res in virtual_stock_data:
                    virtual_stock_data[item_code_res] -= mr_qty

    final_result = []

    if not grouped_by_serial:
        return final_result

    for serial_no, items in grouped_by_serial.items():
        if all(item["allocated_status"] == "Allocated" for item in items):
            final_result.extend(items)

    from operator import itemgetter
    final_result.sort(key=itemgetter("serial_no", "mreq_no"))

    final_results = allocate_serial_no_for_battery(final_result)

    return final_result

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
        # frappe.throw(f"Item Wizard not found for serial no: {item.get('against_serial_no')}")

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
                                },explain=1, debug=1, as_dict=True)

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
    # print("final_result ----------------- 1144 ", final_result)

    for row in final_result:
        # print(f"\nProcessing row ------------ {row}")
        
        if not row:
            # print("Skipping None row")
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
                # print("No NJ warehouses found.")
                continue

            serials = frappe.get_all(
                "Serial No", 
                filters={
                    "item_code": item_code,
                    "warehouse": ["in", nj_warehouses]
                },
                fields=["name", "full_charge_capacity", "battery_average_discharge_rate"]
            )

            # print(f"Serials found for item {item_code}: {serials}")

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

            # print(f"Valid serials for allocation to {item_code}: {valid_serials}")

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
                    # print(f"\n\n\nAllocated serials to Material Request Item: {mreq_no} - {item_code}")
                except Exception as e:
                    print(f"Failed to set allocated_serial_no for {item_code}: {e}")