import json
import time
import frappe
import pymysql
import requests
import traceback
from functools import wraps
from urllib.parse import urlparse
from nj_features import verify_domain_matches_server_ip
from frappe.utils.background_jobs import enqueue
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error
from nj_features.nj_features.doctype.so_quantity_check.so_quantity_check import *
logger = frappe.logger("new_shopify_inv_sync", allow_site=True, file_count=10)

INVENTORY_SYNC_LOCK_KEY = "nj_shopify_inventory_sync_execution"
INVENTORY_SYNC_LOCK_TIMEOUT = 3600
INVENTORY_ORDER_SYNC_TIMEOUT = 3000
INVENTORY_SYNC_LOCK_WAIT = 1200


def inventory_sync_execution_lock(func=None, *, wait=False):
    """Prevent staging and Shopify inventory writes from overlapping."""
    if func is None:
        return lambda method: inventory_sync_execution_lock(method, wait=wait)

    @wraps(func)
    def wrapper(*args, **kwargs):
        cache = frappe.cache()
        lock = cache.lock(
            cache.make_key(INVENTORY_SYNC_LOCK_KEY),
            timeout=INVENTORY_SYNC_LOCK_TIMEOUT,
            blocking_timeout=INVENTORY_SYNC_LOCK_WAIT,
        )
        if not lock.acquire(blocking=wait):
            if wait:
                # A failed order job must be visible in the worker's failed queue.
                raise TimeoutError("Timed out waiting for the Shopify inventory sync lock")
            logger.warning(
                f"Skipped {func.__name__}: another inventory sync operation is running"
            )
            return {
                "status": "skipped",
                "reason": "inventory_sync_already_running",
                "method": func.__name__,
            }
        try:
            result = func(*args, **kwargs)
            if isinstance(result, dict) and result.get("status") == "failed":
                frappe.db.rollback()
            else:
                # Commit before unlocking: the next worker must see these writes.
                frappe.db.commit()
            return result
        except BaseException:
            frappe.db.rollback()
            raise
        finally:
            try:
                lock.release()
            except Exception:
                logger.exception(
                    f"Unable to release inventory sync lock for {func.__name__}"
                )

    return wrapper


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

def get_inventory_sync_flags():
    """
    Safely retrieves the inventory sync rule configuration flags from NJ Settings.
    Falls back to consistent default values.
    """
    def get_setting_int(parameter, default):
        try:
            val = frappe.db.get_value("NJ Settings", {"parameter": parameter}, "value")
            if val is not None and str(val).strip() != "":
                return int(float(str(val).strip()))
        except Exception:
            pass
        return default

    return {
        "enable_parent_override": get_setting_int("enable_parent_override", 1),
        "parent_threshold": get_setting_int("parent_override_threshold", 1),
        "enable_warranty": get_setting_int("enable_warranty_rule", 1),
        "warranty_threshold": get_setting_int("warranty_threshold", 2),
        "pre_order_threshold": get_setting_int("pre_order_threshold", 4),
    }


def _effective_live_qty(rows, flags, parent_qty_dict):
    """Live quantity each variant will actually end up with.

    Mirrors Rule 1 (Parent Override) from the staging loop, which can lift a
    variant's quantity above zero. The Warranty Rule is deliberately NOT
    mirrored: it drives a quantity down to zero to hide a variant, and a
    variant being hidden should not then be handed a pre-order pool.
    """
    effective = {}
    for row in rows:
        variant_id = str(row.shopify_variant_id or "").strip()
        live_qty = safe_float(row.total_actual_qty) or 0

        if flags["enable_parent_override"] and live_qty <= flags["parent_threshold"]:
            parent_keys = [
                key.strip().lower()
                for key in (getattr(row, "parent_keys", "") or "").split("||")
                if key.strip()
            ]
            if not parent_keys and row.parent1:
                parent_keys = [f"{row.parent1} {row.processor or ''}".strip().lower()]
            combined = sum(parent_qty_dict.get(k, 0.0) or 0.0 for k in set(parent_keys))
            if combined > flags["parent_threshold"]:
                live_qty = combined

        effective[variant_id] = live_qty
    return effective


def clear_orphaned_pre_order_flags():
    """Drop shopify_pre_order_enabled on rows that staging can no longer reach.

    A sync row is only rewritten while its Product Bundle still produces it. Once
    a listing is deactivated (is_active=0) the row is never visited again, so a
    flag left at 1 stays at 1 indefinitely - it keeps claiming pre-order in
    resolve_pre_order_claims and keeps reporting a pre-order listing that nobody
    can buy. Measured 2026-09-22: 3 rows frozen since 2026-09-17.

    Only touches deactivated rows. An active row with a real pre-order quantity
    whose push failed is a DIFFERENT problem (status='Error') and is left alone.
    """
    try:
        affected = frappe.db.sql("""
            UPDATE `tabNJ Inventory Sync Main`
            SET shopify_pre_order_enabled = 0,
                shopify_pre_order_qty = 0
            WHERE shopify_pre_order_enabled = 1
              AND COALESCE(is_active, 0) = 0
        """)
        frappe.db.commit()
        cleared = frappe.db._cursor.rowcount if hasattr(frappe.db, "_cursor") else 0
        if cleared:
            log_error(
                f"Cleared shopify_pre_order_enabled on {cleared} deactivated sync "
                f"row(s) that staging can no longer reach",
                "clear_orphaned_pre_order_flags",
                "Info",
            )
        return True
    except Exception:
        frappe.db.rollback()
        log_error(frappe.get_traceback(), "clear_orphaned_pre_order_flags", "Error")
        return False


def resolve_pre_order_claims(rows, allocations=None, effective_live=None):
    """Advertise each physical machine on exactly one Shopify variant.

    update_pre_order_qty() already guarantees that a configuration's pool is
    claimed by a single SO Quantity Check row, so the ERP side never counts a
    machine twice. That alone is not enough: one item code can sit in several
    Product Bundles, so several Shopify variants inherit the same allocation
    and the pool would be advertised once per variant.

    This pass gives each allocated item code to one variant and zeroes the
    rest. The variant already advertising it keeps it, so a claim does not hop
    between variants from run to run; otherwise the lowest variant id wins,
    which is arbitrary but stable.

    Mutates row.total_pre_order_qty in place.
    """
    stats = {
        "allocated_codes": 0, "contested_codes": 0,
        "variants_zeroed": 0, "unsellable_codes": 0,
    }

    if allocations is None:
        allocations = {
            r["item_code"]: safe_float(r["pre_order_qty"]) or 0
            for r in frappe.db.sql(
                "SELECT item_code, pre_order_qty FROM `tabSO Quantity Check` WHERE pre_order_qty > 0",
                as_dict=True,
            )
        }

    if not allocations:
        for row in rows:
            row.total_pre_order_qty = 0
        return stats

    stats["allocated_codes"] = len(allocations)
    codes = list(allocations)
    placeholders = ", ".join(["%s"] * len(codes))

    claimants = {}
    for r in frappe.db.sql(f"""
        SELECT DISTINCT pb.shopify_variant_id, pbi.item_code
        FROM `tabProduct Bundle` pb
        JOIN `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
        WHERE COALESCE(pb.disable, 0) = 0
          AND pbi.item_code IN ({placeholders})
    """, tuple(codes), as_dict=True):
        variant_id = str(r["shopify_variant_id"] or "").strip()
        if variant_id:
            claimants.setdefault(r["item_code"], set()).add(variant_id)

    # is_active=0 rows are deactivated listings. Staging never revisits them,
    # so a flag left at 1 there is frozen forever - and as an incumbent it would
    # keep winning the claim ahead of a variant that can actually be sold.
    incumbents = {
        str(r["shopify_variant_id"] or "").strip()
        for r in frappe.get_all(
            "NJ Inventory Sync Main",
            filters={"shopify_pre_order_enabled": 1, "is_active": 1},
            fields=["shopify_variant_id"],
        )
    }

    # A variant that already has stock on the shelf will never show the
    # pre-order figure, so giving it the claim throws the allocation away.
    #
    # A targeted run only holds the variants in its own batch, so stock for
    # everything else is read from the staged record. Without that, a narrow
    # sync would rank every variant outside its batch as unsellable and pull
    # claims towards itself, and the claim would hop on the next full run.
    live_by_variant = dict(effective_live) if effective_live else {
        str(row.shopify_variant_id or "").strip(): safe_float(row.total_actual_qty) or 0
        for row in rows
    }
    unknown = {
        variant_id
        for variant_ids in claimants.values()
        for variant_id in variant_ids
        if variant_id not in live_by_variant
    }
    if unknown:
        for staged in frappe.get_all(
            "NJ Inventory Sync Main",
            filters={"shopify_variant_id": ["in", sorted(unknown)]},
            fields=["shopify_variant_id", "actual_qty"],
        ):
            live_by_variant.setdefault(
                str(staged.shopify_variant_id or "").strip(),
                safe_float(staged.actual_qty) or 0,
            )

    sellable = {
        variant_id
        for variant_id, live_qty in live_by_variant.items()
        if live_qty <= 0
    }

    winner_by_code = {}
    for code, variant_ids in claimants.items():
        if len(variant_ids) > 1:
            stats["contested_codes"] += 1

        candidates = [v for v in variant_ids if v in sellable]
        if not candidates:
            # Every variant of this configuration has stock on the shelf, so
            # none of them would ever display the pre-order figure - the
            # staging loop takes the live_qty branch. Handing the pool to one
            # anyway strands it and, worse, zeroes whichever variant held it
            # last, which the customer sees as the listing flipping.
            stats["unsellable_codes"] += 1
            continue

        # An incumbent keeps its claim. Recomputing the winner from scratch
        # every run is what pushed one variant to 32 and then straight back to
        # 0: the claim hopped to a sibling, the old holder was zeroed, and the
        # new holder was in a batch that never got pushed.
        held = [v for v in candidates if v in incumbents]
        winner_by_code[code] = sorted(held or candidates, key=lambda v: (len(v), v))[0]

    for row in rows:
        variant_id = str(row.shopify_variant_id or "").strip()
        won = 0.0
        for code in (row.item_codes or "").split(", "):
            code = code.strip()
            if code in allocations and winner_by_code.get(code) == variant_id:
                won += allocations[code]
        if (safe_float(row.total_pre_order_qty) or 0) and not won:
            stats["variants_zeroed"] += 1
        row.total_pre_order_qty = won

    return stats


def post_shopify_api(url, headers, payload=None, json_payload=None, max_retries=5):
    """
    POST request helper for Shopify API that handles 429 Too Many Requests
    rate limits with retry and backoff.
    """
    retry_count = 0
    backoff_time = 1.0
    while retry_count < max_retries:
        try:
            if json_payload is not None:
                resp = requests.post(url, headers=headers, json=json_payload, timeout=200)
            else:
                resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=200)
                
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", backoff_time))
                wait_time = max(retry_after, backoff_time)
                time.sleep(wait_time)
                retry_count += 1
                backoff_time *= 2
                continue
            return resp
        except requests.exceptions.Timeout as e:
            if retry_count < max_retries - 1:
                time.sleep(backoff_time)
                retry_count += 1
                backoff_time *= 2
                continue
            raise e
        except Exception as e:
            if retry_count < max_retries - 1:
                time.sleep(backoff_time)
                retry_count += 1
                backoff_time *= 2
                continue
            raise e
    
    mock_resp = requests.Response()
    mock_resp.status_code = 429
    mock_resp._content = b'{"errors": "Exceeded 2 calls per second for api client. Max retries reached."}'
    return mock_resp

