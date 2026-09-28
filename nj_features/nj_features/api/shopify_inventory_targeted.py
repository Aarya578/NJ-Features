import frappe
import pymysql
import json
import requests
import time
from frappe.utils.background_jobs import enqueue
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error
from nj_features.nj_features.doctype.so_quantity_check.so_quantity_check import updting_sla_department
from nj_features.nj_features.api.shopify_inventory import (
    get_shopify_settings,
    get_shopify_variants,
    safe_float,
    post_shopify_api,
    get_inventory_sync_flags,
    log_shopify_push,
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

        # enqueue_after_commit is essential here, not optional.
        #
        # Sales Order.on_submit reserves serials via
        # calculate_dispatch_eta_for_sales_order(..., do_commit=False), so the
        # reservation is still UNCOMMITTED when this hook runs. Without
        # enqueue_after_commit the job is pushed to Redis immediately and a
        # worker - on its own DB connection - starts counting stock before that
        # commit lands. It cannot see reserved_sales_order yet, so it counts the
        # just-sold unit as still sellable and pushes the pre-sale quantity back
        # to Shopify. That is the 0 -> 1 -> 0 -> 1 flap: Shopify drops available
        # to 0 on the order, we immediately re-advertise 1, and because setting
        # "available" makes Shopify recompute on_hand as available + committed,
        # on_hand creeps up by one on every order.
        enqueue(
            method=create_rq_doc_by_item_codes,
            queue="short",
            timeout=300,
            job_name=f"shopify_inventory_sync_so_{doc.name}",
            enqueue_after_commit=True,
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

    # Copy mode (pre_order_claim = 0): the ordered parent + Processor
    # configurations are recounted in Step 4c. Their sibling variants are
    # already in variant_ids (see get_affected_variant_ids), so all of them are
    # pushed the fresh figure.
    from nj_features.nj_features.api.shopify_inventory import get_inventory_sync_flags
    from nj_features.nj_features.doctype.so_quantity_check.so_quantity_check import (
        get_pre_order_config_keys,
        update_pre_order_qty_for_configs,
    )
    copy_mode = not get_inventory_sync_flags()["pre_order_claim"]
    pre_order_configs = set()
    if copy_mode:
        try:
            pre_order_configs = get_pre_order_config_keys(list(item_codes))
        except Exception:
            log_error(frappe.get_traceback(), "create_rq_doc_by_item_codes - pre-order configs")
            pre_order_configs = set()

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

    # Step 4b: Update SLA & Estimated Time of Dispatch
    try:
        updting_sla_department()
    except Exception:
        log_error(frappe.get_traceback(), "create_rq_doc_by_item_codes - updting_sla_department")

    # Step 4c: Pre-order.
    #
    # Claim mode (pre_order_claim = 1): NOT recomputed here. update_pre_order_qty()
    # reallocates claims across the WHOLE table, but a targeted run only pushes
    # its own batch, so the variant that lost a claim would be zeroed and the
    # winner never pushed (a listing went 32 -> 0). The hourly run owns it.
    #
    # Copy mode (default since 2026-09-25): there are no claims to move, so the
    # ordered configurations are recounted now and pushed to every sibling
    # variant (already in variant_ids). Before 2026-09-26 this step always held the
    # last hourly figure, which put the machine just sold straight back on sale
    # (Shopify order #34095: 2 -> 1 on the order, then pushed back to 2).
    # If the recount fails, the staged figures are held exactly as before.
    pre_order_data_ok = False
    if copy_mode and pre_order_configs:
        pre_order_data_ok = update_pre_order_qty_for_configs(settings, pre_order_configs)

    # Step 5: Stage into NJ Inventory Sync Main
    shopify_data = stage_targeted_variants(variant_ids, settings, pre_order_data_ok=pre_order_data_ok)

    # Step 6: Immediate Push to Shopify
    push_targeted_variants_to_shopify(variant_ids, settings, source=sales_order)

    # Step 7: Push Pre-Order Policies & ETD / Pre-Order Metafields to Shopify
    try:
        from nj_features.nj_features.api.shopify_inventory import (
            sync_shopify_pre_order_policies,
            sync_shopify_etd_metafields,
            sync_shopify_pre_order_metafields_and_tags,
        )
        # These all run normally. A targeted run does not REALLOCATE pre-order
        # (that is the hourly job's job), but it must still publish the state of
        # the variants it just moved - otherwise a variant that gained stock
        # keeps a stale "pre_order" badge until the next hour.
        sync_payload = shopify_data if shopify_data else [{"variant_id": vid} for vid in variant_ids]
        sync_shopify_pre_order_policies(
            sync_payload,
            shop=settings.get("shop"),
            token=settings.get("token"),
        )
        sync_shopify_etd_metafields(
            sync_payload,
            shop=settings.get("shop"),
            token=settings.get("token"),
        )
        sync_shopify_pre_order_metafields_and_tags(
            sync_payload,
            shop=settings.get("shop"),
            token=settings.get("token"),
        )
    except Exception:
        log_error(frappe.get_traceback(), "create_rq_doc_by_item_codes - pre_order_and_etd_sync")

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

        # Only hardware drives stock. Add-ons on the order ('Additional 6 Months
        # warranty', 'Folding Laptop Stand', ...) sit in hundreds of bundles, so
        # looking them up here pulled every listing that carries them into this
        # "targeted" sync and re-pushed them all. Seen 2026-09-27: a Chromebox
        # order and a MacBook order each re-pushed a T460 listing (0, then 2).
        # Same item-group scope the hourly sync stages, so nothing it covers is
        # skipped here.
        from nj_features.nj_features.doctype.so_quantity_check.so_quantity_check import SOQC_ITEM_GROUPS
        settings_groups = [
            g.strip() for g in (frappe.db.get_single_value("NJ Inventory Settings", "item_groups") or "").split(",")
            if g.strip()
        ]
        hardware_groups = list(dict.fromkeys(settings_groups + SOQC_ITEM_GROUPS))
        item_codes = frappe.db.sql_list(f"""
            SELECT item_code FROM `tabItem`
            WHERE item_code IN ({', '.join(['%s'] * len(item_codes))})
              AND item_group IN ({', '.join(['%s'] * len(hardware_groups))})
        """, tuple(item_codes) + tuple(hardware_groups))
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
                AND COALESCE(pb.disable, 0) = 0
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

        # Sibling expansion: find base parents and expand to all sibling variants
        parent_rows = frappe.db.sql(f"""
            SELECT DISTINCT i.variant_of, COALESCE(iva.attribute_value, '') AS processor
            FROM `tabItem` i
            LEFT JOIN `tabItem Variant Attribute` iva
                ON iva.parent = i.item_code AND iva.attribute = 'Processor Type1'
            WHERE i.item_code IN ({placeholders})
              AND i.variant_of IS NOT NULL AND i.variant_of != ''
        """, tuple(item_codes), as_dict=True)

        if parent_rows:
            parent_conditions = []
            parent_params = []
            for pr in parent_rows:
                parent_conditions.append("(i2.variant_of = %s AND COALESCE(iva2.attribute_value, '') = %s)")
                parent_params.extend([pr["variant_of"], pr["processor"]])

            sibling_rows = frappe.db.sql(f"""
                SELECT DISTINCT pb.shopify_variant_id
                FROM `tabProduct Bundle` pb
                JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
                JOIN `tabItem` i2 ON pbi.item_code = i2.item_code
                LEFT JOIN `tabItem Variant Attribute` iva2
                    ON iva2.parent = i2.item_code AND iva2.attribute = 'Processor Type1'
                WHERE ({' OR '.join(parent_conditions)})
                  AND pb.shopify_variant_id IS NOT NULL
                  AND pb.shopify_variant_id != ''
                  AND COALESCE(pb.disable, 0) = 0
            """, tuple(parent_params), as_dict=True)

            for sr in sibling_rows:
                if sr.get("shopify_variant_id"):
                    variant_ids.append(str(sr["shopify_variant_id"]).strip())

        variant_ids = list(set(variant_ids))
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

        warehouse_placeholders = ', '.join(['%s'] * len(warehouses_list))
        item_group_placeholders = ', '.join(['%s'] * len(item_groups_list))
        department_placeholders = ', '.join(['%s'] * len(departments_list))
        variant_placeholders = ', '.join(['%s'] * len(variant_ids))

        parent_warehouse_clause = (
            f"OR b.warehouse IN ({warehouse_placeholders})"
            if warehouses_list else ""
        )
        item_warehouse_clause = (
            f"OR s.warehouse IN ({warehouse_placeholders})"
            if warehouses_list else ""
        )

        # Same CTE query as update_so_quantity_check() but filtered by variant_ids
        query = f"""
            WITH Parent_Stock AS (
                SELECT
                    TRIM(CONCAT(i.variant_of, ' ', COALESCE(proc.attribute_value, ''))) AS parent,
                    COUNT(b.name) AS total_actual_qty_for_parent
                FROM `tabItem` i
                LEFT JOIN `tabSerial No` b ON (i.name = b.item_code OR i.item_code = b.item_code)
                LEFT JOIN `tabWarehouse` w ON b.warehouse = w.name
                LEFT JOIN `tabSales Order` so ON b.sales_order_id = so.name
                LEFT JOIN `tabItem Variant Attribute` proc
                    ON proc.parent = i.name
                    AND proc.attribute = 'Processor Type1'
                WHERE
                    COALESCE(b.item_group, i.item_group) IN ({item_group_placeholders})
                    AND (w.department IN ({department_placeholders}) {parent_warehouse_clause})
                    AND b.status = 'Active'
                    AND b.is_replace = 0
                    AND (b.reserved_sales_order IS NULL OR b.reserved_sales_order = '')
                    AND (b.sales_order IS NULL OR b.sales_order = '')
                    AND (b.return_reason IS NULL OR b.return_reason = '' OR b.return_reason NOT IN ('Repair', 'Replace'))
                GROUP BY i.variant_of, COALESCE(proc.attribute_value, '')
            ),
            Item_Stock AS (
                SELECT
                    s.item_code,
                    COUNT(s.name) AS total_actual_qty_for_itemcode
                FROM `tabSerial No` s
                INNER JOIN `tabWarehouse` w ON w.name = s.warehouse
                INNER JOIN `tabItem` i ON (s.item_code = i.name OR s.item_code = i.item_code)
                LEFT JOIN `tabSales Order` so ON s.sales_order_id = so.name
                WHERE
                    COALESCE(s.item_group, i.item_group) IN ({item_group_placeholders})
                    AND (w.department IN ({department_placeholders}) {item_warehouse_clause})
                    AND s.status = 'Active'
                    AND s.is_replace = 0
                    AND (s.reserved_sales_order IS NULL OR s.reserved_sales_order = '')
                    AND (s.sales_order IS NULL OR s.sales_order = '')
                    AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason NOT IN ('Repair', 'Replace'))
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

        # Step 2: Get sales order pending quantities with line-level delivery matching
        hardware_groups_tuple = tuple(item_groups_list)

        # Imported inside the function: reservation_service imports
        # overrides.sales_order at module level, so a top-level import here risks
        # an import cycle.
        from nj_features.services.reservation_service import RTO_EXCLUSION_SQL

        pending_so_data = frappe.db.sql(f"""
            SELECT 
                so_comp.sales_order,
                so_comp.component_item_code,
                SUM(GREATEST(0, so_comp.line_ordered_qty - IFNULL(dn_line.line_delivered_qty, 0) * so_comp.multiplier)) AS total_pending_qty
            FROM (
                -- Direct stock items
                SELECT
                    so.name AS sales_order,
                    soi.name AS so_detail,
                    soi.item_code AS component_item_code,
                    soi.qty AS line_ordered_qty,
                    1.0 AS multiplier
                FROM `tabSales Order` so
                INNER JOIN `tabSales Order Item` soi ON so.name = soi.parent
                INNER JOIN `tabItem` it ON it.item_code = soi.item_code
                WHERE
                    so.status NOT IN ('Closed', 'Completed', 'Cancelled')
                    AND so.docstatus = 1
                    AND IFNULL(so.per_delivered, 0) < 100
                    AND so.sale_type != 'Amazon'
                    AND IFNULL(it.is_stock_item, 0) = 1
                    AND it.item_group IN %(hardware_groups)s
                    AND so.name NOT IN (
                        SELECT DISTINCT sales_order
                        FROM `tabNJ Refund`
                        WHERE refund_status IN ('Paid', 'Refunded', 'Initiated')
                          AND docstatus = 1
                          AND sales_order IS NOT NULL
                          AND sales_order != ''
                    )
                    -- An RTO'd order is not pending demand: the parcel came back,
                    -- so counting it here subtracted a unit from what Shopify was
                    -- allowed to advertise, for an order that will never ship.
                    -- Same list the allocator uses - see RTO_EXCLUSION_SQL.
                    {RTO_EXCLUSION_SQL}
                    AND (
                        so.creation > CURDATE() - INTERVAL 100 DAY
                        OR so.name IN (
                            SELECT DISTINCT dni_ret.against_sales_order
                            FROM `tabDelivery Note Item` dni_ret
                            INNER JOIN `tabDelivery Note` dn_ret ON dn_ret.name = dni_ret.parent
                            WHERE dn_ret.docstatus = 1 AND dn_ret.is_return = 1 AND dn_ret.posting_date > CURDATE() - INTERVAL 100 DAY
                        )
                    )

                UNION ALL

                -- Product Bundle component items
                SELECT
                    so.name AS sales_order,
                    soi.name AS so_detail,
                    pbi.item_code AS component_item_code,
                    (soi.qty * COALESCE(pbi.qty, 1)) AS line_ordered_qty,
                    COALESCE(pbi.qty, 1) AS multiplier
                FROM `tabSales Order` so
                INNER JOIN `tabSales Order Item` soi ON so.name = soi.parent
                INNER JOIN `tabItem` it_bundle ON it_bundle.item_code = soi.item_code
                INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = soi.item_code
                INNER JOIN `tabItem` it_comp ON it_comp.item_code = pbi.item_code
                WHERE
                    so.status NOT IN ('Closed', 'Completed', 'Cancelled')
                    AND so.docstatus = 1
                    AND IFNULL(so.per_delivered, 0) < 100
                    AND so.sale_type != 'Amazon'
                    AND IFNULL(it_bundle.is_stock_item, 0) = 0
                    AND it_comp.item_group IN %(hardware_groups)s
                    AND so.name NOT IN (
                        SELECT DISTINCT sales_order
                        FROM `tabNJ Refund`
                        WHERE refund_status IN ('Paid', 'Refunded', 'Initiated')
                          AND docstatus = 1
                          AND sales_order IS NOT NULL
                          AND sales_order != ''
                    )
                    -- An RTO'd order is not pending demand: the parcel came back,
                    -- so counting it here subtracted a unit from what Shopify was
                    -- allowed to advertise, for an order that will never ship.
                    -- Same list the allocator uses - see RTO_EXCLUSION_SQL.
                    {RTO_EXCLUSION_SQL}
                    AND (
                        so.creation > CURDATE() - INTERVAL 100 DAY
                        OR so.name IN (
                            SELECT DISTINCT dni_ret.against_sales_order
                            FROM `tabDelivery Note Item` dni_ret
                            INNER JOIN `tabDelivery Note` dn_ret ON dn_ret.name = dni_ret.parent
                            WHERE dn_ret.docstatus = 1 AND dn_ret.is_return = 1 AND dn_ret.posting_date > CURDATE() - INTERVAL 100 DAY
                        )
                    )
            ) AS so_comp

            LEFT JOIN (
                SELECT
                    dni.so_detail,
                    SUM(dni.qty) AS line_delivered_qty
                FROM `tabDelivery Note Item` dni
                WHERE
                    dni.docstatus = 1
                    AND dni.so_detail IS NOT NULL
                    AND dni.so_detail != ''
                GROUP BY dni.so_detail
            ) AS dn_line ON so_comp.so_detail = dn_line.so_detail

            GROUP BY so_comp.sales_order, so_comp.component_item_code
            HAVING total_pending_qty > 0
        """, {"hardware_groups": hardware_groups_tuple}, as_dict=True)

        # Step 2.5: Map allocated/reserved serials per (sales_order, item_code)
        # to prevent double-deduction. An order whose machine is already reserved
        # (whether in Packing, FQC, or upstream in QC/L2/Testing) is covered by that serial
        # and must NOT deduct from unreserved sellable stock in ready departments.
        # Delivered units (sales_order) are handled by line_delivered_qty and excluded here.
        # Reject and Scrap departments/warehouses are strictly excluded from coverage.
        alloc_query = f"""
            SELECT 
                s.reserved_sales_order,
                IFNULL(NULLIF(s.to_make, ''), s.item_code) AS item_code,
                COUNT(s.name) AS allocated_qty
            FROM `tabSerial No` s
            INNER JOIN `tabWarehouse` w ON w.name = s.warehouse
            INNER JOIN `tabItem` i ON (s.item_code = i.name OR s.item_code = i.item_code)
            WHERE s.reserved_sales_order IS NOT NULL 
              AND s.reserved_sales_order != ''
              AND s.status = 'Active'
              AND s.is_replace = 0
              AND COALESCE(s.item_group, i.item_group) IN ({item_group_placeholders})
              AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason NOT IN ('Repair', 'Replace'))
              AND (w.department NOT LIKE '%%%%Reject%%%%' AND w.department NOT LIKE '%%%%Scrap%%%%')
              AND (s.warehouse NOT LIKE '%%%%Reject%%%%' AND s.warehouse NOT LIKE '%%%%Scrap%%%%')
            GROUP BY s.reserved_sales_order, IFNULL(NULLIF(s.to_make, ''), s.item_code)
        """
        alloc_params = tuple(item_groups_list)
        allocated_serials = frappe.db.sql(alloc_query, alloc_params, as_dict=True)
        alloc_map = {(r.reserved_sales_order, r.item_code): r.allocated_qty for r in allocated_serials}

        pending_qty_by_item = {}
        for row in pending_so_data:
            so_name = row.get('sales_order')
            item_code = row.get('component_item_code')
            if item_code:
                raw_pending = row.get('total_pending_qty') or 0
                allocated_qty = alloc_map.get((so_name, item_code), 0)
                unallocated_pending = max(0, raw_pending - allocated_qty)
                if unallocated_pending > 0:
                    pending_qty_by_item[item_code] = pending_qty_by_item.get(item_code, 0) + unallocated_pending

        # Delete and Re-insert ONLY affected item codes atomically with retry on deadlock
        if stock_map:
            affected_item_codes = list(stock_map.keys())
            ip = ', '.join(['%s'] * len(affected_item_codes))

            # A targeted run deliberately does NOT recompute pre-order
            # (pre_order_data_ok is False above - the hourly staging run owns
            # that allocation). But this path rebuilds rows with DELETE+INSERT,
            # so anything not carried across is silently reset to 0. Read the
            # current pre-order figures back and re-insert them unchanged,
            # otherwise a targeted run zeroes the SOQC screen for these items
            # while Shopify keeps showing the held value.
            existing_pre_order = dict(frappe.db.sql(
                f"""SELECT item_code,
                           CAST(COALESCE(NULLIF(pre_order_qty, ''), '0') AS SIGNED)
                    FROM `tabSO Quantity Check`
                    WHERE item_code IN ({ip})""",
                tuple(affected_item_codes),
            ) or [])
            now_time = frappe.utils.now()
            user = frappe.session.user or "Administrator"
            fields = [
                "name", "creation", "modified", "modified_by", "owner",
                "docstatus", "idx", "item_code", "parent1", "actual_qty",
                "so_quantity", "remaining_qty", "update_qty", "need_to_reduce",
                "remove_parent_qty", "update_qty2", "proportional_remove_qty", "sla",
                "pre_order_qty"
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
                    "0", "0", None, 0,
                    int(existing_pre_order.get(item_code, 0) or 0)
                ))

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    frappe.db.sql(f"DELETE FROM `tabSO Quantity Check` WHERE item_code IN ({ip})", tuple(affected_item_codes))
                    if values:
                        placeholders = ', '.join(['(' + ', '.join(['%s'] * len(fields)) + ')'] * len(values))
                        flat_values = [v for row in values for v in row]
                        fields_str = ', '.join([f"`{f}`" for f in fields])
                        frappe.db.sql(f"INSERT INTO `tabSO Quantity Check` ({fields_str}) VALUES {placeholders}", tuple(flat_values))
                    frappe.db.commit()
                    break
                except (pymysql.err.OperationalError, frappe.QueryDeadlockError) as e:
                    frappe.db.rollback()
                    err_code = e.args[0] if getattr(e, 'args', None) else None
                    if (err_code in (1213, 1205) or isinstance(e, frappe.QueryDeadlockError)) and attempt < max_retries - 1:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    log_error(f"OperationalError in update_so_quantity_check_for_variant_ids (attempt {attempt+1}): {e}", "update_so_quantity_check_for_variant_ids")
                    return False
                except Exception:
                    frappe.db.rollback()
                    log_error(frappe.get_traceback(), "update_so_quantity_check_for_variant_ids")
                    return False

            count = len(values)
            log_error(
                f"Targeted SO Quantity Check: updated {count} items for variants={variant_ids}",
                "update_so_quantity_check_for_variant_ids",
                "Info"
            )
        return True

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
        # Left-joined UPDATE so parents with zero shortfall reset remove_parent_qty to '0'
        frappe.db.sql(f"""
            UPDATE `tabSO Quantity Check` t
            LEFT JOIN (
                SELECT parent1, SUM(CAST(need_to_reduce AS DECIMAL(10,2))) AS total
                FROM `tabSO Quantity Check`
                WHERE CAST(need_to_reduce AS DECIMAL(10,2)) > 0
                AND parent1 IN ({pp})
                GROUP BY parent1
            ) s ON t.parent1 = s.parent1
            SET t.remove_parent_qty = CAST(COALESCE(s.total, 0) AS CHAR)
            WHERE t.parent1 IN ({pp})
        """, tuple(parent1_list + parent1_list))

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
    Only updates parent1 groups affected by the given variant_ids using
    the Largest Remainder (Hamilton's) distribution method.
    """
    try:
        parent1_list = _get_affected_parent1_list(variant_ids)
        if not parent1_list:
            return True

        from nj_features.nj_features.doctype.so_quantity_check.so_quantity_check import (
            distribute_proportional_deduction
        )

        pp = ', '.join(['%s'] * len(parent1_list))
        rows = frappe.db.sql(f"""
            SELECT name, parent1, item_code, update_qty, need_to_reduce, pending_allocation_qty
            FROM `tabSO Quantity Check`
            WHERE parent1 IN ({pp})
        """, tuple(parent1_list), as_dict=True)

        if not rows:
            return True

        parents_map = {}
        for r in rows:
            parents_map.setdefault(r["parent1"], []).append(r)

        for parent1, p_rows in parents_map.items():
            # Derive shortfall dynamically from live need_to_reduce across all siblings
            remove_parent_qty = int(sum(float(r.get("need_to_reduce") or 0) for r in p_rows))
            allocations = distribute_proportional_deduction(p_rows, remove_parent_qty)
            for item_alloc in allocations:
                frappe.db.sql("""
                    UPDATE `tabSO Quantity Check`
                    SET remove_parent_qty = %s,
                        proportional_remove_qty = %s,
                        update_qty2 = %s,
                        pending_allocation_qty = %s
                    WHERE name = %s
                """, (
                    str(remove_parent_qty),
                    str(item_alloc["proportional_remove_qty"]),
                    str(item_alloc["update_qty2"]),
                    item_alloc["pending_allocation_qty"],
                    item_alloc["name"]
                ))

        frappe.db.commit()
        log_error(
            f"Targeted proportional qty updated for parents: {parent1_list}",
            "update_proportional_qty_and_updt_qty_for_variant_ids",
            "Info"
        )
        return True

    except pymysql.err.OperationalError:
        return False
    except Exception:
        log_error(frappe.get_traceback(), "update_proportional_qty_and_updt_qty_for_variant_ids")
        return False


# =============================================================================
# 🔹 STEP 5: Stage Affected Variants into NJ Inventory Sync Main
# =============================================================================

def stage_targeted_variants(variant_ids, settings, pre_order_data_ok=True):
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
                v.shopify_variant_id,
                MAX(v.parent1) AS parent1,
                MAX(v.processor) AS processor,
                GROUP_CONCAT(DISTINCT v.parent_key SEPARATOR '||') AS parent_keys,
                GROUP_CONCAT(DISTINCT v.item_code ORDER BY v.item_code SEPARATOR ', ') AS item_codes,
                GROUP_CONCAT(DISTINCT v.item_group ORDER BY v.item_group SEPARATOR ', ') AS item_groups,
                CAST(SUM(v.update_qty2) AS DECIMAL(10, 2)) AS total_actual_qty,
                CAST(SUM(COALESCE(v.pre_order_qty, 0)) AS DECIMAL(10, 2)) AS total_pre_order_qty,
                MIN(NULLIF(v.sla, 0)) AS etd_days,
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
                FROM `tabProduct Bundle` pb
                JOIN `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
                JOIN `tabItem` i ON pbi.item_code = i.item_code
                JOIN `tabSO Quantity Check` soqc ON i.item_code = soqc.item_code
                LEFT JOIN `tabItem Variant Attribute` iva
                    ON iva.parent = i.item_code AND iva.attribute = 'Processor Type1'
                WHERE pb.shopify_variant_id IN ({vp})
                  AND COALESCE(pb.disable, 0) = 0
            ) v
            GROUP BY v.shopify_variant_id
            ORDER BY total_actual_qty DESC
        """
        results = frappe.db.sql(query, tuple(variant_ids), as_dict=True)

        from nj_features.nj_features.api.shopify_inventory import (
            get_inventory_sync_flags,
            resolve_pre_order_claims,
            _effective_live_qty,
            pre_order_etd_allows,
        )
        flags = get_inventory_sync_flags()

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

        # One machine, one variant. resolve_pre_order_claims() looks at every
        # variant an allocated item code appears in, not just the ones in this
        # targeted batch, so a narrow sync cannot hand itself a claim that a
        # variant outside the batch is already advertising.
        # Run AFTER parent quantities are loaded: mirrors Parent Override.
        if pre_order_data_ok and flags["pre_order_claim"]:
            resolve_pre_order_claims(
                results, effective_live=_effective_live_qty(results, flags, parent_qty_dict)
            )

        # Pre-fetch live Shopify quantities and inventory_item_ids so the queueing
        # decision is based on actual live store state, not stale DB records.
        shopify_data = get_shopify_variants(
            variant_ids,
            settings["shop"],
            settings["token"],
            location_id=settings.get("location_id")
        ) or []
        shopify_by_variant = {
            str(d["variant_id"]).strip(): d
            for d in shopify_data
            if d and d.get("variant_id")
        }

        for row in results:
            update_status = ''
            row.total_actual_qty = safe_float(row.total_actual_qty)
            row.total_pre_order_qty = safe_float(row.total_pre_order_qty) or 0

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
                    ) AND item_code LIKE '%%additional%%'
                    -- Same exclusion as create_rq_doc(); without it this sync
                    -- zeroed a 1-unit listing the hourly sync then set back to 1.
                    AND item_code != 'Additional 6 Months warranty';
                """, (row.shopify_variant_id,), as_dict=True)


                if add_item:
                    row.total_actual_qty = 0
                    update_status += "[WarrantyApplied] "

            variant_id = str(row.shopify_variant_id).strip()
            shopify_row = shopify_by_variant.get(variant_id)
            inventory_item_id = shopify_row.get("inventory_item_id") if shopify_row else None
            fresh_shopify_qty = (
                safe_float(shopify_row.get("location_quantity"))
                if shopify_row and shopify_row.get("location_quantity") is not None
                else (safe_float(shopify_row.get("inventory_quantity")) if shopify_row else None)
            )
            live_qty = safe_float(row.total_actual_qty) or 0
            pre_order_qty = safe_float(row.total_pre_order_qty) or 0

            hold_pre_order = False

            if live_qty > 0:
                desired_qty = float(live_qty)
                is_pre_order = 0
            elif pre_order_qty > 0 and pre_order_etd_allows(row, flags):
                # Threshold already applied in update_pre_order_qty (company quantity).
                desired_qty = float(pre_order_qty)
                is_pre_order = 1
                update_status += f"[PreOrderSynced→{desired_qty:g}] "
            elif pre_order_qty > 0:
                # ETD too short (or missing) - same rule as create_rq_doc().
                update_status += (
                    f"[PreOrderSkipped ETD={safe_float(getattr(row, 'etd_days', None)) or 0:g}"
                    f"<={flags['pre_order_min_etd_days']}] "
                )
                pre_order_qty = 0
                desired_qty = 0.0
                is_pre_order = 0
            elif not pre_order_data_ok:
                hold_pre_order = True
                desired_qty = None
                is_pre_order = None
                update_status += "[PreOrderHeld] "
            else:
                desired_qty = 0.0
                is_pre_order = 0

            lookup_error = ""
            if not variant_id.isdigit():
                lookup_error = "Invalid or missing Shopify variant ID mapping"
            elif not shopify_row:
                lookup_error = "Variant ID not found in Shopify"
            elif fresh_shopify_qty is None:
                lookup_error = "Inventory level not found at configured Shopify location"

            # UPSERT into NJ Inventory Sync Main
            item_code_like_clauses = []
            params = [row.shopify_variant_id]
            for code in row.item_codes.split(', '):
                item_code_like_clauses.append("item_code LIKE %s")
                params.append(f"%{code.strip()}%")

            existing = frappe.db.sql(f"""
                SELECT name, actual_qty, updated_qty, status, sync_error, shopify_quantity,
                       estimated_time_of_dispatch, shopify_pre_order_qty,
                       shopify_pre_order_enabled, inventory_item_id
                FROM `tabNJ Inventory Sync Main`
                WHERE shopify_variant_id = %s
                AND ({' OR '.join(item_code_like_clauses)})
                ORDER BY modified DESC
            """, tuple(params), as_dict=True)

            # Breaker tripped: keep whatever this variant already advertises.
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
                existing_etd = str(existing_doc.get("estimated_time_of_dispatch") or "").strip()
                new_etd = str(getattr(row, "estimated_time_of_dispatch", "") or "").strip()

                is_not_found = (
                    existing_doc.status == "Error" 
                    and existing_doc.sync_error 
                    and "Not Found" in existing_doc.sync_error
                )

                if not is_not_found:
                    update_payload = {
                        "is_active": 1,
                        "actual_qty": live_qty,
                        "updated_qty": desired_qty,
                        "shopify_pre_order_qty": pre_order_qty,
                        "shopify_pre_order_enabled": is_pre_order,
                        "estimated_time_of_dispatch": new_etd,
                        "modified": frappe.utils.now(),
                    }
                    if inventory_item_id:
                        update_payload["inventory_item_id"] = inventory_item_id
                    elif existing_doc.get("inventory_item_id"):
                        inventory_item_id = existing_doc.get("inventory_item_id")

                    if fresh_shopify_qty is not None:
                        update_payload["shopify_quantity"] = fresh_shopify_qty

                    if lookup_error:
                        update_payload["status"] = "Error"
                        update_payload["sync_error"] = lookup_error
                    elif quantity_matches:
                        update_payload["status"] = "Completed"
                        update_payload["sync_error"] = (
                            existing_doc.sync_error or update_status
                            if existing_doc.status == "Completed"
                            else update_status
                        )
                    else:
                        update_payload["status"] = "Queued"
                        queue_reason = (
                            f"[QueuedForSync ERP={desired_qty:g} "
                            f"Shopify={fresh_shopify_qty:g}]"
                            if fresh_shopify_qty is not None else "[QueuedForSync]"
                        )
                        update_payload["sync_error"] = f"{update_status}{queue_reason}".strip()

                    frappe.db.set_value("NJ Inventory Sync Main", existing_doc.name, update_payload)
            else:
                new_doc = frappe.new_doc("NJ Inventory Sync Main")
                new_doc.is_active = 1
                new_doc.actual_qty = live_qty
                new_doc.updated_qty = desired_qty
                if inventory_item_id:
                    new_doc.inventory_item_id = inventory_item_id
                if fresh_shopify_qty is not None:
                    new_doc.shopify_quantity = fresh_shopify_qty

                if lookup_error:
                    new_doc.status = "Error"
                    new_doc.sync_error = lookup_error
                elif quantity_matches:
                    new_doc.status = "Completed"
                    new_doc.sync_error = update_status
                else:
                    new_doc.status = "Queued"
                    queue_reason = (
                        f"[QueuedForSync ERP={desired_qty:g} "
                        f"Shopify={fresh_shopify_qty:g}]"
                        if fresh_shopify_qty is not None else "[QueuedForSync]"
                    )
                    new_doc.sync_error = f"{update_status}{queue_reason}".strip()

                new_doc.shopify_pre_order_qty = pre_order_qty
                new_doc.shopify_pre_order_enabled = is_pre_order
                new_doc.estimated_time_of_dispatch = getattr(row, "estimated_time_of_dispatch", "") or ""
                new_doc.item_code = row.item_codes
                new_doc.item_group = row.item_groups
                new_doc.shopify_variant_id = row.shopify_variant_id
                try:
                    new_doc.insert()
                except Exception:
                    log_error(
                        f"Insert error for {row.item_codes}, variant {row.shopify_variant_id}: {frappe.get_traceback()}",
                        "stage_targeted_variants"
                    )

        found_variant_ids = set(shopify_by_variant.keys())
        missing_variant_ids = set(str(v).strip() for v in variant_ids) - found_variant_ids
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
        return shopify_data

    except Exception:
        log_error(frappe.get_traceback(), "stage_targeted_variants")
        return []


def push_targeted_variants_to_shopify(variant_ids, settings, source=None):
    """
    Step 6: Push the staged quantities for the affected variants directly to Shopify.

    source names what triggered the push (the Sales Order) for the push log.
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
            SELECT name, updated_qty, inventory_item_id, shopify_variant_id,
                   shopify_quantity, sync_error
            FROM `tabNJ Inventory Sync Main`
            WHERE status = 'Queued' AND is_active = 1
            AND shopify_variant_id IN ({vp})
        """, tuple(variant_ids), as_dict=True)

        all_staged = frappe.db.sql(f"""
            SELECT name, status, updated_qty, inventory_item_id, shopify_variant_id
            FROM `tabNJ Inventory Sync Main`
            WHERE is_active = 1 
            AND shopify_variant_id IN ({vp})
        """, tuple(variant_ids), as_dict=True)
        staged_map = {row.shopify_variant_id: row for row in all_staged}

        for vid in variant_ids:
            if vid not in staged_map:
                log_error(
                    f"Variant {vid}: Skipping push. Reason: Variant not found in Staging table.",
                    "sales_order_shopify_push",
                    "Info"
                )
            elif not staged_map[vid].get("inventory_item_id"):
                log_error(
                    f"Variant {vid}: Skipping push. Reason: Missing inventory_item_id in Staging table.",
                    "sales_order_shopify_push",
                    "Info"
                )
            elif staged_map[vid].get("status") != "Queued":
                logger.debug(f"[Targeted Push] Variant {vid} status is '{staged_map[vid].get('status')}', not Queued (already matches Shopify or in error). Skipping push.")

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
                log_shopify_push(
                    source or "sales_order", row.shopify_variant_id, row.shopify_quantity,
                    available, "completed" if resp.status_code == 200 else f"http_{resp.status_code}",
                    row.sync_error,
                )

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
