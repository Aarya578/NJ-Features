# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

nj_inventry_settings = frappe.get_single("NJ Inventory Settings")

shop = nj_inventry_settings.shop
token = nj_inventry_settings.token
warehouses = nj_inventry_settings.warehouses
location_id = nj_inventry_settings.location_id
item_groups = nj_inventry_settings.item_groups
departments = nj_inventry_settings.departments

class SOQuantityCheck(Document):
	pass

def update_so_quantity_check():
    """Update SO Quantity Check DocType with data from inventory and pending sales orders"""
    try:
        print("Starting SO Quantity Check update")
        updated_doc_names = set()
        nj_inventory_log = frappe.new_doc("NJ Inventory Sync Log")
        nj_inventory_log.error = ""

        warehouses_list = []
        if warehouses is not None:
            warehouses_list = [i.strip() for i in warehouses.split(',') if i.strip()]
        item_groups_list = [i.strip() for i in item_groups.split(',') if i.strip()]
        departments_list = [d.strip() for d in departments.split(',') if d.strip()]

        warehouse_placeholders = ', '.join(['%s'] * len(warehouses_list))
        item_group_placeholders = ', '.join(['%s'] * len(item_groups_list))
        department_placeholders = ', '.join(['%s'] * len(departments_list))

        warehouse_clause = f"OR b.warehouse IN ({warehouse_placeholders})" if warehouses_list else ""
        # Step 1: Get inventory data from first query
        query = f"""
            WITH Parent_Stock AS (
                SELECT 
                    CONCAT(i.item_model, ' ', proc.attribute_value) AS parent,
                    CAST(SUM(b.actual_qty) AS DECIMAL(10, 2)) AS total_actual_qty_for_parent
                FROM 
                    tabItem i
                INNER JOIN 
                    `tabItem Variant Attribute` proc ON i.name = proc.parent 
                        AND proc.attribute LIKE '%%Processor%%'
                LEFT JOIN 
                    tabBin b ON i.item_code = b.item_code
                LEFT JOIN 
                    tabWarehouse w ON b.warehouse = w.name
                WHERE 
                    i.item_group IN ({item_group_placeholders})
                    AND w.department IN ({department_placeholders})
                GROUP BY 
                    parent
            ),

            Item_Stock AS (
                SELECT 
                    i.item_code,
                    CAST(SUM(b.actual_qty) AS DECIMAL(10, 2)) AS total_actual_qty_for_itemcode
                FROM 
                    tabItem i
                LEFT JOIN 
                    tabBin b ON i.item_code = b.item_code
                LEFT JOIN 
                    tabWarehouse w ON b.warehouse = w.name
                WHERE 
                    i.item_group IN ({item_group_placeholders})
                    AND w.department IN ({department_placeholders})
                GROUP BY 
                    i.item_code
            ),

            Main_Data AS (
                SELECT DISTINCT
                    pb.shopify_variant_id,
                    i.item_code,
                    i.item_group,
                    CONCAT(i.item_model, ' ', proc.attribute_value) AS parent,
                    ps.total_actual_qty_for_parent,
                    isq.total_actual_qty_for_itemcode
                FROM 
                    `tabProduct Bundle` pb
                LEFT JOIN 
                    `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
                LEFT JOIN 
                    tabItem i ON pbi.item_code = i.item_code
                LEFT JOIN 
                    `tabItem Variant Attribute` proc ON i.name = proc.parent 
                        AND proc.attribute LIKE '%%Processor%%'
                LEFT JOIN 
                    Parent_Stock ps ON ps.parent = CONCAT(i.item_model, ' ', proc.attribute_value)
                LEFT JOIN 
                    Item_Stock isq ON isq.item_code = i.item_code
                WHERE 
                    i.item_group IN ({item_group_placeholders})
            )

            SELECT 
                shopify_variant_id,
                item_code,
                item_group,
                total_actual_qty_for_itemcode AS actual_qty,
                parent,
                total_actual_qty_for_parent
            FROM 
                Main_Data
            ORDER BY 
                shopify_variant_id, item_code
        """

        params = (
            item_groups_list + departments_list +  # For Parent_Stock
            item_groups_list + departments_list +  # For Item_Stock
            item_groups_list                        # For Main_Data
        )

        inventory_data = frappe.db.sql(query, tuple(params), as_dict=True)

        print(f"Retrieved {len(inventory_data)} records from inventory query")

        # Create a dictionary to store inventory data by item_code
        stock_map = {}
        for row in inventory_data:
            item_code = row.get('item_code')
            if item_code:
                # Ensure actual_qty is always a number, defaulting to 0 if None
                actual_qty = row.get('actual_qty', 0) or 0
                stock_map[item_code] = {
                    'parent1': row.get('parent', ''),
                    'actual_qty': actual_qty
                }


        # # Create a dictionary to store inventory data by item_code
        # stock_map = {}
        # for row in inventory_data:
        #     item_code = row.get('item_code')
        #     if item_code:
        #         # Ensure actual_qty is always a number, defaulting to 0 if None
        #         actual_qty = row.get('actual_qty', 0) or 0
        #         stock_map[item_code] = {
        #             'parent1': row.get('parent', ''),
        #             'actual_qty': actual_qty
        #         }

        # Step 2: Get sales order pending quantities from second query
        pending_so_data = frappe.db.sql("""
           SELECT 
                so_data.sales_order,
                so_data.item_code,
                so_data.pb_code,
                so_data.item_group,
                so_data.qty AS so_qty,
                IFNULL(dn_data.qty, 0) AS dn_qty,
                LEAST(so_data.qty, IFNULL(dn_data.qty, 0)) AS min_so_dn_qty,
                so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.qty, 0)) AS pending_qty,
                CONCAT(it2.variant_of, ' ', proc.attribute_value) AS variant_processor,

                -- Existing: total pending qty by variant_with_processor
                SUM(so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.qty, 0))) 
                    OVER (PARTITION BY CONCAT(it2.variant_of, ' ', proc.attribute_value)) AS total_pending_by_variant,

                -- ✅ New: total pending qty by pb_code
                SUM(so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.qty, 0))) 
                    OVER (PARTITION BY so_data.pb_code) AS total_pending_by_pb_code

            FROM (
                SELECT 
                    soi.parent AS sales_order,
                    soi.item_code,
                    IFNULL(pb.item_code, soi.item_code) AS pb_code,
                    soi.qty,
                    soi.item_group,
                    so.creation,
                    soi.rate
                FROM `tabSales Order` so
                INNER JOIN `tabSales Order Item` soi ON so.name = soi.parent
                LEFT JOIN `tabProduct Bundle Item` pb ON soi.item_code = pb.parent
                LEFT JOIN `tabItem` it ON it.item_code = pb.item_code
                WHERE 
                    so.status NOT IN ('Closed', 'Completed', 'Draft', 'Cancelled')
                    AND so.creation > CURDATE() - INTERVAL 20 DAY
                    AND soi.item_group IN ('Laptops','Chromebooks')
                    AND so.sale_type != 'Amazon'
                    AND (
                        pb.item_code IS NULL 
                        OR it.item_group IN ('Laptops', 'Chromebooks')
                    )
            ) AS so_data

            LEFT JOIN (
                SELECT 
                    dni.against_sales_order,
                    dni.item_code,
                    SUM(dni.qty) AS qty
                FROM `tabDelivery Note Item` dni
                WHERE 
                    dni.docstatus = 1
                    AND dni.creation >= CURDATE() - INTERVAL 20 DAY
                    AND dni.item_group IN ('Laptops', 'Chromebooks')
                    AND dni.qty > 0
                GROUP BY dni.against_sales_order, dni.item_code
            ) AS dn_data 
            ON so_data.sales_order = dn_data.against_sales_order 
            AND so_data.item_code = dn_data.item_code

            LEFT JOIN `tabItem` it2 
                ON it2.item_code = so_data.pb_code

            LEFT JOIN `tabItem Variant Attribute` proc 
                ON proc.parent = it2.name
                AND proc.attribute LIKE '%Processor%'

            ORDER BY so_data.sales_order, so_data.item_code;

        """, as_dict=True)

        print(f"Retrieved {len(pending_so_data)} records from pending SO query")

        # Create a dictionary to store pending quantities by item_code
        pending_qty_by_item = {}
        for row in pending_so_data:
            item_code = row.get('pb_code')
            if item_code:
                # If multiple SO entries exist for same item, sum them up
                pending_qty = row.get('pending_qty', 0)
                print(f"pb_code======================: {item_code}, pending_qty:=============================== {pending_qty}")
                if item_code in pending_qty_by_item:
                    pending_qty_by_item[item_code] += pending_qty
                else:
                    pending_qty_by_item[item_code] = pending_qty

        # Step 3: Delete existing records to start fresh
        frappe.db.sql("DELETE FROM `tabSO Quantity Check`")
        frappe.db.commit()
        print("Cleared existing SO Quantity Check records")

        # Step 4: Insert ONLY items from inventory data 
        # If they have pending SO, include that quantity
        count = 0
        for item_code, data in stock_map.items():
            parent1 = data.get('parent1', '')
            actual_qty = data.get('actual_qty', 0)
            # Check if this item has any pending SO quantities
            so_quantity = pending_qty_by_item.get(item_code, 0)
            
            # Ensure we have numeric values for calculation
            actual_qty = data.get('actual_qty', 0) or 0  # Convert None to 0
            so_quantity = pending_qty_by_item.get(item_code, 0) or 0  # Convert None to 0
            
            # Calculate remaining quantity after pending sales orders
            remaining_qty = actual_qty - so_quantity
            
            # Calculate update_qty as MAX(remaining_qty, 0)
            update_qty = max(remaining_qty, 0)
            
            # Calculate need_to_reduce as IF(remaining_qty<0, ABS(remaining_qty), 0)
            need_to_reduce = abs(remaining_qty) if remaining_qty < 0 else 0
            print(f"item_code: {item_code}, actual_qty: {actual_qty}, so_quantity: {so_quantity}, remaining_qty: {remaining_qty}, update_qty: {update_qty}, need_to_reduce: {need_to_reduce}")
            
            # Since fields are of type "Data", convert values to string
            remaining_qty_str = str(remaining_qty)
            update_qty_str = str(update_qty)
            need_to_reduce_str = str(need_to_reduce)
            
            doc = frappe.get_doc({
                "doctype": "SO Quantity Check",
                "item_code": item_code,
                "parent1": parent1,
                "actual_qty": actual_qty,
                "so_quantity": so_quantity,
                "remaining_qty": remaining_qty_str,
                "update_qty": update_qty_str,
                "need_to_reduce": need_to_reduce_str
            })
            doc.insert(ignore_permissions=True)
            count += 1
        
        frappe.db.commit()
        print(f"Successfully updated SO Quantity Check with {count} records")
        
        return True
    
    except Exception as e:
        print(f"Error updating SO Quantity Check: {e}")
        frappe.log_error(frappe.get_traceback(), "SO Quantity Check Update Error")
        return False
    