def nj_temp_shopify_session(func):
    def wrapper(*args, **kwargs):
        if frappe.flags.in_test:
            return func(*args, **kwargs)
        from shopify import Session
        settings = get_shopify_settings()
        if not settings:
            log_error("Shopify settings not found", "nj_temp_shopify_session")
            return
        with Session.temp(settings["shop"], "2026-10", settings["token"]):
            return func(*args, **kwargs)
    return wrapper

@frappe.whitelist()
@nj_temp_shopify_session
def fetch_and_stage_inventory_sync():
    job = enqueue(
        method=create_rq_doc,
        queue="long",
        timeout=1200,
        job_name=f"shopify_inventory_sync_batch_erp"
    )
    logger.info(
        f"create_rq_doc queued on long queue; rq_job_id={getattr(job, 'id', 'unknown')} timeout=1200s"
    )
    return {"queued": True, "job_id": getattr(job, "id", None)}

# def create_rq_doc():
#     settings = get_shopify_settings()
#     update_so_quantity_check_status = update_so_quantity_check(settings)
#     if update_so_quantity_check_status:
#         update_parent_quantity_status = update_parent_quantity()
#         if update_parent_quantity_status:
#             update_proportional_qty_and_updt_qty_status = update_proportional_qty_and_updt_qty()
#             if update_proportional_qty_and_updt_qty_status:
#                 try:
#                     query = """
#                         SELECT 
#                             pb.shopify_variant_id,
#                             GROUP_CONCAT(DISTINCT i.item_code ORDER BY i.item_code SEPARATOR ', ') AS item_codes,
#                             GROUP_CONCAT(DISTINCT i.item_group ORDER BY i.item_group SEPARATOR ', ') AS item_groups,
#                             CAST(SUM(soqc.update_qty2) AS DECIMAL(10, 2)) AS total_actual_qty
#                         FROM 
#                             `tabProduct Bundle` pb
#                         JOIN 
#                             `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
#                         JOIN 
#                             `tabItem` i ON pbi.item_code = i.item_code
#                         JOIN 
#                             `tabSO Quantity Check` soqc ON i.item_code = soqc.item_code
#                         GROUP BY 
#                             pb.shopify_variant_id
#                         ORDER BY 
#                             total_actual_qty DESC
#                     """
#                     results = frappe.db.sql(query, as_dict=True)

#                     updated_doc_names = set()
                    
#                     product_ids = [row.shopify_variant_id for row in results]

#                     for row in results:
#                         update_status = ''
#                         row.total_actual_qty = safe_float(row.total_actual_qty)

#                         if row.total_actual_qty is None:
#                             continue

#                         if 0 <= row.total_actual_qty <= 3:
#                             add_item_code_available_query = """
#                                 SELECT item_code
#                                 FROM `tabProduct Bundle Item` 
#                                 WHERE parent in (SELECT pdi.parent
#                                 FROM `tabProduct Bundle` pd
#                                 LEFT JOIN `tabProduct Bundle Item` pdi on pdi.parent = pd.name
#                                 WHERE pd.shopify_variant_id = %s
#                                 group by pdi.parent having count(pdi.parent) > 0) and item_code like '%%additional%%';
#                             """
#                             add_item_code_available = frappe.db.sql(add_item_code_available_query, (row.shopify_variant_id), as_dict=True)
                            
#                             if add_item_code_available:
#                                 row.total_actual_qty = 0
#                                 update_status = "0 <= row.total_actual_qty <= 3 & additional warranty available"
                        
#                         item_code_like_clauses = []
#                         params = [row.shopify_variant_id]
#                         for code in row.item_codes.split(', '):
#                             item_code_like_clauses.append("item_code LIKE %s")
#                             params.append(f"%{code.strip()}%")

#                         query = f"""
#                             SELECT name, actual_qty, status, is_active, inventory_item_id
#                             FROM `tabNJ Inventory Sync Main`
#                             WHERE shopify_variant_id = %s AND ({' OR '.join(item_code_like_clauses)})
#                             ORDER BY modified DESC
#                         """
#                         existing = frappe.db.sql(query, tuple(params), as_dict=True)

#                         if existing:
#                             existing_doc = existing[0]
#                             updated_doc_names.add(existing_doc.name)
#                             existing_doc_actual_qty = safe_float(existing_doc.actual_qty) or 0

#                             if float(row.total_actual_qty) != existing_doc_actual_qty:
#                                 frappe.db.set_value("NJ Inventory Sync Main", existing_doc.name, {
#                                     "is_active": 1,
#                                     "sync_error": update_status,
#                                     "status": "Queued",
#                                     "actual_qty": row.total_actual_qty,
#                                     "updated_qty": row.total_actual_qty,
#                                     "modified": frappe.utils.now(),
#                                 })

#                         else:
#                             doc = frappe.new_doc("NJ Inventory Sync Main")
#                             qty = safe_float(row.total_actual_qty)

#                             doc.is_active = 1
#                             doc.actual_qty = qty
#                             doc.status = "Queued"
#                             doc.updated_qty = qty
#                             doc.item_code = row.item_codes
#                             doc.item_group = row.item_groups
#                             doc.shopify_variant_id = row.shopify_variant_id
#                             doc.sync_error = update_status

#                             try:
#                                 doc.insert()
#                                 updated_doc_names.add(doc.name)
#                             except Exception:
#                                 log_error(f"Error inserting document: {row.item_codes}, shopify_variant_id: {row.shopify_variant_id} - Error: {frappe.get_traceback()}", "fetch_and_stage_inventory_sync")

#                     get_shopify_variant_data = get_shopify_variants(product_ids, settings["shop"], settings["token"])
#                     for data in get_shopify_variant_data:
#                         frappe.db.sql("""UPDATE `tabNJ Inventory Sync Main` SET inventory_item_id = %s, shopify_quantity = %s, modified = NOW() WHERE shopify_variant_id = %s""", (data["inventory_item_id"], data["inventory_quantity"], data["variant_id"]))

#                     all_docs = frappe.get_all("NJ Inventory Sync Main", fields=["name"])
#                     all_doc_names = set(doc["name"] for doc in all_docs)

#                     not_updated_doc_names = all_doc_names - updated_doc_names

#                     log_error(f"Total Docs: {len(all_doc_names)}, Updated Docs: {len(updated_doc_names)}, Not Updated Docs: {len(not_updated_doc_names)}", "Total Updates", "Info")

#                     for name in not_updated_doc_names:
#                         frappe.db.set_value("NJ Inventory Sync Main", name, {
#                             "sync_error": "",
#                             "actual_qty": "0",
#                             "updated_qty": "0",
#                             "status": "Queued",
#                             "modified": frappe.utils.now()
#                         })

#                     all_active_docs = frappe.get_all("NJ Inventory Sync Main", 
#                                         fields=["name", "actual_qty", "shopify_quantity", "status", "item_group", "is_active"],
#                                         filters={"inventory_item_id": ["!=", None]})
                    
#                     for doc in all_active_docs:
#                         actual_qty = safe_float(doc.actual_qty) or 0
#                         shopify_quantity = safe_float(doc.shopify_quantity) or 0
                        
#                         if actual_qty == shopify_quantity or doc.item_group not in settings["item_groups"]:
#                             frappe.db.set_value("NJ Inventory Sync Main", doc.name, "is_active", 0)
#                         else:
#                             frappe.db.set_value("NJ Inventory Sync Main", doc.name, {
#                                 "is_active": 1,
#                                 "status": "Queued"
#                             })

#                 except pymysql.err.OperationalError as e:
#                     if e.args[0] == 2013:
#                         return False
#                     else:
#                         return False

#                 except Exception:
#                     log_error(f"Error in fetching & staging inventory sync: {frappe.get_traceback()}", "fetch_and_stage_inventory_sync")
#                     return str(traceback.format_exc())
@inventory_sync_execution_lock
def create_rq_doc():
    return _create_rq_doc()


