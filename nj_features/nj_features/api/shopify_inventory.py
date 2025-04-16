import requests as rs
import frappe
import json
shop = "https://newjaisa.myshopify.com"
location_id = 65940881590
@frappe.whitelist()
def fetch_and_stage_inventory_sync():
    # Step 1: Inventory sync from product bundle
    results = frappe.db.sql("""
        SELECT 
            pb.shopify_variant_id,
            COUNT(DISTINCT i.item_code) AS item_code_count,
            GROUP_CONCAT(DISTINCT i.item_code ORDER BY i.item_code SEPARATOR ', ') AS item_codes,
            GROUP_CONCAT(DISTINCT i.item_group ORDER BY i.item_group SEPARATOR ', ') AS item_groups,
            CAST(SUM(b.actual_qty) AS DECIMAL(10, 2)) AS total_actual_qty
        FROM 
            `tabProduct Bundle` pb
        JOIN 
            `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
        JOIN 
            `tabItem` i ON pbi.item_code = i.item_code
        JOIN 
            `tabBin` b ON i.item_code = b.item_code
        JOIN 
            `tabWarehouse` w ON b.warehouse = w.name
        JOIN 
            `tabDepartment` d ON w.department = d.name
        WHERE 
            i.item_group IN ('Laptops', 'Desktops', 'MacBooks')
            AND i.has_variants = 0 
            AND d.department_name IN ('Packing & Dispatch', 'BG - Adaptor QC')
        GROUP BY 
            pb.shopify_variant_id
        HAVING 
            total_actual_qty > 0
        ORDER BY 
            total_actual_qty DESC;
    """, as_dict=True)
    print("results----39---", results)
    item_to_variant_map = {}
    for row in results:
        if float(row.total_actual_qty) <= 0:
            continue

        item_codes = row.item_codes.split(", ")
        for item_code in item_codes:
            item_to_variant_map[item_code] = row.shopify_variant_id
        item_groups = row.item_groups.split(", ") if row.item_groups else []

        for idx, item_code in enumerate(item_codes):
            item_group = item_groups[idx] if idx < len(item_groups) else ""

                        # Before inserting a new document
            existing = frappe.get_all("NJ Inventory Sync Main", filters={
                "shopify_variant_id": row.shopify_variant_id,
                "item_code": item_code
            }, fields=["name", "actual_qty", "sync_status", "is_active"])

            if existing:
                existing_doc = existing[0]
                if float(row.total_actual_qty) != float(existing_doc.actual_qty):
                    frappe.db.set_value("NJ Inventory Sync Main", existing_doc.name, {
                        "actual_qty": row.total_actual_qty,
                        "sync_status": "Queued",
                        "is_active": 1
                    })
            else:
                doc = frappe.new_doc("NJ Inventory Sync Main")
                doc.item_code = item_code
                doc.item_name = item_code
                doc.actual_qty = row.total_actual_qty
                doc.item_group = item_group
                doc.shopify_variant_id = row.shopify_variant_id
                doc.sync_status = "Queued"
                doc.is_active = 1
                try:
                    doc.insert()
                except frappe.UniqueValidationError as e:
                    error_msg = f"Duplicate item_code: {item_code} — {str(e)}"
                    # Truncate the error message to 140 characters
                    truncated_error_msg = error_msg[:140]
                    frappe.log_error(frappe.get_traceback(), truncated_error_msg)

                    # Try to fetch the existing doc and update syncerror field
                    try:
                        existing_doc_name = frappe.get_value("NJ Inventory Sync Main", {"item_code": item_code}, "name")
                        if existing_doc_name:
                            frappe.db.set_value("NJ Inventory Sync Main", existing_doc_name, {
                                "syncerror": error_msg
                            })
                    except Exception:
                        frappe.log_error(frappe.get_traceback(), f"Failed to set syncerror for duplicate item_code: {item_code}")

                    continue

                except Exception as e:
                    error_msg = f"General error for item_code: {item_code} — {str(e)}"
                    # Truncate the error message to 140 characters
                    truncated_error_msg = error_msg[:140]
                    frappe.log_error(frappe.get_traceback(), truncated_error_msg)
                    try:
                        doc.syncerror = error_msg
                        doc.flags.ignore_permissions = True
                        doc.insert()
                    except Exception:
                        frappe.log_error(frappe.get_traceback(), f"Failed to log syncerror for item_code: {item_code}")
                    continue

    open_so_data = frappe.db.sql("""
        SELECT 
            so_data.sales_order,
            so_data.item_code,
            so_data.item_group,
            so_data.creation AS so_creation,
            so_data.rate,
            so_data.qty AS so_qty,
            IFNULL(dn_data.qty, 0) AS dn_qty,
            LEAST(so_data.qty, IFNULL(dn_data.qty, 0)) AS min_so_dn_qty,
            so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.qty, 0)) AS pending_qty
        FROM 
            (
                SELECT 
                    soi.parent AS sales_order, 
                    soi.item_code, 
                    soi.qty, 
                    soi.item_group, 
                    so.creation, 
                    soi.rate 
                FROM 
                    `tabSales Order` so 
                INNER JOIN 
                    `tabSales Order Item` soi ON so.name = soi.parent 
                WHERE 
                    so.status NOT IN ('Closed','Completed','Draft','Cancelled') 
                    AND so.creation > CURDATE() - INTERVAL 20 DAY 
                    AND soi.item_group IN ('Laptops', 'Chromebooks','MacBooks') 
                    AND so.sale_type != 'Amazon'
            ) AS so_data
        LEFT JOIN 
            (
                SELECT 
                    b.against_sales_order,
                    b.item_code,
                    SUM(b.qty) AS qty
                FROM 
                    `tabDelivery Note` a 
                INNER JOIN 
                    `tabDelivery Note Item` b ON a.name = b.parent 
                WHERE 
                    a.docstatus = '1' 
                    AND b.item_group IN ('Laptops', 'Chromebooks','MacBooks') 
                    AND a.creation >= CURDATE() - INTERVAL 20 DAY 
                    AND b.qty > 0
                GROUP BY 
                    b.against_sales_order, b.item_code
            ) AS dn_data
        ON 
            so_data.sales_order = dn_data.against_sales_order 
            AND so_data.item_code = dn_data.item_code
        ORDER BY 
            so_data.sales_order, so_data.item_code;
    """, as_dict=True)
    print("so_data----70---", open_so_data)
    try:
        for row in open_so_data:
            item_code = row.item_code
            shopify_variant_id = item_to_variant_map.get(item_code)

            if not shopify_variant_id:
                continue
            inventory_docs = frappe.get_all("NJ Inventory Sync Main", filters={
                "item_name": row.item_code,
                "shopify_variant_id": shopify_variant_id
            }, fields=["name", "actual_qty"])

            for doc in inventory_docs:
                actual_qty = float(doc.actual_qty or 0)
                so_qty = float(row.pending_qty or 0)
                updated_qty = actual_qty - so_qty

                frappe.db.set_value("NJ Inventory Sync Main", doc.name, {
                    "so_qty": so_qty,
                    "updated_qty": updated_qty
                })
    except Exception as e:
        print("Error updating pending_qty and updated_qty:", str(e))



