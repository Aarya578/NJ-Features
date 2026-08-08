import frappe
import pymysql
import json
import requests
import time
from frappe.utils.background_jobs import enqueue
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error
from nj_features.nj_features.api.shopify_inventory import (
    get_shopify_settings,
    get_shopify_variants,
    safe_float,
    post_shopify_api,
    get_inventory_sync_flags,
)

logger = frappe.logger("NEW SHOPIFY INVENTORY SYNC LOG", allow_site=True, file_count=10)


# =============================================================================
# 🔹 HOOK ENTRY POINT — Called by Sales Order on_submit
# =============================================================================

def trigger_inventory_sync_from_sales_order(doc, method=None):
    """
    Hook triggered on Sales Order on_submit.
    Collects item codes from Sales Order Item and Packed Item rows,
    then enqueues a single background job for the targeted sync.
    """
    try:
        item_codes = set()

        # From normal Sales Order Items
        for row in doc.get("items") or []:
            if row.item_code:
                item_codes.add(str(row.item_code).strip())

        # From Packed Items (for Product Bundles)
        for row in doc.get("packed_items") or []:
            if row.item_code:
                item_codes.add(str(row.item_code).strip())

        if not item_codes:
            log_error(
                f"No item codes found in Sales Order {doc.name}",
                "trigger_inventory_sync_from_sales_order",
                "Info"
            )
            return

        log_error(
            f"Triggering targeted inventory sync for SO {doc.name} with items: {list(item_codes)}",
            "trigger_inventory_sync_from_sales_order",
            "Info"
        )

        enqueue(
            method=create_rq_doc_by_item_codes,
            queue="short",
            timeout=300,
            job_name=f"shopify_inventory_sync_so_{doc.name}",
            item_codes=list(item_codes),
            sales_order=doc.name
        )

    except Exception:
        log_error(frappe.get_traceback(), "trigger_inventory_sync_from_sales_order")


# =============================================================================
# 🔹 BACKGROUND WORKER
# =============================================================================

def create_rq_doc_by_item_codes(item_codes, sales_order=None):
    """
    Background worker:
    1. Resolve affected Shopify Variant IDs from item codes.
    2. Run targeted SO Quantity Check calculation.
    3. Run targeted parent and proportional qty updates.
    4. Stage affected variants into NJ Inventory Sync Main.
    5. Update inventory_item_id and shopify_quantity from Shopify API.
    6. Push the staged quantities directly to Shopify.
    """
    logger.debug(f"[Targeted Sync] Started for SO={sales_order}, items={item_codes}")

    settings = get_shopify_settings()
    if not settings:
        log_error("Shopify settings not found", "create_rq_doc_by_item_codes")
        return

    # Step 1: Resolve variant IDs
    variant_ids = get_affected_variant_ids(item_codes, sales_order)
    if not variant_ids:
        # Already logged in get_affected_variant_ids
        return

    logger.debug(f"[Targeted Sync] Affected variant IDs: {variant_ids}")

    # Step 2: Targeted SO Quantity Check
    if not update_so_quantity_check_for_variant_ids(settings, variant_ids):
        log_error("Targeted SO Quantity Check failed", "create_rq_doc_by_item_codes")
        return

    # Step 3: Targeted parent qty update
    if not update_parent_quantity_for_variant_ids(variant_ids):
        log_error("Targeted parent quantity update failed", "create_rq_doc_by_item_codes")
        return

    # Step 4: Targeted proportional qty update
    if not update_proportional_qty_and_updt_qty_for_variant_ids(variant_ids):
        log_error("Targeted proportional qty update failed", "create_rq_doc_by_item_codes")
        return

    # Step 5: Stage into NJ Inventory Sync Main
    stage_targeted_variants(variant_ids, settings)

    # Step 6: Immediate Push to Shopify
    push_targeted_variants_to_shopify(variant_ids, settings)

    log_error(
        f"[Targeted Sync] Completed for SO={sales_order}, variants={variant_ids}",
        "create_rq_doc_by_item_codes",
        "Info"
    )


