"""
Unified Reservation Service for NJ Features.

Provides a single source of truth for:
1. Hardened atomic reservation swapping.
2. 6-Tier candidate matching with explicit dispatch-ready stock preference.
3. Order-priority-respecting reservation upgrades.
4. Pure, non-mutating ETA calculations.
"""

import frappe
from frappe.utils import add_days, getdate, nowdate, now_datetime, flt
from nj_features.overrides.sales_order import add_working_days
import logging

logger = logging.getLogger("nj_reservation_service")


# ==============================================================================
# 0. SHARED REFUND-BLOCKING CHECK (single source of truth)
# ==============================================================================
# Previously this existed as three separately hand-copied variants across the
# codebase (two checking only ('Paid', 'Refunded'), one checking ('Paid',
# 'Refunded', 'Initiated')), and two allocation entry points (get_open_sales_orders,
# upgrade_order_reservations) had no refund check at all. That gap let a
# refunded-then-reopened Sales Order get silently re-allocated a fresh serial on
# every hourly cron run, only to have it released again by trim_over_allocated_serials
# — an hourly allocate/release churn that briefly locked real inventory away from
# genuine orders each cycle.
#
# 'Debit Failed' and 'Returned' are included here defensively (block-by-default):
# the cost of wrongly holding back a legitimate order (an ops person notices and
# clears it) is far lower than the cost of wrongly allocating a dead one (a real
# unit ships to an already-refunded customer). Revisit if the refund team confirms
# either status should NOT block allocation — this is the only place to change it.
# 'Hold' (the default status on new refund records, and the vast majority of all
# NJ Refund rows) and 'Rejected'/'Deleted' (refund didn't happen / was voided) are
# deliberately NOT blocking.
REFUND_BLOCKING_STATUSES = ('Paid', 'Refunded', 'Initiated', 'Debit Failed', 'Returned')

REFUND_EXCLUSION_SQL = """
    AND so.name NOT IN (
        SELECT DISTINCT sales_order FROM `tabNJ Refund`
        WHERE docstatus = 1
          AND refund_status IN ('Paid', 'Refunded', 'Initiated', 'Debit Failed', 'Returned')
          AND sales_order IS NOT NULL AND sales_order != ''
    )
    AND so.name NOT IN (
        -- An NJ Refund record may never get created at all - the return itself
        -- (Delivery Note, cause_of_return = 'Refund') is often the only signal
        -- that this order shouldn't be refilled. Only the LATEST submitted
        -- Delivery Note per order counts, so a genuine later re-delivery
        -- (someone deliberately decided to replace instead of refund) naturally
        -- un-blocks it again without needing a manual override.
        SELECT DISTINCT dni.against_sales_order
        FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dn.docstatus = 1
          AND dn.is_return = 1
          AND dn.cause_of_return = 'Refund'
          AND dni.against_sales_order IS NOT NULL AND dni.against_sales_order != ''
          AND NOT EXISTS (
              SELECT 1
              FROM `tabDelivery Note Item` dni2
              INNER JOIN `tabDelivery Note` dn2 ON dn2.name = dni2.parent
              WHERE dni2.against_sales_order = dni.against_sales_order
                AND dn2.docstatus = 1
                AND dn2.creation > dn.creation
          )
    )
"""


def is_sales_order_refund_blocked(so_name):
    """True if this SO has a submitted refund record, or its latest submitted
    Delivery Note is a Refund-cause return, that should stop allocation."""
    if frappe.db.exists("NJ Refund", {
        "sales_order": so_name,
        "docstatus": 1,
        "refund_status": ["in", REFUND_BLOCKING_STATUSES],
    }):
        return True

    latest_dn = frappe.db.sql("""
        SELECT dn.is_return, dn.cause_of_return
        FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dni.against_sales_order = %s AND dn.docstatus = 1
        ORDER BY dn.creation DESC
        LIMIT 1
    """, (so_name,), as_dict=True)

    if latest_dn and latest_dn[0].get("is_return") and latest_dn[0].get("cause_of_return") == "Refund":
        return True

    return False


# ==============================================================================
# 1. HARDENED ATOMIC RESERVATION SWAP
# ==============================================================================

