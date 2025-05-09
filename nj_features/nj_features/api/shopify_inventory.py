import shopify
import traceback
import json, time
import frappe, requests

nj_inventry_settings = frappe.get_single("NJ Inventory Settings")

shop = nj_inventry_settings.shop
token = nj_inventry_settings.token
warehouses = nj_inventry_settings.warehouses
location_id = nj_inventry_settings.location_id
item_groups = nj_inventry_settings.item_groups
departments = nj_inventry_settings.departments

headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json"
        }

def nj_temp_shopify_session(func):
    """ Starts a temporary Shopify session using NJ Inventory Settings."""

    def wrapper(*args, **kwargs):
        if frappe.flags.in_test:
            return func(*args, **kwargs)

        settings = frappe.get_single("NJ Inventory Settings")
        if settings:
            shop_url = settings.shop
            password = settings.token
            api_version = "2025-04"

            from shopify import Session
            with Session.temp(shop_url, api_version, password):
                return func(*args, **kwargs)

        return func(*args, **kwargs)

    return wrapper

@frappe.whitelist()
@nj_temp_shopify_session
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
            params = [row.shopify_variant_id]

            for code in row.item_codes:
                item_code_like_clauses.append("item_code LIKE %s")
                params.append(f"%{code.strip()}%")

            query = f"""
                SELECT name, actual_qty, sync_status, is_active, inventory_item_id
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

                if existing_doc.inventory_item_id is None or existing_doc.inventory_item_id == "":
                    variant_url = f"{shop}/admin/api/2023-01/variants/{row.shopify_variant_id}.json"
                    variant_resp = requests.get(variant_url, headers=headers)
                    variant_data = variant_resp.json()

                    if variant_resp.status_code == 200:
                        inventory_item_id = variant_data["variant"]["inventory_item_id"]
                        frappe.db.set_value("NJ Inventory Sync Main", existing_doc.name, "inventory_item_id", inventory_item_id)
                    else:
                        error_msg = variant_data.get("error") or variant_data.get("errors") or "Unknown error"
                        frappe.db.set_value("NJ Inventory Sync Main", existing_doc.name, "sync_error", f"API response: {error_msg}")
                    
            else:
                doc = frappe.new_doc("NJ Inventory Sync Main")

                qty = safe_float(row.total_actual_qty) or 0
                doc.is_active = 1
                doc.item_code = row.item_codes
                doc.sync_status = "Queued"
                doc.item_group = row.item_groups
                doc.actual_qty = qty
                doc.updated_qty = qty

                variant_url = f"{shop}/admin/api/2023-01/variants/{row.shopify_variant_id}.json"
                variant_resp = requests.get(variant_url, headers=headers)
                variant_data = variant_resp.json()

                if variant_resp.status_code == 200:
                    doc.inventory_item_id = variant_data["variant"]["inventory_item_id"]
                else:
                    error_msg = variant_data.get("error") or variant_data.get("errors") or "Unknown error"
                    doc.sync_error = f"API response: {error_msg}"
                
                doc.shopify_variant_id = row.shopify_variant_id

                try:
                    doc.insert()
                    updated_doc_names.add(doc.name)

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
@nj_temp_shopify_session
def start_shopify_inventory_sync():
    try:
        batch_size = 50
        start = 0
        total_records_query = """SELECT COUNT(*) AS count FROM `tabNJ Inventory Sync Main` 
                WHERE sync_status = 'Queued' AND is_active = 1 
                AND (inventory_item_id IS NOT NULL OR inventory_item_id != '')"""
        total_records = frappe.db.sql(total_records_query, as_dict=True)[0].count

        nj_inventory_log = frappe.new_doc("NJ Inventory Sync Log")
        nj_inventory_log.error = f"Total Records: {total_records}\n"

        while start < total_records:
            nj_inventory_log.error += f"\nProcessing batch from {start} to {start + batch_size}"

            queued = frappe.db.sql("""
                SELECT name, item_code, actual_qty, shopify_variant_id, updated_qty, inventory_item_id
                FROM `tabNJ Inventory Sync Main`
                WHERE sync_status = 'Queued' AND is_active = 1 AND 
                (inventory_item_id IS NOT NULL OR inventory_item_id != '') LIMIT %s OFFSET %s
            """, (batch_size, start), as_dict=True)


            for row in queued:
                try:
                    updated_qty = safe_float(row.updated_qty)
                    if updated_qty is None or updated_qty < 0:
                        nj_inventory_log.error += f"\nSkipping {row.name} — invalid data"
                        continue

                    available = int(updated_qty)
                    update_url = f"{shop}/admin/api/2023-01/inventory_levels/set.json"
                    payload = {
                        "location_id": location_id,
                        "inventory_item_id": row.inventory_item_id,
                        "available": available
                    }
                    update_resp = requests.post(update_url, headers=headers, data=json.dumps(payload))
                    variant_data = update_resp.json()
                    error_msg = variant_data.get("error") or variant_data.get("errors") or "Unknown error"
                    
                    if update_resp.status_code == 200:
                        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                            "sync_status": "Completed",
                            "is_active": 1
                        })
                    else:
                        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                            "sync_status": "Error",
                            "sync_error" : f"API response: {error_msg}"
                        })

                except Exception as e:
                    nj_inventory_log.error += f"\nException in {row.name}: {str(e)}\n{frappe.get_traceback()}"
                    continue
                
            frappe.db.commit()
            start += batch_size
            time.sleep(0.5)

        nj_inventory_log.error += "\nSync complete for all records."
        nj_inventory_log.save(ignore_permissions=True)
        return "All inventory sync batches processed."

    except Exception as e:
        return str(traceback.format_exc())

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