# =============================================================================
# 🔹 STEP 1: Resolve Affected Shopify Variant IDs
# =============================================================================

def get_affected_variant_ids(item_codes, sales_order=None):
    """
    Given a list of ERP item codes, find all Shopify Variant IDs
    in Product Bundle that contain any of those item codes.
    Logs missing mappings to sales_order_shopify_push.
    """
    try:
        if not item_codes:
            return []

        placeholders = ', '.join(['%s'] * len(item_codes))
        rows = frappe.db.sql(f"""
            SELECT pb.shopify_variant_id, pbi.item_code
            FROM `tabProduct Bundle` pb
            INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
            WHERE
                pbi.item_code IN ({placeholders})
                AND pb.shopify_variant_id IS NOT NULL
                AND pb.shopify_variant_id != ''
        """, tuple(item_codes), as_dict=True)

        found_item_codes = {row.get("item_code") for row in rows}
        missing_item_codes = set(item_codes) - found_item_codes

        if missing_item_codes:
            log_error(
                f"SO {sales_order}: No Shopify Variant mapping found for items: {list(missing_item_codes)}",
                "sales_order_shopify_push",
                "Info"
            )

        variant_ids = list(set(
            str(row.shopify_variant_id).strip()
            for row in rows
            if row.get("shopify_variant_id")
        ))
        
        return variant_ids

    except Exception:
        log_error(frappe.get_traceback(), "get_affected_variant_ids")
        return []


# =============================================================================
# 🔹 STEP 2: Targeted SO Quantity Check Update
# =============================================================================