def get_effective_order_source(so_name, base_sale_type=None):
    """Returns the effective order_source for a Sales Order.
    If the order has an active return Delivery Note (e.g. Repair, Replace),
    returns '{sale_type} - {cause_of_return}'. Otherwise returns '{sale_type}'.
    """
    sale_type = base_sale_type or frappe.db.get_value("Sales Order", so_name, "sale_type") or ""
    ret_cause = frappe.db.sql("""
        SELECT dn.cause_of_return
        FROM `tabDelivery Note Item` dni
        JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dni.against_sales_order = %s
          AND dn.docstatus = 1
          AND dn.is_return = 1
          AND dn.cause_of_return IS NOT NULL
          AND dn.cause_of_return != ''
        ORDER BY dn.posting_date DESC, dn.creation DESC
        LIMIT 1
    """, (so_name,), as_dict=True)
    if ret_cause and ret_cause[0].get("cause_of_return"):
        cause = ret_cause[0]["cause_of_return"].strip()
        if cause:
            return f"{sale_type} - {cause}" if sale_type else cause
    return sale_type


def swap_order_reservation(so_name, old_serial_no, new_serial_no, target_item_code=None, reason=None, operator=None):
    """
    Atomically swap an order's reservation from an old serial to a new ready serial.

    Guarantees:
    - Order and serial row-level locks (deterministic lexicographical order to prevent deadlocks).
    - Validation of open order status and pending quantity.
    - Idempotency: repeated calls when already swapped return success.
    - Strict rowcount validation (cursor.rowcount == 1).
    - Preservation of existing production commitments on released serials.
    - Audit logging on Sales Order and both Serial No records.
    - Complete rollback on any failure.
    """
    if not so_name or not old_serial_no or not new_serial_no:
        raise ValueError("so_name, old_serial_no, and new_serial_no are required for swap.")

    if old_serial_no == new_serial_no:
        return {"success": True, "status": "no_op", "message": "Old and new serial numbers are identical."}

    operator = operator or frappe.session.user or "System"
    reason = reason or "Upgrade to dispatch-ready stock"

    frappe.db.begin()
    try:
        # 1. Lock Sales Order
        so_rows = frappe.db.sql("""
            SELECT name, status, docstatus, delivery_date, committed_delivery_date, sale_type
            FROM `tabSales Order`
            WHERE name = %s
            FOR UPDATE
        """, (so_name,), as_dict=True)

        if not so_rows:
            raise frappe.ValidationError(f"Sales Order {so_name} not found.")

        so = so_rows[0]
        docstatus = so.get("docstatus") if isinstance(so, dict) else getattr(so, "docstatus", None)
        status = so.get("status") if isinstance(so, dict) else getattr(so, "status", None)
        if docstatus != 1:
            raise frappe.ValidationError(f"Sales Order {so_name} is not submitted (docstatus={docstatus}).")
        if status in ("Cancelled", "Closed", "Completed"):
            raise frappe.ValidationError(f"Sales Order {so_name} is in closed/completed status ({status}).")

        # 2. Lock both serials in deterministic order (avoids deadlocks)
        sorted_serials = sorted([old_serial_no, new_serial_no])
        locked_serials = frappe.db.sql("""
            SELECT name, status, warehouse, department, reserved_sales_order, to_make, item_code, return_reason, is_replace
            FROM `tabSerial No`
            WHERE name IN (%s, %s)
            ORDER BY name ASC
            FOR UPDATE
        """, tuple(sorted_serials), as_dict=True)

        sn_map = {s["name"]: s for s in locked_serials}
        if old_serial_no not in sn_map or new_serial_no not in sn_map:
            missing = [s for s in (old_serial_no, new_serial_no) if s not in sn_map]
            raise frappe.ValidationError(f"Serial(s) not found in database: {missing}")

        old_sn = sn_map[old_serial_no]
        new_sn = sn_map[new_serial_no]

        # 3. Check idempotency: already swapped?
        if new_sn["reserved_sales_order"] == so_name and old_sn["reserved_sales_order"] != so_name:
            frappe.db.rollback()
            return {
                "success": True,
                "status": "already_swapped",
                "message": f"Order {so_name} is already reserved to {new_serial_no}."
            }

        # 4. Validate old serial: must currently be reserved to this SO
        if old_sn["reserved_sales_order"] != so_name:
            raise frappe.ValidationError(
                f"Old serial {old_serial_no} is currently reserved to '{old_sn['reserved_sales_order']}', not {so_name}."
            )

        # 4b. Validate old serial: cannot be swapped if it is a customer return unit
        return_causes = ("Repair", "Replace", "RTO Customer", "RTO Delivery Partner")
        if old_sn.get("return_reason") in return_causes or any(f"- {c}" in (old_sn.get("order_source") or "") for c in return_causes):
            reason_label = old_sn.get("return_reason") if old_sn.get("return_reason") in return_causes else "Repair"
            raise frappe.ValidationError(
                f"Cannot swap reservation on {so_name}: Serial {old_serial_no} is a customer unit returned for {reason_label}."
            )

        # 5. Validate new serial: must be unreserved and active
        if new_sn["reserved_sales_order"] and new_sn["reserved_sales_order"] != so_name:
            raise frappe.ValidationError(
                f"New serial {new_serial_no} is already reserved to '{new_sn['reserved_sales_order']}'."
            )

        if new_sn["status"] != "Active":
            raise frappe.ValidationError(
                f"New serial {new_serial_no} is not Active (status='{new_sn['status']}')."
            )

        if new_sn.get("is_replace") == 1:
            raise frappe.ValidationError(f"New serial {new_serial_no} is flagged for replacement (is_replace=1).")

        if new_sn.get("return_reason") in ("Repair", "Replace", "RTO Customer", "RTO Delivery Partner"):
            raise frappe.ValidationError(
                f"New serial {new_serial_no} has active return reason: {new_sn['return_reason']}"
            )

        # Verify no open draft stock entries for new serial
        open_draft_entries = frappe.db.sql("""
            SELECT se.name
            FROM `tabStock Entry Detail` sed
            JOIN `tabStock Entry` se ON se.name = sed.parent
            WHERE sed.serial_no LIKE %s AND se.docstatus = 0
            LIMIT 1
        """, (f"%{new_serial_no}%",))
        if open_draft_entries:
            raise frappe.ValidationError(
                f"New serial {new_serial_no} is locked in draft Stock Entry {open_draft_entries[0][0]}."
            )

        # Target item code
        final_to_make = target_item_code or new_sn.get("to_make") or old_sn.get("to_make") or new_sn.get("item_code")

        now_str = now_datetime().strftime("%Y-%m-%d %H:%M:%S")

        # 6. Apply atomic updates with strict rowcount check
        # Reserve new serial
        frappe.db.sql("""
            UPDATE `tabSerial No`
            SET reserved_sales_order = %s,
                to_make = %s,
                order_source = %s,
                remarks = %s,
                modified = %s
            WHERE name = %s
              AND (reserved_sales_order IS NULL OR reserved_sales_order = '' OR reserved_sales_order = %s)
        """, (
            so_name,
            final_to_make,
            get_effective_order_source(so_name, so.get("sale_type")),
            f"Allocated: Swapped to ready stock for Sales Order {so_name} ({reason})",
            now_str,
            new_serial_no,
            so_name
        ))
        if getattr(frappe.db, "_cursor", None) and frappe.db._cursor.rowcount <= 0:
            raise frappe.ValidationError(f"Failed to reserve {new_serial_no}: row was modified concurrently.")

        # Release old serial (preserve to_make so upstream production requirement remains intact)
        frappe.db.sql("""
            UPDATE `tabSerial No`
            SET reserved_sales_order = NULL,
                order_source = NULL,
                remarks = %s,
                modified = %s
            WHERE name = %s
              AND reserved_sales_order = %s
        """, (
            f"Released from {so_name} (Upgraded to {new_serial_no} on {now_str})",
            now_str,
            old_serial_no,
            so_name
        ))
        if getattr(frappe.db, "_cursor", None) and frappe.db._cursor.rowcount <= 0:
            raise frappe.ValidationError(f"Failed to release {old_serial_no}: row was modified concurrently.")

        # 7. Audit log comments
        def _add_comment(ref_dt, ref_name, content):
            c = frappe.new_doc("Comment")
            c.comment_type = "Comment"
            c.reference_doctype = ref_dt
            c.reference_name = ref_name
            c.content = content
            c.insert(ignore_permissions=True)

        _add_comment(
            "Sales Order", so_name,
            f"Serial Reservation Swapped by {operator}: Replaced {old_serial_no} (WIP) with {new_serial_no} (Ready Stock). Reason: {reason}."
        )
        _add_comment(
            "Serial No", old_serial_no,
            f"Released reservation for {so_name} by {operator}. Order upgraded to ready unit {new_serial_no}."
        )
        _add_comment(
            "Serial No", new_serial_no,
            f"Reserved for {so_name} by {operator}. Upgraded from WIP unit {old_serial_no}."
        )

        frappe.db.commit()

        logger.info(f"[SWAP_SUCCESS] SO: {so_name}, Old: {old_serial_no}, New: {new_serial_no}, By: {operator}")
        return {
            "success": True,
            "status": "swapped",
            "so_name": so_name,
            "old_serial_no": old_serial_no,
            "new_serial_no": new_serial_no,
            "message": f"Successfully swapped reservation on {so_name} to {new_serial_no}."
        }

    except Exception as e:
        frappe.db.rollback()
        logger.error(f"[SWAP_FAILED] SO: {so_name}, Old: {old_serial_no}, New: {new_serial_no}, Error: {str(e)}")
        raise


