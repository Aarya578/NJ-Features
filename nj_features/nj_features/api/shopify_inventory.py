import math
import traceback
import json
import time
import frappe
import requests
from frappe.utils.background_jobs import enqueue
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error

# -------------------------------
# Utility Functions
# -------------------------------

def get_shopify_settings():
    settings = frappe.get_single("NJ Inventory Settings")
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
        with Session.temp(settings["shop"], "2025-04", settings["token"]):
            return func(*args, **kwargs)
    return wrapper

# -------------------------------
# Step 1: Fetch and Stage Inventory
# -------------------------------

@frappe.whitelist()
@nj_temp_shopify_session
def fetch_and_stage_inventory_sync():
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
        # batch_size = 1000
        # num_batches = math.ceil(len(results) / batch_size)

        # for i in range(num_batches):
        #     batch = results[i * batch_size:(i + 1) * batch_size]
        #     log_error(f"Processing batch {i + 1} of {num_batches} for inventory sync.", "fetch_and_stage_inventory_sync", "Info")
        enqueue(
            method=create_rq_doc,
            queue="long",
            timeout=3600,
            job_name=f"inventory_sync_batch",
            results=results
        )

    except Exception:
        log_error(f"Error in fetching & staging inventory sync: {frappe.get_traceback()}", "fetch_and_stage_inventory_sync")
        return str(traceback.format_exc())

# -------------------------------
# Step 2: Create Documents Per Batch
# -------------------------------

def create_rq_doc(results):
    updated_doc_names = set()
    log_error("Processing batch for inventory sync.", "fetch_and_stage_inventory_sync - RQ Doc", "Info")

    settings = get_shopify_settings()
    shop = settings["shop"]
    headers = settings["headers"]

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

        variant_url = f"{shop}/admin/api/2023-01/variants/{row.shopify_variant_id}.json"
        variant_resp = requests.get(variant_url, headers=headers)
        variant_data = variant_resp.json()

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

            if variant_resp.status_code == 200 and "variant" in variant_data and "inventory_item_id" in variant_data["variant"]:
                update_obj = {
                    "shopify_quantity": variant_data["variant"]["inventory_quantity"],
                    "modified": frappe.utils.now()
                }
                if existing_doc.inventory_item_id != variant_data["variant"]["inventory_item_id"]:
                    update_obj["inventory_item_id"] = variant_data["variant"]["inventory_item_id"]
                frappe.db.set_value("NJ Inventory Sync Main", existing_doc.name, update_obj)
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
            doc.shopify_variant_id = row.shopify_variant_id

            if variant_resp.status_code == 200 and "variant" in variant_data and "inventory_item_id" in variant_data["variant"]:
                doc.inventory_item_id = variant_data["variant"]["inventory_item_id"]
                doc.shopify_quantity = variant_data["variant"]["inventory_quantity"]
            else:
                error_msg = variant_data.get("error") or variant_data.get("errors") or "Unknown error"
                doc.sync_error = f"API response: {error_msg}"

            try:
                doc.insert()
                updated_doc_names.add(doc.name)
            except Exception:
                log_error(f"Error inserting document: {row.item_codes}, shopify_variant_id: {row.shopify_variant_id} - Error: {frappe.get_traceback()}", "fetch_and_stage_inventory_sync")

        time.sleep(0.5)
    frappe.db.commit()

# -------------------------------
# Step 3: Push to Shopify
# -------------------------------

@frappe.whitelist()
@nj_temp_shopify_session
def start_shopify_inventory_sync():
    try:
        settings = get_shopify_settings()
        shop = settings["shop"]
        headers = settings["headers"]
        location_id = settings["location_id"]

        batch_size = 50
        start = 0

        total_records_query = """
            SELECT COUNT(*) AS count FROM `tabNJ Inventory Sync Main` 
            WHERE status = 'Queued' AND is_active = 1 
            AND inventory_item_id IS NOT NULL AND inventory_item_id != ''
        """
        total_records = frappe.db.sql(total_records_query, as_dict=True)[0].count

        while start < total_records:
            completed_docs = []
            errored_docs = []
            skipped_docs = []

            queued = frappe.db.sql("""
                SELECT name, item_code, actual_qty, shopify_variant_id, updated_qty, inventory_item_id
                FROM `tabNJ Inventory Sync Main`
                WHERE status = 'Queued' AND is_active = 1 
                AND inventory_item_id IS NOT NULL AND inventory_item_id != '' 
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
                        log_error(f"Timeout (>200s) while syncing {row.name}", "Shopify Inventory Sync Timeout")
                        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                            "status": "Error",
                            "sync_error": "Timeout while updating inventory"
                        })
                        errored_docs.append(row.name)
                        continue

                    if update_resp.status_code == 200 and "inventory_level" in variant_data:
                        updated_available = variant_data["inventory_level"].get("available", None)
                        if updated_available == available:
                            frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                                "status": "Completed",
                                "is_active": 1,
                                "sync_error": json.dumps(variant_data["inventory_level"])
                            })
                            completed_docs.append(row.name)
                        else:
                            frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                                "status": "Error",
                                "sync_error": f"Mismatch: Expected {available}, got {updated_available}"
                            })
                            errored_docs.append(row.name)
                    else:
                        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                            "status": "Error",
                            "sync_error": f"API Error: {error_msg}"
                        })
                        errored_docs.append(row.name)

                    time.sleep(0.5)

                except Exception as e:
                    log_error(f"Exception in {row.name}: {str(e)}\n{frappe.get_traceback()}", "Shopify Inventory Sync")
                    errored_docs.append(row.name)

            frappe.db.commit()

            if completed_docs:
                log_error(f"✅ Synced: {len(completed_docs)} records", "Shopify Inventory Sync", "Info")
            if errored_docs:
                log_error(f"❌ Errors in: {len(errored_docs)} records", "Shopify Inventory Sync", "Error")
            if skipped_docs:
                log_error(f"⚠️ Skipped: {len(skipped_docs)} invalid qty", "Shopify Inventory Sync", "Info")

            start += batch_size

        return "Inventory sync completed."

    except Exception as e:
        log_error(f"Error in start_shopify_inventory_sync: {str(e)}\n{frappe.get_traceback()}", "Shopify Inventory Sync", "Error")
        return str(traceback.format_exc())