def update_so_quantity_check_for_variant_ids(settings, variant_ids):
    """
    Targeted version of update_so_quantity_check().
    Recalculates SO Quantity Check only for the given Shopify Variant IDs.
    Deletes and re-inserts ONLY the affected item codes (not the full table).
    """
    try:
        if not variant_ids:
            return True

        warehouses = settings['warehouses']
        departments = settings['departments']
        item_groups = settings['item_groups']

        warehouses_list = [i.strip() for i in (warehouses or '').split(',') if i.strip()]
        item_groups_list = [i.strip() for i in item_groups.split(',') if i.strip()]
        departments_list = [d.strip() for d in departments.split(',') if d.strip()]

        item_group_placeholders = ', '.join(['%s'] * len(item_groups_list))
        department_placeholders = ', '.join(['%s'] * len(departments_list))
        variant_placeholders = ', '.join(['%s'] * len(variant_ids))
        warehouse_clause = (
            f"OR b.warehouse IN ({', '.join(['%s'] * len(warehouses_list))})"
            if warehouses_list else ""
        )

        # Same CTE query as update_so_quantity_check() but filtered by variant_ids
        query = f"""
            WITH Parent_Stock AS (
                SELECT
                    TRIM(CONCAT(i.variant_of, ' ', COALESCE(proc.attribute_value, ''))) AS parent,
                    COUNT(b.serial_no) AS total_actual_qty_for_parent
                FROM `tabItem` i
                LEFT JOIN `tabSerial No` b ON i.item_code = b.item_code
                LEFT JOIN `tabWarehouse` w ON b.warehouse = w.name
                LEFT JOIN `tabSales Order` so ON b.sales_order_id = so.name
                LEFT JOIN `tabItem Variant Attribute` proc
                    ON proc.parent = i.item_code
                    AND proc.attribute = 'Processor Type1'
                WHERE
                    b.item_group IN ({item_group_placeholders})
                    AND w.department IN ({department_placeholders})
                    AND b.is_replace = 0
                    AND (
                        b.return_reason IS NULL OR b.return_reason = ''
                        OR b.return_reason != 'Repair'
                        OR (b.return_reason = 'Repair' AND (
                            so.name IS NULL OR so.status = 'Closed' OR so.per_delivered = 100
                        ))
                    )
                    {warehouse_clause}
                GROUP BY i.variant_of, COALESCE(proc.attribute_value, '')
            ),
            Item_Stock AS (
                SELECT
                    s.item_code,
                    COUNT(s.serial_no) AS total_actual_qty_for_itemcode
                FROM `tabSerial No` s
                INNER JOIN `tabWarehouse` w ON w.name = s.warehouse
                INNER JOIN `tabItem` i ON s.item_code = i.item_code
                LEFT JOIN `tabSales Order` so ON s.sales_order_id = so.name
                WHERE
                    i.item_group IN ({item_group_placeholders})
                    AND w.department IN ({department_placeholders})
                    AND s.is_replace = 0
                    AND (
                        s.return_reason IS NULL OR s.return_reason = ''
                        OR s.return_reason != 'Repair'
                        OR (s.return_reason = 'Repair' AND (
                            so.name IS NULL OR so.status = 'Closed' OR so.per_delivered = 100
                        ))
                    )
                    {warehouse_clause}
                GROUP BY s.item_code
            ),
            Main_Data AS (
                SELECT DISTINCT
                    pb.shopify_variant_id,
                    i.item_code,
                    i.item_group,
                    TRIM(CONCAT(i.variant_of, ' ', COALESCE(proc.attribute_value, ''))) AS parent,
                    ps.total_actual_qty_for_parent,
                    isq.total_actual_qty_for_itemcode
                FROM `tabProduct Bundle` pb
                LEFT JOIN `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
                LEFT JOIN `tabItem` i ON pbi.item_code = i.item_code
                LEFT JOIN `tabItem Variant Attribute` proc
                    ON proc.parent = i.item_code
                    AND proc.attribute = 'Processor Type1'
                LEFT JOIN Parent_Stock ps ON ps.parent = TRIM(CONCAT(i.variant_of, ' ', COALESCE(proc.attribute_value, '')))
                LEFT JOIN Item_Stock isq ON isq.item_code = i.item_code
                WHERE
                    i.item_group IN ({item_group_placeholders})
                    AND pb.shopify_variant_id IN ({variant_placeholders})
            )
            SELECT
                shopify_variant_id,
                item_code,
                item_group,
                total_actual_qty_for_itemcode AS actual_qty,
                parent,
                total_actual_qty_for_parent
            FROM Main_Data
            ORDER BY shopify_variant_id, item_code;
        """

        params = (
            item_groups_list + departments_list + warehouses_list +
            item_groups_list + departments_list + warehouses_list +
            item_groups_list + variant_ids
        )

        inventory_data = frappe.db.sql(query, tuple(params), as_dict=True)

        stock_map = {}
        for row in inventory_data:
            item_code = row.get('item_code')
            if item_code:
                stock_map[item_code] = {
                    'parent1': row.get('parent', ''),
                    'actual_qty': row.get('actual_qty', 0) or 0
                }

        # Pending SO calculation (same as original - runs for all, but we only insert for affected)
        pending_so_data = frappe.db.sql("""
            SELECT
                so_data.pb_code,
                so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.qty, 0)) AS pending_qty
            FROM (
                SELECT
                    soi.parent AS sales_order, soi.item_code,
                    IFNULL(pb.item_code, soi.item_code) AS pb_code,
                    soi.qty, soi.item_group, so.creation, soi.rate
                FROM `tabSales Order` so
                INNER JOIN `tabSales Order Item` soi ON so.name = soi.parent
                LEFT JOIN `tabProduct Bundle Item` pb ON soi.item_code = pb.parent
                LEFT JOIN `tabItem` it ON it.item_code = pb.item_code
                LEFT JOIN `tabItem` main_it ON main_it.item_code = soi.item_code
                WHERE
                    so.status NOT IN ('Closed', 'Completed', 'Cancelled')
                    AND so.docstatus = 1
                    AND so.creation > CURDATE() - INTERVAL 100 DAY
                    AND so.sale_type != 'Amazon'
                    AND (
                        soi.item_group IN ('Laptops(Bundle)', 'Chromebooks(Bundle)', 'MacBooks(Bundle)', 'MacBooks', 'Laptops', 'Chromebooks')
                        OR main_it.item_group IN ('Laptops(Bundle)', 'Chromebooks(Bundle)', 'MacBooks(Bundle)', 'MacBooks', 'Laptops', 'Chromebooks')
                        OR it.item_group IN ('Laptops(Bundle)', 'Chromebooks(Bundle)', 'MacBooks(Bundle)', 'MacBooks', 'Laptops', 'Chromebooks')
                    )
            ) AS so_data
            LEFT JOIN (
                SELECT dni.against_sales_order, dni.item_code, SUM(dni.qty) AS qty
                FROM `tabDelivery Note Item` dni
                LEFT JOIN `tabItem` main_it ON main_it.item_code = dni.item_code
                WHERE
                    dni.docstatus = 1 AND dni.qty > 0
                    AND dni.creation >= CURDATE() - INTERVAL 100 DAY
                    AND (
                        dni.item_group IN ('Laptops(Bundle)', 'Chromebooks(Bundle)', 'MacBooks(Bundle)', 'MacBooks', 'Laptops', 'Chromebooks')
                        OR main_it.item_group IN ('Laptops(Bundle)', 'Chromebooks(Bundle)', 'MacBooks(Bundle)', 'MacBooks', 'Laptops', 'Chromebooks')
                    )
                GROUP BY dni.against_sales_order, dni.item_code
            ) AS dn_data
                ON so_data.sales_order = dn_data.against_sales_order
                AND so_data.item_code = dn_data.item_code
            ORDER BY so_data.sales_order, so_data.item_code;
        """, as_dict=True)

        pending_qty_by_item = {}
        for row in pending_so_data:
            item_code = row.get('pb_code')
            if item_code:
                pending_qty_by_item[item_code] = pending_qty_by_item.get(item_code, 0) + (row.get('pending_qty') or 0)

        # Delete ONLY affected item codes (not the full table)
        if stock_map:
            affected_item_codes = list(stock_map.keys())
            ip = ', '.join(['%s'] * len(affected_item_codes))
            frappe.db.sql(f"DELETE FROM `tabSO Quantity Check` WHERE item_code IN ({ip})", tuple(affected_item_codes))
            frappe.db.commit()

        # Re-insert for affected items only using bulk_insert
        count = 0
        if stock_map:
            now_time = frappe.utils.now()
            user = frappe.session.user or "Administrator"
            fields = [
                "name", "creation", "modified", "modified_by", "owner",
                "docstatus", "idx", "item_code", "parent1", "actual_qty",
                "so_quantity", "remaining_qty", "update_qty", "need_to_reduce",
                "remove_parent_qty", "update_qty2", "proportional_remove_qty", "sla"
            ]
            values = []
            for item_code, data in stock_map.items():
                actual_qty = data.get('actual_qty', 0) or 0
                so_quantity = pending_qty_by_item.get(item_code, 0) or 0
                remaining_qty = actual_qty - so_quantity
                update_qty = max(remaining_qty, 0)
                need_to_reduce = abs(remaining_qty) if remaining_qty < 0 else 0
                values.append((
                    frappe.generate_hash(length=10), now_time, now_time, user, user,
                    0, 0, item_code, data.get('parent1', ''), str(actual_qty),
                    str(so_quantity), str(remaining_qty), str(update_qty), str(need_to_reduce),
                    "0", "0", None, 0
                ))
                count += 1
            frappe.db.bulk_insert("SO Quantity Check", fields, values)

        frappe.db.commit()
        log_error(
            f"Targeted SO Quantity Check: updated {count} items for variants={variant_ids}",
            "update_so_quantity_check_for_variant_ids",
            "Info"
        )
        return True

    except pymysql.err.OperationalError as e:
        if e.args and e.args[0] == 2013:
            return False
        return False
    except Exception:
        log_error(frappe.get_traceback(), "update_so_quantity_check_for_variant_ids")
        return False


