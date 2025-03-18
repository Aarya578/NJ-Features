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

    print("all_dept", all_dept)

    for dept in all_dept:
        dept_doc = get_department_document(dept.get("name"))

        in_model = dept_doc.get("inwarded_model") 
        in_config = dept_doc.get("inwarded_config")
        fw_model = dept_doc.get("forwarded_model") 
        fw_config = dept_doc.get("forwarded_config")

        if str(in_model) == '1' and str(in_config) == '1':
            data = process_merged_configuration(dept_doc)
            new_doc = create_production_planning(data, dept.get("name"))
            calculate_to_make(new_doc, DOI_threshold=10)
        elif str(in_model) == '1' and str(fw_model) == '1':
            process_model_configuration(dept_doc)
        elif str(in_config) == '1' and str(fw_config) == '1':
            data = process_default_configuration(dept_doc)
            new_doc = create_production_planning(data, dept.get("name"))
            calculate_to_make(new_doc, DOI_threshold=10)

@frappe.whitelist()
def create_production_planning(data, department):
    new_doc = frappe.new_doc("NJ Production Planning")

    for item in data:
        new_doc.department = department
        child = new_doc.append("nj_production_planning_child", {})
        child.model = item.get("model", "").upper()
        child.processor = item.get("processor_type", "").upper()
        child.ram = item.get("ram_capacity", "").upper()
        child.ssd = item.get("storage_capacity", "").upper()
        child.sales_rate = item.get("sales_rate", 0.0)
        child.inward_inventory = item.get("inwarded_qty", 0.0)
        child.forward_inventory = item.get("forwarded_qty", 0.0)
        child.days_of_inventory = item.get("DOI", 0.0)
        child.to_make = item.get("to_make", 0.0)

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
    item_code_list = calculate_sales_order_rate_with_weights_for_model_config(merged_data)
    return calculate_doi(item_code_list)

def process_inventory_rows(dept_doc):
    merged_data = {}
    for row in dept_doc.get("inventory_details_child"):
        process_inwarded_inventory_merged(row, merged_data)
        process_forwarded_inventory_merged(row, merged_data)
    return merged_data

def process_inwarded_inventory_merged(row, merged_data):
    if row.get("inwarded_inventory"):
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
    item_code_list = calculate_sales_order_rate_with_weights_for_model(item_code_list)
    return calculate_doi(item_code_list)

def get_model_counts(dept_doc, inventory_type):
    counts = {}
    for row in dept_doc.get("inventory_details_child"):
        department = row.get(inventory_type)
        if department:
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
    item_code_list = calculate_sales_order_rate_with_weights(item_code_list)
    return calculate_doi(item_code_list)

def get_item_counts(dept_doc, inventory_type):
    counts = {}
    for row in dept_doc.get("inventory_details_child"):
        department = row.get(inventory_type)
        if department:
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
        try:
            item["DOI"] = item["forwarded_qty"] / item["sales_rate"] if item.get("sales_rate", 0) > 0 else 0
        except KeyError:
            item["DOI"] = 0
    return items


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

            print("sales_rate ----------- 242", item['sales_rate'])
        else:
            item['total_sales_qty'] = 0
            item['sales_rate'] = 0

    return updated_item_code_list


def calculate_sales_order_rate_with_weights(item_code_list, days=20, weight_factor=2):
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

    return updated_item_code_list


@frappe.whitelist()
def calculate_to_make(doc, DOI_threshold=10):

    if isinstance(doc, str):
        doc = frappe.parse_json(doc)

    for item in doc.get("nj_production_planning_child", []):

        sales_rate = flt(item.get("sales_rate", 0)) 
        forwarded_qty = flt(item.get("forward_inventory", 0)) 
        inwarded_qty = flt(item.get("inward_inventory", 0)) 

        to_make = (forwarded_qty - inwarded_qty) + (sales_rate * DOI_threshold)
        to_make = max(0, round(to_make))
        
        item.update({"to_make": to_make})

    suggested_serial_no = suggest_to_make_serial_no(doc.get("nj_production_planning_child", []),doc, doc.get("department"))

    return doc.get("nj_production_planning_child", [])


def suggest_to_make_serial_no(nj_pro_child, doc, department=None):

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

                        print("suggested_serial_no ---------------------- ", suggest_serial_no)
                        
                        if suggest_serial_no:
                            suggested_serial_no_data.append({
                                "model": item.get("model").upper(),
                                "suggested_serial_no": ", ".join(suggest_serial_no)
                            })
                        break

    else:

        for child in doc.get("nj_production_planning_child", []):
            if child.get("to_make", 0) > 0:
                matched_serials = []
                remaining_needed = child.get("to_make")

                for item in get_serial_no_config:
                    if (
                        child.get("model", "").strip().lower() == item.get("model", "").strip().lower() and
                        child.get("processor", "").strip().lower() == item.get("processor_type", "").strip().lower() and
                        child.get("ram", "").strip().lower() == item.get("ram_capacity", "").strip().lower() and
                        child.get("ssd", "").strip().lower() == item.get("storage_capacity", "").strip().lower()
                    ):
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
                            child.get("model", "").strip().lower() == alt_item.get("model", "").strip().lower() and
                            child.get("processor", "").strip().lower() == alt_item.get("processor_type", "").strip().lower() and
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
                    "item_code": item.get("item_code") if matched_serials else None,
                })

    doc.update({"suggested_serial_no": suggested_serial_no_data})
    doc.save()
    frappe.db.commit()