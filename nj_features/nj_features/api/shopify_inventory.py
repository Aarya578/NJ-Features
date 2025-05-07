import json, time
import traceback
import frappe, requests

nj_inventry_settings = frappe.get_single("NJ Inventory Settings")

shop = nj_inventry_settings.shop
token = nj_inventry_settings.token
warehouses = nj_inventry_settings.warehouses
location_id = nj_inventry_settings.location_id
item_groups = nj_inventry_settings.item_groups
departments = nj_inventry_settings.departments

@frappe.whitelist()
def fetch_and_stage_inventory_sync():
    try:
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

        query = f"""
            SELECT 
                pb.shopify_variant_id,
                GROUP_CONCAT(DISTINCT i.item_code ORDER BY i.item_code SEPARATOR ', ') AS item_codes,
                GROUP_CONCAT(DISTINCT i.item_group ORDER BY i.item_group SEPARATOR ', ') AS item_groups,
                CAST(SUM(CASE 
                    WHEN d.department_name IN ({department_placeholders}) THEN b.actual_qty 
                    ELSE 0 
                END) AS DECIMAL(10, 2)) AS total_actual_qty
            FROM 
                `tabProduct Bundle` pb
            JOIN 
                `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
            JOIN 
                `tabItem` i ON pbi.item_code = i.item_code
            LEFT JOIN 
                `tabBin` b ON i.item_code = b.item_code
            LEFT JOIN 
                `tabWarehouse` w ON b.warehouse = w.name
            LEFT JOIN 
                `tabDepartment` d ON w.department = d.name
            WHERE 
                i.item_group IN ({item_group_placeholders})
                AND i.has_variants = 0 
                {warehouse_clause}
            GROUP BY 
                pb.shopify_variant_id
            HAVING 
                total_actual_qty >= 0
            ORDER BY 
                total_actual_qty DESC
        """

        params = departments_list + item_groups_list

        results = frappe.db.sql(query, params, as_dict=True)

        for row in results:

            row.total_actual_qty = safe_float(row.total_actual_qty)
            if row.total_actual_qty is None or row.total_actual_qty < 0:
                continue

            item_code_like_clauses = []
            params = [row.shopify_variant_id]  # First param for variant_id

            for code in row.item_codes:
                item_code_like_clauses.append("item_code LIKE %s")
                params.append(f"%{code.strip()}%")

            query = f"""
                SELECT name, actual_qty, sync_status, is_active
                FROM `tabNJ Inventory Sync Main`
                WHERE shopify_variant_id = %s AND ({' OR '.join(item_code_like_clauses)})
                ORDER BY modified DESC
            """

            existing = frappe.db.sql(query, tuple(params), as_dict=True)

            if existing:
                existing_doc = existing[0]
                updated_doc_names.add(existing_doc.name)
                existing_doc_actual_qty = safe_float(existing_doc.actual_qty) or 0
                if float(row.total_actual_qty) != existing_doc_actual_qty:
                    frappe.db.set_value("NJ Inventory Sync Main", existing_doc.name, {
                        "so_qty": "",
                        "is_active": 1,
                        "sync_error": "",
                        "sync_status": "Queued",
                        "actual_qty": row.total_actual_qty,
                        "updated_qty": row.total_actual_qty,
                    })
            else:
                doc = frappe.new_doc("NJ Inventory Sync Main")

                doc.is_active = 1
                doc.item_code = row.item_codes
                doc.sync_status = "Queued"
                doc.item_group = row.item_groups
                doc.actual_qty = row.total_actual_qty
                doc.updated_qty = row.total_actual_qty
                doc.shopify_variant_id = row.shopify_variant_id

                try:
                    doc.insert()

                except frappe.UniqueValidationError as e:
                    error_msg = f"Duplicate item_codes: {row.item_codes}, shopify_variant_id: {row.shopify_variant_id}"
                    nj_inventory_log.error += f"\n168 - error_msg: {error_msg}"
                    nj_inventory_log.save(ignore_permissions=True)

                    continue

                except Exception as e:
                    error_msg = f"Duplicate item_codes: {row.item_codes}, shopify_variant_id: {row.shopify_variant_id}"
                    nj_inventory_log.error += f"\n184 - Error in sync_inventory_to_shopify: {frappe.get_traceback()}\nitem_code: {item_code}, shopify_variant_id: {row.shopify_variant_id}"
                    nj_inventory_log.save(ignore_permissions=True)

                    continue

        item_groups_list = [i.strip() for i in item_groups.split(',') if i.strip()]
        item_group_placeholders = ', '.join(['%s'] * len(item_groups_list))

        open_so_query = f"""
            SELECT 
                so_data.sales_order,
                so_data.item_code,
                so_data.item_group,
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
                        AND soi.item_group IN ({item_group_placeholders}) 
                        AND so.sale_type != 'Amazon'
                ) AS so_data
            LEFT JOIN 
                (
                    SELECT 
                        b.against_sales_order,
                        b.item_code,
                        SUM(b.qty) AS qty
                    FROM `tabDelivery Note Item` b
                    WHERE 
                        b.docstatus = '1' 
                        AND b.item_group IN ({item_group_placeholders}) 
                        AND b.creation >= CURDATE() - INTERVAL 20 DAY 
                        AND b.qty > 0
                    GROUP BY 
                        b.against_sales_order, b.item_code
                ) AS dn_data
            ON 
                so_data.sales_order = dn_data.against_sales_order 
                AND so_data.item_code = dn_data.item_code
            ORDER BY 
                so_data.sales_order, so_data.item_code
            """

        open_so_data = frappe.db.sql(open_so_query, item_groups_list * 2, as_dict=True)

        try:
            pending_qty_map = {}
            for row in open_so_data:
                item_code = row.item_code
                pending_qty = float(row.pending_qty or 0)
                if item_code in pending_qty_map:
                    pending_qty_map[item_code] += pending_qty
                else:
                    pending_qty_map[item_code] = pending_qty

            for item_code, total_so_qty in pending_qty_map.items():
                inventory_docs = frappe.get_all("NJ Inventory Sync Main", 
                    filters={ "item_code": ["in", item_code] }, fields=["name", "actual_qty"])
                
                for doc in inventory_docs:
                    updated_actual_qty = float(doc.actual_qty or 0)

                    if total_so_qty >= updated_actual_qty:
                        updated_qty = 0
                    else:
                        updated_qty = updated_actual_qty - total_so_qty
                    frappe.db.set_value("NJ Inventory Sync Main", doc.name, {
                        "so_qty": total_so_qty,
                        "updated_qty": updated_qty
                    })
                    updated_doc_names.add(doc.name)

        except Exception as e:
            nj_inventory_log.error += f"\nError updating pending_qty and updated_qty: {str(e)}\n{frappe.get_traceback()}"
            nj_inventory_log.save(ignore_permissions=True)

        all_docs = frappe.get_all("NJ Inventory Sync Main", fields=["name"])
        all_doc_names = set(doc["name"] for doc in all_docs)

        not_updated_doc_names = all_doc_names - updated_doc_names

        nj_inventory_log.error += (
            f"\nTotal Docs: {len(all_doc_names)}, "
            f"Updated Docs: {len(updated_doc_names)}, "
            f"Not Updated Docs: {len(not_updated_doc_names)}"
        )

        nj_inventory_log.save(ignore_permissions=True)

        for name in not_updated_doc_names:
            frappe.db.set_value("NJ Inventory Sync Main", name, {
                "actual_qty": "0",
                "updated_qty": "0"
            })

    except Exception as e:
        return str(traceback.format_exc())