def _create_rq_doc(variant_ids=None):
    """Shared calculation/staging engine; caller must hold the execution lock.

    Refresh all quantity-check rows so parent availability uses fresh siblings.
    An optional variant scope limits Shopify reads, staging and policy writes.
    """
    if variant_ids is not None and not variant_ids:
        return {"status": "completed", "total": 0}

    run_id = frappe.generate_hash(length=8)
    started_at = time.monotonic()
    stats = {
        "total": 0,
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "failed": 0,
        "shopify_found": 0,
        "shopify_missing": 0,
    }
    logger.info(f"[{run_id}] create_rq_doc started")

    settings = get_shopify_settings()
    if not settings:
        logger.error(f"[{run_id}] stopped: Shopify settings are missing or disabled")
        return {"run_id": run_id, "status": "failed", "reason": "missing_settings"}
    logger.info(f"[{run_id}] Shopify settings loaded for shop={settings.get('shop')}")

    def run_stage(stage_number, stage_name, method):
        logger.info(f"[{run_id}] stage {stage_number}/4 started: {stage_name}")
        try:
            stage_result = method()
        except Exception:
            logger.exception(f"[{run_id}] stage {stage_number}/4 raised an exception: {stage_name}")
            return False
        if not stage_result:
            logger.error(f"[{run_id}] stage {stage_number}/4 returned false: {stage_name}")
            return False
        logger.info(f"[{run_id}] stage {stage_number}/4 completed: {stage_name}")
        return True

    # =========================================================
    # 🔹 Fetch Rule Config (Flags)
    # =========================================================
    try:
        rule_config = frappe.db.get_value("NJ Settings", {"parameter": "reconfigsync"}, "value")
    except Exception:
        logger.exception(f"[{run_id}] failed to read reconfigsync")
        rule_config = 0

    # Continue only when reconfigsync is enabled.
    if str(rule_config).strip() != "1":
        logger.warning(f"[{run_id}] skipped: reconfigsync is disabled or missing")
        log_error(
            "Skipped create_rq_doc because reconfigsync is 0 or missing",
            "Inventory Sync Config",
            "Info",
        )
        return {"run_id": run_id, "status": "skipped", "reason": "reconfigsync_disabled"}

    flags = get_inventory_sync_flags()
    logger.info(f"[{run_id}] inventory sync flags loaded: {flags}")

    # =========================================================
    # 🔹 Run Pre-Processing
    # =========================================================
    if not run_stage(1, "update_so_quantity_check", lambda: update_so_quantity_check(settings)):
        return {"run_id": run_id, "status": "failed", "stage": "update_so_quantity_check"}

    if not run_stage(2, "update_parent_quantity", update_parent_quantity):
        return {"run_id": run_id, "status": "failed", "stage": "update_parent_quantity"}

    if not run_stage(3, "update_proportional_qty_and_updt_qty", update_proportional_qty_and_updt_qty):
        return {"run_id": run_id, "status": "failed", "stage": "update_proportional_qty_and_updt_qty"}

    # A pre-order failure must NOT abort the stock sync, and must NOT be read
    # as "there are no pre-orders". It trips a breaker: pre-order figures are
    # left exactly as they are and Shopify is not touched on that axis.
    pre_order_data_ok = run_stage(4, "update_pre_order_qty", lambda: update_pre_order_qty(settings))
    if not pre_order_data_ok:
        log_error(
            "Pre-order staging failed - pre-order quantities held at their last "
            "known values and the Shopify pre-order push is skipped for this run",
            "Pre-Order Circuit Breaker",
            "Error",
        )

    # Frozen flags on deactivated listings are cleared every cycle, whether or
    # not the pre-order stage succeeded - a stale claim is wrong either way.
    clear_orphaned_pre_order_flags()

    if not run_stage(5, "updting_sla_department", updting_sla_department):
        return {"run_id": run_id, "status": "failed", "stage": "updting_sla_department"}

    try:
        # =========================================================
        # 🔹 Main Aggregation Query (Item-Level Qty)
        # =========================================================
        settings_item_groups = [ig.strip() for ig in settings.get('item_groups', '').split(',') if ig.strip()]
        if settings_item_groups:
            ig_placeholders = ', '.join(['%s'] * len(settings_item_groups))
            where_item_group = f"AND i.item_group IN ({ig_placeholders})"
            query_params = tuple(settings_item_groups)
        else:
            where_item_group = ""
            query_params = ()

        where_variant = ""
        if variant_ids is not None:
            placeholders = ', '.join(['%s'] * len(variant_ids))
            where_variant = f"AND pb.shopify_variant_id IN ({placeholders})"
            query_params += tuple(variant_ids)

        query = f"""
            SELECT 
                v.shopify_variant_id,
                MAX(v.parent1) AS parent1,
                MAX(v.processor) AS processor,
                GROUP_CONCAT(DISTINCT v.parent_key SEPARATOR '||') AS parent_keys,
                GROUP_CONCAT(DISTINCT v.item_code ORDER BY v.item_code SEPARATOR ', ') AS item_codes,
                GROUP_CONCAT(DISTINCT v.item_group ORDER BY v.item_group SEPARATOR ', ') AS item_groups,
                CAST(SUM(v.update_qty2) AS DECIMAL(10, 2)) AS total_actual_qty,
                CAST(SUM(COALESCE(v.pre_order_qty, 0)) AS DECIMAL(10, 2)) AS total_pre_order_qty,
                CASE 
                    WHEN MIN(NULLIF(v.sla, 0)) IS NULL THEN ''
                    WHEN MIN(NULLIF(v.sla, 0)) = 1 THEN '1 Day'
                    ELSE CONCAT(MIN(NULLIF(v.sla, 0)), ' Days')
                END AS estimated_time_of_dispatch
            FROM (
                SELECT DISTINCT
                    pb.shopify_variant_id,
                    i.item_code,
                    i.item_group,
                    i.variant_of AS parent1,
                    COALESCE(iva.attribute_value, '') AS processor,
                    TRIM(CONCAT(i.variant_of, ' ', COALESCE(iva.attribute_value, ''))) AS parent_key,
                    soqc.update_qty2,
                    soqc.pre_order_qty,
                    soqc.sla
                FROM 
                    `tabProduct Bundle` pb
                JOIN 
                    `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
                JOIN 
                    `tabItem` i ON pbi.item_code = i.item_code
                JOIN 
                    `tabSO Quantity Check` soqc ON i.item_code = soqc.item_code
                LEFT JOIN
                    `tabItem Variant Attribute` iva
                    ON iva.parent = i.item_code
                    AND iva.attribute = 'Processor Type1'
                WHERE
                    COALESCE(pb.disable, 0) = 0
                    {where_item_group}
                    {where_variant}
            ) v
            GROUP BY 
                v.shopify_variant_id
            ORDER BY 
                total_actual_qty DESC
        """
        logger.debug(f"query================== {query}")

        results = frappe.db.sql(query, query_params, as_dict=True) if query_params else frappe.db.sql(query, as_dict=True)
        stats["total"] = len(results)

        logger.info(f"[{run_id}] aggregation completed: {stats['total']} variants to process")

        # =========================================================
        # 🔹 Preload Parent Quantities (IMPORTANT)
        # =========================================================
        parent_qty_map = frappe.db.sql("""
            SELECT
                sqc.parent1,
                SUM(sqc.update_qty2) AS total_parent_qty
            FROM `tabSO Quantity Check` sqc
            GROUP BY sqc.parent1
        """, as_dict=True)
        logger.debug(f"parent_qty_map================== {parent_qty_map}")

        parent_qty_dict = {
            str(row["parent1"]).strip().lower(): safe_float(row["total_parent_qty"])
            for row in parent_qty_map
        }
        logger.debug(f"parent_qty_dict================== {parent_qty_dict}")

        # One machine, one variant. Without this the same allocation is
        # inherited by every bundle the item code appears in.
        #
        # Run AFTER parent quantities are loaded: Parent Override can raise a
        # variant's quantity above zero further down, and a variant with stock
        # never displays the pre-order figure. Claiming on the raw rollup would
        # hand the pool to a variant that is about to gain stock, stranding the
        # allocation and zeroing whoever held it before.
        if pre_order_data_ok:
            claim_stats = resolve_pre_order_claims(
                results, effective_live=_effective_live_qty(results, flags, parent_qty_dict)
            )
            logger.info(f"[{run_id}] pre-order claims resolved: {claim_stats}")

        updated_doc_names = set()
        all_product_ids = [
            str(row.shopify_variant_id or "").strip()
            for row in results
        ]
        product_ids = [variant_id for variant_id in all_product_ids if variant_id.isdigit()]
        invalid_product_ids = {
            variant_id for variant_id in all_product_ids if not variant_id.isdigit()
        }
        stats["shopify_invalid"] = len(invalid_product_ids)
        logger.debug(f"product_ids================== {product_ids}")
        if invalid_product_ids:
            logger.warning(
                f"[{run_id}] excluded invalid Shopify variant IDs from lookup: "
                f"count={len(invalid_product_ids)}, values={sorted(invalid_product_ids)}"
            )

        # Fetch fresh Shopify quantities before deciding which records need a
        # stock update. The comparison must use the configured location's
        # available quantity, not ProductVariant.inventoryQuantity (all sites).
        shopify_data = (
            get_shopify_variants(
                product_ids,
                settings["shop"],
                settings["token"],
                location_id=settings["location_id"],
            )
            if product_ids else []
        )
        if shopify_data is None:
            logger.error(f"[{run_id}] stopped: fresh Shopify inventory lookup failed")
            return {
                "run_id": run_id,
                "status": "failed",
                "stage": "fetch_fresh_shopify_inventory",
            }

        shopify_by_variant = {
            str(data["variant_id"]).strip(): data
            for data in shopify_data
            if data.get("variant_id")
        }
        found_variant_ids = set(shopify_by_variant)
        stats["shopify_found"] = len(found_variant_ids)
        stats["shopify_missing"] = len(set(product_ids) - found_variant_ids)
        logger.info(
            f"[{run_id}] fresh Shopify lookup completed: "
            f"found={stats['shopify_found']}, missing={stats['shopify_missing']}"
        )

        # =========================================================
        # 🔁 MAIN LOOP
        # =========================================================
        for row_number, row in enumerate(results, start=1):
            stats["processed"] = row_number
            update_status = ''
            row.total_actual_qty = safe_float(row.total_actual_qty)
            row.total_pre_order_qty = safe_float(row.total_pre_order_qty) or 0

            if row.total_actual_qty is None:
                stats["skipped"] += 1
                logger.warning(
                    f"[{run_id}] skipped variant={row.shopify_variant_id}: invalid total quantity"
                )
                continue

            # =====================================================
            # 🔹 RULE 1: Parent Override (FLAG-BASED)
            # =====================================================
            if (
                flags["enable_parent_override"]
                and row.total_actual_qty <= flags["parent_threshold"]
            ):
                parent_keys = [
                    k.strip().lower()
                    for k in (getattr(row, "parent_keys", "") or "").split("||")
                    if k.strip()
                ]
                if not parent_keys and row.parent1:
                    parent_keys = [f"{row.parent1} {row.processor or ''}".strip().lower()]
                combined_parent_qty = sum(parent_qty_dict.get(k, 0.0) or 0.0 for k in set(parent_keys))
                logger.debug(f"parent_keys================== {parent_keys}, combined_parent_qty================== {combined_parent_qty}")

                if combined_parent_qty > flags["parent_threshold"]:
                    row.total_actual_qty = combined_parent_qty
                    logger.debug(f"row.total_actual_qty================== {row.total_actual_qty}")
                    update_status += f"[ParentOverride<={flags['parent_threshold']}→{combined_parent_qty}] "
                    logger.debug(f"update_status================== {update_status}")

            # =====================================================
            # 🔹 RULE 2: Warranty Rule (FLAG-BASED)
            # =====================================================
            if (
                flags["enable_warranty"]
                and 0 <= row.total_actual_qty <= flags["warranty_threshold"]
            ):
                add_item_code_available_query = """
                    SELECT item_code
                    FROM `tabProduct Bundle Item` 
                    WHERE parent in (
                        SELECT pdi.parent
                        FROM `tabProduct Bundle` pd
                        LEFT JOIN `tabProduct Bundle Item` pdi on pdi.parent = pd.name
                        WHERE pd.shopify_variant_id = %s
                        GROUP BY pdi.parent HAVING COUNT(pdi.parent) > 0
                    )
                    AND item_code LIKE '%%additional%%'
                    AND item_code != 'Additional 6 Months warranty';
                """
                logger.debug(f"add_item_code_available_query================== {add_item_code_available_query}")

                add_item_code_available = frappe.db.sql(
                    add_item_code_available_query,
                    (row.shopify_variant_id,),
                    as_dict=True
                )
                logger.debug(f"add_item_code_available================== {add_item_code_available}")

                if add_item_code_available:
                    row.total_actual_qty = 0
                    update_status += "[WarrantyApplied] "
                    logger.debug(f"update_status================== {update_status}")

            variant_id = str(row.shopify_variant_id).strip()
            shopify_row = shopify_by_variant.get(variant_id)
            fresh_shopify_qty = (
                safe_float(shopify_row.get("location_quantity"))
                if shopify_row else None
            )
            live_qty = safe_float(row.total_actual_qty) or 0
            pre_order_qty = safe_float(row.total_pre_order_qty) or 0

            # hold_pre_order means "we do not know", which is a different thing
            # from "there are none" - resolved once the current record is read.
            hold_pre_order = False

            if live_qty > 0:
                desired_qty = float(live_qty)
                is_pre_order = 0
            elif pre_order_qty > 0:
                # The threshold was already applied upstream in update_pre_order_qty
                # (against company quantity); anything still > 0 has passed it.
                desired_qty = float(pre_order_qty)
                is_pre_order = 1
                update_status += f"[PreOrderSynced→{desired_qty:g}] "
            elif not pre_order_data_ok:
                hold_pre_order = True
                desired_qty = None
                is_pre_order = None
                update_status += "[PreOrderHeld] "
            else:
                desired_qty = 0.0
                is_pre_order = 0

            if not variant_id.isdigit():
                lookup_error = "Invalid or missing Shopify variant ID mapping"
            elif not shopify_row:
                lookup_error = "Variant ID not found in Shopify"
            elif fresh_shopify_qty is None:
                lookup_error = "Inventory level not found at configured Shopify location"
            else:
                lookup_error = ""

            # =====================================================
            # 🔹 UPSERT INTO NJ Inventory Sync Main
            # =====================================================
            item_code_like_clauses = []
            params = [row.shopify_variant_id]
            logger.debug(f"item_code_like_clauses================== {item_code_like_clauses}")
            logger.debug(f"params================== {params}")

            for code in row.item_codes.split(', '):
                item_code_like_clauses.append("item_code LIKE %s")
                params.append(f"%{code.strip()}%")

            existing = frappe.db.sql(f"""
                SELECT name, actual_qty, updated_qty, status, sync_error, shopify_quantity,
                       shopify_pre_order_qty, shopify_pre_order_enabled
                FROM `tabNJ Inventory Sync Main`
                WHERE shopify_variant_id = %s 
                AND ({' OR '.join(item_code_like_clauses)})
                ORDER BY modified DESC
            """, tuple(params), as_dict=True)
            logger.debug(f"existing================== {existing}")

            # Breaker tripped: keep whatever this variant already advertises.
            # With no prior record there is nothing live on Shopify to protect,
            # so zero is safe.
            if hold_pre_order:
                if existing:
                    desired_qty = safe_float(existing[0].get("updated_qty")) or 0.0
                    pre_order_qty = safe_float(existing[0].get("shopify_pre_order_qty")) or 0
                    is_pre_order = int(existing[0].get("shopify_pre_order_enabled") or 0)
                else:
                    desired_qty = 0.0
                    is_pre_order = 0

            quantity_matches = (
                fresh_shopify_qty is not None
                and desired_qty == fresh_shopify_qty
            )

            if existing:
                existing_doc = existing[0]
                logger.debug(f"existing_doc================== {existing_doc}")
                updated_doc_names.add(existing_doc.name)

                values = {
                    "is_active": 1,
                    "actual_qty": live_qty,
                    "updated_qty": desired_qty,
                    "shopify_pre_order_qty": pre_order_qty,
                    "shopify_pre_order_enabled": is_pre_order,
                    "estimated_time_of_dispatch": getattr(row, "estimated_time_of_dispatch", "") or "",
                    "modified": frappe.utils.now(),
                }

                if shopify_row:
                    values["inventory_item_id"] = shopify_row.get("inventory_item_id")
                if fresh_shopify_qty is not None:
                    values["shopify_quantity"] = fresh_shopify_qty

                if lookup_error:
                    values["status"] = "Error"
                    values["sync_error"] = lookup_error
                    stats["skipped"] += 1
                elif quantity_matches:
                    values["status"] = "Completed"
                    # Keep the last successful Shopify response/details when
                    # a later staging run confirms that quantity is unchanged.
                    # A non-completed record must not retain an old error.
                    values["sync_error"] = (
                        existing_doc.sync_error or update_status
                        if existing_doc.status == "Completed"
                        else update_status
                    )
                    stats["unchanged"] += 1
                else:
                    values["status"] = "Queued"
                    queue_reason = (
                        f"[QueuedForSync ERP={desired_qty:g} "
                        f"Shopify={fresh_shopify_qty:g}]"
                    )
                    values["sync_error"] = f"{update_status}{queue_reason}".strip()
                    stats["updated"] += 1

                frappe.db.set_value(
                    "NJ Inventory Sync Main",
                    existing_doc.name,
                    values,
                )
            else:
                doc = frappe.new_doc("NJ Inventory Sync Main")
                logger.debug(f"doc================== {doc}")

                logger.debug(f"live_qty================== {live_qty}")

                doc.is_active = 1
                logger.debug(f"doc.is_active================== {doc.is_active}")
                doc.actual_qty = live_qty
                logger.debug(f"doc.actual_qty================== {doc.actual_qty}")
                doc.status = (
                    "Error" if lookup_error
                    else "Completed" if quantity_matches
                    else "Queued"
                )
                logger.debug(f"doc.status================== {doc.status}")
                doc.updated_qty = desired_qty
                logger.debug(f"doc.updated_qty================== {doc.updated_qty}")
                doc.shopify_pre_order_qty = pre_order_qty
                logger.debug(f"doc.shopify_pre_order_qty================== {doc.shopify_pre_order_qty}")
                doc.shopify_pre_order_enabled = is_pre_order
                logger.debug(f"doc.shopify_pre_order_enabled================== {doc.shopify_pre_order_enabled}")
                doc.estimated_time_of_dispatch = getattr(row, "estimated_time_of_dispatch", "") or ""
                doc.item_code = row.item_codes
                logger.debug(f"doc.item_code================== {doc.item_code}")
                doc.item_group = row.item_groups
                logger.debug(f"doc.item_group================== {doc.item_group}")
                doc.shopify_variant_id = row.shopify_variant_id
                logger.debug(f"doc.shopify_variant_id================== {doc.shopify_variant_id}")
                doc.inventory_item_id = (
                    shopify_row.get("inventory_item_id") if shopify_row else None
                )
                doc.shopify_quantity = fresh_shopify_qty
                queue_reason = (
                    f"[QueuedForSync ERP={desired_qty:g} Shopify={fresh_shopify_qty:g}]"
                    if not lookup_error and not quantity_matches
                    else ""
                )
                doc.sync_error = (
                    lookup_error
                    or f"{update_status}{queue_reason}".strip()
                )
                logger.debug(f"doc.sync_error================== {doc.sync_error}")

                try:
                    doc.insert()
                    updated_doc_names.add(doc.name)
                    stats["inserted"] += 1
                    if lookup_error:
                        stats["skipped"] += 1
                    elif quantity_matches:
                        stats["unchanged"] += 1
                except Exception:
                    stats["failed"] += 1
                    logger.exception(
                        f"[{run_id}] failed to insert variant={row.shopify_variant_id}"
                    )
                    log_error(
                        f"Insertion error for {row.item_codes}, variant {row.shopify_variant_id}: {frappe.get_traceback()}",
                        "Inventory Sync Insert Error"
                    )

            if row_number % 100 == 0 or row_number == stats["total"]:
                elapsed = time.monotonic() - started_at
                logger.info(
                    f"[{run_id}] progress {row_number}/{stats['total']} variants; "
                    f"inserted={stats['inserted']}, updated={stats['updated']}, "
                    f"unchanged={stats['unchanged']}, skipped={stats['skipped']}, "
                    f"failed={stats['failed']}, elapsed={elapsed:.1f}s"
                )

        # =========================================================
        # 🔹 Deactivate / Zero-out Inactive or Disabled Bundle Records
        # =========================================================
        try:
            if updated_doc_names:
                stale_filters = {"name": ["not in", list(updated_doc_names)]}
                if variant_ids is not None:
                    stale_filters["shopify_variant_id"] = ["in", list(variant_ids)]
                stale_docs = frappe.get_all(
                    "NJ Inventory Sync Main",
                    filters=stale_filters,
                    fields=["name", "actual_qty", "updated_qty", "shopify_quantity", "shopify_pre_order_qty", "status", "is_active"]
                )
            else:
                stale_docs = []

            for stale in stale_docs:
                current_shop_qty = safe_float(stale.get("shopify_quantity")) or 0
                has_stock = (safe_float(stale.get("actual_qty")) or 0) > 0 or (safe_float(stale.get("updated_qty")) or 0) > 0
                has_preorder = (safe_float(stale.get("shopify_pre_order_qty")) or 0) > 0
                is_active = stale.get("is_active")

                if current_shop_qty > 0:
                    frappe.db.set_value("NJ Inventory Sync Main", stale.name, {
                        "actual_qty": 0,
                        "updated_qty": 0,
                        "shopify_pre_order_qty": 0,
                        "shopify_pre_order_enabled": 0,
                        "estimated_time_of_dispatch": "",
                        "status": "Queued",
                        "is_active": 1,
                        "sync_error": "[Inactive/Disabled Bundle - Queued to 0]",
                        "modified": frappe.utils.now(),
                    })
                elif has_stock or has_preorder or is_active == 1 or stale.get("status") != "Completed":
                    frappe.db.set_value("NJ Inventory Sync Main", stale.name, {
                        "actual_qty": 0,
                        "updated_qty": 0,
                        "shopify_pre_order_qty": 0,
                        "shopify_pre_order_enabled": 0,
                        "estimated_time_of_dispatch": "",
                        "status": "Completed",
                        "is_active": 0,
                        "sync_error": "[Inactive/Disabled Bundle]",
                        "modified": frappe.utils.now(),
                    })
        except Exception:
            logger.exception(f"[{run_id}] Error during stale inventory cleanup")
            log_error(frappe.get_traceback(), "Stale Inventory Cleanup Error")

        # =========================================================
        # 🔹 Shopify Pre-Order Policy & ETD Metafield Sync (independent from stock)
        # =========================================================
        if shopify_data and not pre_order_data_ok:
            logger.warning(
                f"[{run_id}] pre-order breaker tripped - holding pre-order "
                f"state; ETD sync still runs"
            )
            # ETD has nothing to do with pre-order and must not be held back.
            sync_shopify_etd_metafields(
                shopify_data, settings["shop"], settings["token"],
            )

        if shopify_data and pre_order_data_ok:
            # Pre-order policy sync is intentionally independent from stock sync.
            # A policy error must not block inventory quantity processing.
            pre_order_policy_result = sync_shopify_pre_order_policies(
                shopify_data,
                settings["shop"],
                settings["token"],
            )
            logger.info(
                f"[{run_id}] Shopify pre-order policy sync completed: "
                f"{pre_order_policy_result}"
            )

            # Synchronize estimated_time_of_dispatch variant metafields to Shopify
            etd_metafield_result = sync_shopify_etd_metafields(
                shopify_data,
                settings["shop"],
                settings["token"],
            )
            logger.info(
                f"[{run_id}] Shopify ETD metafield sync completed: "
                f"{etd_metafield_result}"
            )

            # Synchronize pre-order status metafields and tags to Shopify
            pre_order_metafield_result = sync_shopify_pre_order_metafields_and_tags(
                shopify_data,
                settings["shop"],
                settings["token"],
            )
            logger.info(
                f"[{run_id}] Shopify pre-order metafield & tag sync completed: "
                f"{pre_order_metafield_result}"
            )

        if variant_ids is not None and product_ids:
            sync_result = _create_shopify_inventory_sync(variant_ids=product_ids)
            logger.info(
                f"[{run_id}] targeted Shopify inventory push completed: {sync_result}"
            )

        elapsed = time.monotonic() - started_at
        logger.info(
            f"[{run_id}] create_rq_doc completed successfully in {elapsed:.1f}s; stats={stats}"
        )
        return {
            "run_id": run_id, "status": "completed",
            "elapsed_seconds": round(elapsed, 1), "variant_ids": product_ids, **stats,
        }

    except Exception:
        elapsed = time.monotonic() - started_at
        logger.exception(
            f"[{run_id}] create_rq_doc failed after {elapsed:.1f}s; stats={stats}"
        )
        log_error(
            f"Error in create_rq_doc: {frappe.get_traceback()}",
            "Inventory Sync Error"
        )
        return {"run_id": run_id, "status": "failed", "elapsed_seconds": round(elapsed, 1), **stats}
        
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
@inventory_sync_execution_lock
def create_shopify_inventory_sync():
    return _create_shopify_inventory_sync()