def update_parent_quantity():
    # Fetch parent-wise sum of need_to_reduce
    result = frappe.db.sql("""
        SELECT parent1, SUM(need_to_reduce)
        FROM `tabSO Quantity Check`
        WHERE need_to_reduce > 0
        GROUP BY parent1
    """, as_dict=True)

    for row in result:
        parent1 = row.parent1
        total = row["SUM(need_to_reduce)"]

        # Find all matching child rows to update
        child_rows = frappe.get_all(
            "SO Quantity Check",
            filters={"parent1": parent1},
            fields=["name"]
        )
        print("child_rows================",child_rows)

        for child in child_rows:
            frappe.db.set_value("SO Quantity Check", child.name, "remove_parent_qty", total)

    frappe.db.commit()


def update_proportional_qty_and_updt_qty():
    try:
        print("Starting update_proportional_qty_and_updt_qty")
        
        # Step 1: Fetch grouped total_update_qty for parent1 having more than one row
        # Handle NULL values in SQL query itself
        parent_totals = frappe.db.sql("""
            SELECT parent1, 
                   SUM(CAST(COALESCE(NULLIF(update_qty, ''), '0') AS DECIMAL(10,2))) AS total_update_qty
            FROM `tabSO Quantity Check`
            WHERE COALESCE(NULLIF(update_qty, ''), '0') != '0'
            GROUP BY parent1
        """, as_dict=True)
        
        print(f"Found {len(parent_totals)} parent groups with multiple items")
        
        for row in parent_totals:
            parent1 = row.parent1
            # Safely convert to float with default 0
            total_update_qty = float(row.total_update_qty or 0)
            
            # if total_update_qty == 0:
            #     print(f"Skipping parent {parent1} - total update qty is zero")
            #     continue  # Avoid division by zero
            
            # Step 2: Get individual records for this parent1
            items = frappe.get_all("SO Quantity Check",
                filters={"parent1": parent1},
                fields=["name", "update_qty", "remove_parent_qty", "remaining_qty", 
                       "proportional_remove_qty", "update_qty2"]
            )
            
            print(f"Processing {len(items)} items for parent {parent1}")
            
            for item in items:
                # Helper function to safely convert field values to float
                def safe_float(value, default=0.0):
                    """Convert value to float, handling None, empty string, and invalid values"""
                    if value is None or value == '' or value == 'None':
                        return default
                    try:
                        return float(str(value).strip())
                    except (ValueError, TypeError):
                        return default
                
                try:
                    # Convert all fields to float with default 0
                    update_qty = safe_float(item.update_qty, 0.0)
                    remove_parent_qty = safe_float(item.remove_parent_qty, 0.0)
                    # remaining_qty = safe_float(item.remaining_qty, 0.0)
                    
                    print(f"Item {item.name}: update_qty={update_qty}, remove_parent_qty={remove_parent_qty}")
                    
                    # Always calculate values, even for zero update_qty
                    # Calculate proportional values - get raw value first
                    if total_update_qty > 0:
                        proportional_remove_qty_raw = (update_qty / total_update_qty) * remove_parent_qty
                    else:
                        proportional_remove_qty_raw = 0.0
                    
                    # Convert to integer by rounding and ensure it's never None/NULL
                    proportional_remove_qty_int = 0
                    if proportional_remove_qty_raw is not None and proportional_remove_qty_raw != 0:
                        proportional_remove_qty_int = round(proportional_remove_qty_raw)
                    proportional_remove_qty_int = int(proportional_remove_qty_int or 0)  # Ensure integer
                    
                    # Calculate update_qty2 - convert update_qty to int first
                    update_qty_int = int(float(update_qty or 0))  # Convert float to int properly
                    update_qty2 = max(update_qty_int - proportional_remove_qty_int, 0)
                    
                    print(f"Item: {item.name}")
                    print(f"  - update_qty: {update_qty} -> update_qty_int: {update_qty_int}")
                    print(f"  - proportional_remove_qty_raw: {proportional_remove_qty_raw:.4f}")
                    print(f"  - proportional_remove_qty_int: {proportional_remove_qty_int}")
                    print(f"  - Calculation: {update_qty_int} - {proportional_remove_qty_int} = {update_qty2}")
                    print(f"  - Final update_qty2: {update_qty2}")
                    
                    # Skip items with zero or negative update_qty for processing but still update fields
                    if update_qty <= 0:
                        print(f"Note: Item {item.name} has zero/negative update qty, setting update_qty2 to 0")
                        update_qty2 = 0
                    
                    # Step 3: Update the record - ensure values are stored as strings and not empty
                    update_values = {
                        "proportional_remove_qty": str(int(proportional_remove_qty_int)),
                        "update_qty2": str(int(update_qty2))
                    }
                    
                    print(f"Updating database with values: {update_values}")
                    frappe.db.set_value("SO Quantity Check", item.name, update_values)
                    
                    # Verify the update worked
                    updated_record = frappe.get_doc("SO Quantity Check", item.name)
                    print(f"Verification - proportional_remove_qty: '{updated_record.proportional_remove_qty}', update_qty2: '{updated_record.update_qty2}'")
                    
                except (ValueError, TypeError, ZeroDivisionError) as e:
                    print(f"Error processing item {item.name}: {e}")
                    # Set default values even on error
                    frappe.db.set_value("SO Quantity Check", item.name, {
                        "proportional_remove_qty": "0",
                        "update_qty2": "0"
                    })
                    continue
            
            frappe.db.commit()
            print(f"Completed processing for parent {parent1}")
        
        print("Completed update_proportional_qty_and_updt_qty")
        return True
        
    except Exception as e:
        print(f"Error in update_proportional_qty_and_updt_qty: {e}")
        frappe.log_error(frappe.get_traceback(), "Proportional Qty Update Error")
        return False    