@frappe.whitelist()
def sync_inventory_to_shopify():
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }
    
    queued = frappe.get_all("NJ Inventory Sync Main", filters={
        "sync_status": "Queued", "is_active": 1,
        }, fields=["name", "item_code", "actual_qty", "shopify_variant_id", "updated_qty"])
    
    for row in queued:
        row_updated_qty = safe_float(row.updated_qty)
        variant_ids = [v.strip() for v in row.shopify_variant_id.split(",") if v.strip()]
        if (
                not variant_ids 
                or (row.actual_qty is None or float(row.actual_qty) <0)
                or (row_updated_qty is not None and float(row_updated_qty) <0)
            ):
            continue

        for variant_id in variant_ids:
            try:
                variant_url = f"{shop}/admin/api/2023-01/variants/{variant_id}.json"
                variant_resp = requests.get(variant_url, headers=headers)
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
                update_resp = requests.post(update_url, headers=headers, data=json.dumps(payload))
                if update_resp.status_code != 200:
                    frappe.log_error(f"Shopify Inventory Update Error for {variant_id}", update_resp.text)

                frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                    "sync_status": "Completed",
                    "is_active": 0
                })
                frappe.db.commit()

            except Exception as e:
                frappe.log_error(f"Inventory sync failed for {variant_id}", str(e))
                continue