def _create_shopify_inventory_sync(variant_ids=None):
    """Send queued quantities in GraphQL batches under the caller's execution lock."""
    if variant_ids is not None and not variant_ids:
        return {"status": "completed", "completed": 0, "errored": 0, "skipped": 0}

    try:
        batch_size = 50
        settings = get_shopify_settings()

        if not settings:
            log_error("Shopify settings not found", "create_shopify_inventory_sync")
            return {"status": "failed", "reason": "missing_settings"}

        headers = {
            "X-Shopify-Access-Token": settings["token"],
            "Content-Type": "application/json",
        }
        # Use Shopify's current stable Admin API. Its inventorySetQuantities
        # contract requires changeFromQuantity and an idempotent field call.
        graphql_url = f"{settings['shop']}/admin/api/2026-07/graphql.json"
        location_id = str(settings["location_id"]).strip()
        location_gid = (
            location_id
            if location_id.startswith("gid://shopify/Location/")
            else f"gid://shopify/Location/{location_id}"
        )
        mutation = """
            mutation SetInventoryQuantities(
                $input: InventorySetQuantitiesInput!,
                $idempotencyKey: String!
            ) {
                inventorySetQuantities(input: $input)
                    @idempotent(key: $idempotencyKey) {
                    inventoryAdjustmentGroup {
                        createdAt
                        reason
                        changes {
                            name
                            delta
                            quantityAfterChange
                        }
                    }
                    userErrors {
                        field
                        message
                        code
                    }
                }
            }
        """
        totals = {"completed": 0, "errored": 0, "skipped": 0, "batches": 0}
        where_variant = ""
        query_params = ()
        if variant_ids is not None:
            placeholders = ', '.join(['%s'] * len(variant_ids))
            where_variant = f"AND shopify_variant_id IN ({placeholders})"
            query_params = tuple(variant_ids)

        while True:
            completed_docs = []
            errored_docs = []
            skipped_docs = []

            queued = frappe.db.sql(f"""
                SELECT name, item_code, actual_qty, shopify_variant_id,
                       updated_qty, inventory_item_id, shopify_quantity, sync_error
                FROM `tabNJ Inventory Sync Main`
                WHERE status = 'Queued'
                  AND is_active = 1
                  AND inventory_item_id IS NOT NULL
                  AND inventory_item_id != ''
                  {where_variant}
                LIMIT %s
            """, query_params + (batch_size,), as_dict=True)

            if not queued:
                break

            batch_number = totals["batches"] + 1
            batch_id = frappe.generate_hash(length=32)
            selected_count = len(queued)
            variant_id_by_doc = {
                row.name: str(row.shopify_variant_id or "").strip()
                for row in queued
            }
            valid_rows = []
            quantities = []

            for row in queued:
                updated_qty = safe_float(row.updated_qty)
                current_shopify_qty = safe_float(row.shopify_quantity)
                if updated_qty is None or updated_qty < 0:
                    skipped_docs.append(row.name)
                    frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                        "status": "Error",
                        "sync_error": str({
                            "result": "skipped",
                            "reason": "Invalid or negative updated_qty",
                            "batch_id": batch_id,
                            "batch_number": batch_number,
                            "selected_count": selected_count,
                            "shopify_variant_id": variant_id_by_doc[row.name],
                        }),
                        "modified": frappe.utils.now(),
                    })
                    continue
                if current_shopify_qty is None:
                    skipped_docs.append(row.name)
                    frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                        "status": "Error",
                        "sync_error": str({
                            "result": "skipped",
                            "reason": "Missing fresh Shopify quantity",
                            "batch_id": batch_id,
                            "batch_number": batch_number,
                            "selected_count": selected_count,
                            "shopify_variant_id": variant_id_by_doc[row.name],
                        }),
                        "modified": frappe.utils.now(),
                    })
                    continue

                available = int(updated_qty)
                inventory_item_id = str(row.inventory_item_id).strip()
                inventory_item_gid = (
                    inventory_item_id
                    if inventory_item_id.startswith("gid://shopify/InventoryItem/")
                    else f"gid://shopify/InventoryItem/{inventory_item_id}"
                )
                valid_rows.append((row, available))
                quantities.append({
                    "inventoryItemId": inventory_item_gid,
                    "locationId": location_gid,
                    "quantity": available,
                    "changeFromQuantity": int(current_shopify_qty),
                })

            if valid_rows:
                totals["batches"] += 1
                batch_error = None
                batch_updated_at = None
                indexed_user_errors = {}

                try:
                    response = post_shopify_api(
                        graphql_url,
                        headers=headers,
                        json_payload={
                            "query": mutation,
                            "variables": {
                                "idempotencyKey": batch_id,
                                "input": {
                                    # "available" is correct here: the quantity we
                                    # stage (updated_qty) already excludes serials
                                    # reserved to a sales order, so it is a
                                    # SELLABLE number, not a physical on-hand one.
                                    # Pushing it as on_hand would double-count the
                                    # reservation (once in our exclusion, once in
                                    # Shopify's committed) and drive available
                                    # negative.
                                    "name": "available",
                                    "reason": "correction",
                                    "quantities": quantities,
                                }
                            },
                        },
                    )

                    if response.status_code != 200:
                        batch_error = f"Shopify GraphQL HTTP {response.status_code}: {response.text}"
                    else:
                        response_data = response.json()
                        graphql_errors = response_data.get("errors") or []
                        payload = (
                            response_data.get("data", {})
                            .get("inventorySetQuantities")
                        ) or {}
                        user_errors = payload.get("userErrors") or []
                        adjustment_group = payload.get("inventoryAdjustmentGroup") or {}
                        batch_updated_at = adjustment_group.get("createdAt")

                        for user_error in user_errors:
                            field_path = user_error.get("field") or []
                            if isinstance(field_path, str):
                                field_path = field_path.split(".")
                            quantity_index = next(
                                (
                                    int(part) for part in field_path
                                    if str(part).isdigit()
                                ),
                                None,
                            )
                            if quantity_index is not None:
                                indexed_user_errors.setdefault(quantity_index, []).append(user_error)

                        if graphql_errors or user_errors:
                            batch_error = (
                                f"Shopify GraphQL errors={graphql_errors}; "
                                f"userErrors={user_errors}"
                            )
                except requests.exceptions.Timeout:
                    batch_error = "Timeout while updating inventory batch to Shopify (200+ sec)"
                except Exception as exc:
                    batch_error = f"Unknown error while updating inventory batch to Shopify: {exc}"

                # Verify every record against Shopify after the mutation. This
                # makes the final status per-record even when Shopify returns a
                # batch-level error or only part of a request is applied.
                verification_data = None
                verification_error = None
                try:
                    verification_data = get_shopify_variants(
                        [row.shopify_variant_id for row, _available in valid_rows],
                        settings["shop"],
                        settings["token"],
                        location_id=settings["location_id"],
                    )
                    if verification_data is None:
                        verification_error = "Post-batch Shopify verification failed"
                except Exception as exc:
                    verification_error = (
                        f"Post-batch Shopify verification raised an error: {exc}"
                    )

                verified_by_variant = {
                    str(data.get("variant_id") or "").strip(): data
                    for data in (verification_data or [])
                    if data.get("variant_id")
                }
                verified_results = []

                for row_index, (row, available) in enumerate(valid_rows):
                    variant_id = variant_id_by_doc[row.name]
                    verified_row = verified_by_variant.get(variant_id)
                    verified_qty = (
                        safe_float(verified_row.get("location_quantity"))
                        if verified_row else None
                    )
                    is_verified = (
                        verified_qty is not None
                        and int(verified_qty) == available
                    )

                    if is_verified:
                        completed_docs.append(row.name)
                        verified_results.append(
                            ("completed", row, available, int(verified_qty), None)
                        )
                        continue

                    record_errors = indexed_user_errors.get(row_index)
                    if record_errors:
                        record_error = f"Shopify userErrors={record_errors}"
                    elif verification_error:
                        record_error = verification_error
                    elif verified_qty is None:
                        record_error = "Variant or inventory level missing during verification"
                    elif batch_error:
                        record_error = batch_error
                    else:
                        record_error = (
                            f"Shopify quantity verification mismatch: "
                            f"expected={available}, verified={verified_qty:g}"
                        )

                    errored_docs.append(row.name)
                    verified_results.append(
                        ("error", row, available, verified_qty, record_error)
                    )

                batch_result = {
                    "completed": len(completed_docs),
                    "errored": len(errored_docs),
                    "skipped": len(skipped_docs),
                }

                for result, row, available, verified_qty, record_error in verified_results:
                    variant_id = variant_id_by_doc[row.name]
                    result_details = {
                        "result": result,
                        "inventory_item_id": str(row.inventory_item_id),
                        "location_id": str(settings["location_id"]),
                        "expected_quantity": available,
                        "verified_shopify_quantity": verified_qty,
                        "updated_at": batch_updated_at or frappe.utils.now(),
                        "sync_method": "GraphQL batch with post-verification",
                        "batch_id": batch_id,
                        "batch_number": batch_number,
                        "batch_size": selected_count,
                        "shopify_variant_id": variant_id,
                        "batch_result": batch_result,
                    }

                    if result == "completed":
                        previous_message = (row.sync_error or "").strip()
                        preserved_rules = []
                        for message_part in previous_message.split("]"):
                            message_part = message_part.strip()
                            if message_part.startswith("[ParentOverride"):
                                preserved_rules.append(f"{message_part}]")
                            elif message_part.startswith("[WarrantyApplied"):
                                preserved_rules.append(f"{message_part}]")
                        success_message = " ".join(
                            preserved_rules + [str(result_details)]
                        ).strip()
                        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                            "status": "Completed",
                            "is_active": 1,
                            "shopify_quantity": verified_qty,
                            "sync_error": success_message,
                            "modified": frappe.utils.now(),
                        })
                    else:
                        result_details["error"] = record_error
                        values = {
                            "status": "Error",
                            "sync_error": str(result_details),
                            "modified": frappe.utils.now(),
                        }
                        if verified_qty is not None:
                            values["shopify_quantity"] = verified_qty
                        frappe.db.set_value(
                            "NJ Inventory Sync Main",
                            row.name,
                            values,
                        )

            batch_summary = {
                "batch_id": batch_id,
                "batch_number": batch_number,
                "batch_size": selected_count,
                "completed_count": len(completed_docs),
                "completed_variant_ids": [
                    variant_id_by_doc[name] for name in completed_docs
                ],
                "error_count": len(errored_docs),
                "error_variant_ids": [
                    variant_id_by_doc[name] for name in errored_docs
                ],
                "skipped_count": len(skipped_docs),
                "skipped_variant_ids": [
                    variant_id_by_doc[name] for name in skipped_docs
                ],
            }
            classified_count = (
                batch_summary["completed_count"]
                + batch_summary["error_count"]
                + batch_summary["skipped_count"]
            )
            if classified_count != selected_count:
                logger.error(
                    f"Shopify inventory batch classification mismatch: "
                    f"batch_id={batch_id}, selected={selected_count}, "
                    f"classified={classified_count}"
                )

            batch_summary_json = json.dumps(batch_summary, separators=(",", ":"))
            for row in queued:
                frappe.db.set_value(
                    "NJ Inventory Sync Main",
                    row.name,
                    "batch_summary",
                    batch_summary_json,
                    update_modified=False,
                )

            frappe.db.commit()
            totals["completed"] += len(completed_docs)
            totals["errored"] += len(errored_docs)
            totals["skipped"] += len(skipped_docs)

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

        logger.info(f"Shopify GraphQL inventory sync completed: {totals}")
        return {"status": "completed", **totals}

    except Exception as e:
        log_error(f"Error in start_shopify_inventory_sync: {str(e)}\n{frappe.get_traceback()}", "Shopify Inventory Sync", "Error")
        return {"status": "failed", "error": str(e)}