# ==============================================================================
# 2. PURE, READ-ONLY ETA COMPUTATION
# ==============================================================================

def compute_pure_sales_order_eta(so_name):
    """
    Compute ETA for a Sales Order without side-effect reservations or commits.
    Returns: (calc_delivery_date, eta_days, reason_text)
    """
    so = frappe.get_doc("Sales Order", so_name)
    today = getdate(nowdate())

    # Get reserved serials for this order
    reserved_serials = frappe.db.sql("""
        SELECT sn.name, sn.item_code, sn.to_make, sn.warehouse, dp.name as department, dp.department_sequence, dp.department_sla, dp.sla
        FROM `tabSerial No` sn
        LEFT JOIN `tabWarehouse` w ON w.name = sn.warehouse
        LEFT JOIN `tabDepartment` dp ON dp.name = w.department
        WHERE sn.reserved_sales_order = %s AND sn.status = 'Active'
    """, (so_name,), as_dict=True)

    if not reserved_serials:
        # Check unreserved items pending in order
        return add_days(today, 15), 15, "Pending allocation (15-day default SLA)"
        return add_working_days(today, 45), 45, "Pending allocation (45-day default SLA)"

    max_wip_days = 0
    reasons = []

    for sn in reserved_serials:
        dept_name = sn.get("department") or "Unknown"
        dept_seq = int(sn.get("department_sequence") or 0)
        sla_val = int(sn.get("sla") or sn.get("department_sla") or 1)

        if dept_seq >= 20 or "packing & dispatch" in dept_name.lower():
            # Ready stock in Packing & Dispatch requires 1 day for dispatch packaging
            wip_days = 1
            reasons.append(f"{sn['name']}: Ready in {dept_name} (1 day dispatch SLA)")
        else:
            # Accumulate SLA from this department sequence up to sequence 20
            depts_ahead = frappe.db.sql("""
                SELECT sla, department_sla FROM `tabDepartment`
                WHERE department_sequence >= %s AND department_sequence < 20
            """, (dept_seq,), as_dict=True)
            wip_days = sum(int(d.get("sla") or d.get("department_sla") or 1) for d in depts_ahead) + 1
            reasons.append(f"{sn['name']}: In {dept_name} (Estimated {wip_days} days to dispatch)")

        if wip_days > max_wip_days:
            max_wip_days = wip_days

    calc_delivery_date = add_days(today, max_wip_days)
    calc_delivery_date = add_working_days(today, max_wip_days)
    reason_summary = " | ".join(reasons)
    return calc_delivery_date, max_wip_days, reason_summary


