import math
import json, time
import requests as rs
import frappe, requests

shop = "https://newjaisa.myshopify.com"
# location_id = 65940881590  # Main location
location_id = 65940800500

@frappe.whitelist()
def fetch_and_stage_inventory_sync():
    # Step 1: Inventory sync from product bundle
    nj_inventory_log = frappe.new_doc("NJ Inventory Sync Log")
    results = frappe.db.sql("""WITH Parent_Stock AS (
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

            Main_Data AS (
                SELECT 
                    pb.shopify_variant_id,
                    COUNT(DISTINCT i.item_code) AS item_code_count,
                    GROUP_CONCAT(DISTINCT i.item_code ORDER BY i.item_code SEPARATOR ', ') AS item_codes,
                     GROUP_CONCAT(DISTINCT i.item_group ORDER BY i.item_group SEPARATOR ', ') AS item_groups,
                    b.actual_qty AS total_actual_qty,
                    CONCAT(i.item_model, ' ', proc.attribute_value) AS parent,
                    ps.total_actual_qty_for_parent
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
                    tabBin b ON i.item_code = b.item_code
                LEFT JOIN 
                    tabWarehouse w ON b.warehouse = w.name
                LEFT JOIN 
                    Parent_Stock ps ON ps.parent = CONCAT(i.item_model, ' ', proc.attribute_value)
                WHERE 
                    i.item_group IN ('Laptops', 'Desktops', 'MacBooks', 'Chromebooks')
                    AND w.department IN ('Packing & Dispatch - NJ', 'BG - Adaptor QC - NJ')
            )

            SELECT 
                md.shopify_variant_id,
                COUNT(DISTINCT md.item_code) AS item_code_count,
                GROUP_CONCAT(DISTINCT md.item_code ORDER BY md.item_code SEPARATOR ', ') AS item_codes,
                GROUP_CONCAT(DISTINCT md.item_group ORDER BY md.item_group SEPARATOR ', ') AS item_groups,
                CAST(SUM(md.actual_qty) AS DECIMAL(10,2)) AS total_actual_qty,
                GROUP_CONCAT(DISTINCT md.parent ORDER BY md.parent SEPARATOR ', ') AS parents,
                GROUP_CONCAT(DISTINCT md.total_actual_qty_for_parent ORDER BY md.parent SEPARATOR ', ') AS parentwise_total_actual_qty,
                CAST(SUM(DISTINCT md.total_actual_qty_for_parent) AS DECIMAL(10,2)) AS summed_parent_total_actual_qty
            FROM 
                Main_Data md
            GROUP BY 
                md.shopify_variant_id
            ORDER BY 
                total_actual_qty DESC;""", as_dict=True)

    # results = frappe.db.sql("""
    #         SELECT 
    #             pb.shopify_variant_id,
    #             COUNT(DISTINCT i.item_code) AS item_code_count,
    #             GROUP_CONCAT(DISTINCT i.item_code ORDER BY i.item_code SEPARATOR ', ') AS item_codes,
    #             GROUP_CONCAT(DISTINCT i.item_group ORDER BY i.item_group SEPARATOR ', ') AS item_groups,
    #             CAST(SUM(CASE 
    #                 WHEN d.department_name IN ('Packing & Dispatch', 'BG - Adaptor QC') THEN b.actual_qty 
    #                 ELSE 0 
    #             END) AS DECIMAL(10, 2)) AS total_actual_qty
    #         FROM 
    #             `tabProduct Bundle` pb
    #         JOIN 
    #             `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
    #         JOIN 
    #             `tabItem` i ON pbi.item_code = i.item_code
    #         LEFT JOIN 
    #             `tabBin` b ON i.item_code = b.item_code
    #         LEFT JOIN 
    #             `tabWarehouse` w ON b.warehouse = w.name
    #         LEFT JOIN 
    #             `tabDepartment` d ON w.department = d.name
    #         WHERE 
    #             i.item_group IN ('Laptops', 'Desktops', 'MacBooks')
    #             AND i.has_variants = 0
    #         GROUP BY 
    #             pb.shopify_variant_id
    #         HAVING 
    #             total_actual_qty >= 0
    #         ORDER BY 
    #             total_actual_qty DESC;
    # """, as_dict=True)
    nj_inventory_log.error("\n\nresults", results)
    item_to_variant_map = {}
    for row in results:
        if float(row.total_actual_qty) < 0:
            continue
        item_codes = row.item_codes.split(", ")
        for item_code in item_codes:
            item_to_variant_map[item_code] = row.shopify_variant_id
        item_groups = row.item_groups.split(", ") if row.item_groups else []

        for idx, item_code in enumerate(item_codes):
            item_group = item_groups[idx] if idx < len(item_groups) else ""
            existing = frappe.get_all("NJ Inventory Sync Main", filters={
                "shopify_variant_id": row.shopify_variant_id,
                "item_code": item_code
            }, fields=["name", "actual_qty", "sync_status", "is_active"])

            if existing:
                existing_doc = existing[0]
                if float(row.total_actual_qty) != float(existing_doc.actual_qty):
                    frappe.db.set_value("NJ Inventory Sync Main", existing_doc.name, {
                        "actual_qty": row.total_actual_qty,
                        "parent_qty": row.total_actual_qty_for_parent,
                        "sync_status": "Queued",
                        "is_active": 1
                    })
            else:
                doc = frappe.new_doc("NJ Inventory Sync Main")
                doc.item_code = item_code
                doc.item_name = item_code
                doc.actual_qty = row.total_actual_qty
                doc.parent_qty = row.total_actual_qty_for_parent
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
                    nj_inventory_log.error("\n168 - Duplicate item_code: %s", item_code, "\n", frappe.get_traceback())

                    # Try to fetch the existing doc and update syncerror field
                    try:
                        existing_doc_name = frappe.get_value("NJ Inventory Sync Main", {"item_code": item_code}, "name")
                        if existing_doc_name:
                            frappe.db.set_value("NJ Inventory Sync Main", existing_doc_name, {
                                "syncerror": error_msg
                            })
                    except Exception:
                        nj_inventory_log.error("\n", frappe.get_traceback(), f"178 - Failed to set syncerror for duplicate item_code: {item_code}")

                    continue

                except Exception as e:
                    error_msg = f"General error for item_code: {item_code} — {str(e)}"
                    nj_inventory_log.error("\n184 - Error in sync_inventory_to_shopify",frappe.get_traceback())
                    try:
                        doc.syncerror = error_msg
                        doc.flags.ignore_permissions = True
                        doc.insert()
                    except Exception:
                        nj_inventory_log.error("\n",frappe.get_traceback(), f"190 - Failed to log syncerror for item_code: {item_code}")
                    continue

    nj_inventory_log.save(ignore_permissions=True)
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

    try:
        # Step 1: Aggregate total pending qty per item_code
        pending_qty_map = {}
        for row in open_so_data:
            item_code = row.item_code
            pending_qty = float(row.pending_qty or 0)
            if item_code in pending_qty_map:
                pending_qty_map[item_code] += pending_qty
            else:
                pending_qty_map[item_code] = pending_qty

        # Step 2: For each item_code, update all matching inventory docs
        for item_code, total_so_qty in pending_qty_map.items():
            inventory_docs = frappe.get_all("NJ Inventory Sync Main", filters={
                "item_name": item_code
            }, fields=["name", "actual_qty"])

            for doc in inventory_docs:
                actual_qty = math.floor(0.4 * doc.total_qty) if float(doc.actual_qty or 0) <= 3 and doc.total_qty >= 10 else float(doc.actual_qty or 0)
                
                if total_so_qty >= actual_qty:
                    updated_qty = 0
                else:
                    updated_qty = actual_qty - total_so_qty
                frappe.db.set_value("NJ Inventory Sync Main", doc.name, {
                    "so_qty": total_so_qty,
                    "updated_qty": updated_qty
                })
    except Exception as e:
        nj_inventory_log.error("\nError updating pending_qty and updated_qty:", str(e))
        nj_inventory_log.save(ignore_permissions=True)