def sync_shopify_pre_order_policies(shopify_data, shop, token):
    """Synchronize Shopify inventoryPolicy without affecting inventory quantities."""
    stats = {"checked": 0, "updated": 0, "unchanged": 0, "failed": 0}

    try:
        variant_ids = [
            str(data.get("variant_id") or "").strip()
            for data in shopify_data
            if data.get("variant_id")
        ]
        if not variant_ids:
            return stats

        sync_rows = frappe.get_all(
            "NJ Inventory Sync Main",
            filters={"shopify_variant_id": ["in", variant_ids]},
            fields=["name", "shopify_variant_id", "actual_qty", "shopify_pre_order_qty"],
        )
        sync_row_by_variant = {
            str(row.shopify_variant_id).strip(): row for row in sync_rows
        }

        variants_by_product = {}

        for data in shopify_data:
            variant_id = str(data.get("variant_id") or "").strip()
            product_id = str(data.get("product_id") or "").strip()
            current_policy = str(data.get("inventory_policy") or "").upper()
            sync_row = sync_row_by_variant.get(variant_id)

            if not variant_id or not product_id or not sync_row:
                continue

            stats["checked"] += 1
            pre_order_qty = safe_float(sync_row.shopify_pre_order_qty) or 0
            live_qty = safe_float(sync_row.actual_qty) or 0
            # Pre-order quantity is now synced directly to Shopify as available inventory.
            # We set policy to DENY so Shopify strictly sells up to the synced quantity and prevents overselling.
            desired_policy = "DENY"
            is_pre = 1 if (live_qty <= 0 and pre_order_qty > 0) else 0

            if current_policy == desired_policy:
                frappe.db.set_value(
                    "NJ Inventory Sync Main",
                    sync_row.name,
                    "shopify_pre_order_enabled",
                    is_pre,
                    update_modified=False,
                )
                stats["unchanged"] += 1
                continue

            variants_by_product.setdefault(product_id, []).append({
                "id": f"gid://shopify/ProductVariant/{variant_id}",
                "inventoryPolicy": desired_policy,
            })

        if not variants_by_product:
            frappe.db.commit()
            return stats

        url = f"{shop}/admin/api/2026-10/graphql.json"
        headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        }
        mutation = """
            mutation UpdatePreOrderPolicies(
                $productId: ID!,
                $variants: [ProductVariantsBulkInput!]!
            ) {
                productVariantsBulkUpdate(
                    productId: $productId,
                    variants: $variants
                ) {
                    productVariants {
                        id
                        inventoryPolicy
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
        """

        for product_id, variants in variants_by_product.items():
            response = post_shopify_api(
                url,
                headers=headers,
                json_payload={
                    "query": mutation,
                    "variables": {
                        "productId": f"gid://shopify/Product/{product_id}",
                        "variants": variants,
                    },
                },
            )

            if response.status_code != 200:
                stats["failed"] += len(variants)
                log_error(
                    f"Shopify pre-order policy HTTP error for product {product_id}: {response.text}",
                    "Shopify Pre-Order Policy Sync",
                )
                continue

            response_data = response.json()
            graphql_errors = response_data.get("errors") or []
            payload = (
                response_data.get("data", {})
                .get("productVariantsBulkUpdate")
            ) or {}
            user_errors = payload.get("userErrors") or []

            if graphql_errors or user_errors:
                stats["failed"] += len(variants)
                log_error(
                    f"Shopify pre-order policy error for product {product_id}: "
                    f"graphql_errors={graphql_errors}, user_errors={user_errors}",
                    "Shopify Pre-Order Policy Sync",
                )
                continue

            updated_variants = payload.get("productVariants") or []
            updated_variant_ids = set()

            for updated_variant in updated_variants:
                variant_gid = updated_variant.get("id") or ""
                variant_id = variant_gid.split("/")[-1]
                confirmed_policy = str(
                    updated_variant.get("inventoryPolicy") or ""
                ).upper()
                sync_row = sync_row_by_variant.get(variant_id)

                if not sync_row or confirmed_policy not in ("CONTINUE", "DENY"):
                    continue

                live_qty = safe_float(sync_row.actual_qty) or 0
                pre_order_qty = safe_float(sync_row.shopify_pre_order_qty) or 0
                is_pre = 1 if (live_qty <= 0 and pre_order_qty > 0) else 0

                frappe.db.set_value(
                    "NJ Inventory Sync Main",
                    sync_row.name,
                    "shopify_pre_order_enabled",
                    is_pre,
                    update_modified=False,
                )
                updated_variant_ids.add(variant_id)
                stats["updated"] += 1

            stats["failed"] += max(len(variants) - len(updated_variant_ids), 0)

        frappe.db.commit()
        return stats

    except Exception:
        stats["failed"] += 1
        log_error(
            f"Error syncing Shopify pre-order policies: {frappe.get_traceback()}",
            "Shopify Pre-Order Policy Sync",
        )
        return stats