# =============================================================================
# 🔹 STEP 3: Targeted Parent Quantity Update
# =============================================================================

def _get_affected_parent1_list(variant_ids):
    """Helper: resolve parent1 groups from variant_ids."""
    if not variant_ids:
        return []
    vp = ', '.join(['%s'] * len(variant_ids))
    rows = frappe.db.sql(f"""
        SELECT DISTINCT TRIM(CONCAT(i.variant_of, ' ', COALESCE(proc.attribute_value, ''))) AS parent1
        FROM `tabProduct Bundle` pb
        INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
        INNER JOIN `tabItem` i ON i.item_code = pbi.item_code
        LEFT JOIN `tabItem Variant Attribute` proc
            ON proc.parent = i.item_code
            AND proc.attribute = 'Processor Type1'
        WHERE pb.shopify_variant_id IN ({vp})
        AND i.variant_of IS NOT NULL AND i.variant_of != ''
    """, tuple(variant_ids), as_dict=True)
    return [r.parent1 for r in rows if r.get("parent1")]


def update_parent_quantity_for_variant_ids(variant_ids):
    """
    Targeted version of update_parent_quantity().
    Only updates parent1 groups affected by the given variant_ids.
    """
    try:
        parent1_list = _get_affected_parent1_list(variant_ids)
        if not parent1_list:
            return True

        pp = ', '.join(['%s'] * len(parent1_list))
        # Single joined UPDATE - no N+1 loop needed
        frappe.db.sql(f"""
            UPDATE `tabSO Quantity Check` t
            INNER JOIN (
                SELECT parent1, SUM(CAST(need_to_reduce AS DECIMAL(10,2))) AS total
                FROM `tabSO Quantity Check`
                WHERE CAST(need_to_reduce AS DECIMAL(10,2)) > 0
                AND parent1 IN ({pp})
                GROUP BY parent1
            ) s ON t.parent1 = s.parent1
            SET t.remove_parent_qty = CAST(s.total AS CHAR)
        """, tuple(parent1_list))

        frappe.db.commit()
        log_error(
            f"Targeted parent qty updated for parents: {parent1_list}",
            "update_parent_quantity_for_variant_ids",
            "Info"
        )
        return True

    except pymysql.err.OperationalError as e:
        return False
    except Exception:
        log_error(frappe.get_traceback(), "update_parent_quantity_for_variant_ids")
        return False