@frappe.whitelist()
def sync_inventory_to_shopify():
    token = "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"
    # shop = frappe.db.get_single_value("Shopify Settings", "shop_url")
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }
    
    queued = frappe.get_all("NJ Inventory Sync Main", filters={
        "sync_status": "Queued",
        "is_active": 1,
   }, fields=["name", "item_code", "actual_qty", "shopify_variant_id","updated_qty"])
    for row in queued:
        variant_ids = [v.strip() for v in row.shopify_variant_id.split(",") if v.strip()]
        if (
                not variant_ids 
                or (row.actual_qty is None or float(row.actual_qty) <0)
                or (row.updated_qty is not None and float(row.updated_qty) <0)
            ):
            continue

        for variant_id in variant_ids:
            try:
                variant_url = f"{shop}/admin/api/2023-01/variants/{variant_id}.json"
                variant_resp = rs.get(variant_url, headers=headers)
                variant_data = variant_resp.json()

                inventory_item_id = variant_data["variant"]["inventory_item_id"]
                update_url = f"{shop}/admin/api/2023-01/inventory_levels/set.json"
                
                updated_qty = row.updated_qty
                actual_qty = row.actual_qty

                # Skip if both are None or <= 0
                if not updated_qty and not actual_qty:
                    continue
                available = None
                if updated_qty is not None:
                    available = int(float(updated_qty))  # allows 0 and 0.0
                elif actual_qty is not None:
                    available = int(float(actual_qty))   # fallback
                else:
                    continue

                payload = {
                    "location_id": location_id,
                    "inventory_item_id": inventory_item_id,
                    "available":available

                }
                time.sleep(0.5)
                update_resp = rs.post(update_url, headers=headers, data=json.dumps(payload))
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

