# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
import pymysql
from frappe.model.document import Document
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error

class SOQuantityCheck(Document):
	pass

@frappe.whitelist()
def update_so_quantity_check(settings):
    """Update SO Quantity Check DocType with data from inventory and pending sales orders"""
    try:
        warehouses_list = []
        warehouses = settings['warehouses']
        departments = settings['departments']
        item_groups = settings['item_groups']

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
                        i.variant_of AS parent,
                        COUNT(b.serial_no) AS total_actual_qty_for_parent
                    FROM 
                        `tabItem` i
                    LEFT JOIN 
                        `tabSerial No` b ON i.item_code = b.item_code
                    LEFT JOIN 
                        `tabWarehouse` w ON b.warehouse = w.name
                    WHERE 
                        b.item_group IN ({item_group_placeholders})
                        AND w.department IN ({department_placeholders})
                        AND (b.return_reason != 'Repair' OR b.is_replace = 0)
                        {warehouse_clause}
                    GROUP BY 
                        i.variant_of
                ),

                Item_Stock AS (
                    SELECT 
                        s.item_code,
                        COUNT(s.serial_no) AS total_actual_qty_for_itemcode
                    FROM
                        `tabSerial No` s
                    INNER JOIN
                        `tabWarehouse` w ON w.name = s.warehouse
                    INNER JOIN
                        `tabItem` i ON s.item_code = i.item_code
                    WHERE
                        i.item_group IN ({item_group_placeholders})
                        AND w.department IN ({department_placeholders})
                        AND (s.return_reason != 'Repair' OR s.is_replace = 0)
                        {warehouse_clause}
                    GROUP BY 
                        s.item_code
                ),

                Main_Data AS (
                    SELECT DISTINCT
                        pb.shopify_variant_id,
                        i.item_code,
                        i.item_group,
                        i.variant_of AS parent,
                        ps.total_actual_qty_for_parent,
                        isq.total_actual_qty_for_itemcode
                    FROM 
                        `tabProduct Bundle` pb
                    LEFT JOIN 
                        `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
                    LEFT JOIN 
                        `tabItem` i ON pbi.item_code = i.item_code
                    LEFT JOIN 
                        Parent_Stock ps ON ps.parent = i.variant_of
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
            item_groups_list + departments_list + warehouses_list +
            item_groups_list + departments_list + warehouses_list +
            item_groups_list
        )

        inventory_data = frappe.db.sql(query, tuple(params), as_dict=True)

        stock_map = {}
        for row in inventory_data:
            item_code = row.get('item_code')
            if item_code:
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

                SUM(so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.qty, 0))) 
                    OVER (PARTITION BY CONCAT(it2.variant_of, ' ', proc.attribute_value)) AS total_pending_by_variant,

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
                    AND so.creation > CURDATE() - INTERVAL 50 DAY
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
                    AND dni.creation >= CURDATE() - INTERVAL 50 DAY
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

        pending_qty_by_item = {}
        for row in pending_so_data:
            item_code = row.get('pb_code')
            if item_code:
                pending_qty = row.get('pending_qty', 0)
                if item_code in pending_qty_by_item:
                    pending_qty_by_item[item_code] += pending_qty
                else:
                    pending_qty_by_item[item_code] = pending_qty

        frappe.db.sql("DELETE FROM `tabSO Quantity Check`")
        frappe.db.commit()

        # Step 4: Insert ONLY items from inventory data 
        # If they have pending SO, include that quantity
        count = 0
        for item_code, data in stock_map.items():
            parent1 = data.get('parent1', '')
            
            # Ensure we have numeric values for calculation
            actual_qty = data.get('actual_qty', 0) or 0
            so_quantity = pending_qty_by_item.get(item_code, 0) or 0
            
            # Calculate remaining quantity after pending sales orders
            remaining_qty = actual_qty - so_quantity
            
            # Calculate update_qty as MAX(remaining_qty, 0)
            update_qty = max(remaining_qty, 0)
            
            # Calculate need_to_reduce as IF(remaining_qty<0, ABS(remaining_qty), 0)
            need_to_reduce = abs(remaining_qty) if remaining_qty < 0 else 0
            
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
        log_error(f"SO Quantity Check updated for {count} items", "update_so_quantity_check", "Info")
        
        return True
    
    except pymysql.err.OperationalError as e:
        if e.args[0] == 2013:
            return False
        else:
            return False
    
    except Exception:
        log_error(frappe.get_traceback(), "update_so_quantity_check")
        return False
    
def update_parent_quantity():
    try:
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

            for child in child_rows:
                frappe.db.set_value("SO Quantity Check", child.name, "remove_parent_qty", total)

        frappe.db.commit()
        log_error("SO Quantity Check parent quantity updated", "update_parent_quantity", "Info")

        return True
    
    except pymysql.err.OperationalError as e:
        if e.args[0] == 2013:
            return False
        else:
            return False

    except Exception:
        log_error(frappe.get_traceback(), "update_parent_quantity")
        return False

def update_proportional_qty_and_updt_qty():
    try:
        # Step 1: Fetch grouped total_update_qty for parent1 having more than one row
        # Handle NULL values in SQL query itself
        parent_totals = frappe.db.sql("""
            SELECT parent1, 
                SUM(CAST(COALESCE(NULLIF(update_qty, ''), '0') AS DECIMAL(10,2))) AS total_update_qty
            FROM `tabSO Quantity Check`
            WHERE COALESCE(NULLIF(update_qty, ''), '0') != '0'
            GROUP BY parent1
        """, as_dict=True)
        
        for row in parent_totals:
            parent1 = row.parent1
            # Safely convert to float with default 0
            total_update_qty = float(row.total_update_qty or 0)
            
            # Step 2: Get individual records for this parent1
            items = frappe.get_all("SO Quantity Check",
                filters={"parent1": parent1},
                fields=["name", "update_qty", "remove_parent_qty", "remaining_qty", 
                       "proportional_remove_qty", "update_qty2"]
            )
            
            for item in items:
                def safe_float(value, default=0.0):
                    """Convert value to float, handling None, empty string, and invalid values"""
                    if value is None or value == '' or value == 'None':
                        return default
                    try:
                        return float(str(value).strip())
                    except (ValueError, TypeError):
                        return default
                
                try:
                    update_qty = safe_float(item.update_qty, 0.0)
                    remove_parent_qty = safe_float(item.remove_parent_qty, 0.0)
                    # remaining_qty = safe_float(item.remaining_qty, 0.0)
                    
                    if total_update_qty > 0:
                        proportional_remove_qty_raw = (update_qty / total_update_qty) * remove_parent_qty
                    else:
                        proportional_remove_qty_raw = 0.0
                    
                    proportional_remove_qty_int = 0
                    if proportional_remove_qty_raw is not None and proportional_remove_qty_raw != 0:
                        proportional_remove_qty_int = round(proportional_remove_qty_raw)
                    proportional_remove_qty_int = int(proportional_remove_qty_int or 0)
                    
                    update_qty_int = int(float(update_qty or 0))
                    update_qty2 = max(update_qty_int - proportional_remove_qty_int, 0)
                    
                    if update_qty <= 0:
                        update_qty2 = 0
                    
                    # Step 3: Update the record - ensure values are stored as strings and not empty
                    update_values = {
                        "proportional_remove_qty": str(int(proportional_remove_qty_int)),
                        "update_qty2": str(int(update_qty2))
                    }
                    
                    frappe.db.set_value("SO Quantity Check", item.name, update_values)

                except (ValueError, TypeError, ZeroDivisionError) as e:
                    frappe.db.set_value("SO Quantity Check", item.name, {
                        "proportional_remove_qty": "0",
                        "update_qty2": "0"
                    })
                    continue
            
            frappe.db.commit()
        
        log_error("SO Quantity Check proportional quantity and update quantity updated", "update_proportional_qty_and_updt_qty", "Info")
        return True
    
    except pymysql.err.OperationalError as e:
        if e.args[0] == 2013:
            return False
        else:
            return False
        
    except Exception:
        log_error(frappe.get_traceback(), "update_proportional_qty_and_updt_qty")
        return False