@frappe.whitelist()
def sync_shopify_etd_metafields(shopify_data, shop=None, token=None):
    """Synchronize variant-level estimated_time_of_dispatch metafields to Shopify."""
    stats = {"checked": 0, "updated": 0, "unchanged": 0, "failed": 0}

    try:
        if not shop or not token:
            settings = get_shopify_settings()
            if not settings:
                log_error("Shopify settings not found", "sync_shopify_etd_metafields")
                return stats
            shop = settings["shop"]
            token = settings["token"]

        variant_ids = [
            str(data.get("variant_id") or "").strip()
            for data in shopify_data
            if data.get("variant_id")
        ]
        if not variant_ids:
            return stats

        sync_rows = frappe.get_all(
            "NJ Inventory Sync Main",
            filters={"shopify_variant_id": ["in", variant_ids]},
            fields=["name", "shopify_variant_id", "estimated_time_of_dispatch"],
        )
        sync_row_by_variant = {
            str(row.shopify_variant_id).strip(): row for row in sync_rows
        }

        metafields_to_set = []
        for variant_id in variant_ids:
            sync_row = sync_row_by_variant.get(variant_id)
            if not sync_row:
                continue

            stats["checked"] += 1
            etd_val = str(sync_row.get("estimated_time_of_dispatch") or "").strip()
            metafields_to_set.append({
                "ownerId": f"gid://shopify/ProductVariant/{variant_id}",
                "namespace": "custom",
                "key": "estimated_time_of_dispatch",
                "type": "single_line_text_field",
                "value": etd_val,
            })

        if not metafields_to_set:
            return stats

        url = f"{shop}/admin/api/2026-10/graphql.json"
        headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        }
        mutation = """
            mutation SetVariantETDMetafields($metafields: [MetafieldsSetInput!]!) {
                metafieldsSet(metafields: $metafields) {
                    metafields {
                        id
                        namespace
                        key
                        value
                    }
                    userErrors {
                        field
                        message
                        code
                    }
                }
            }
        """

        # Shopify allows up to 25 metafields per metafieldsSet mutation call
        batch_size = 25
        for i in range(0, len(metafields_to_set), batch_size):
            batch = metafields_to_set[i:i + batch_size]
            response = post_shopify_api(
                url,
                headers=headers,
                json_payload={
                    "query": mutation,
                    "variables": {"metafields": batch},
                },
            )

            if response.status_code != 200:
                stats["failed"] += len(batch)
                log_error(
                    f"Shopify ETD metafield HTTP error: {response.text}",
                    "Shopify ETD Metafield Sync",
                )
                continue

            response_data = response.json()
            graphql_errors = response_data.get("errors") or []
            payload = (
                response_data.get("data", {})
                .get("metafieldsSet")
            ) or {}
            user_errors = payload.get("userErrors") or []

            if graphql_errors:
                stats["failed"] += len(batch)
                log_error(
                    f"Shopify ETD metafield GraphQL error: {graphql_errors}",
                    "Shopify ETD Metafield Sync",
                )
                continue

            if user_errors:
                # Isolate invalid variant indexes (e.g. Owner does not exist) and retry valid ones
                invalid_indexes = set()
                for err in user_errors:
                    field = err.get("field") or []
                    if len(field) >= 2 and str(field[1]).isdigit():
                        invalid_indexes.add(int(field[1]))
                
                stats["failed"] += len(invalid_indexes)
                valid_sub_batch = [item for idx, item in enumerate(batch) if idx not in invalid_indexes]
                if valid_sub_batch:
                    retry_resp = post_shopify_api(
                        url,
                        headers=headers,
                        json_payload={
                            "query": mutation,
                            "variables": {"metafields": valid_sub_batch},
                        },
                    )
                    if retry_resp.status_code == 200:
                        retry_payload = retry_resp.json().get("data", {}).get("metafieldsSet", {})
                        retry_updated = retry_payload.get("metafields") or []
                        stats["updated"] += len(retry_updated)
                        continue
                continue

            updated_metafields = payload.get("metafields") or []
            stats["updated"] += len(updated_metafields)

        return stats

    except Exception:
        stats["failed"] += 1
        log_error(
            f"Error syncing Shopify ETD metafields: {frappe.get_traceback()}",
            "Shopify ETD Metafield Sync",
        )
        return stats


def _shopify_graphql(url, headers, query, variables, context):
    """POST a GraphQL document and hand back its data block, or None on failure."""
    try:
        response = post_shopify_api(
            url, headers=headers,
            json_payload={"query": query, "variables": variables},
        )
    except Exception:
        log_error(f"{context}: request failed\n{frappe.get_traceback()}", context)
        return None

    if response.status_code != 200:
        log_error(f"{context}: HTTP {response.status_code} {response.text}", context)
        return None

    body = response.json()
    if body.get("errors"):
        log_error(f"{context}: GraphQL errors {body['errors']}", context)
        return None

    return body.get("data") or {}


# Definitions only have to exist once per store. Remembering that for the life
# of the worker keeps a steady state at zero API calls.
_PRE_ORDER_DEFINITIONS_READY = False

PRE_ORDER_METAFIELD_OWNERS = ("PRODUCTVARIANT", "PRODUCT")