@frappe.whitelist()
def sync_inventory_to_shopify_2(batch_size=50, start=0):
    nj_inventory_log = frappe.new_doc("NJ Inventory Sync Log")
    nj_inventory_log.error(f"Processing batch starting at {start} with size {batch_size}")
    token = "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"

    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    queued = frappe.get_all(
        "NJ Inventory Sync Main", 
        filters={"sync_status": "Queued", "is_active": 1},
        fields=["name", "item_code", "actual_qty", "shopify_variant_id", "updated_qty"],
        start=start,
        page_length=batch_size
    )
    nj_inventory_log.error(f"\nFound {len(queued)} records to process.")

    processed_count = 0

    for row in queued:
        nj_inventory_log.error(f"\nProcessing row: {row}")
        try:
            variant_ids = [v.strip() for v in row.shopify_variant_id.split(",") if v.strip()] if row.shopify_variant_id else []
        except Exception as e:
            nj_inventory_log.error(f"\nError parsing variant IDs: {e}")
            variant_ids = []

        if not variant_ids or (row.actual_qty is None or float(row.actual_qty) < 0) or (row.updated_qty is not None and float(row.updated_qty) < 0):
            nj_inventory_log.error(f"\nSkipping row {row.name} due to missing or invalid data")
            continue

        nj_inventory_log.error(f"\nVariant IDs: {variant_ids}")
        sync_success = True

        for variant_id in variant_ids:
            try:
                variant_url = f"\n{shop}/admin/api/2023-01/variants/{variant_id}.json"
                nj_inventory_log.error(f"\nGetting variant info from: {variant_url}")
                variant_resp = requests.get(variant_url, headers=headers)
                nj_inventory_log.error(f"\nVariant response code: {variant_resp.status_code}")

                if variant_resp.status_code != 200:
                    nj_inventory_log.error(f"\nFailed to get variant info for {variant_id}: {variant_resp.text}")
                    sync_success = False
                    continue

                variant_data = variant_resp.json()
                inventory_item_id = variant_data["variant"]["inventory_item_id"]
                nj_inventory_log.error(f"\nInventory item ID: {inventory_item_id}")

                available = int(float(row.updated_qty)) if row.updated_qty is not None else int(float(row.actual_qty))
                payload = {
                    "location_id": location_id,
                    "inventory_item_id": inventory_item_id,
                    "available": available
                }
                time.sleep(0.5)
                update_url = f"{shop}/admin/api/2023-01/inventory_levels/set.json"
                update_resp = requests.post(update_url, headers=headers, data=json.dumps(payload))

                if update_resp.status_code != 200:
                    nj_inventory_log.error(f"\nFailed to update inventory for {variant_id}: {update_resp.text}")
                    nj_inventory_log.save(ignore_permissions=True)
                    sync_success = False
            except Exception as e:
                nj_inventory_log.error(f"\nException during sync for {variant_id}: {str(e)}")
                nj_inventory_log.save(ignore_permissions=True)
                sync_success = False
                continue
        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
            "sync_status": "Completed",
            "is_active": 1
        })

        new_status = "Synced" if sync_success else "Failed"
        processed_count += 1
        nj_inventory_log.error(f"\nProcessed count: {processed_count}")

        if processed_count % 10 == 0:
            frappe.db.commit()

    frappe.db.commit()

    total_remaining = frappe.db.count("NJ Inventory Sync Main", filters={"sync_status": "Queued", "is_active": 1})
    if total_remaining > 0:
        nj_inventory_log.error(f"\n{total_remaining} records still queued. Scheduling next batch from {start + batch_size}")
        try:
            frappe.enqueue(
                sync_inventory_to_shopify_2,
                batch_size=batch_size,
                start=start + batch_size,
                queue='long',
                timeout=4500
            )
        except Exception as e:
            nj_inventory_log.error(f"\n440 - Failed to enqueue next batch: {str(e)}")
            nj_inventory_log.save(ignore_permissions=True)

        nj_inventory_log.error(f"\n442 - Processed {processed_count} records. Scheduled next batch.")
        nj_inventory_log.save(ignore_permissions=True)
        return f"Processed {processed_count} records. Scheduled next batch."

    nj_inventory_log.error(f"\nCompleted processing {processed_count} records.")
    nj_inventory_log.save(ignore_permissions=True)
    return f"Completed processing {processed_count} records."