@frappe.whitelist()
def sync_inventory_to_shopify_2(batch_size=50, start=0):
    nj_inventory_log = frappe.new_doc("NJ Inventory Sync Log")
    nj_inventory_log.error += f"Processing batch starting at {start} with size {batch_size}"

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
    nj_inventory_log.error += f"\nFound {len(queued)} records to process."

    processed_count = 0

    for row in queued:
        nj_inventory_log.error += f"\nProcessing row: {row}"
        try:
            variant_ids = [v.strip() for v in row.shopify_variant_id.split(",") if v.strip()] if row.shopify_variant_id else []
        except Exception as e:
            nj_inventory_log.error += f"\nError parsing variant IDs: {e}"
            variant_ids = []

        row_updated_qty = safe_float(row.updated_qty)
        if not variant_ids or (row.actual_qty is None or float(row.actual_qty) < 0) or (row_updated_qty is not None and float(row_updated_qty) < 0):
            nj_inventory_log.error += f"\nSkipping row {row.name} due to missing or invalid data"
            continue

        nj_inventory_log.error += f"\nVariant IDs: {variant_ids}"
        sync_success = True

        for variant_id in variant_ids:
            try:
                variant_url = f"{shop}/admin/api/2023-01/variants/{variant_id}.json"
                nj_inventory_log.error += f"\nGetting variant info from: {variant_url}"
                variant_resp = requests.get(variant_url, headers=headers)
                nj_inventory_log.error += f"\nVariant response code: {variant_resp.status_code}"

                if variant_resp.status_code != 200:
                    nj_inventory_log.error += f"\nFailed to get variant info for {variant_id}: {variant_resp.text}"
                    sync_success = False
                    continue

                variant_data = variant_resp.json()
                inventory_item_id = variant_data["variant"]["inventory_item_id"]
                nj_inventory_log.error += f"\nInventory item ID: {inventory_item_id}"

                available = int(float(row_updated_qty)) if row_updated_qty is not None else int(float(row.actual_qty))
                payload = {
                    "location_id": location_id,
                    "inventory_item_id": inventory_item_id,
                    "available": available
                }
                time.sleep(0.5)
                update_url = f"{shop}/admin/api/2023-01/inventory_levels/set.json"
                update_resp = requests.post(update_url, headers=headers, data=json.dumps(payload))

                if update_resp.status_code != 200:
                    nj_inventory_log.error += f"\nFailed to update inventory for {variant_id}: {update_resp.text}"
            
            except Exception as e:
                nj_inventory_log.error += f"\nException during sync for {variant_id}: {str(e)}"
                continue

        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
            "sync_status": "Completed",
            "is_active": 1
        })

        processed_count += 1
        nj_inventory_log.error += f"\nProcessed count: {processed_count}"

    frappe.db.commit()

    total_remaining = frappe.db.count("NJ Inventory Sync Main", filters={"sync_status": "Queued", "is_active": 1})
    if total_remaining > 0:
        nj_inventory_log.error += f"\n{total_remaining} records still queued. Scheduling next batch from {start + batch_size}"
        try:
            frappe.enqueue(
                sync_inventory_to_shopify_2,
                batch_size=batch_size,
                start=start + batch_size,
                queue='long',
                timeout=4500
            )
        except Exception as e:
            nj_inventory_log.error += f"\nFailed to enqueue next batch: {str(e)}"

        nj_inventory_log.error += f"\nProcessed {processed_count} records. Scheduled next batch."
        return f"Processed {processed_count} records. Scheduled next batch."

    nj_inventory_log.error += f"\nCompleted processing {processed_count} records."
    nj_inventory_log.save(ignore_permissions=True)
    return f"Completed processing {processed_count} records."

# Function to initiate the batch process
@frappe.whitelist()
def start_shopify_inventory_sync(batch_size=50):
    """Start the inventory sync process with batching"""
    return sync_inventory_to_shopify_2(batch_size=int(batch_size), start=0)

@frappe.whitelist()
def get_all_variant_ids():
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

def safe_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# Not used, This is based 40% on parent qty
# def calculate_qty(actual_qty, parent_qty):

#     if isinstance(actual_qty, str):
#         actual_qty = float(actual_qty)

#     if isinstance(parent_qty, str):
#         parent_qty = float(parent_qty)

#     if actual_qty <= 3:
#         if parent_qty >= 10:
#             return int(0.4 * parent_qty)
#         else:
#             return actual_qty
#     else:
#         return actual_qty