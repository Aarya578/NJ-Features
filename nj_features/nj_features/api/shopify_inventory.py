import traceback
import json, time
import frappe, requests
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error

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
        
        for row in results:
            row.total_actual_qty = safe_float(row.total_actual_qty)
            if row.total_actual_qty is None or row.total_actual_qty < 0:    
                continue
            
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
                        "sync_error": "",
                        "status": "Queued",
                        "actual_qty": row.total_actual_qty,
                        "updated_qty": row.total_actual_qty,
                        "modified": frappe.utils.now()
                    })
                
                if existing_doc.inventory_item_id is None or existing_doc.inventory_item_id == "":
                    variant_url = f"{shop}/admin/api/2023-01/variants/{row.shopify_variant_id}.json"
                    variant_resp = requests.get(variant_url, headers=headers)
                    variant_data = variant_resp.json()
                    
                    if variant_resp.status_code == 200 and "variant" in variant_data and "inventory_item_id" in variant_data["variant"]:
                        frappe.db.set_value("NJ Inventory Sync Main", existing_doc.name, {
                            "inventory_item_id": variant_data["variant"]["inventory_item_id"],
                            "shopify_quantity": variant_data["variant"]["inventory_quantity"],
                            "modified": frappe.utils.now()
                        })
                    else:
                        error_msg = variant_data.get("error") or variant_data.get("errors") or "Unknown error"
                        log_error(f"API response: {error_msg} - variant_url: {variant_url}, name: {existing_doc.name}", "fetch_and_stage_inventory_sync")
            else:
                doc = frappe.new_doc("NJ Inventory Sync Main")
                qty = safe_float(row.total_actual_qty) or 0

                doc.is_active = 1
                doc.actual_qty = qty
                doc.status = "Queued"
                doc.updated_qty = qty
                doc.item_code = row.item_codes
                doc.item_group = row.item_groups
                
                # variant_url = f"{shop}/admin/api/2023-01/variants/{row.shopify_variant_id}.json"
                # variant_resp = requests.get(variant_url, headers=headers)
                # variant_data = variant_resp.json()
                
                # if variant_resp.status_code == 200:
                #     doc.inventory_item_id = variant_data["variant"]["inventory_item_id"]
                # else:
                #     error_msg = variant_data.get("error") or variant_data.get("errors") or "Unknown error"
                #     doc.sync_error = f"API response: {error_msg}"
                
                # doc.shopify_variant_id = row.shopify_variant_id
                
                # try:
                #     doc.insert()
                #     updated_doc_names.add(doc.name)
                
                # except Exception as e:
                #     error_msg = f"Error inserting document: {row.item_codes}, shopify_variant_id: {row.shopify_variant_id}"
                #     continue

                variant_url = f"{shop}/admin/api/2023-01/variants/{row.shopify_variant_id}.json"
                variant_resp = requests.get(variant_url, headers=headers)
                variant_data = variant_resp.json()
                if variant_resp.status_code == 200 and "variant" in variant_data and "inventory_item_id" in variant_data["variant"] and "inventory_quantity" in variant_data["variant"]:
                    doc.inventory_item_id = variant_data["variant"]["inventory_item_id"]
                    doc.shopify_quantity = variant_data["variant"]["inventory_quantity"]
                else:
                    error_msg = variant_data.get("error") or variant_data.get("errors") or "Unknown error"
                    doc.sync_error = f"API response: {error_msg}"
                
                doc.shopify_variant_id = row.shopify_variant_id

                try:
                    doc.insert()
                    updated_doc_names.add(doc.name)

                except Exception:
                    log_error(f"Error inserting document: {row.item_codes}, shopify_variant_id: {row.shopify_variant_id} - Error: {frappe.get_traceback()}", "fetch_and_stage_inventory_sync")
                    continue

        all_docs = frappe.get_all("NJ Inventory Sync Main", fields=["name"])
        all_doc_names = set(doc["name"] for doc in all_docs)

        not_updated_doc_names = all_doc_names - updated_doc_names

        log_error(
            f"Total Docs: {len(all_doc_names)}, Updated Docs: {len(updated_doc_names)}, Not Updated Docs: {len(not_updated_doc_names)}", "Total Updates", "Info"
        )

        for name in not_updated_doc_names:
            frappe.db.set_value("NJ Inventory Sync Main", name, {
                "actual_qty": "0",
                "updated_qty": "0"
            })

        all_active_docs = frappe.get_all("NJ Inventory Sync Main", 
                            fields=["name", "actual_qty", "shopify_quantity", "status"],
                            filters={"is_active": 1})
        
        for doc in all_active_docs:
            actual_qty = safe_float(doc.actual_qty) or 0
            shopify_quantity = safe_float(doc.shopify_quantity) or 0
            
            if actual_qty == shopify_quantity and doc.status != "Queued":
                frappe.db.set_value("NJ Inventory Sync Main", doc.name, "is_active", 0)
            else:
                frappe.db.set_value("NJ Inventory Sync Main", doc.name, "is_active", 1)

    except Exception:
        log_error(f"Error in fetching & staging inventory sync: {frappe.get_traceback()}", "fetch_and_stage_inventory_sync")
        return str(traceback.format_exc())
    
@frappe.whitelist()
@nj_temp_shopify_session
def start_shopify_inventory_sync():
    try:
        batch_size = 50
        start = 0

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
                            "sync_error": "Skipped: Invalid or negative updated_qty"
                        })
                        continue

                    available = int(updated_qty)
                    update_url = f"{shop}/admin/api/2023-01/inventory_levels/set.json"
                    payload = {
                        "location_id": location_id,
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
                            "sync_error": "Timeout while updating inventory to Shopify (200+ sec)"
                        })
                        errored_docs.append(row.name)
                        continue
                    except Exception as e:
                        log_error(f"Error while syncing {row.name} - Skipping record.", "Shopify Inventory Sync Error")
                        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                            "status": "Error",
                            "sync_error": f"Unknown error while updating inventory to Shopify + {e}"
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
                                "is_active": 1
                            })
                            completed_docs.append(row.name)
                        else:
                            frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                                "status": "Error",
                                "sync_error": f"Available qty mismatch. Expected {available}, got {updated_available}"
                            })
                            errored_docs.append(row.name)
                    else:
                        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                            "status": "Error",
                            "sync_error": f"API response: {error_msg}"
                        })
                        errored_docs.append(row.name)

                    time.sleep(0.6)

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