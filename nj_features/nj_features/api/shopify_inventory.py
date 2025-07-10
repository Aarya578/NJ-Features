import json
import time
import frappe
import pymysql
import requests
import traceback
from nj_features import verify_domain_matches_server_ip
from frappe.utils.background_jobs import enqueue
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error
from nj_features.nj_features.doctype.so_quantity_check.so_quantity_check import *

def get_shopify_settings():
    settings = frappe.get_single("NJ Inventory Settings")
    if settings.enable == 1 and verify_domain_matches_server_ip("erp.newjaisa.com"):
        return {
            "shop": settings.shop,
            "token": settings.token,
            "headers": {
                "X-Shopify-Access-Token": settings.token,
                "Content-Type": "application/json"
            },
            "warehouses": settings.warehouses,
            "location_id": settings.location_id,
            "item_groups": settings.item_groups,
            "departments": settings.departments,
        }
    return None

def safe_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def nj_temp_shopify_session(func):
    def wrapper(*args, **kwargs):
        if frappe.flags.in_test:
            return func(*args, **kwargs)
        from shopify import Session
        settings = get_shopify_settings()
        if not settings:
            log_error("Shopify settings not found", "nj_temp_shopify_session")
            return
        with Session.temp(settings["shop"], "2025-04", settings["token"]):
            return func(*args, **kwargs)
    return wrapper

@frappe.whitelist()
@nj_temp_shopify_session
def fetch_and_stage_inventory_sync():
    enqueue(
        method=create_rq_doc,
        queue="long",
        timeout=1200,
        job_name=f"shopify_inventory_sync_batch_erp"
    )