@frappe.whitelist()
def sync_inventory_to_shopify():
    print("hii inside sync_inventory_to_shopify")
    token = "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"
    # shop = frappe.db.get_single_value("Shopify Settings", "shop_url")
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }
    
    print("headers-----71", headers)
    queued = frappe.get_all("NJ Inventory Sync Main", filters={
        "sync_status": "Queued",
        "is_active": 1,
        "shopify_variant_id": ["in", ["43748392042678", "43748392075446", "43748392108214","43765186953398","43792147873974","43792147841206","43792147611830","42205312909494","43790420967606"]],
   }, fields=["name", "item_code", "actual_qty", "shopify_variant_id","updated_qty"])
    print("queued-----78", queued)
    for row in queued:
        print("row-----79", row)
        variant_ids = [v.strip() for v in row.shopify_variant_id.split(",") if v.strip()]
        print("variant_ids-----80", variant_ids)
        if (
                not variant_ids 
                or (row.actual_qty is None or float(row.actual_qty) <= 0)
                or (row.updated_qty is not None and float(row.updated_qty) <= 0)
            ):
            continue

        for variant_id in variant_ids:
            try:
                variant_url = f"{shop}/admin/api/2023-01/variants/{variant_id}.json"
                variant_resp = rs.get(variant_url, headers=headers)
                variant_data = variant_resp.json()

                inventory_item_id = variant_data["variant"]["inventory_item_id"]
                print("inventory_item_id-----88", inventory_item_id)
                update_url = f"{shop}/admin/api/2023-01/inventory_levels/set.json"
                print("update_url-----89", update_url)
                print("row.updated_qty-----90", row.updated_qty)
                print("row.actual_qty-----91", row.actual_qty)
                updated_qty = row.updated_qty
                actual_qty = row.actual_qty

                # Skip if both are None or <= 0
                if not updated_qty and not actual_qty:
                    continue
                available = None
                if updated_qty and float(updated_qty) > 0:
                    available = int(float(updated_qty))
                elif actual_qty and float(actual_qty) > 0:
                    available = int(float(actual_qty))
                else:
                    continue 
                payload = {
                    "location_id": location_id,
                    "inventory_item_id": inventory_item_id,
                    "available":available

                }
                print("payload-----90", payload)
                update_resp = rs.post(update_url, headers=headers, data=json.dumps(payload))
                print("update_resp-----91", update_resp)
                if update_resp.status_code != 200:
                    frappe.log_error(f"Shopify Inventory Update Error for {variant_id}", update_resp.text)

            except Exception as e:
                frappe.log_error(f"Inventory sync failed for {variant_id}", str(e))
                continue
        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
            "sync_status": "Completed",
            "is_active": 0
        })
        frappe.db.commit()