# =============================================================================
# 🔹 STEP 4: Targeted Proportional Qty Update
# =============================================================================

def update_proportional_qty_and_updt_qty_for_variant_ids(variant_ids):
    """
    Targeted version of update_proportional_qty_and_updt_qty().
    Only updates parent1 groups affected by the given variant_ids.
    """
    try:
        parent1_list = _get_affected_parent1_list(variant_ids)
        if not parent1_list:
            return True

        pp = ', '.join(['%s'] * len(parent1_list))
        # Single joined UPDATE - replaces N+1 loop
        frappe.db.sql(f"""
            UPDATE `tabSO Quantity Check` t
            INNER JOIN (
                SELECT parent1,
                    SUM(CAST(COALESCE(NULLIF(update_qty, ''), '0') AS DECIMAL(10,2))) AS total_update_qty
                FROM `tabSO Quantity Check`
                WHERE parent1 IN ({pp})
                GROUP BY parent1
            ) s ON t.parent1 = s.parent1
            SET
                t.proportional_remove_qty = CAST(
                    IF(s.total_update_qty > 0,
                        ROUND((CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS DECIMAL(10,2)) / s.total_update_qty) * CAST(COALESCE(NULLIF(t.remove_parent_qty, ''), '0') AS DECIMAL(10,2))),
                        0
                    ) AS SIGNED
                ),
                t.update_qty2 = CAST(
                    IF(CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS DECIMAL(10,2)) <= 0,
                        0,
                        GREATEST(
                            CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS SIGNED) -
                            CAST(
                                IF(s.total_update_qty > 0,
                                    ROUND((CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS DECIMAL(10,2)) / s.total_update_qty) * CAST(COALESCE(NULLIF(t.remove_parent_qty, ''), '0') AS DECIMAL(10,2))),
                                    0
                                ) AS SIGNED
                            ),
                            0
                        )
                    ) AS SIGNED
                )
        """, tuple(parent1_list))

        frappe.db.commit()
        log_error(
            f"Targeted proportional qty updated for parents: {parent1_list}",
            "update_proportional_qty_and_updt_qty_for_variant_ids",
            "Info"
        )
        return True

    except pymysql.err.OperationalError as e:
        return False
    except Exception:
        log_error(frappe.get_traceback(), "update_proportional_qty_and_updt_qty_for_variant_ids")
        return False