def ensure_pre_order_metafield_definitions(shop, token, force=False):
    """Make sure custom.pre_order_status is a DEFINED field, not just a value.

    metafieldsSet happily writes a value with no definition behind it: the
    value is stored and Liquid can read it, but Shopify's admin shows nothing,
    it is not searchable or filterable, and the theme editor will not offer it
    as a dynamic source. Creating the definition is a separate mutation that
    nothing else calls.

    Definitions adopt values that were written before they existed, so this is
    safe to run against a store that already has pre-order values on it -
    nothing needs re-pushing.

    Idempotent: existing definitions are left untouched.
    """
    global _PRE_ORDER_DEFINITIONS_READY
    stats = {"existing": 0, "created": 0, "failed": 0}

    if _PRE_ORDER_DEFINITIONS_READY and not force:
        return stats

    url = f"{shop}/admin/api/2026-10/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    # Ask for this one key rather than listing the namespace: Products already
    # carry 68 definitions in "custom", so a first:50 listing silently misses
    # it and we would try to create a definition that already exists.
    lookup = """
        query ExistingDefinition($owner: MetafieldOwnerType!) {
            metafieldDefinitions(
                first: 5, ownerType: $owner,
                namespace: "custom", key: "pre_order_status"
            ) {
                nodes { key }
            }
        }
    """
    create = """
        mutation CreatePreOrderDefinition($definition: MetafieldDefinitionInput!) {
            metafieldDefinitionCreate(definition: $definition) {
                createdDefinition { id key ownerType }
                userErrors { field message code }
            }
        }
    """

    for owner in PRE_ORDER_METAFIELD_OWNERS:
        data = _shopify_graphql(
            url, headers, lookup, {"owner": owner},
            "Shopify Pre-Order Metafield Definition",
        )
        if data is None:
            stats["failed"] += 1
            continue

        keys = {
            node.get("key")
            for node in ((data.get("metafieldDefinitions") or {}).get("nodes") or [])
        }
        if "pre_order_status" in keys:
            stats["existing"] += 1
            continue

        definition = {
            "name": "Pre Order Status",
            "namespace": "custom",
            "key": "pre_order_status",
            "type": "single_line_text_field",
            "ownerType": owner,
            "description": (
                "Set by the ERP inventory sync: 'pre_order' when the item is "
                "sold from machines still in the build pipeline, 'ready_stock' "
                "when it ships from shelf stock."
            ),
            "access": {"storefront": "PUBLIC_READ"},
        }

        data = _shopify_graphql(
            url, headers, create, {"definition": definition},
            "Shopify Pre-Order Metafield Definition",
        )

        # Older stores reject the access block; the definition itself is still
        # worth having, so fall back to the default visibility.
        if data is not None:
            errors = (data.get("metafieldDefinitionCreate") or {}).get("userErrors") or []
            if errors and any("access" in str(e.get("field") or "").lower() for e in errors):
                definition.pop("access", None)
                data = _shopify_graphql(
                    url, headers, create, {"definition": definition},
                    "Shopify Pre-Order Metafield Definition",
                )

        if data is None:
            stats["failed"] += 1
            continue

        payload = data.get("metafieldDefinitionCreate") or {}
        errors = payload.get("userErrors") or []

        if errors:
            # A definition someone added by hand in the meantime is not a failure.
            if any(str(e.get("code") or "") == "TAKEN" for e in errors):
                stats["existing"] += 1
                continue
            stats["failed"] += 1
            log_error(
                f"Could not create {owner} custom.pre_order_status definition: {errors}",
                "Shopify Pre-Order Metafield Definition",
            )
            continue

        if payload.get("createdDefinition"):
            stats["created"] += 1
            log_error(
                f"Created metafield definition custom.pre_order_status on {owner}",
                "Shopify Pre-Order Metafield Definition",
                "Info",
            )

    if not stats["failed"]:
        _PRE_ORDER_DEFINITIONS_READY = True

    return stats


# The value published to Shopify. Kept as a constant because it is compared
# against what the store already holds - a literal typed twice would silently
# republish every variant on every run.
PRE_ORDER_STATUS_VALUE = "pre-order"
READY_STOCK_STATUS_VALUE = "ready_stock"


VARIANT_PAGE_QUERY = """
    query ProductVariantPage($id: ID!, $after: String!) {
        product(id: $id) {
            variants(first: 100, after: $after) {
                pageInfo { hasNextPage endCursor }
                nodes {
                    id
                    metafield(namespace: "custom", key: "pre_order_status") { value }
                }
            }
        }
    }
"""


def fetch_product_pre_order_state(product_ids, shop, token):
    """Read what Shopify currently holds for a set of products.

    Returns {product_id: {"tags": [...], "status": "...",
                          "variant_status": {variant_id: "..."}}}.

    This exists so a targeted sync can decide a product's tag from every one
    of its variants. Deciding from the handful of variants in the batch is
    what strips the tag off products whose other variants are still on
    pre-order.
    """
    state = {}
    product_ids = [str(p).strip() for p in product_ids if str(p or "").strip()]
    if not product_ids:
        return state

    query = """
        query ProductPreOrderState($ids: [ID!]!) {
            nodes(ids: $ids) {
                ... on Product {
                    id
                    tags
                    metafield(namespace: "custom", key: "pre_order_status") { value }
                    variants(first: 100) {
                        pageInfo { hasNextPage endCursor }
                        nodes {
                            id
                            metafield(namespace: "custom", key: "pre_order_status") { value }
                        }
                    }
                }
            }
        }
    """
    url = f"{shop}/admin/api/2026-10/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    for i in range(0, len(product_ids), 25):
        batch = product_ids[i:i + 25]
        data = _shopify_graphql(
            url, headers, query,
            {"ids": [f"gid://shopify/Product/{p}" for p in batch]},
            "Shopify Pre-Order Product State",
        )
        if not data:
            continue
        for node in data.get("nodes") or []:
            if not node or not node.get("id"):
                continue
            product_id = str(node["id"]).split("/")[-1]
            variant_status = {}
            variants = node.get("variants") or {}
            for variant in (variants.get("nodes") or []):
                variant_id = str(variant.get("id") or "").split("/")[-1]
                if variant_id:
                    variant_status[variant_id] = (variant.get("metafield") or {}).get("value") or ""

            # A product with more than 100 variants would otherwise be judged on
            # its first 100 only, and a pre-order variant past the cut-off would
            # be invisible - the tag would come off a product that still has one.
            page = variants.get("pageInfo") or {}
            cursor = page.get("endCursor")
            while page.get("hasNextPage") and cursor:
                more = _shopify_graphql(
                    url, headers, VARIANT_PAGE_QUERY,
                    {"id": node["id"], "after": cursor},
                    "Shopify Pre-Order Product State",
                )
                if not more:
                    break
                page_variants = ((more.get("product") or {}).get("variants") or {})
                for variant in (page_variants.get("nodes") or []):
                    variant_id = str(variant.get("id") or "").split("/")[-1]
                    if variant_id:
                        variant_status[variant_id] = (variant.get("metafield") or {}).get("value") or ""
                page = page_variants.get("pageInfo") or {}
                cursor = page.get("endCursor")

            state[product_id] = {
                "tags": node.get("tags") or [],
                "status": (node.get("metafield") or {}).get("value") or "",
                "variant_status": variant_status,
            }

    return state


@frappe.whitelist()
def sync_shopify_pre_order_metafields_and_tags(shopify_data, shop=None, token=None):
    """Publish pre-order status to Shopify as variant/product metafields and a product tag.

    Everything here is a diff against what Shopify already holds, which the
    inventory read brings back with it, so a run where nothing moved costs no
    API calls at all.

    Three things this deliberately does NOT do:

      * push a blank metafield value - Shopify rejects a blank
        single_line_text_field, so clearing one means metafieldsDelete;
      * re-publish a status that is already live;
      * decide a product's tag from the variants in the current batch - a
        targeted sync sees one variant, and removing the tag on that basis
        strips it from products whose other variants are still on pre-order.
    """
    stats = {
        "checked": 0, "unchanged": 0, "metafields_set": 0,
        "metafields_cleared": 0, "products_updated": 0, "failed": 0,
    }

    try:
        if not shop or not token:
            settings = get_shopify_settings()
            if not settings:
                log_error("Shopify settings not found", "sync_shopify_pre_order_metafields_and_tags")
                return stats
            shop = settings["shop"]
            token = settings["token"]

        variant_ids = [
            str(data.get("variant_id") or "").strip()
            for data in shopify_data
            if data.get("variant_id")
        ]
        if not variant_ids:
            return stats

        sync_rows = frappe.get_all(
            "NJ Inventory Sync Main",
            filters={"shopify_variant_id": ["in", variant_ids]},
            fields=["name", "shopify_variant_id", "actual_qty", "shopify_pre_order_qty"],
        )
        sync_row_by_variant = {
            str(row.shopify_variant_id).strip(): row for row in sync_rows
        }

        def status_for(row):
            """Pre-order status derived from quantities only.

            The stored shopify_pre_order_enabled flag is deliberately not
            consulted: it is written earlier in the same run, so it cannot say
            what was previously published, and when it is a run behind it
            labels a variant that has stock on the shelf as a pre-order.
            """
            live_qty = safe_float(row.get("actual_qty")) or 0
            pre_order_qty = safe_float(row.get("shopify_pre_order_qty")) or 0
            if live_qty <= 0 and pre_order_qty > 0:
                return PRE_ORDER_STATUS_VALUE
            if live_qty > 0:
                return READY_STOCK_STATUS_VALUE
            return ""

        url = f"{shop}/admin/api/2026-10/graphql.json"
        headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

        # The field has to exist before values mean anything in the admin.
        ensure_pre_order_metafield_definitions(shop, token)

        metafields_to_set = []
        metafields_to_clear = []
        desired_by_variant = {}
        products_by_variant = {}
        changed_product_ids = set()

        for data in shopify_data:
            variant_id = str(data.get("variant_id") or "").strip()
            sync_row = sync_row_by_variant.get(variant_id)
            if not variant_id or not sync_row:
                continue

            stats["checked"] += 1

            product_id = str(data.get("product_id") or "").strip()
            if product_id:
                products_by_variant[variant_id] = product_id

            desired = status_for(sync_row)
            published = str(data.get("pre_order_status") or "")
            desired_by_variant[variant_id] = desired

            if desired == published:
                stats["unchanged"] += 1
                continue

            if product_id:
                changed_product_ids.add(product_id)

            identifier = {
                "ownerId": f"gid://shopify/ProductVariant/{variant_id}",
                "namespace": "custom",
                "key": "pre_order_status",
            }
            if desired:
                metafields_to_set.append(
                    dict(identifier, type="single_line_text_field", value=desired)
                )
            else:
                metafields_to_clear.append(identifier)

        # ---- variant metafields ------------------------------------------
        set_mutation = """
            mutation SetPreOrderMetafields($metafields: [MetafieldsSetInput!]!) {
                metafieldsSet(metafields: $metafields) {
                    metafields { id }
                    userErrors { field message code }
                }
            }
        """
        for i in range(0, len(metafields_to_set), 25):
            batch = metafields_to_set[i:i + 25]
            data = _shopify_graphql(
                url, headers, set_mutation, {"metafields": batch},
                "Shopify Pre-Order Metafield Sync",
            )
            if data is None:
                stats["failed"] += len(batch)
                continue
            payload = data.get("metafieldsSet") or {}
            if payload.get("userErrors"):
                stats["failed"] += len(payload["userErrors"])
                log_error(
                    f"Shopify pre-order metafield userErrors: {payload['userErrors']}",
                    "Shopify Pre-Order Metafield Sync",
                )
            stats["metafields_set"] += len(payload.get("metafields") or [])

        clear_mutation = """
            mutation ClearPreOrderMetafields($metafields: [MetafieldIdentifierInput!]!) {
                metafieldsDelete(metafields: $metafields) {
                    deletedMetafields { ownerId }
                    userErrors { field message }
                }
            }
        """
        for i in range(0, len(metafields_to_clear), 25):
            batch = metafields_to_clear[i:i + 25]
            data = _shopify_graphql(
                url, headers, clear_mutation, {"metafields": batch},
                "Shopify Pre-Order Metafield Sync",
            )
            if data is None:
                stats["failed"] += len(batch)
                continue
            payload = data.get("metafieldsDelete") or {}
            if payload.get("userErrors"):
                log_error(
                    f"Shopify pre-order metafield delete userErrors: {payload['userErrors']}",
                    "Shopify Pre-Order Metafield Sync",
                )
            stats["metafields_cleared"] += len(payload.get("deletedMetafields") or [])

        if not changed_product_ids:
            return stats

        # ---- product metafield + tag ---------------------------------------
        # Only products whose variants actually moved, and decided across ALL
        # of their variants: the ones this run knows about carry their new
        # status, the rest are read back from Shopify.
        product_state = fetch_product_pre_order_state(changed_product_ids, shop, token)

        for product_id in sorted(changed_product_ids):
            state = product_state.get(product_id)
            if not state:
                continue

            statuses = dict(state["variant_status"])
            for variant_id, desired in desired_by_variant.items():
                if products_by_variant.get(variant_id) == product_id:
                    statuses[variant_id] = desired

            is_pre = any(value == PRE_ORDER_STATUS_VALUE for value in statuses.values())
            desired_status = PRE_ORDER_STATUS_VALUE if is_pre else ""
            # Shopify preserves whatever casing a tag was first created with
            # and dedupes case-insensitively. This store already carries
            # "Pre-Order", so a case-sensitive check reports the tag missing on
            # every run: tagsAdd fires forever as a no-op, and - worse - a
            # product that should LOSE the tag never does, because is_pre and
            # has_tag both read False and the branch is skipped.
            existing_tags = state["tags"] or []
            matching_tags = [t for t in existing_tags if str(t).strip().lower() == "pre-order"]
            has_tag = bool(matching_tags)
            product_gid = f"gid://shopify/Product/{product_id}"
            touched = False

            if desired_status != str(state["status"] or ""):
                if desired_status:
                    data = _shopify_graphql(
                        url, headers, set_mutation,
                        {"metafields": [{
                            "ownerId": product_gid,
                            "namespace": "custom",
                            "key": "pre_order_status",
                            "type": "single_line_text_field",
                            "value": desired_status,
                        }]},
                        "Shopify Pre-Order Product Metafield",
                    )
                else:
                    data = _shopify_graphql(
                        url, headers, clear_mutation,
                        {"metafields": [{
                            "ownerId": product_gid,
                            "namespace": "custom",
                            "key": "pre_order_status",
                        }]},
                        "Shopify Pre-Order Product Metafield",
                    )
                if data is None:
                    stats["failed"] += 1
                else:
                    touched = True

            # Shopify keeps whatever casing a tag was first created with and
            # dedupes case-insensitively, so tagsAdd("pre-order") on a product
            # already carrying "Pre-Order" silently does nothing. To publish the
            # canonical lowercase form the old casing has to be removed first.
            PRE_ORDER_TAG = "pre-order"
            stale_casing = [t for t in matching_tags if str(t) != PRE_ORDER_TAG]

            tag_ops = []
            if is_pre:
                if stale_casing:
                    tag_ops.append(("tagsRemove", stale_casing))
                if stale_casing or not has_tag:
                    tag_ops.append(("tagsAdd", [PRE_ORDER_TAG]))
            elif has_tag:
                # Remove every casing present, not just our canonical one.
                tag_ops.append(("tagsRemove", matching_tags))

            for op, tag_values in tag_ops:
                tag_mutation = """
                    mutation AddProductTags($id: ID!, $tags: [String!]!) {
                        tagsAdd(id: $id, tags: $tags) {
                            node { id }
                            userErrors { field message }
                        }
                    }
                """ if op == "tagsAdd" else """
                    mutation RemoveProductTags($id: ID!, $tags: [String!]!) {
                        tagsRemove(id: $id, tags: $tags) {
                            node { id }
                            userErrors { field message }
                        }
                    }
                """
                data = _shopify_graphql(
                    url, headers, tag_mutation,
                    {"id": product_gid, "tags": tag_values},
                    "Shopify Pre-Order Tag Sync",
                )
                if data is None:
                    stats["failed"] += 1
                    continue
                # userErrors here were previously ignored, so a rejected tag
                # change looked like a success.
                errors = (data.get(op) or {}).get("userErrors") or []
                if errors:
                    stats["failed"] += 1
                    log_error(
                        f"Shopify {op} rejected for {product_id}: {errors}",
                        "Shopify Pre-Order Tag Sync",
                    )
                else:
                    touched = True

            if touched:
                stats["products_updated"] += 1

        return stats

    except Exception:
        stats["failed"] += 1
        log_error(
            f"Error syncing Shopify pre-order metafields and tags: {frappe.get_traceback()}",
            "Shopify Pre-Order Metafield Sync",
        )
        return stats