# ==============================================================================
# 3. CONTROLLED RESERVATION UPGRADES (ORDER-PRIORITY RESPECTING)
# ==============================================================================

def upgrade_order_reservations(target_item_code=None, dry_run=False, so_name=None):
    """
    Scan open orders holding upstream reservations and upgrade them to available stock
    in higher departments (prioritizing Packing & Dispatch and departments closest to dispatch).

    Rules:
    - Orders are evaluated strictly by `committed_delivery_date ASC, creation ASC`.
    - Earliest customer promises receive first claim on downstream/ready stock.
    - Swaps are executed via `swap_order_reservation()`.
    - Supports Condition 1 (Exact), Condition 2 (Shopify Variant), Condition 3 (Model + CPU).

    Pass `so_name` to scope the scan to a single Sales Order — used to actively
    trigger an immediate reallocation attempt for one order (e.g. when its
    estimated/committed delivery dates have drifted) instead of waiting for the
    next full hourly pass over every open order.

    A reservation is only eligible for upgrade once it's been stable 24h+
    (sn.modified), so a unit briefly dipping out of Packing & Dispatch for
    routine QC doesn't get endlessly re-swapped to fresh ready stock daily.
    """
    from collections import defaultdict
    from nj_features.nj_features.doctype.nj_production_planning.nj_production_planning import (
        _cfg_tuple_from_item,
        _get_equivalent_parent_models,
        _get_shopify_variant_id,
        _get_variant_bundle_item_codes,
    )
    from nj_features.overrides.sales_order import compute_sales_order_delivery_date

    # 1. Pre-fetch draft stock entry serials in a single query
    draft_serials = set()
    draft_rows = frappe.db.sql("""
        SELECT sed.serial_no FROM `tabStock Entry Detail` sed
        JOIN `tabStock Entry` se ON se.name = sed.parent
        WHERE se.docstatus = 0 AND sed.serial_no IS NOT NULL AND sed.serial_no != ''
    """)
    for r in draft_rows:
        for s in (r[0] or "").split("\n"):
            cleaned = s.strip()
            if cleaned:
                draft_serials.add(cleaned)

    # 2. Pre-fetch all available unreserved stock across all departments (sequence > 0)
    pnd_rows = frappe.db.sql("""
        SELECT sn.name, sn.item_code, sn.to_make, sn.warehouse, dp.name as department, dp.department_sequence
        FROM `tabSerial No` sn
        JOIN `tabWarehouse` w ON w.name = sn.warehouse
        JOIN `tabDepartment` dp ON dp.name = w.department
        WHERE sn.status = 'Active'
          AND (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '')
          AND (sn.return_reason IS NULL OR sn.return_reason = '')
          AND sn.is_replace = 0
          AND dp.department_sequence > 0
          AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
        ORDER BY dp.department_sequence DESC, sn.creation ASC
    """, as_dict=True)

    available_cands = [r for r in pnd_rows if r["name"] not in draft_serials]

    # Pre-index candidates by exact sku, variant, and model+cpu
    exact_index = defaultdict(list)
    model_cpu_index = defaultdict(list)

    for cand in available_cands:
        exact_index[cand["item_code"]].append(cand)
        if cand.get("to_make"):
            exact_index[cand["to_make"]].append(cand)

        cfg = _cfg_tuple_from_item(cand["item_code"])
        if cfg:
            model_cpu_index[(cfg[0], cfg[1])].append(cand)

    # 3. Find open orders with reservations in sequence < 20 (WITHOUT joining soi to prevent duplicate rows)
    item_filter = "AND (sn.item_code = %s OR sn.to_make = %s)" if target_item_code else ""
    params = [target_item_code, target_item_code] if target_item_code else []

    if so_name:
        item_filter += " AND so.name = %s"
        params.append(so_name)

    query = f"""
        SELECT so.name as so_name, so.committed_delivery_date, so.delivery_date, so.creation,
               sn.name as old_serial_no, sn.item_code, sn.to_make, sn.warehouse, dp.name as current_dept,
               IFNULL(dp.department_sequence, 0) as current_seq
        FROM `tabSales Order` so
        JOIN `tabSerial No` sn ON sn.reserved_sales_order = so.name
        LEFT JOIN `tabWarehouse` w ON w.name = sn.warehouse
        LEFT JOIN `tabDepartment` dp ON dp.name = w.department
        WHERE so.docstatus = 1
          AND so.status IN ('To Deliver', 'To Deliver and Bill')
          AND sn.status = 'Active'
          AND IFNULL(dp.department_sequence, 0) < 20
          AND sn.modified <= DATE_SUB(DATE_ADD(NOW(), INTERVAL 330 MINUTE), INTERVAL 24 HOUR)
          AND (sn.return_reason IS NULL OR sn.return_reason = '' OR sn.return_reason NOT IN ('Repair', 'Replace', 'RTO Customer', 'RTO Delivery Partner'))
          AND (sn.order_source IS NULL OR (
              sn.order_source NOT LIKE '%%- Repair%%'
              AND sn.order_source NOT LIKE '%%- Replace%%'
              AND sn.order_source NOT LIKE '%%- RTO Customer%%'
              AND sn.order_source NOT LIKE '%%- RTO Delivery Partner%%'
              AND sn.order_source NOT LIKE '%%- Refund%%'
          ))
          AND so.name NOT IN (
              SELECT DISTINCT dni.against_sales_order
              FROM `tabDelivery Note Item` dni
              JOIN `tabDelivery Note` dn ON dn.name = dni.parent
              WHERE dn.docstatus = 1 AND dn.is_return = 1 AND dn.cause_of_return IN ('Repair', 'Replace', 'RTO Customer', 'RTO Delivery Partner', 'Refund')
                AND dni.against_sales_order IS NOT NULL AND dni.against_sales_order != ''
          )
          {REFUND_EXCLUSION_SQL}
          {item_filter}
        ORDER BY IFNULL(so.committed_delivery_date, so.delivery_date) ASC, so.creation ASC
    """
    candidate_orders = frappe.db.sql(query, tuple(params), as_dict=True)

    upgrades_executed = []
    claimed_serials = set()
    bundle_cache = {}
    variant_cache = {}
    cfg_cache = {}

    for order_row in candidate_orders:
        so_name = order_row["so_name"]
        old_sn = order_row["old_serial_no"]
        curr_seq = int(order_row["current_seq"] or 0)
        target_sku = order_row["to_make"] or order_row["item_code"]

        if target_sku not in bundle_cache:
            bundle_child = frappe.db.sql("""
                SELECT item_code FROM `tabProduct Bundle Item` WHERE parent = %s
            """, target_sku, as_dict=True)
            if bundle_child:
                bundle_cache[target_sku] = bundle_child[0]["item_code"]
            else:
                pi = frappe.db.sql("""
                    SELECT item_code FROM `tabPacked Item` WHERE parent = %s
                """, so_name, as_dict=True)
                bundle_cache[target_sku] = pi[0]["item_code"] if pi else target_sku
        real_target = bundle_cache[target_sku]

        # Pre-compute model+CPU equivalence once per target. Used both to validate
        # to_make-based "exact" matches below (a candidate's to_make may have been
        # set incorrectly by an earlier allocation pass, so it must be re-checked
        # against the candidate's own physical spec) and for Condition 3.
        if real_target not in cfg_cache:
            target_cfg = _cfg_tuple_from_item(real_target)
            target_tmpl, target_proc = (target_cfg[0], target_cfg[1]) if target_cfg else (None, None)
            equiv_tmpls = _get_equivalent_parent_models(target_tmpl) if target_tmpl else set()
            cfg_cache[real_target] = (target_tmpl, target_proc, equiv_tmpls)
        else:
            target_tmpl, target_proc, equiv_tmpls = cfg_cache[real_target]

        # Scan for best candidate with higher department sequence
        cand_found = None
        match_cond = None

        # 1. Exact Match in any higher department
        for cand in exact_index.get(real_target, []):
            if cand["name"] in claimed_serials or cand["department_sequence"] <= curr_seq:
                continue
            if cand["item_code"] == real_target:
                cand_found = cand
                match_cond = f"C1 (Exact Match in {cand['department']} seq {cand['department_sequence']})"
                break
            # Matched only via to_make (candidate's own item_code differs) —
            # don't trust to_make blindly, re-verify it's genuinely the same
            # model+CPU family as the target before accepting it.
            cand_cfg = _cfg_tuple_from_item(cand["item_code"])
            if cand_cfg and target_proc and cand_cfg[1] == target_proc and cand_cfg[0] in equiv_tmpls:
                cand_found = cand
                match_cond = f"C1 (WIP to_make match, verified in {cand['department']} seq {cand['department_sequence']})"
                break

        # 2. Shopify Variant match in any higher department
        if not cand_found:
            if real_target not in variant_cache:
                v_id = _get_shopify_variant_id(real_target)
                v_codes = set(_get_variant_bundle_item_codes(v_id)) - {real_target} if v_id else set()
                variant_cache[real_target] = v_codes
            else:
                v_codes = variant_cache[real_target]

            for v_code in v_codes:
                for cand in exact_index.get(v_code, []):
                    if cand["name"] not in claimed_serials and cand["department_sequence"] > curr_seq:
                        cand_found = cand
                        match_cond = f"C2 (Shopify Variant in {cand['department']} seq {cand['department_sequence']})"
                        break
                if cand_found:
                    break

        # 3. Model + CPU match in any higher department
        if not cand_found:
            if target_proc and equiv_tmpls:
                for eq_tmpl in equiv_tmpls:
                    for cand in model_cpu_index.get((eq_tmpl, target_proc), []):
                        if cand["name"] not in claimed_serials and cand["department_sequence"] > curr_seq:
                            cand_found = cand
                            match_cond = f"C3 (Model {eq_tmpl} + CPU {target_proc} in {cand['department']} seq {cand['department_sequence']})"
                            break
                    if cand_found:
                        break

        if not cand_found:
            continue

        new_sn = cand_found["name"]
        claimed_serials.add(new_sn)

        if dry_run:
            upgrades_executed.append({
                "so_name": so_name,
                "target_sku": real_target,
                "old_serial": old_sn,
                "new_serial": new_sn,
                "new_dept": cand_found["department"],
                "new_seq": cand_found["department_sequence"],
                "match_cond": match_cond,
                "status": "dry_run"
            })
            continue

        try:
            res = swap_order_reservation(
                so_name=so_name,
                old_serial_no=old_sn,
                new_serial_no=new_sn,
                target_item_code=real_target,
                reason=f"Automated Order-Priority Upgrade: {match_cond}"
            )
            # Recalculate ETA and update child table
            orig_committed = frappe.db.get_value("Sales Order", so_name, "committed_delivery_date")
            eta_res = compute_sales_order_delivery_date(so_name, return_reason=True)
            if eta_res:
                deliv_date = eta_res[0] if isinstance(eta_res, (list, tuple)) else eta_res
                upd = {
                    "estimated_delivery_date": deliv_date
                }
                if orig_committed:
                    upd["committed_delivery_date"] = orig_committed
                frappe.db.set_value("Sales Order", so_name, upd, update_modified=False)
            frappe.db.commit()
            upgrades_executed.append(res)
        except Exception as e:
            logger.warning(f"Failed to auto-upgrade {so_name}: {e}")

    return upgrades_executed