# =============================================================================
# 🔹 STEP 5: Stage Affected Variants into NJ Inventory Sync Main
# =============================================================================

def stage_targeted_variants(variant_ids, settings):
    """
    Aggregates final quantities from SO Quantity Check for affected variants,
    applies business rules, UPSERTs into NJ Inventory Sync Main,
    and updates inventory_item_id and shopify_quantity from Shopify API.
    """
    try:
        if not variant_ids:
            return

        vp = ', '.join(['%s'] * len(variant_ids))

        # Same aggregation query as create_rq_doc() but filtered by variant_ids
        query = f"""
            SELECT
                pb.shopify_variant_id,
                MAX(i.variant_of) AS parent1,
                MAX(COALESCE(iva.attribute_value, '')) AS processor,
                GROUP_CONCAT(DISTINCT TRIM(CONCAT(i.variant_of, ' ', COALESCE(iva.attribute_value, ''))) SEPARATOR '||') AS parent_keys,
                GROUP_CONCAT(DISTINCT i.item_code ORDER BY i.item_code SEPARATOR ', ') AS item_codes,
                GROUP_CONCAT(DISTINCT i.item_group ORDER BY i.item_group SEPARATOR ', ') AS item_groups,
                CAST(SUM(soqc.update_qty2) AS DECIMAL(10, 2)) AS total_actual_qty
            FROM `tabProduct Bundle` pb
            JOIN `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
            JOIN `tabItem` i ON pbi.item_code = i.item_code
            JOIN `tabSO Quantity Check` soqc ON i.item_code = soqc.item_code
            LEFT JOIN `tabItem Variant Attribute` iva
                ON iva.parent = i.item_code AND iva.attribute = 'Processor Type1'
            WHERE pb.shopify_variant_id IN ({vp})
            GROUP BY pb.shopify_variant_id
            ORDER BY total_actual_qty DESC
        """
        results = frappe.db.sql(query, tuple(variant_ids), as_dict=True)

        # Parent qty map (same as create_rq_doc)
        parent_qty_map = frappe.db.sql("""
            SELECT
                sqc.parent1,
                SUM(sqc.update_qty2) AS total_parent_qty
            FROM `tabSO Quantity Check` sqc
            GROUP BY sqc.parent1
        """, as_dict=True)

        parent_qty_dict = {
            str(row["parent1"]).strip().lower(): safe_float(row["total_parent_qty"])
            for row in parent_qty_map
        }

        flags = get_inventory_sync_flags()

        for row in results:
            update_status = ''
            row.total_actual_qty = safe_float(row.total_actual_qty)

            if row.total_actual_qty is None:
                continue

            # Rule 1: Parent Override
            if flags["enable_parent_override"] and row.total_actual_qty <= flags["parent_threshold"]:
                parent_keys = [k.strip().lower() for k in (getattr(row, "parent_keys", "") or "").split("||") if k.strip()]
                combined_parent_qty = sum(parent_qty_dict.get(k, 0.0) or 0.0 for k in set(parent_keys))
                if combined_parent_qty > flags["parent_threshold"]:
                    row.total_actual_qty = combined_parent_qty
                    update_status += f"[ParentOverride<={flags['parent_threshold']}→{combined_parent_qty}] "

            # Rule 2: Warranty Rule
            if flags["enable_warranty"] and 0 <= row.total_actual_qty <= flags["warranty_threshold"]:
                add_item = frappe.db.sql("""
                    SELECT item_code FROM `tabProduct Bundle Item`
                    WHERE parent IN (
                        SELECT pdi.parent FROM `tabProduct Bundle` pd
                        LEFT JOIN `tabProduct Bundle Item` pdi ON pdi.parent = pd.name
                        WHERE pd.shopify_variant_id = %s
                        GROUP BY pdi.parent HAVING COUNT(pdi.parent) > 0
                    ) AND item_code LIKE '%%additional%%';
                """, (row.shopify_variant_id,), as_dict=True)


                if add_item:
                    row.total_actual_qty = 0
                    update_status += "[WarrantyApplied] "

            # UPSERT into NJ Inventory Sync Main
            item_code_like_clauses = []
            params = [row.shopify_variant_id]
            for code in row.item_codes.split(', '):
                item_code_like_clauses.append("item_code LIKE %s")
                params.append(f"%{code.strip()}%")

            existing = frappe.db.sql(f"""
                SELECT name, actual_qty, status, sync_error, shopify_quantity
                FROM `tabNJ Inventory Sync Main`
                WHERE shopify_variant_id = %s
                AND ({' OR '.join(item_code_like_clauses)})
                ORDER BY modified DESC
            """, tuple(params), as_dict=True)

            if existing:
                existing_doc = existing[0]
                existing_qty = safe_float(existing_doc.actual_qty) or 0
                shopify_qty = safe_float(existing_doc.shopify_quantity)

                is_not_found = (
                    existing_doc.status == "Error" 
                    and existing_doc.sync_error 
                    and "Not Found" in existing_doc.sync_error
                )

                if not is_not_found:
                    if (
                        float(row.total_actual_qty) != existing_qty
                        or (shopify_qty is not None and float(row.total_actual_qty) != shopify_qty)
                    ):
                        frappe.db.set_value("NJ Inventory Sync Main", existing_doc.name, {
                            "is_active": 1,
                            "sync_error": update_status,
                            "status": "Queued",
                            "actual_qty": row.total_actual_qty,
                            "updated_qty": row.total_actual_qty,
                            "modified": frappe.utils.now(),
                        })
            else:
                new_doc = frappe.new_doc("NJ Inventory Sync Main")
                qty = safe_float(row.total_actual_qty)
                new_doc.is_active = 1
                new_doc.actual_qty = qty
                new_doc.status = "Queued"
                new_doc.updated_qty = qty
                new_doc.item_code = row.item_codes
                new_doc.item_group = row.item_groups
                new_doc.shopify_variant_id = row.shopify_variant_id
                new_doc.sync_error = update_status
                try:
                    new_doc.insert()
                except Exception:
                    log_error(
                        f"Insert error for {row.item_codes}, variant {row.shopify_variant_id}: {frappe.get_traceback()}",
                        "stage_targeted_variants"
                    )

        # Update inventory_item_id and shopify_quantity from Shopify API
        shopify_data = get_shopify_variants(variant_ids, settings["shop"], settings["token"])
        found_variant_ids = set()
        if shopify_data:
            for data in shopify_data:
                found_variant_ids.add(str(data["variant_id"]).strip())
                frappe.db.sql("""
                    UPDATE `tabNJ Inventory Sync Main`
                    SET inventory_item_id = %s, shopify_quantity = %s, modified = NOW()
                    WHERE shopify_variant_id = %s
                """, (data["inventory_item_id"], data["inventory_quantity"], data["variant_id"]))

        missing_variant_ids = set(variant_ids) - found_variant_ids
        if missing_variant_ids:
            for m_vid in missing_variant_ids:
                frappe.db.sql("""
                    UPDATE `tabNJ Inventory Sync Main`
                    SET status = 'Error', sync_error = 'Variant ID not found in Shopify', modified = NOW()
                    WHERE shopify_variant_id = %s AND status = 'Queued'
                """, (m_vid,))

        frappe.db.commit()
        log_error(
            f"Targeted staging complete for variants: {variant_ids}",
            "stage_targeted_variants",
            "Info"
        )

    except Exception:
        log_error(frappe.get_traceback(), "stage_targeted_variants")