@frappe.whitelist()
def get_shopify_variants(
    product_ids,
    shop,
    token,
    location_id=None,
    retry_missing=True,
):
    try:
        url = f"{shop}/admin/api/2026-10/graphql.json"
        headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json"
        }

        normalized_product_ids = []
        seen_product_ids = set()
        for product_id in product_ids or []:
            product_id = str(product_id or "").strip()
            if product_id.startswith("gid://shopify/ProductVariant/"):
                product_id = product_id.rsplit("/", 1)[-1]
            if product_id.isdigit() and product_id not in seen_product_ids:
                normalized_product_ids.append(product_id)
                seen_product_ids.add(product_id)

        gids = [
            f"gid://shopify/ProductVariant/{product_id}"
            for product_id in normalized_product_ids
        ]
        location_gid = None
        if location_id:
            location_id = str(location_id).strip()
            location_gid = (
                location_id
                if location_id.startswith("gid://shopify/Location/")
                else f"gid://shopify/Location/{location_id}"
            )
        result = []

        def fetch_batch(batch):
            # "available" drives the sync (it matches the semantics of the
            # quantity we stage - see the mutation input below). on_hand is
            # fetched alongside it for diagnostics: a growing gap between
            # on_hand and available means Shopify is accumulating committed
            # units we are re-advertising.
            inventory_level_fields = """
                    inventoryLevel(locationId: $locationId) {
                        quantities(names: ["on_hand", "available"]) {
                            name
                            quantity
                        }
                    }
            """ if location_gid else ""
            location_variable = ", $locationId: ID!" if location_gid else ""

            graphql_query = f"""
            query GetShopifyVariants($ids: [ID!]!{location_variable}) {{
            nodes(ids: $ids) {{
                ... on ProductVariant {{
                id
                inventoryQuantity
                inventoryPolicy
                inventoryItem {{
                    id
                    {inventory_level_fields}
                }}
                metafield(namespace: "custom", key: "pre_order_status") {{
                    value
                }}
                product {{
                    id
                    tags
                    metafield(namespace: "custom", key: "pre_order_status") {{
                        value
                    }}
                }}
                }}
            }}
            }}
            """

            variables = {"ids": batch}
            if location_gid:
                variables["locationId"] = location_gid

            response = post_shopify_api(
                url,
                headers=headers,
                json_payload={"query": graphql_query, "variables": variables},
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"Shopify API HTTP {response.status_code}: {response.text}"
                )

            data = response.json()
            if data.get("errors"):
                raise RuntimeError(f"Shopify GraphQL errors: {data['errors']}")

            batch_result = []
            for node in data.get("data", {}).get("nodes", []):
                if not node:
                    continue

                inventory_quantity = node.get("inventoryQuantity", 0)
                variant_gid = node.get("id", "")
                variant_id = variant_gid.split("/")[-1]

                inventory_item = node.get("inventoryItem") or {}
                inventory_item_gid = inventory_item.get("id", "")
                inventory_item_id = (
                    inventory_item_gid.split("/")[-1]
                    if inventory_item_gid else None
                )
                product = node.get("product") or {}
                product_gid = product.get("id", "")
                product_id = product_gid.split("/")[-1] if product_gid else None
                location_quantity = None
                location_on_hand_quantity = None
                inventory_level = inventory_item.get("inventoryLevel")
                if inventory_level:
                    for quantity in inventory_level.get("quantities") or []:
                        if quantity.get("name") == "available":
                            location_quantity = quantity.get("quantity")
                        elif quantity.get("name") == "on_hand":
                            location_on_hand_quantity = quantity.get("quantity")

                batch_result.append({
                    "variant_id": variant_id,
                    "inventory_item_id": inventory_item_id,
                    "inventory_quantity": inventory_quantity,
                    "location_quantity": location_quantity,
                    "location_on_hand_quantity": location_on_hand_quantity,
                    "inventory_policy": node.get("inventoryPolicy"),
                    "product_id": product_id,
                    "pre_order_status": (node.get("metafield") or {}).get("value") or "",
                    "product_pre_order_status": (product.get("metafield") or {}).get("value") or "",
                    "product_tags": product.get("tags") or [],
                })

            return batch_result

        def fetch_in_batches(batch_gids, batch_size, fail_entire_lookup):
            fetched = []
            for i in range(0, len(batch_gids), batch_size):
                batch = batch_gids[i:i + batch_size]
                try:
                    fetched.extend(fetch_batch(batch))
                except Exception as exc:
                    log_error(
                        f"Shopify variant lookup batch failed: {exc}",
                        "Error in get_shopify_variants_method",
                    )
                    if fail_entire_lookup:
                        return None
            return fetched

        initial_result = fetch_in_batches(gids, 50, fail_entire_lookup=True)
        if initial_result is None:
            return None
        result.extend(initial_result)

        if retry_missing:
            found_ids = {
                str(row.get("variant_id") or "").strip() for row in result
            }
            missing_ids = [
                product_id for product_id in normalized_product_ids
                if product_id not in found_ids
            ]

            if missing_ids:
                logger.warning(
                    f"Shopify bulk lookup missed {len(missing_ids)} variants; "
                    "retrying in batches of 10"
                )
                retry_gids = [
                    f"gid://shopify/ProductVariant/{product_id}"
                    for product_id in missing_ids
                ]
                retry_result = fetch_in_batches(
                    retry_gids,
                    10,
                    fail_entire_lookup=False,
                )
                result.extend(retry_result or [])

                found_ids = {
                    str(row.get("variant_id") or "").strip() for row in result
                }
                still_missing_ids = [
                    product_id for product_id in missing_ids
                    if product_id not in found_ids
                ]

                # Existing records with an inventory_item_id were previously
                # confirmed by Shopify. Retry those IDs individually before a
                # transient bulk omission is treated as "not found".
                known_variant_ids = set()
                if still_missing_ids:
                    known_rows = frappe.get_all(
                        "NJ Inventory Sync Main",
                        filters={
                            "shopify_variant_id": ["in", still_missing_ids],
                        },
                        fields=["shopify_variant_id", "inventory_item_id"],
                    )
                    known_variant_ids = {
                        str(row.shopify_variant_id or "").strip()
                        for row in known_rows
                        if str(row.inventory_item_id or "").strip()
                    }

                if known_variant_ids:
                    logger.warning(
                        f"Individually retrying {len(known_variant_ids)} "
                        "previously known Shopify variants"
                    )
                    individual_gids = [
                        f"gid://shopify/ProductVariant/{product_id}"
                        for product_id in still_missing_ids
                        if product_id in known_variant_ids
                    ]
                    individual_result = fetch_in_batches(
                        individual_gids,
                        1,
                        fail_entire_lookup=False,
                    )
                    result.extend(individual_result or [])

        # A retry may return an ID that was already present in the first pass.
        # Keep one authoritative result per Shopify variant.
        result_by_variant = {
            str(row.get("variant_id") or "").strip(): row
            for row in result
            if row.get("variant_id")
        }

        return list(result_by_variant.values())

    except Exception as e:
        log_error(f"Error in get_shopify_variants_method: {str(e)}\n{frappe.get_traceback()}", "Error in get_shopify_variants_method")
        return None