# ==============================================================================
# 4. CANONICAL RESERVED-SERIAL COUNT (single source of truth)
# ==============================================================================
# THE RULE: a reservation is a reservation regardless of where the machine is
# standing. Any query answering "how many machines does this order already
# hold?" must be blind to location.
#
# This was written out by hand six times across sales_order.py and
# nj_production_planning.py, and every copy filtered the count by
# `department_sequence != 0` and `warehouse_type != 'Employee Personal
# Warehouse'`, and reached `tabSerial No` through an INNER JOIN on Warehouse.
# Those filters are correct in a SEARCH pool -- you should not grab new stock
# out of Asset or a technician's bench. They are wrong in a COUNT. A machine
# already reserved to an order that moved into Asset - NJ (department_sequence
# = 0) or into an Employee Personal Warehouse counted as zero, so the allocator
# issued the order a SECOND machine while the first stayed reserved and
# invisible. `trim_over_allocated_serials` carried the same filters, so it never
# saw the duplicate it exists to remove; all three audit tools carried them too,
# so the reports used to hunt this reported clean.
#
# New code counting reservations calls this. It does not hand-write the query.
# `tests/test_reservation_count_invariants.py` fails the build if a counting
# query reintroduces a location filter -- it needs no site or database, so run
# it before any restart shipping allocator changes:
#     cd apps/nj_features && python3 -m unittest tests.test_reservation_count_invariants

# The key a reserved serial is counted against: where it is GOING (to_make),
# falling back to what it currently is. Must stay identical to the key the
# production planner and the Shopify quantity query group by.
RESERVED_COUNT_ITEM_KEY_SQL = "COALESCE(NULLIF(sn.to_make, ''), sn.item_code)"

RESERVED_SERIAL_COUNT_SQL = f"""
    SELECT COUNT(*)
    FROM `tabSerial No` sn
    WHERE sn.reserved_sales_order = %s
      AND {RESERVED_COUNT_ITEM_KEY_SQL} = %s
      AND sn.status = 'Active'
"""


def get_reserved_serial_count(so_name, item_code):
    """How many Active serials are reserved to this order for this destination SKU.

    Location-blind by design -- see the rule above. Never add a warehouse or
    department condition here; put it in the search pool instead.
    """
    if not so_name or not item_code:
        return 0
    return frappe.db.sql(RESERVED_SERIAL_COUNT_SQL, (so_name, item_code))[0][0] or 0
