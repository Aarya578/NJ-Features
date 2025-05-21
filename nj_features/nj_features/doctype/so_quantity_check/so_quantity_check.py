# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SOQuantityCheck(Document):
	pass




def update_so_quantity_check():
    # Clear existing records (optional, depending on your requirement)
    # frappe.db.sql("DELETE FROM `tabSO Quantity Check`")

    # --- First Query: Stock and Parent Info ---
    stock_data = frappe.db.sql("""
        WITH Parent_Stock AS (
            SELECT 
                CONCAT(i.item_model, ' ', proc.attribute_value) AS parent,
                CAST(SUM(b.actual_qty) AS DECIMAL(10, 2)) AS total_actual_qty_for_parent
            FROM 
                tabItem i
            INNER JOIN 
                `tabItem Variant Attribute` proc ON i.name = proc.parent 
                    AND proc.attribute LIKE '%Processor%'
            LEFT JOIN 
                tabBin b ON i.item_code = b.item_code
            LEFT JOIN 
                tabWarehouse w ON b.warehouse = w.name
            WHERE 
                i.item_group IN ('Laptops', 'Desktops', 'MacBooks', 'Chromebooks')
                AND w.department IN ('Packing & Dispatch - NJ', 'BG - Adaptor QC - NJ')
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
                i.item_group IN ('Laptops', 'Desktops', 'MacBooks', 'Chromebooks')
                AND w.department IN ('Packing & Dispatch - NJ', 'BG - Adaptor QC - NJ')
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
                    AND proc.attribute LIKE '%Processor%'
            LEFT JOIN 
                Parent_Stock ps ON ps.parent = CONCAT(i.item_model, ' ', proc.attribute_value)
            LEFT JOIN 
                Item_Stock isq ON isq.item_code = i.item_code
            WHERE 
                i.item_group IN ('Laptops', 'Desktops', 'MacBooks', 'Chromebooks')
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
    """, as_dict=True)

    # Create mapping of item_code to actual_qty and parent
    stock_map = {
        row["item_code"]: {
            "actual_qty": row["actual_qty"],
            "parent1": row["parent"]
        } for row in stock_data
    }

    # --- Second Query: Sales Order and Pending Quantity ---
    pending_data = frappe.db.sql("""
        SELECT 
            so_data.sales_order,
            so_data.item_code,
            IFNULL(so_data.pb_code, so_data.item_code) AS pb_code,
            so_data.item_group,
            so_data.qty AS so_qty,
            IFNULL(dn_data.qty, 0) AS dn_qty,
            LEAST(so_data.qty, IFNULL(dn_data.qty, 0)) AS min_so_dn_qty,
            so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.qty, 0)) AS pending_qty,
            CONCAT(it2.variant_of, ' ', proc.attribute_value) AS variant_with_processor,

            SUM(so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.qty, 0))) 
                OVER (PARTITION BY CONCAT(it2.variant_of, ' ', proc.attribute_value)) AS total_pending_by_variant

        FROM (
            SELECT 
                soi.parent AS sales_order,
                soi.item_code,
                pb.item_code AS pb_code,
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
        ON it2.item_code = IFNULL(so_data.pb_code, so_data.item_code)

        LEFT JOIN `tabItem Variant Attribute` proc 
        ON proc.parent = it2.name
        AND proc.attribute LIKE '%Processor%'

        ORDER BY so_data.sales_order, so_data.item_code
    """, as_dict=True)

    # Insert new records
    for row in pending_data:
        item_code = row.get("item_code")
        pending_qty = row.get("pending_qty", 0)

        stock_info = stock_map.get(item_code, {})

        frappe.get_doc({
            "doctype": "SO Quantity Check",
            "item_code": item_code,
            "parent1": stock_info.get("parent1", ""),
            "actual_qty": stock_info.get("actual_qty", 0),
            "so_quantity": pending_qty
        }).insert(ignore_permissions=True)

    frappe.db.commit()