# Function to initiate the batch process
@frappe.whitelist()
def start_shopify_inventory_sync(batch_size=50):
    """Start the inventory sync process with batching"""
    return sync_inventory_to_shopify_2(batch_size=int(batch_size), start=0)

@frappe.whitelist()
def get_all_variant_ids():
    token = "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"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    base_url = "https://newjaisa.myshopify.com/admin/api/2024-01/products.json"
    params = {
        "limit": 250,
        "fields": "id,title,variants,product_type"
    }

    variant_ids_added = 0
    variant_ids_skipped = 0

    while base_url:
        response = requests.get(base_url, headers=headers, params=params)
        if response.status_code != 200:
            frappe.log_error(f"Error fetching Shopify products: {response.text}")
            break

        products = response.json().get("products", [])

        for product in products:
            product_type = product.get("product_type") or "Default"

            # Check if Item Group exists
            item_group_exists = frappe.db.exists("Item Group", {"name": product_type})

            for variant in product.get("variants", []):
                variant_id = str(variant.get("id"))

                if not frappe.db.exists("NJ Inventory Sync Main", {"shopify_variant_id": variant_id}):
                    doc = frappe.new_doc("NJ Inventory Sync Main")
                    doc.shopify_variant_id = variant_id
                    if item_group_exists:
                        doc.item_group = product_type
                    doc.actual_qty = 0
                    doc.updated_qty = 0
                    doc.is_active = 0
                    doc.insert(ignore_permissions=True)
                    variant_ids_added += 1

        # Handle pagination
        link_header = response.headers.get("Link")
        if link_header and 'rel="next"' in link_header:
            links = link_header.split(",")
            next_url = None
            for link in links:
                if 'rel="next"' in link:
                    next_url = link.split(";")[0].strip()[1:-1]
                    break
            base_url = next_url
            params = {}  # Reset params since URL has them
        else:
            base_url = None

    frappe.msgprint(f"{variant_ids_added} variant IDs added successfully.")
@frappe.whitelist()
def corrected_updated_qty():
    docs = frappe.get_all("NJ Inventory Sync Main", fields=["name", "actual_qty", "so_qty"])

    for doc in docs:
        actual_qty = float(doc.actual_qty or 0)
        so_qty = float(doc.so_qty or 0)

        updated_qty = 0.0 if so_qty > actual_qty else actual_qty - so_qty

        frappe.db.set_value("NJ Inventory Sync Main", doc.name, {
            "updated_qty": updated_qty
        })

    frappe.db.commit()