def create_rq_doc():
    settings = get_shopify_settings()
    update_status = ''
    update_so_quantity_check_status = update_so_quantity_check(settings)
    if update_so_quantity_check_status:
        update_parent_quantity_status = update_parent_quantity()
        if update_parent_quantity_status:
            update_proportional_qty_and_updt_qty_status = update_proportional_qty_and_updt_qty()
            if update_proportional_qty_and_updt_qty_status:
                try:
                    query = """
                        SELECT 
                            pb.shopify_variant_id,
                            GROUP_CONCAT(DISTINCT i.item_code ORDER BY i.item_code SEPARATOR ', ') AS item_codes,
                            GROUP_CONCAT(DISTINCT i.item_group ORDER BY i.item_group SEPARATOR ', ') AS item_groups,
                            CAST(SUM(soqc.update_qty2) AS DECIMAL(10, 2)) AS total_actual_qty
                        FROM 
                            `tabProduct Bundle` pb
                        JOIN 
                            `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
                        JOIN 
                            `tabItem` i ON pbi.item_code = i.item_code
                        JOIN 
                            `tabSO Quantity Check` soqc ON i.item_code = soqc.item_code
                        GROUP BY 
                            pb.shopify_variant_id
                        ORDER BY 
                            total_actual_qty DESC
                    """
                    results = frappe.db.sql(query, as_dict=True)

                    updated_doc_names = set()
                    
                    product_ids = [row.shopify_variant_id for row in results]

                    for row in results:
                        row.total_actual_qty = safe_float(row.total_actual_qty)

                        if row.total_actual_qty is None:
                            continue

                        if 0 <= row.total_actual_qty <= 3:
                            add_item_code_available_query = """
                                SELECT item_code
                                FROM `tabProduct Bundle Item` 
                                WHERE parent in (SELECT pdi.parent
                                FROM `tabProduct Bundle` pd
                                LEFT JOIN `tabProduct Bundle Item` pdi on pdi.parent = pd.name
                                WHERE pd.shopify_variant_id = %s
                                group by pdi.parent having count(pdi.parent) > 0) and item_code like '%%additional%%';
                            """
                            add_item_code_available = frappe.db.sql(add_item_code_available_query, (row.shopify_variant_id), as_dict=True)
                            
                            if add_item_code_available:
                                row.total_actual_qty = 0
                                update_status = "0 <= row.total_actual_qty <= 3 & additional warranty available"
                        
                        item_code_like_clauses = []
                        params = [row.shopify_variant_id]
                        for code in row.item_codes.split(', '):
                            item_code_like_clauses.append("item_code LIKE %s")
                            params.append(f"%{code.strip()}%")

                        query = f"""
                            SELECT name, actual_qty, status, is_active, inventory_item_id
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
                                    "is_active": 1,
                                    "sync_error": update_status,
                                    "status": "Queued",
                                    "actual_qty": row.total_actual_qty,
                                    "updated_qty": row.total_actual_qty,
                                    "modified": frappe.utils.now(),
                                })

                        else:
                            doc = frappe.new_doc("NJ Inventory Sync Main")
                            qty = safe_float(row.total_actual_qty)

                            doc.is_active = 1
                            doc.actual_qty = qty
                            doc.status = "Queued"
                            doc.updated_qty = qty
                            doc.item_code = row.item_codes
                            doc.item_group = row.item_groups
                            doc.shopify_variant_id = row.shopify_variant_id
                            doc.sync_error = update_status

                            try:
                                doc.insert()
                                updated_doc_names.add(doc.name)
                            except Exception:
                                log_error(f"Error inserting document: {row.item_codes}, shopify_variant_id: {row.shopify_variant_id} - Error: {frappe.get_traceback()}", "fetch_and_stage_inventory_sync")

                    get_shopify_variant_data = get_shopify_variants(product_ids, settings["shop"], settings["token"])
                    for data in get_shopify_variant_data:
                        frappe.db.sql("""UPDATE `tabNJ Inventory Sync Main` SET inventory_item_id = %s, shopify_quantity = %s, modified = NOW() WHERE shopify_variant_id = %s""", (data["inventory_item_id"], data["inventory_quantity"], data["variant_id"]))

                    frappe.db.commit()

                    all_docs = frappe.get_all("NJ Inventory Sync Main", fields=["name"])
                    all_doc_names = set(doc["name"] for doc in all_docs)

                    not_updated_doc_names = all_doc_names - updated_doc_names

                    log_error(f"Total Docs: {len(all_doc_names)}, Updated Docs: {len(updated_doc_names)}, Not Updated Docs: {len(not_updated_doc_names)}", "Total Updates", "Info")

                    for name in not_updated_doc_names:
                        frappe.db.set_value("NJ Inventory Sync Main", name, {
                            "actual_qty": "0",
                            "updated_qty": "0",
                            "modified": frappe.utils.now()
                        })

                    all_active_docs = frappe.get_all("NJ Inventory Sync Main", 
                                        fields=["name", "actual_qty", "shopify_quantity", "status", "item_group", "is_active"],
                                        filters={"inventory_item_id": ["!=", None]})
                    
                    for doc in all_active_docs:
                        actual_qty = safe_float(doc.actual_qty) or 0
                        shopify_quantity = safe_float(doc.shopify_quantity) or 0
                        
                        if actual_qty == shopify_quantity or doc.item_group not in settings["item_groups"]:
                            frappe.db.set_value("NJ Inventory Sync Main", doc.name, "is_active", 0)
                        else:
                            frappe.db.set_value("NJ Inventory Sync Main", doc.name, {
                                "is_active": 1,
                                "status": "Queued"
                            })

                except pymysql.err.OperationalError as e:
                    if e.args[0] == 2013:
                        return False
                    else:
                        return False

                except Exception:
                    log_error(f"Error in fetching & staging inventory sync: {frappe.get_traceback()}", "fetch_and_stage_inventory_sync")
                    return str(traceback.format_exc())

@frappe.whitelist()
@nj_temp_shopify_session
def start_shopify_inventory_sync():

    enqueue(
        method=create_shopify_inventory_sync,
        queue="long",
        timeout=1200,
        job_name=f"sync_to_shopify_inventory"
    )

@frappe.whitelist()
def create_shopify_inventory_sync():
    try:
        start = 0
        batch_size = 50
        settings = get_shopify_settings()
        
        if not settings:
            log_error("Shopify settings not found", "create_shopify_inventory_sync")
            return
        
        headers = {
            "X-Shopify-Access-Token": settings["token"],
            "Content-Type": "application/json"
        }

        total_records_query = """
            SELECT COUNT(*) AS count FROM `tabNJ Inventory Sync Main` 
            WHERE status = 'Queued' AND is_active = 1 
            AND (inventory_item_id IS NOT NULL OR inventory_item_id != '')
        """
        total_records = frappe.db.sql(total_records_query, as_dict=True)[0].count

        while start < total_records:
            completed_docs = []
            errored_docs = []
            skipped_docs = []

            queued = frappe.db.sql("""
                SELECT name, item_code, actual_qty, shopify_variant_id, updated_qty, inventory_item_id
                FROM `tabNJ Inventory Sync Main`
                WHERE status = 'Queued' AND is_active = 1 AND 
                (inventory_item_id IS NOT NULL OR inventory_item_id != '') 
                LIMIT %s OFFSET %s
            """, (batch_size, start), as_dict=True)

            for row in queued:
                try:
                    updated_qty = safe_float(row.updated_qty)
                    if updated_qty is None or updated_qty < 0:
                        skipped_docs.append(row.name)
                        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                            "status": "Error",
                            "sync_error": "Skipped: Invalid or negative updated_qty",
                            "modified": frappe.utils.now()
                        })
                        continue

                    available = int(updated_qty)
                    update_url = f"{settings['shop']}/admin/api/2023-01/inventory_levels/set.json"
                    payload = {
                        "location_id": settings["location_id"],
                        "inventory_item_id": row.inventory_item_id,
                        "available": available,
                    }

                    try:
                        update_resp = requests.post(update_url, headers=headers, data=json.dumps(payload), timeout=200)
                        variant_data = update_resp.json()
                        error_msg = variant_data.get("error") or variant_data.get("errors") or "Unknown error"
                    except requests.exceptions.Timeout:
                        log_error(f"Timeout (>200s) while syncing {row.name} - Skipping record.", "Shopify Inventory Sync Timeout")
                        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                            "status": "Error",
                            "sync_error": "Timeout while updating inventory to Shopify (200+ sec)",
                            "modified": frappe.utils.now()
                        })
                        errored_docs.append(row.name)
                        continue
                    except Exception as e:
                        log_error(f"Error while syncing {row.name} - Skipping record.", "Shopify Inventory Sync Error")
                        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                            "status": "Error",
                            "sync_error": f"Unknown error while updating inventory to Shopify + {e}",
                            "modified": frappe.utils.now()
                        })
                        errored_docs.append(row.name)
                        continue

                    if update_resp.status_code == 200:
                        updated_available = None
                        if "inventory_level" in variant_data and "available" in variant_data["inventory_level"]:
                            updated_available = variant_data["inventory_level"]["available"]

                        if updated_available == available:
                            frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                                "status": "Completed",
                                "is_active": 1,
                                "sync_error": str(variant_data["inventory_level"]),
                                "modified": frappe.utils.now()
                            })
                            completed_docs.append(row.name)
                        else:
                            frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                                "status": "Error",
                                "sync_error": f"Available qty mismatch. Expected {available}, got {updated_available}",
                                "modified": frappe.utils.now()
                            })
                            errored_docs.append(row.name)
                    else:
                        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                            "status": "Error",
                            "sync_error": f"API response: {error_msg}",
                            "modified": frappe.utils.now()
                        })
                        errored_docs.append(row.name)

                    time.sleep(0.5)

                except Exception as e:
                    log_error(f"Exception in {row.name}: {str(e)}\n{frappe.get_traceback()}", "Shopify Inventory Sync")
                    errored_docs.append(row.name)
                    continue

            frappe.db.commit()

            if completed_docs:
                log_error(
                    f"[{len(completed_docs)}] Completed sync for: {', '.join(completed_docs)}",
                    "Shopify Inventory Sync",
                    "Info"
                )
            if errored_docs:
                log_error(
                    f"[{len(errored_docs)}] Errored sync for: {', '.join(errored_docs)}",
                    "Shopify Inventory Sync",
                    "Error"
                )
            if skipped_docs:
                log_error(
                    f"[{len(skipped_docs)}] Skipped due to invalid qty: {', '.join(skipped_docs)}",
                    "Shopify Inventory Sync",
                    "Info"
                )

            start += batch_size

        return "Inventory sync batches processed1"

    except Exception as e:
        log_error(f"Error in start_shopify_inventory_sync: {str(e)}\n{frappe.get_traceback()}", "Shopify Inventory Sync", "Error")
        return str(traceback.format_exc())

@frappe.whitelist()
def get_shopify_variants(product_ids, shop, token):
    try:
        url = f"{shop}/admin/api/2025-04/graphql.json"
        headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json"
        }

        gids = [f"gid://shopify/ProductVariant/{pid}" for pid in product_ids]
        batch_size = 50
        result = []

        for i in range(0, len(gids), batch_size):
            batch = gids[i:i + batch_size]
            batch_ids = ',\n'.join([f'"{gid}"' for gid in batch])

            graphql_query = f"""
            {{
            nodes(ids: [
                {batch_ids}
            ]) {{
                ... on ProductVariant {{
                id
                inventoryQuantity
                inventoryItem {{
                    id
                }}
                product {{
                    id
                }}
                }}
            }}
            }}
            """

            response = requests.post(url, json={"query": graphql_query}, headers=headers)

            if response.status_code == 200:
                data = response.json()
                for node in data.get("data", {}).get("nodes", []):
                    if node:
                        inventory_quantity = node.get("inventoryQuantity", 0)
                        variant_gid = node.get("id", "")
                        variant_id = variant_gid.split("/")[-1]

                        inventory_item_gid = node.get("inventoryItem", {}).get("id", "")
                        inventory_item_id = inventory_item_gid.split("/")[-1] if inventory_item_gid else None

                        result.append({
                            "variant_id": variant_id,
                            "inventory_item_id": inventory_item_id,
                            "inventory_quantity": inventory_quantity
                        })
            else:
                log_error(f"Shopify API error: {response.text}", "Error in get_shopify_variants_method")
                return None

        return result

    except Exception as e:
        log_error(f"Error in get_shopify_variants_method: {str(e)}\n{frappe.get_traceback()}", "Error in get_shopify_variants_method")
        return None