def push_targeted_variants_to_shopify(variant_ids, settings):
    """
    Step 6: Push the staged quantities for the affected variants directly to Shopify.
    """
    try:
        if not variant_ids:
            return

        headers = {
            "X-Shopify-Access-Token": settings["token"],
            "Content-Type": "application/json"
        }

        # Fetch the staged records we just updated/inserted
        vp = ', '.join(['%s'] * len(variant_ids))
        queued = frappe.db.sql(f"""
            SELECT name, updated_qty, inventory_item_id, shopify_variant_id
            FROM `tabNJ Inventory Sync Main`
            WHERE status = 'Queued' AND is_active = 1 
            AND shopify_variant_id IN ({vp})
        """, tuple(variant_ids), as_dict=True)

        found_variants = {row.shopify_variant_id for row in queued}
        
        # Log variants that exist but are missing inventory_item_id or weren't staged
        for vid in variant_ids:
            if vid not in found_variants:
                log_error(
                    f"Variant {vid}: Skipping push. Reason: Missing inventory_item_id in Staging table.",
                    "sales_order_shopify_push",
                    "Info"
                )

        # Filter out records without inventory_item_id for the push loop
        sync_ready = [r for r in queued if r.inventory_item_id]

        if not sync_ready:
            logger.debug(f"[Targeted Push] No variants ready for API push (missing inventory_item_ids).")
            return

        completed_docs = []
        errored_docs = []

        for row in sync_ready:
            try:
                available = int(safe_float(row.updated_qty) or 0)
                update_url = f"{settings['shop']}/admin/api/2023-01/inventory_levels/set.json"
                payload = {
                    "location_id": settings["location_id"],
                    "inventory_item_id": row.inventory_item_id,
                    "available": available,
                }

                resp = post_shopify_api(update_url, headers, payload)
                data = resp.json()

                if resp.status_code == 200:
                    frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                        "status": "Completed",
                        "shopify_quantity": available,
                        "sync_error": f"{row.sync_error or ''} {str(data.get('inventory_level', 'Success'))}".strip(),
                        "modified": frappe.utils.now()
                    })
                    completed_docs.append(row.name)
                else:
                    error_msg = data.get("error") or data.get("errors") or "Unknown error"
                    frappe.db.set_value("NJ Inventory Sync Main", row.name, {
                        "status": "Error",
                        "sync_error": f"API Error: {error_msg}",
                        "modified": frappe.utils.now()
                    })
                    log_error(
                        f"Variant {row.shopify_variant_id}: Shopify API failed. Reason: {error_msg}",
                        "sales_order_shopify_push",
                        "Error"
                    )
                    errored_docs.append(row.name)
                
                # Small sleep to respect Shopify's leaky bucket (standard is 2 req/s)
                time.sleep(0.5)

            except Exception as e:
                log_error(f"Variant {row.shopify_variant_id}: Exception during push. Reason: {str(e)}", "sales_order_shopify_push")
                errored_docs.append(row.name)

        frappe.db.commit()
        log_error(
            f"Targeted push complete: {len(completed_docs)} success, {len(errored_docs)} error.",
            "push_targeted_variants_to_shopify",
            "Info"
        )

    except Exception:
        log_error(frappe.get_traceback(), "push_targeted_variants_to_shopify")
