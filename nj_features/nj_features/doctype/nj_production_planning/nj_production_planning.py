# nj_planning/plan_all.py

import math
import re
import frappe
import random
import logging
import functools
from frappe import _
from frappe.utils import add_days, flt
from typing import Dict, List, Optional, Union

from frappe.utils import flt
from typing import Dict, List, Optional, Union, Set
from frappe.model.document import Document
from datetime import timedelta
from collections import defaultdict, Counter
from itertools import product

# -------------------------
# Logger setup
# -------------------------
logger = frappe.logger("new_Production_planning", allow_site=True, file_count=5)



def _safe_repr(obj, maxlen: int = 4000):
    try:
        s = repr(obj)
    except Exception:
        try:
            s = str(obj)
        except Exception:
            s = f"<unreprable {type(obj).__name__}>"
    if s is None:
        s = "None"
    if len(s) > maxlen:
        return s[:maxlen] + "... <truncated>"
    return s


def log_io(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # Log function inputs
        logger.debug(f"Calling function {fn.__name__} with args: {args} and kwargs: {kwargs}")
        try:
            result = fn(*args, **kwargs)
            return result
        except Exception as e:
            logger.exception("ERROR %s: %s", fn.__name__, e)
            raise

    return wrapper


class NJProductionPlanning(Document):
    pass


# =========================
# Tunables / Constants
# =========================
SELLABLE_ITEM_GROUPS = {"Laptops", "Chromebooks", "Chromeboxes", "MacBooks"}

# Take only the last 15 days for sales rate calc
RECENCY_WINDOW_DAYS = 15
RECENCY_MAX_WEIGHT = 30

REQUIRE_SHOPIFY_IDS_FOR_SELLABLE = True

PROCESSOR_ATTR = "Processor Type1"
RAM_ATTR = "RAM Capacity"
STORAGE_ATTR = "Storage Capacity"

ALLOWED_ITEM_MODELS = set()

# Control whether planner writes to Serial No.to_make
UPDATE_SERIAL_TO_MAKE = True  # set to True if you really want to update Serial No in this run

# Control whether planner writes to Serial No.reserved_sales_order
UPDATE_SERIAL_RESERVED_SO = True


# =========================
# Global caches
# =========================
_ITEM_CORE: Dict[str, Dict] = {}
_ITEM_ATTRS: Dict[str, Dict] = {}
_ITEM_KEYS: Dict[str, Dict] = {}
_MODEL_TO_SELLABLE_ITEMS: Dict[tuple, List[str]] = defaultdict(list)
_SELLABLE_ITEM_CODES: Set[str] = set()

# =========================
# Part allocation global state (virtual stock)
# =========================
_PART_VIRTUAL_STOCK: Dict[str, float] = {}       # item_code -> physical stock in Stores - NJ (virtual snapshot)
_PART_PLANNED_ALLOCATION: Dict[str, float] = {}  # item_code -> qty already virtually allocated in this run
_DEPT_ALLOCATE_PARTS: Dict[str, bool] = {}       # department_name -> allocate_parts flag
_SERIAL_TO_MR_ITEMS: Dict[str, List[Dict]] = defaultdict(list)


# =========================
# Helpers
# =========================
@log_io
def _update_serial_to_make(serial_no: str, item_code_to_make: str) -> None:
    """Update Serial No.to_make (lightweight db write)."""
    if not UPDATE_SERIAL_TO_MAKE:
        return
    try:
        frappe.db.set_value(
            "Serial No",
            serial_no,
            "to_make",
            item_code_to_make,
            update_modified=False,
        )
    except Exception as e:
        logger.warning("Could not update Serial No.to_make for %s: %s", serial_no, e)


@log_io
def _update_serial_reserved_sales_order(serial_no: str, sales_order_no: Optional[str]) -> None:
    """Update Serial No.reserved_sales_order (lightweight db write)."""
    if not UPDATE_SERIAL_RESERVED_SO:
        return

    so_val = (sales_order_no or "").strip()
    try:
        frappe.db.set_value(
            "Serial No",
            serial_no,
            "reserved_sales_order",
            so_val if so_val else None,
            update_modified=False,
        )
    except Exception as e:
        logger.warning("Could not update Serial No.reserved_sales_order for %s: %s", serial_no, e)


def _round_half_up(value) -> int:
    """Business rounding: .5 always rounds up."""
    return int(math.floor(float(value or 0) + 0.5))


# =========================
# Helpers for ordering serials
# =========================
@log_io
def _oldest_first(lst: List[Dict]) -> List[Dict]:
    """
    Age-aware sort:
    - prefer items with higher age_days (older first)
    - fallback to purchase_date
    - fallback to creation
    """

    def _key(s):
        if s.get("age_days") is not None:
            return (-int(s.get("age_days") or 0), s.get("purchase_date") or s.get("creation") or "")
        return (0, s.get("purchase_date") or s.get("creation") or "")

    return sorted(lst, key=_key)


# -------------------------
# Processor-lock helpers
# -------------------------
def _serial_cfg(serial: Dict) -> tuple:
    """
    Extract (template, proc, ram, sto) from serial['forward_key_config'].
    """
    k = serial.get("forward_key_config")
    if not k or k[0] != "CONFIG":
        return (None, None, None, None)
    _, template, proc, ram, sto = k
    return (template, proc, ram, sto)


def _same_config(serial: Dict, target_cfg: tuple) -> bool:
    """
    target_cfg = (template, proc, ram, sto)
    """
    st, sp, sr, ss = _serial_cfg(serial)
    tt, tp, tr, ts = target_cfg
    return (st == tt and sp == tp and sr == tr and ss == ts)


def _same_storage_diff_ram(serial: Dict, target_cfg: tuple) -> bool:
    """
    Same template + SAME processor + SAME storage, only RAM differs.
    """
    st, sp, sr, ss = _serial_cfg(serial)
    tt, tp, tr, ts = target_cfg
    return (st == tt and sp == tp and ss == ts and sr != tr)


@log_io
def _cfg_tuple_from_item(item_code: str) -> tuple:
    """
    Return (template, processor, ram, storage) so we NEVER cross processor.
    """
    if item_code not in _ITEM_KEYS:
        _prime_item_cache([item_code])
    _, template, proc, ram, sto = _ITEM_KEYS[item_code]["config_key"]
    return (template, proc, ram, sto)


# =========================
# Forward inventory helper
# =========================
@log_io
def _get_forward_inventory_excluding_current_dept(
    inward_serials_per_dept: Dict[str, List[Dict]],
    current_department: str,
    forward_keys,
    forward_grain: str,
):
    """
    Build forward inventory using serials from all departments
    EXCEPT the current department.
    """
    other_serials = []

    for dept_name, serial_rows in inward_serials_per_dept.items():
        if dept_name == current_department:
            continue

        for sn in serial_rows:
            other_serials.append(_enrich_serial_from_attrs(sn))

    return _estimate_forward_inventory(forward_keys, other_serials, forward_grain)


# =========================
# Public API (batch run)
# =========================
@frappe.whitelist()
@log_io
def nj_run_unified_production_plan(planning_horizon_days: int = 30, **kwargs) -> Dict:
    # return {"message": "Unified production plan ran successfully", "status": "success"}
    print("Running unified production plan...=============")

    # -------------------------------------------------------
    # CLEANUP: Clear stale reserved_sales_order on Serial Nos
    # where the linked Sales Order is Closed/Cancelled/Completed.
    # This prevents serials from being permanently invisible to
    # the planner after their SO closes without clearing the field.
    # -------------------------------------------------------
    stale_cleared = frappe.db.sql("""
        UPDATE `tabSerial No` sn
        INNER JOIN `tabSales Order` so ON so.name = sn.reserved_sales_order
        SET sn.reserved_sales_order = NULL
        WHERE so.status IN ('Closed', 'Cancelled', 'Completed')
          AND sn.reserved_sales_order IS NOT NULL
          AND sn.reserved_sales_order != ''
    """)
    frappe.db.commit()
    logger.debug("[CLEANUP] Cleared stale reserved_sales_order for serials linked to Closed/Cancelled/Completed SOs.")

    depts = frappe.get_all(
        "Department",
        filters=[["sla", ">", 0], ["run_production_planning", "=", 1]],
        fields=[
            "name",
            "department_sequence",
            "sla",
            "allow_reconfig",
            "inwarded_model",
            "forwarded_model",
            "inwarded_config",
            "forwarded_config",
            "run_production_planning",
            "allocate_parts",
        ],
        order_by="department_sequence asc, name asc",
    )
    if not depts:
        frappe.throw("No departments with SLA found.")

    depts_by_seq: Dict[int, List[Dict]] = defaultdict(list)
    for d in depts:
        depts_by_seq[d["department_sequence"]].append(d)

    sequences = sorted(depts_by_seq.keys())
    max_seq = max(sequences)

    global _DEPT_ALLOCATE_PARTS, _PART_VIRTUAL_STOCK, _PART_PLANNED_ALLOCATION
    _DEPT_ALLOCATE_PARTS = {d["name"]: bool(d.get("allocate_parts")) for d in depts}

    if any(_DEPT_ALLOCATE_PARTS.values()):
        _PART_VIRTUAL_STOCK, _PART_PLANNED_ALLOCATION = _build_initial_part_stock()
    else:
        _PART_VIRTUAL_STOCK = {}
        _PART_PLANNED_ALLOCATION = {}

    cum_sla = _build_cumulative_sla_multi(depts_by_seq, sequences)

    forward_grain_per_seq: Dict[int, str] = {}
    for s in sequences:
        forward_grain_per_seq[s] = "config" if any(bool(d.get("forwarded_config")) for d in depts_by_seq[s]) else "model"

    today = frappe.utils.getdate(frappe.utils.nowdate())
    horizon_end = today + timedelta(days=int(planning_horizon_days or 30))
    pending_orders = _get_pending_sales_orders(horizon_end=horizon_end)

    _prime_item_cache([r["item_code"] for r in pending_orders])

    order_demand_by_seq = _allocate_orders_to_sequences_multi(
        pending_orders=pending_orders,
        sequences=sequences,
        cum_sla=cum_sla,
        today=today,
        forward_grain_per_seq=forward_grain_per_seq,
        max_seq=max_seq,
    )

    _SELLABLE_ITEM_CODES.clear()
    _MODEL_TO_SELLABLE_ITEMS.clear()
    sellable_items = _get_sellable_items()
    _prime_item_cache(list(_SELLABLE_ITEM_CODES))
    
    # Build reverse lookup map for O(1) matching
    for ic in _SELLABLE_ITEM_CODES:
        key = _ITEM_KEYS.get(ic, {}).get("model_key")
        if key:
            _MODEL_TO_SELLABLE_ITEMS[key].append(ic)

    sales_rate = _compute_recency_weighted_sales_rates_SO_union(sellable_items)
    if not sales_rate:
        logger.warning("No sales_rate computed.")

    random.seed(42)

    plan_date = frappe.utils.nowdate()
    now_stamp = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")

    plan_doc = frappe.new_doc("NJ Production Planning")
    plan_doc.plan_date = plan_date
    plan_doc.department = "All Departments"
    plan_doc.name = f"NJ Production Plan - {now_stamp}"
    plan_doc.flags.ignore_mandatory = True
    plan_doc.set("lines", [])

    desired_name = f"Unified-{plan_date}"
    try:
        plan_doc.name = desired_name
        plan_doc.set_new_name(desired_name)
    except Exception as e:
        logger.warning("Could not set custom unified name %s: %s", desired_name, e)

    forward_keys_per_seq: Dict[int, List] = {}
    for s in sequences:
        forward_grain = forward_grain_per_seq[s]
        forward_keys_per_seq[s] = _build_forward_keys(sellable_items, forward_grain, sales_rate)

    inward_serials_per_dept: Dict[str, List[Dict]] = {}
    all_serial_ids = []
    for s in sequences:
        for d in depts_by_seq[s]:
            dept_name = d["name"]
            dept_doc = frappe.get_doc("Department", dept_name)
            rows = _get_inward_serials_for_department(dept_doc)
            inward_serials_per_dept[dept_name] = rows
            all_serial_ids.extend([r["name"] for r in rows])
            logger.debug(f"has taken {len(rows)} serial no from the department {dept_name}")

    # Batch fetch all MR items for all serials to avoid N+1 queries
    _SERIAL_TO_MR_ITEMS.clear()
    if all_serial_ids:
        mr_rows = frappe.db.sql(
            """
            SELECT
                MRI.item_code,
                MRI.item_group,
                MRI.creation,
                MRI.parent AS material_request,
                MRI.serial_no,
                MRI.stock_qty,
                MRI.qty AS mr_qty
            FROM `tabMaterial Request Item` MRI
            INNER JOIN `tabMaterial Request` MR
                ON MR.name = MRI.parent
                AND MR.status = 'Pending'
                AND IFNULL(MR.post_order_status, '') != 'Completed'
                AND MR.docstatus = 1
            WHERE MRI.serial_no IN %(serial_list)s
                AND IFNULL(MRI.post_order_status, '') IN ('Not Completed', '')
                AND MRI.docstatus = 1
                AND MRI.item_group IS NOT NULL
            ORDER BY MRI.modified DESC
            """,
            {"serial_list": tuple(all_serial_ids)},
            as_dict=True,
        )
        for row in mr_rows:
            _SERIAL_TO_MR_ITEMS[row["serial_no"]].append(row)

    priority_per_dept: Dict[str, int] = defaultdict(lambda: 1)

    for s in sorted(sequences, reverse=True):
        seq_forward_grain = forward_grain_per_seq[s]
        forward_keys = forward_keys_per_seq[s]
        seq_order_queues = order_demand_by_seq[s]

        for dept in sorted(depts_by_seq[s], key=lambda x: x["name"]):
            dept_name = dept["name"]

            if not dept.get("run_production_planning"):
                continue

            # Log department execution
            logger.debug(f"running for this department: {dept_name}")

            allow_reconfig = bool(dept.get("allow_reconfig"))
            inward_grain = "config" if dept.get("inwarded_config") else "model"
            forward_grain = seq_forward_grain

            serial_rows = inward_serials_per_dept.get(dept_name, [])
            initial_serial_count = len(serial_rows)
            initial_serial_lookup = {sn['name']: sn for sn in serial_rows} # For warehouse info

            # -------------------------------------------------------
            # RESERVED SERIALS: Serials already committed to active SOs.
            # These bypass normal match/forecast logic. We add them
            # directly to plan lines with reason='Order'.
            # to_make item code = sn.to_make (set by previous plan run)
            # or fallback Product Bundle. Reserved SO is NOT cleared.
            # -------------------------------------------------------
            reserved_rows = _get_reserved_serials_for_department(dept_name)
            _today = frappe.utils.getdate(frappe.utils.nowdate())
            for res_row in reserved_rows:
                sn_id = res_row['name']
                wh = res_row['warehouse']

                # Validate Item Wizard
                if not res_row.get("item_wizard"):
                    plan_doc.append("missing_serial_nos", {
                        "serial_no": sn_id,
                        "current_department": dept_name,
                        "current_warehouse": wh,
                        "reason": "Reserved for SO - Item Wizard not found"
                    })
                    continue

                if res_row.get("part_list_status") != "Completed" or res_row.get("iw_docstatus") != 1:
                    reason = (
                        "Reserved for SO - Item Wizard not Completed"
                        if res_row.get("part_list_status") != "Completed"
                        else "Reserved for SO - Item Wizard not Submitted"
                    )
                    plan_doc.append("missing_serial_nos", {
                        "serial_no": sn_id,
                        "current_department": dept_name,
                        "current_warehouse": wh,
                        "reason": reason
                    })
                    continue

                # Determine item_code_to_make:
                # Use sn.to_make (set by previous plan run) or fallback PB
                item_code_to_make = res_row.get("to_make") or _get_fallback_pb_item_code(res_row["item_code"])
                if not item_code_to_make:
                    plan_doc.append("missing_serial_nos", {
                        "serial_no": sn_id,
                        "current_department": dept_name,
                        "current_warehouse": wh,
                        "reason": "Reserved for SO - Product Bundle not found"
                    })
                    continue

                # Compute age_days
                purchase_date = res_row.get("purchase_date")
                creation = res_row.get("creation")
                base_date = frappe.utils.getdate(purchase_date or creation or frappe.utils.nowdate())
                age_days = (_today - base_date).days if base_date else 0

                # Append directly to plan — do NOT clear reserved_sales_order
                _update_serial_to_make(sn_id, item_code_to_make)
                plan_doc.append(
                    "lines",
                    {
                        "serial_no": sn_id,
                        "current_warehouse": wh,
                        "current_department": dept_name,
                        "sales_rate": 1.0,
                        "doi": 0,
                        "sales_order_no": res_row["reserved_sales_order"],
                        "delivery_date": res_row.get("delivery_date"),
                        "item_code": item_code_to_make,
                        "reason": "Order",
                        "priority_rank": int(priority_per_dept[dept_name]),
                        "serial_age_days": age_days,
                        "allocate_parts": 1,
                    },
                )
                priority_per_dept[dept_name] += 1
                logger.debug(
                    f"[RESERVED] serial_no={sn_id}, so={res_row['reserved_sales_order']}, "
                    f"to_make={item_code_to_make}, dept={dept_name}"
                )


            # Pre-Planning Validation
            healthy_serials = []
            for row in serial_rows:
                sn_id = row['name']
                wh = row['warehouse']
                
                # 1. Check Item Wizard existence
                if not row.get("item_wizard"):
                    plan_doc.append("missing_serial_nos", {
                        "serial_no": sn_id,
                        "current_department": dept_name,
                        "current_warehouse": wh,
                        "reason": "Item Wizard not found"
                    })
                    continue
                
                # 2. Check Part List Status and Submission (Incomplete Wizard)
                if row.get("part_list_status") != "Completed" or row.get("iw_docstatus") != 1:
                    reason = "Item Wizard not Completed" if row.get("part_list_status") != "Completed" else "Item Wizard not Submitted"
                    plan_doc.append("missing_serial_nos", {
                        "serial_no": sn_id,
                        "current_department": dept_name,
                        "current_warehouse": wh,
                        "reason": reason
                    })
                    continue
                
                healthy_serials.append(row)

            # Enrich and check Product Bundle mapping
            serial_map = []
            for row in healthy_serials:
                enriched = _enrich_serial_from_attrs(row)
                
                # 3. Check Product Bundle mapping
                if not enriched.get("fallback_pb_item_code"):
                    plan_doc.append("missing_serial_nos", {
                        "serial_no": row['name'],
                        "current_department": dept_name,
                        "current_warehouse": row['warehouse'],
                        "reason": "Product Bundle not found"
                    })
                    continue
                
                serial_map.append(enriched)

            serials_before_match = {s['serial_no'] for s in serial_map}

            order_allocs, remaining_serials = _match_inventory_to_order_queues_for_sequence(
                seq=s,
                serial_map=serial_map,
                seq_order_queues=seq_order_queues,
                allow_reconfig=allow_reconfig,
                inward_grain=inward_grain,
                forward_grain=forward_grain,
                current_department=dept_name,
            )

            # Identify serials dropped due to parts in Match
            allocated_in_match = {a['serial_no'] for a in order_allocs}
            remaining_after_match = {r['serial_no'] for r in remaining_serials}
            dropped_in_match = serials_before_match - allocated_in_match - remaining_after_match
            for sn in dropped_in_match:
                info = initial_serial_lookup[sn]
                plan_doc.append("missing_serial_nos", {
                    "serial_no": sn,
                    "current_department": dept_name,
                    "current_warehouse": info['warehouse'],
                    "reason": "Part allocation failed (Order Match)"
                })
            
            serials_before_forecast = remaining_after_match

            fwd_inventory = _get_forward_inventory_excluding_current_dept(
                inward_serials_per_dept=inward_serials_per_dept,
                current_department=dept_name,
                forward_keys=forward_keys,
                forward_grain=forward_grain,
            )

            for alloc in order_allocs:
                k = alloc["forward_key"]
                fwd_inventory[k] = fwd_inventory.get(k, 0) + 1

            doi_snapshot = {
                k: (float(fwd_inventory.get(k, 0)) / max(1.0, float(sales_rate.get(k, 1.0))))
                for k in forward_keys
            }

            for alloc in order_allocs:
                k = alloc["forward_key"]
                rate_display = float(sales_rate.get(k, 1.0))
                doi_display = float(doi_snapshot.get(k, 0.0))
                _append_plan_row(
                    plan_doc,
                    serial_no=alloc["serial_no"],
                    current_warehouse=alloc["warehouse"],
                    current_department=dept_name,
                    sales_rate=rate_display,
                    doi=doi_display,
                    sales_order_number=alloc.get("order_name"),
                    delivery_date=alloc.get("required_by"),
                    item_code_to_make=alloc["target_item_code"],
                    reason="Order",
                    priority_rank=priority_per_dept[dept_name],
                    serial_age_days=alloc.get("age_days"),
                )
                priority_per_dept[dept_name] += 1

            forecast_allocs = _allocate_forecast_to_balance_doi(
                remaining_serials=remaining_serials,
                forward_grain=forward_grain,
                allow_reconfig=allow_reconfig,
                forward_keys=forward_keys,
                sales_rate=sales_rate,
                current_doi=doi_snapshot,
                current_department=dept_name,
            )

            for alloc in forecast_allocs:
                k = alloc["forward_key"]
                rate_display = float(sales_rate.get(k, 1.0))
                doi_display = float(alloc.get("doi", 0.0))
                _append_plan_row(
                    plan_doc,
                    serial_no=alloc["serial_no"],
                    current_warehouse=alloc["warehouse"],
                    current_department=dept_name,
                    sales_rate=rate_display,
                    doi=doi_display,
                    sales_order_number=None,
                    delivery_date=None,
                    item_code_to_make=alloc["target_item_code"],
                    reason="Forecast",
                    priority_rank=priority_per_dept[dept_name],
                    serial_age_days=alloc.get("age_days"),
                )
                priority_per_dept[dept_name] += 1

            # Identify serials dropped due to parts in Forecast or no demand
            allocated_in_forecast = {a['serial_no'] for a in forecast_allocs}
            remaining_after_forecast = {r['serial_no'] for r in remaining_serials}
            
            dropped_in_forecast = serials_before_forecast - allocated_in_forecast - remaining_after_forecast
            for sn in dropped_in_forecast:
                info = initial_serial_lookup[sn]
                plan_doc.append("missing_serial_nos", {
                    "serial_no": sn,
                    "current_department": dept_name,
                    "current_warehouse": info['warehouse'],
                    "reason": "Part allocation failed (Forecast)"
                })

            for sn in remaining_after_forecast:
                info = initial_serial_lookup[sn]
                plan_doc.append("missing_serial_nos", {
                    "serial_no": sn,
                    "current_department": dept_name,
                    "current_warehouse": info['warehouse'],
                    "reason": "No matching order or forecast demand found"
                })

            consumed_serial_nos = {a["serial_no"] for a in order_allocs + forecast_allocs}
            
            # Log serials skipped due to no demand
            for sn in remaining_serials:
                logger.debug(f"Skipping serial_no: {sn['serial_no']} - Reason: No matching order or forecast demand found.")

            inward_serials_per_dept[dept_name] = [
                sn for sn in inward_serials_per_dept[dept_name] if sn["name"] not in consumed_serial_nos
            ]

            # Print Department Summary
            added_count = len(consumed_serial_nos)
            skipped_count = initial_serial_count - added_count
            logger.debug(f"--- Department Summary for {dept_name} ---")
            logger.debug(f"Total serial numbers received: {initial_serial_count}")
            logger.debug(f"Total serial numbers added to plan: {added_count}")
            logger.debug(f"Total serial numbers skipped: {skipped_count}")
            logger.debug(f"-------------------------------------------")

    # =======================================================
    # RECONFIG PHASE: Rescue stale serials from downstream depts
    # =======================================================
    reconfig_aging_days = frappe.db.get_single_value(
        "NewJaisa Configuration", "reconfig_aging"
    ) or 0
    reconfig_aging_days = int(reconfig_aging_days)

    if reconfig_aging_days > 0:
        logger.debug(f"[RECONFIG_PHASE] Starting reconfig phase with aging threshold = {reconfig_aging_days} days")

        # Collect all serials already planned to avoid duplicates
        planned_sns = {row.serial_no for row in plan_doc.get("lines", [])}

        for s in sorted(sequences, reverse=True):
            seq_forward_grain = forward_grain_per_seq[s]
            forward_keys = forward_keys_per_seq[s]

            for dept in sorted(depts_by_seq[s], key=lambda x: x["name"]):
                dept_name = dept["name"]

                if not dept.get("run_production_planning"):
                    continue

                dept_doc = frappe.get_doc("Department", dept_name)

                # Read reconfig_department Table MultiSelect (child doctype: Department Multi Models)
                reconfig_dept_rows = dept_doc.get("reconfig_department", [])
                reconfig_dept_names = [r.department for r in reconfig_dept_rows if r.department]

                if not reconfig_dept_names:
                    continue

                logger.debug(
                    f"[RECONFIG] Department {dept_name} scanning reconfig departments: {reconfig_dept_names}"
                )

                # Refresh planned set (grows as we add reconfig rows)
                planned_sns = {row.serial_no for row in plan_doc.get("lines", [])}

                stale_serials = _get_reconfig_serials_for_departments(
                    department_names=reconfig_dept_names,
                    reconfig_aging_days=reconfig_aging_days,
                    already_planned_sns=planned_sns,
                )

                if not stale_serials:
                    logger.debug(f"[RECONFIG] No stale serials found for {dept_name}")
                    continue

                # Compute current DOI snapshot for reconfig allocation
                fwd_inventory_reconfig = _estimate_forward_inventory(
                    forward_keys, [], seq_forward_grain
                )
                # Include already-planned serials in DOI calculation
                for row in plan_doc.get("lines", []):
                    if row.item_code:
                        if row.item_code not in _ITEM_KEYS:
                            _prime_item_cache([row.item_code])
                        ik = _ITEM_KEYS.get(row.item_code, {})
                        fk = ik.get("config_key") if seq_forward_grain == "config" else ik.get("model_key")
                        if fk and fk in forward_keys:
                            fwd_inventory_reconfig[fk] = fwd_inventory_reconfig.get(fk, 0) + 1

                doi_snapshot_reconfig = {
                    k: (float(fwd_inventory_reconfig.get(k, 0)) / max(1.0, float(sales_rate.get(k, 1.0))))
                    for k in forward_keys
                }

                reconfig_allocs = _allocate_reconfig_serials(
                    stale_serials=stale_serials,
                    forward_keys=forward_keys,
                    sales_rate=sales_rate,
                    current_doi=doi_snapshot_reconfig,
                    current_department=dept_name,
                )

                for alloc in reconfig_allocs:
                    k = alloc["forward_key"]
                    rate_display = float(sales_rate.get(k, 1.0))
                    doi_display = float(alloc.get("doi", 0.0))
                    _append_plan_row(
                        plan_doc,
                        serial_no=alloc["serial_no"],
                        current_warehouse=alloc["warehouse"],
                        current_department=dept_name,
                        sales_rate=rate_display,
                        doi=doi_display,
                        sales_order_number=None,
                        delivery_date=None,
                        item_code_to_make=alloc["target_item_code"],
                        reason="Reconfig",
                        priority_rank=priority_per_dept[dept_name],
                        serial_age_days=alloc.get("dwell_days"),
                    )
                    priority_per_dept[dept_name] += 1

                # Log serials that failed part allocation during reconfig
                allocated_sns = {a["serial_no"] for a in reconfig_allocs}
                for serial in stale_serials:
                    if serial["serial_no"] not in allocated_sns:
                        plan_doc.append("missing_serial_nos", {
                            "serial_no": serial["serial_no"],
                            "current_department": serial.get("source_department", ""),
                            "current_warehouse": serial["warehouse"],
                            "reason": "Part allocation failed (Reconfig)" if _DEPT_ALLOCATE_PARTS.get(dept_name) else "No matching reconfig target found",
                        })

                logger.debug(
                    f"[RECONFIG_SUMMARY] Department {dept_name}: "
                    f"{len(stale_serials)} stale serials found, "
                    f"{len(reconfig_allocs)} allocated for reconfig"
                )
    else:
        logger.debug("[RECONFIG_PHASE] Skipped — reconfig_aging is 0 or not configured")

    plan_doc.save(ignore_permissions=True)
    total_rows = len(plan_doc.get("lines") or [])
    frappe.db.commit()

    return {
        "total_departments": 1,
        "total_rows": total_rows,
        "plans": [
            {
                "department": "All Departments",
                "plan_name": plan_doc.name,
                "title": getattr(plan_doc, "plan_title", plan_doc.name),
                "total_rows": total_rows,
            }
        ],
    }


# =========================
# SLA helpers
# =========================
@log_io
def _build_cumulative_sla_multi(depts_by_seq: Dict, sequences: List[int]) -> Dict:
    max_sla_per_seq = {}
    for s in sequences:
        max_sla_per_seq[s] = max(float(d.get("sla") or 0.0) for d in depts_by_seq[s]) if depts_by_seq[s] else 0.0
    cum_sla = {}
    for s in sorted(sequences):
        tail = sum(max_sla_per_seq[t] for t in sequences if t >= s)
        cum_sla[s] = tail
    return cum_sla


# -------------------------
# Pending Sales Orders
# -------------------------
@log_io
def _get_pending_sales_orders(horizon_end=None) -> List[Dict]:
    """
    Pending SO lines computed using Delivery Note Item quantities (SO vs DN).
    Expands Product Bundles into stock-item components (pbi.qty * soi.qty).

    No filtering on soi.delivery_date.
    """
    LOOKBACK_DAYS_B2C = 50
    LOOKBACK_DAYS_B2B = 100

    rows = frappe.db.sql(
        """
        SELECT
            so_data.sales_order                                   AS so_name,
            so_data.soi_name                                      AS soi_name,
            so_data.customer                                      AS customer,
            so_data.transaction_date                              AS transaction_date,
            so_data.delivery_date                                 AS delivery_date,

            so_data.item_code                                     AS item_code,
            so_data.pb_code                                       AS pb_code,
            so_data.item_group                                    AS item_group,

            so_data.qty                                           AS so_qty,
            IFNULL(dn_data.dn_qty, 0)                             AS dn_qty,

            LEAST(so_data.qty, IFNULL(dn_data.dn_qty, 0))         AS min_so_dn_qty,

            GREATEST(0, so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.dn_qty, 0)) - IFNULL(res_data.reserved_qty, 0))
                                                                AS qty_pending,

            CONCAT(COALESCE(it2.variant_of, it2.name), ' ', COALESCE(proc.attribute_value, ''))
                                                                AS variant_processor,

            SUM(GREATEST(0, so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.dn_qty, 0)) - IFNULL(res_data.reserved_qty, 0)))
                OVER (
                    PARTITION BY CONCAT(COALESCE(it2.variant_of, it2.name), ' ', COALESCE(proc.attribute_value, ''))
                )                                               AS total_pending_by_variant,

            SUM(GREATEST(0, so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.dn_qty, 0)) - IFNULL(res_data.reserved_qty, 0)))
                OVER (PARTITION BY so_data.pb_code)              AS total_pending_by_pb_code

        FROM (
            SELECT
                so.name                        AS sales_order,
                soi.name                       AS soi_name,
                so.customer                    AS customer,
                so.transaction_date            AS transaction_date,
                so.creation                    AS so_creation,
                soi.delivery_date              AS delivery_date,

                soi.item_code                  AS pb_code,

                CASE
                    WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                    ELSE pbi.item_code
                END                            AS item_code,

                CASE
                    WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_group
                    ELSE it_comp.item_group
                END                            AS item_group,

                CASE
                    WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.qty
                    ELSE (IFNULL(pbi.qty, 0) * soi.qty)
                END                            AS qty

            FROM `tabSales Order` so
            INNER JOIN `tabSales Order Item` soi
                ON soi.parent = so.name
            INNER JOIN `tabItem` it_so
                ON it_so.name = soi.item_code

            LEFT JOIN `tabProduct Bundle` pb
                ON pb.new_item_code = soi.item_code
            LEFT JOIN `tabProduct Bundle Item` pbi
                ON pbi.parent = pb.name
            LEFT JOIN `tabItem` it_comp
                ON it_comp.name = pbi.item_code

            WHERE
                so.status NOT IN ('Closed', 'Completed', 'Draft', 'Cancelled')
                AND so.docstatus = 1
                AND (
                    (so.sale_type IN ('NJ-Website-B2C', 'NJ-Direct-B2C') AND so.creation > CURDATE() - INTERVAL %(lookback_b2c)s DAY)
                    OR
                    (so.sale_type IN ('NJ-Website-B2B', 'NJ-Direct-B2B') AND so.creation > CURDATE() - INTERVAL %(lookback_b2b)s DAY)
                )

                AND soi.item_group IN ('Laptops','Chromebooks', 'MacBooks')
                AND so.customer != 'King Technologies'

                AND (
                    IFNULL(it_so.is_stock_item, 0) = 1
                    OR pbi.item_code IS NOT NULL
                )

                AND (
                    IFNULL(it_so.is_stock_item, 0) = 1
                    OR it_comp.item_group IN ('Laptops','Chromebooks', 'MacBooks')
                )
                AND IFNULL(it_so.disabled, 0) = 0
                AND (IFNULL(it_so.is_stock_item, 0) = 1 OR IFNULL(it_comp.disabled, 0) = 0)
        ) AS so_data

        LEFT JOIN (
            SELECT
                dni.against_sales_order       AS against_sales_order,
                dni.item_code                 AS item_code,
                SUM(dni.qty)                  AS dn_qty
            FROM `tabDelivery Note Item` dni
            WHERE
                dni.docstatus = 1
                AND dni.qty > 0
                AND dni.creation >= CURDATE() - INTERVAL %(lookback_max)s DAY
                AND dni.item_group IN ('Laptops', 'Chromebooks')
            GROUP BY dni.against_sales_order, dni.item_code
        ) AS dn_data
            ON so_data.sales_order = dn_data.against_sales_order
           AND so_data.item_code   = dn_data.item_code

        LEFT JOIN (
            SELECT
                reserved_sales_order    AS sales_order,
                COALESCE(NULLIF(to_make, ''), item_code) AS item_code,
                COUNT(*)                AS reserved_qty
            FROM `tabSerial No`
            WHERE
                reserved_sales_order IS NOT NULL
                AND reserved_sales_order != ''
                AND (status IS NULL OR status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
            GROUP BY reserved_sales_order, COALESCE(NULLIF(to_make, ''), item_code)
        ) AS res_data
            ON so_data.sales_order = res_data.sales_order
           AND so_data.item_code   = res_data.item_code

        LEFT JOIN `tabItem` it2
            ON it2.name = so_data.item_code

        LEFT JOIN (
            SELECT
                parent,
                MAX(attribute_value) AS attribute_value
            FROM `tabItem Variant Attribute`
            WHERE attribute LIKE '%%Processor%%'
            GROUP BY parent
        ) proc
            ON proc.parent = it2.name

        WHERE GREATEST(0, so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.dn_qty, 0)) - IFNULL(res_data.reserved_qty, 0)) > 0
        ORDER BY so_data.delivery_date ASC, so_data.so_creation ASC, so_data.sales_order, so_data.item_code
        """,
        {
            "lookback_b2c": LOOKBACK_DAYS_B2C,
            "lookback_b2b": LOOKBACK_DAYS_B2B,
            "lookback_max": max(LOOKBACK_DAYS_B2C, LOOKBACK_DAYS_B2B),
        },
        as_dict=True,
    )

    return rows

@log_io
def _allocate_orders_to_sequences_multi(
    pending_orders, sequences, cum_sla, today, forward_grain_per_seq, max_seq
):
    """
    UPDATED:
    - Build ONE shared order queue for ALL sequences (global pool).
    - Orders are queued at CONFIG grain (exact item requirement).
    - Every sequence receives the SAME dict reference, so consuming an order in any
      department/sequence removes it for everyone (prevents double-allocation).
    - Reverse loop order in nj_run_unified_production_plan ensures higher sequence depts pick first.
    """
    from collections import defaultdict

    # ✅ One shared pool across all sequences
    shared_queue = defaultdict(list)

    # Optional: unique id for debugging/tracing
    uid = 0

    for row in pending_orders:
        ic = row["item_code"]
        qty = int(math.ceil(row["qty_pending"]))

        # ✅ Always use CONFIG key for order fulfillment (orders are specific SKUs)
        key = _key_for_grain(ic, "config")

        base_ref = {
            "so_name": row["so_name"],
            "delivery_date": row.get("delivery_date"),
            "order_item_code": ic,
            "pb_code": row.get("pb_code"),
        }

        for _ in range(qty):
            uid += 1
            ref = dict(base_ref)
            ref["_uid"] = uid  # debug only
            shared_queue[key].append(ref)

    # ✅ Every sequence points to the same shared queue object
    demand_by_seq = {s: shared_queue for s in sequences}
    return demand_by_seq

# =========================
# Sellable portfolio & sales-rate
# =========================
@log_io
def _get_sellable_items() -> List[Dict]:
    global _SELLABLE_ITEM_CODES

    where_shopify = ""
    if REQUIRE_SHOPIFY_IDS_FOR_SELLABLE:
        where_shopify = """
            AND i.shopify_product_id IS NOT NULL
            AND i.shopify_product_id != ''
        """

    if ALLOWED_ITEM_MODELS:
        placeholders_list = list(tuple(ALLOWED_ITEM_MODELS))
        rows = frappe.db.sql(
            f"""
            SELECT DISTINCT pbi.item_code AS item_code
            FROM `tabItem` i
            INNER JOIN `tabProduct Bundle` pb ON i.name = pb.new_item_code
            INNER JOIN `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
            INNER JOIN `tabItem` ci ON pbi.item_code = ci.name
            WHERE
                1=1
                {where_shopify}
                AND i.item_model IN ({",".join(["%s"] * len(placeholders_list))})
                AND ci.item_group IN %s
                AND i.has_variants = 0
                AND i.disabled = 0
                AND ci.disabled = 0
                AND pb.disable = 0
            """,
            tuple(placeholders_list) + (tuple(SELLABLE_ITEM_GROUPS),),
            as_dict=True,
        )
    else:
        rows = frappe.db.sql(
            f"""
            SELECT DISTINCT pbi.item_code AS item_code
            FROM `tabItem` i
            INNER JOIN `tabProduct Bundle` pb ON i.name = pb.new_item_code
            INNER JOIN `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
            INNER JOIN `tabItem` ci ON pbi.item_code = ci.name
            WHERE
                1=1
                {where_shopify}
                AND ci.item_group IN %(igroups)s
                AND i.has_variants = 0
                AND i.disabled = 0
                AND ci.disabled = 0
                AND pb.disable = 0
            """,
            {"igroups": tuple(SELLABLE_ITEM_GROUPS)},
            as_dict=True,
        )

    sellable = [{"name": r["item_code"]} for r in (rows or [])]
    _SELLABLE_ITEM_CODES = {r["name"] for r in sellable}

    if not sellable:
        logger.warning("No sellable Product Bundle components found with current filters.")

    _prime_item_cache([r["name"] for r in sellable])
    return sellable



@log_io
def _compute_recency_weighted_sales_rates_SO_union(sellable_items: List[Dict]) -> Dict:
    """
    Compute recency-weighted sales rates over the last 15 days.
    Days with zero sales are ignored.
    If no non-zero-sales day exists for a key, fall back to 1.0.
    """
    rates: Dict = {}

    start_date = frappe.utils.getdate(
        frappe.utils.add_days(frappe.utils.nowdate(), -RECENCY_WINDOW_DAYS + 1)
    )

    rows = frappe.db.sql(
        """
        WITH SalesData AS (
            SELECT
                soi.item_code      AS item_code,
                DATE(so.creation)  AS sale_date,
                SUM(soi.qty)       AS daily_sales
            FROM `tabSales Order` so
            JOIN `tabSales Order Item` soi ON so.name = soi.parent
            JOIN `tabItem` i ON soi.item_code = i.name
            WHERE so.docstatus = 1
              AND DATE(so.creation) >= %(start)s
              AND i.is_stock_item = 1
              AND soi.item_group IN %(igroups)s
            GROUP BY soi.item_code, DATE(so.creation)

            UNION ALL

            SELECT
                pbi.item_code      AS item_code,
                DATE(so.creation)  AS sale_date,
                SUM(pbi.qty * soi.qty) AS daily_sales
            FROM `tabSales Order` so
            JOIN `tabSales Order Item` soi ON so.name = soi.parent
            JOIN `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code
            JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
            JOIN `tabItem` i ON pbi.item_code = i.name
            WHERE so.docstatus = 1
              AND DATE(so.creation) >= %(start)s
              AND soi.item_group IN %(igroups)s
              AND soi.item_code IN (SELECT name FROM `tabItem` WHERE is_stock_item = 0)
              AND i.is_stock_item = 1
              AND pb.disable <> 1
            GROUP BY pbi.item_code, DATE(so.creation)
        )
        SELECT * FROM SalesData
        ORDER BY sale_date DESC
        """,
        {"start": start_date, "igroups": tuple(SELLABLE_ITEM_GROUPS)},
        as_dict=True,
    )

    if not rows:
        logger.warning("SalesData query returned 0 rows in the last %s days.", RECENCY_WINDOW_DAYS)

    _prime_item_cache([r["item_code"] for r in rows])

    daily = defaultdict(lambda: defaultdict(float))
    today = frappe.utils.getdate(frappe.utils.nowdate())

    for r in rows:
        ic = r["item_code"]
        km = _get_model_key(ic)
        kc = _get_config_key(ic)
        d = frappe.utils.getdate(r["sale_date"])
        qty = float(r["daily_sales"])
        daily[km][d] += qty
        daily[kc][d] += qty

    for key in daily:
        num = 0.0
        den = 0.0
        for dd in range(RECENCY_WINDOW_DAYS, 0, -1):
            day = today - timedelta(days=(dd - 1))
            qty = float(daily[key].get(day, 0.0))
            if qty <= 0.0:
                continue
            w = max(1, min(RECENCY_MAX_WEIGHT, RECENCY_WINDOW_DAYS - dd + 1))
            num += w * qty
            den += w
        rate = (num / den) if den else 0.0
        rates[key] = (rate if rate > 0 else 1.0)

    # Load to_make_ratio from Shopify Item List for default rate calculation
    ratio_rows = frappe.db.sql(
        """
        SELECT item_code, MAX(IFNULL(to_make_ratio, 0)) AS to_make_ratio
        FROM `tabShopify Item List`
        WHERE item_code IS NOT NULL AND item_code != ''
        GROUP BY item_code
        """,
        as_dict=True,
    )
    to_make_ratio_map = {}
    for r in ratio_rows:
        ratio = int(r.get("to_make_ratio") or 0)
        to_make_ratio_map[r["item_code"]] = ratio

    for it in (sellable_items or []):
        ic = it["name"]
        km = _get_model_key(ic)
        kc = _get_config_key(ic)

        # Use to_make_ratio as multiplier; if 0 or missing, fall back to 1.0
        ratio = to_make_ratio_map.get(ic, 0)
        default_rate = max(1.0, 1.0 * ratio) if ratio > 0 else 1.0

        rates[km] = max(rates.get(km, 0.0), default_rate)
        rates[kc] = max(rates.get(kc, 0.0), default_rate)

    return rates


@log_io
def _build_forward_keys(sellable_items, forward_grain, sales_rate):
    """
    - "model" grain means ("MODEL", template, proc)
    - "config" grain means ("CONFIG", template, proc, ram, sto)
    """
    variants_by_model = defaultdict(list)

    for it in sellable_items or []:
        ic = it["name"]
        km = _get_model_key(ic)
        kc = _get_config_key(ic)
        variants_by_model[km].append(kc)

    if forward_grain == "model":
        model_keys = list(variants_by_model.keys())

        def _model_score(mk):
            configs = variants_by_model.get(mk) or []
            return max(float(sales_rate.get(ck, 1.0)) for ck in configs) if configs else 1.0

        model_keys.sort(key=lambda mk: (-_model_score(mk), random.random()))
        return model_keys

    keys = []
    for mk, configs in variants_by_model.items():
        configs.sort(key=lambda ck: (-(sales_rate.get(ck, 1.0)), random.random()))
        keys.extend(configs)

    seen, out = set(), []
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


# =========================
# Allocation helpers
# =========================
@log_io
def _match_inventory_to_order_queues_for_sequence(
    seq,
    serial_map,
    seq_order_queues,
    allow_reconfig,
    inward_grain,
    forward_grain,
    current_department: str,
):
    allocations = []
    remaining = serial_map[:]
    if not seq_order_queues:
        return allocations, remaining

    by_model = defaultdict(list)
    by_config = defaultdict(list)
    for s in remaining:
        by_model[s["forward_key_model"]].append(s)
        by_config[s["forward_key_config"]].append(s)

    for k in by_model:
        by_model[k] = _oldest_first(by_model[k])
    for k in by_config:
        by_config[k] = _oldest_first(by_config[k])

    for key, ref_list in sorted(list(seq_order_queues.items()), key=lambda kv: len(kv[1]), reverse=True):
        while ref_list:
            order_ref = ref_list[0]

            target_cfg_tuple = None
            if order_ref.get("order_item_code"):
                target_cfg_tuple = _cfg_tuple_from_item(order_ref["order_item_code"])

            chosen = None

            if key and key[0] == "CONFIG":
                if not allow_reconfig:
                    cfg_pool = by_config.get(key, [])
                    if not cfg_pool:
                        break
                    chosen = _oldest_first(cfg_pool)[0] if cfg_pool else None
                else:
                    model_key = ("MODEL", key[1], key[2])
                    model_pool = by_model.get(model_key, [])
                    if not model_pool:
                        break

                    if target_cfg_tuple:
                        exact = [s for s in model_pool if _same_config(s, target_cfg_tuple)]
                        exact = _oldest_first(exact)
                        if exact:
                            chosen = exact[0]

                    if not chosen and target_cfg_tuple:
                        near = [s for s in model_pool if _same_storage_diff_ram(s, target_cfg_tuple)]
                        near = _oldest_first(near)
                        if near:
                            chosen = near[0]

                    if not chosen and model_pool:
                        chosen = _oldest_first(model_pool)[0]

            else:
                model_pool = by_model.get(key, [])
                if not model_pool:
                    break
                chosen = _oldest_first(model_pool)[0] if model_pool else None

            if not chosen:
                break

            pb_fallback = chosen.get("fallback_pb_item_code")

            if key and key[0] == "CONFIG":
                # Check if this is a reconfig match (serial config differs from SO config)
                is_reconfig_match = (
                    allow_reconfig
                    and target_cfg_tuple
                    and not _same_config(chosen, target_cfg_tuple)
                )
                if is_reconfig_match:
                    # Use the SO's actual item code as the target (technician must reconfigure)
                    target_item_code = (
                        order_ref.get("order_item_code")
                        or _resolve_target_item_code(
                            key,
                            fallback_pb_code=order_ref.get("pb_code") or pb_fallback,
                        )
                    )
                else:
                    target_item_code = _resolve_target_item_code(
                        key,
                        fallback_pb_code=order_ref.get("pb_code") or pb_fallback,
                    )
            else:
                target_item_code = pb_fallback

            if not target_item_code:
                target_item_code = order_ref.get("pb_code") or pb_fallback

            if _DEPT_ALLOCATE_PARTS.get(current_department):
                ok = _maybe_allocate_parts_for_serial(chosen["serial_no"], current_department)
                if not ok:
                    _update_serial_to_make(chosen["serial_no"], target_item_code)

                    remaining = [x for x in remaining if x["serial_no"] != chosen["serial_no"]]
                    by_model[chosen["forward_key_model"]] = [
                        x for x in by_model[chosen["forward_key_model"]] if x["serial_no"] != chosen["serial_no"]
                    ]
                    by_config[chosen["forward_key_config"]] = [
                        x for x in by_config[chosen["forward_key_config"]] if x["serial_no"] != chosen["serial_no"]
                    ]
                    logger.debug(f"Skipping serial_no: {chosen['serial_no']} - Reason: Part allocation failed for department {current_department} (Order Match)")
                    continue

            ref_list.pop(0)

            allocations.append(
                {
                    "serial_no": chosen["serial_no"],
                    "warehouse": chosen["warehouse"],
                    "target_item_code": target_item_code,
                    "forward_key": key,
                    "order_name": order_ref.get("so_name"),
                    "required_by": order_ref.get("delivery_date"),
                    "age_days": chosen.get("age_days"),
                }
            )

            remaining = [x for x in remaining if x["serial_no"] != chosen["serial_no"]]
            by_model[chosen["forward_key_model"]] = [
                x for x in by_model[chosen["forward_key_model"]] if x["serial_no"] != chosen["serial_no"]
            ]
            by_config[chosen["forward_key_config"]] = [
                x for x in by_config[chosen["forward_key_config"]] if x["serial_no"] != chosen["serial_no"]
            ]

    for k in [k for k, v in list(seq_order_queues.items()) if not v]:
        del seq_order_queues[k]

    return allocations, remaining

@log_io
def _estimate_forward_inventory(forward_keys, serials, forward_grain):
    inv = Counter()
    for s in serials:
        k = s["forward_key_config"] if forward_grain == "config" else s["forward_key_model"]
        if k in forward_keys:
            inv[k] += 1
    return dict(inv)


def _allocate_forecast_to_balance_doi(
    remaining_serials,
    forward_grain,
    allow_reconfig,
    forward_keys,
    sales_rate,
    current_doi,
    current_department: str,
):
    """
    Forecast allocation logic:
    - choose the lowest exact DOI first
    - if DOI ties, choose higher sales-rate first
    - after each successful allocation, add 1 implied unit to that target
      and recompute DOI immediately
    """
    allocations = []

    if forward_grain == "config":
        buckets = defaultdict(list)
        any_by_model = defaultdict(list)
        for s in remaining_serials:
            buckets[s["forward_key_config"]].append(s)
            any_by_model[s["forward_key_model"]].append(s)
        for k in buckets:
            buckets[k] = _oldest_first(buckets[k])
        for k in any_by_model:
            any_by_model[k] = _oldest_first(any_by_model[k])
    else:
        buckets = defaultdict(list)
        for s in remaining_serials:
            buckets[s["forward_key_model"]].append(s)
        for k in buckets:
            buckets[k] = _oldest_first(buckets[k])

    work = list(forward_keys)

    while work and remaining_serials:
        work.sort(
            key=lambda k: (
                float(current_doi.get(k, 0.0)),
                -float(sales_rate.get(k, 1.0)),
            )
        )
        target = work[0]

        chosen = None

        if forward_grain == "config":
            pool = buckets.get(target, [])
            if pool:
                chosen = pool[0]
            elif allow_reconfig:
                model_key = ("MODEL", target[1], target[2])
                pool2 = any_by_model.get(model_key, [])
                if pool2:
                    _, template, proc, ram, sto = target
                    target_cfg_tuple = (template, proc, ram, sto)

                    near = [s for s in pool2 if _same_storage_diff_ram(s, target_cfg_tuple)]
                    near = _oldest_first(near)
                    if near:
                        chosen = near[0]
                    else:
                        chosen = _oldest_first(pool2)[0] if pool2 else None
        else:
            pool = buckets.get(target, [])
            if pool:
                chosen = pool[0]

        if not chosen:
            work.pop(0)
            continue

        pb_fallback = chosen.get("fallback_pb_item_code")

        if target and target[0] == "CONFIG":
            target_item_code = _resolve_existing_item_for_key(target)
        else:
            target_item_code = pb_fallback

        if not target_item_code:
            target_item_code = pb_fallback

        if _DEPT_ALLOCATE_PARTS.get(current_department):
            ok = _maybe_allocate_parts_for_serial(chosen["serial_no"], current_department)
            if not ok:
                _update_serial_to_make(chosen["serial_no"], target_item_code)

                remaining_serials[:] = [x for x in remaining_serials if x["serial_no"] != chosen["serial_no"]]
                if forward_grain == "config":
                    kcfg = chosen["forward_key_config"]
                    if kcfg in buckets:
                        buckets[kcfg] = [x for x in buckets[kcfg] if x["serial_no"] != chosen["serial_no"]]
                    mk = chosen["forward_key_model"]
                    if mk in any_by_model:
                        any_by_model[mk] = [x for x in any_by_model[mk] if x["serial_no"] != chosen["serial_no"]]
                else:
                    mk = chosen["forward_key_model"]
                    if mk in buckets:
                        buckets[mk] = [x for x in buckets[mk] if x["serial_no"] != chosen["serial_no"]]
                logger.debug(f"Skipping serial_no: {chosen['serial_no']} - Reason: Part allocation failed for department {current_department} (Forecast)")
                continue

        rate = max(1.0, float(sales_rate.get(target, 1.0)))
        inv_now = float(current_doi.get(target, 0.0)) * rate
        new_doi = (inv_now + 1.0) / rate
        current_doi[target] = new_doi

        allocations.append(
            {
                "serial_no": chosen["serial_no"],
                "warehouse": chosen["warehouse"],
                "target_item_code": target_item_code,
                "forward_key": target,
                "doi": new_doi,
                "age_days": chosen.get("age_days"),
            }
        )

        remaining_serials[:] = [x for x in remaining_serials if x["serial_no"] != chosen["serial_no"]]
        if forward_grain == "config":
            kcfg = chosen["forward_key_config"]
            if kcfg in buckets:
                buckets[kcfg] = [x for x in buckets[kcfg] if x["serial_no"] != chosen["serial_no"]]
            mk = chosen["forward_key_model"]
            if mk in any_by_model:
                any_by_model[mk] = [x for x in any_by_model[mk] if x["serial_no"] != chosen["serial_no"]]
        else:
            mk = chosen["forward_key_model"]
            if mk in buckets:
                buckets[mk] = [x for x in buckets[mk] if x["serial_no"] != chosen["serial_no"]]

    return allocations


# =========================
# Reconfig stale serial helpers
# =========================
@log_io
def _get_serial_dwell_days(serial_nos: List[str]) -> Dict[str, int]:
    """
    For each serial, find the last submitted Material Transfer (Stock Entry)
    and compute dwell_days = today - posting_date.
    Returns {serial_no: dwell_days}.
    Falls back to Serial No creation date if no Material Transfer found.
    """
    if not serial_nos:
        return {}

    today = frappe.utils.getdate(frappe.utils.nowdate())
    result: Dict[str, int] = {}

    # Batch query: find the latest Material Transfer posting_date per serial
    # Stock Entry Detail stores serial_no as a text field (newline-separated for multi)
    # For single serial items, it's just the serial name.
    placeholders = ",".join(["%s"] * len(serial_nos))
    rows = frappe.db.sql(
        f"""
        SELECT
            sed.serial_no AS raw_serial,
            MAX(se.posting_date) AS last_transfer_date
        FROM `tabStock Entry Detail` sed
        INNER JOIN `tabStock Entry` se
            ON se.name = sed.parent
            AND se.stock_entry_type = 'Material Transfer'
            AND se.docstatus = 1
        WHERE sed.serial_no IN ({placeholders})
        GROUP BY sed.serial_no
        """,
        tuple(serial_nos),
        as_dict=True,
    )

    transfer_dates = {}
    for r in rows:
        raw = (r.get("raw_serial") or "").strip()
        if raw:
            # Handle single serial per row
            transfer_dates[raw] = r["last_transfer_date"]

    for sn in serial_nos:
        last_date = transfer_dates.get(sn)
        if last_date:
            dwell = (today - frappe.utils.getdate(last_date)).days
        else:
            # Fallback: use serial creation date
            creation = frappe.db.get_value("Serial No", sn, "creation")
            if creation:
                dwell = (today - frappe.utils.getdate(creation)).days
            else:
                dwell = 0
        result[sn] = max(dwell, 0)

    return result


@log_io
def _get_reconfig_serials_for_departments(
    department_names: List[str],
    reconfig_aging_days: int,
    already_planned_sns: set,
) -> List[Dict]:
    """
    Fetch active serials from the given departments that have been sitting
    longer than reconfig_aging_days (based on last Material Transfer).
    Excludes serials already in the current plan.
    Returns enriched serial dicts ready for allocation.
    """
    if not department_names or reconfig_aging_days <= 0:
        return []

    dept_tuple = tuple(department_names)
    igroup_tuple = tuple(SELLABLE_ITEM_GROUPS)

    rows = frappe.db.sql(
        """
        SELECT
            sn.name,
            sn.item_code,
            sn.warehouse,
            sn.department,
            sn.creation,
            sn.purchase_date,
            sn.item_wizard,
            iw.part_list_status,
            iw.docstatus AS iw_docstatus
        FROM `tabSerial No` sn
        INNER JOIN `tabItem` it
            ON sn.item_code = it.name
        LEFT JOIN `tabItem Wizards` iw
            ON sn.item_wizard = iw.name
        WHERE sn.department IN %(depts)s
          AND (sn.status IS NULL OR sn.status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
          AND it.item_group IN %(igroups)s
        """,
        {"depts": dept_tuple, "igroups": igroup_tuple},
        as_dict=True,
    )

    if not rows:
        return []

    # Filter out already-planned serials
    rows = [r for r in rows if r["name"] not in already_planned_sns]
    if not rows:
        return []

    # Validate: must have Item Wizard with completed part list
    valid_rows = []
    for r in rows:
        if not r.get("item_wizard"):
            continue
        if r.get("part_list_status") != "Completed" or r.get("iw_docstatus") != 1:
            continue
        valid_rows.append(r)

    if not valid_rows:
        return []

    # Compute dwell days
    serial_names = [r["name"] for r in valid_rows]
    dwell_map = _get_serial_dwell_days(serial_names)

    # Filter by aging threshold
    stale_rows = [r for r in valid_rows if dwell_map.get(r["name"], 0) > reconfig_aging_days]
    if not stale_rows:
        return []

    logger.debug(
        f"[RECONFIG] Found {len(stale_rows)} stale serials (aging > {reconfig_aging_days} days) "
        f"from departments {department_names}"
    )

    # Prime item cache and enrich
    _prime_item_cache([r["item_code"] for r in stale_rows])
    enriched = []
    for r in stale_rows:
        e = _enrich_serial_from_attrs(r)
        e["dwell_days"] = dwell_map.get(r["name"], 0)
        e["source_department"] = r["department"]

        # Must have a fallback PB item code
        if not e.get("fallback_pb_item_code"):
            continue

        enriched.append(e)

    return enriched


@log_io
def _allocate_reconfig_serials(
    stale_serials: List[Dict],
    forward_keys: List,
    sales_rate: Dict,
    current_doi: Dict,
    current_department: str,
) -> List[Dict]:
    """
    Allocate stale serials to the best target config using lowest-DOI logic.
    For each stale serial:
      1. Find its model_key
      2. Among forward_keys, find configs matching the same model
      3. Pick the config with the lowest DOI
      4. Run part allocation check
      5. If OK -> allocate; if not -> skip
    Returns list of allocation dicts.
    """
    allocations = []

    # Sort stale serials: oldest first (highest dwell_days first)
    stale_serials = sorted(stale_serials, key=lambda s: -s.get("dwell_days", 0))

    for serial in stale_serials:
        model_key = serial["forward_key_model"]
        # model_key is ("MODEL", template, processor)
        if not model_key or len(model_key) < 3:
            continue

        template = model_key[1]
        proc = model_key[2]

        # Find all forward_keys that match this model (same template + processor)
        matching_keys = []
        for fk in forward_keys:
            if fk[0] == "CONFIG" and len(fk) >= 3 and fk[1] == template and fk[2] == proc:
                matching_keys.append(fk)
            elif fk[0] == "MODEL" and len(fk) >= 3 and fk[1] == template and fk[2] == proc:
                matching_keys.append(fk)

        if not matching_keys:
            logger.debug(
                f"[RECONFIG_SKIP] serial_no={serial['serial_no']} - no matching forward keys for model {model_key}"
            )
            continue

        # Sort by DOI ascending (lowest DOI = most urgently needed)
        matching_keys.sort(key=lambda k: (float(current_doi.get(k, 0.0)), -float(sales_rate.get(k, 1.0))))
        target_key = matching_keys[0]

        # Resolve target item code
        if target_key[0] == "CONFIG":
            target_item_code = _resolve_existing_item_for_key(target_key)
        else:
            target_item_code = target_key[1]  # template item for MODEL key

        if not target_item_code:
            target_item_code = serial.get("fallback_pb_item_code")

        if not target_item_code:
            continue

        # Part allocation check
        if _DEPT_ALLOCATE_PARTS.get(current_department):
            ok = _maybe_allocate_parts_for_serial(serial["serial_no"], current_department)
            if not ok:
                _update_serial_to_make(serial["serial_no"], target_item_code)
                logger.debug(
                    f"[RECONFIG_SKIP] serial_no={serial['serial_no']} - "
                    f"Part allocation failed for department {current_department}"
                )
                continue

        # Update DOI after allocation
        rate = max(1.0, float(sales_rate.get(target_key, 1.0)))
        inv_now = float(current_doi.get(target_key, 0.0)) * rate
        new_doi = (inv_now + 1.0) / rate
        current_doi[target_key] = new_doi

        allocations.append({
            "serial_no": serial["serial_no"],
            "warehouse": serial["warehouse"],
            "target_item_code": target_item_code,
            "forward_key": target_key,
            "doi": new_doi,
            "dwell_days": serial.get("dwell_days", 0),
            "source_department": serial.get("source_department"),
            "age_days": serial.get("age_days"),
        })

        logger.debug(
            f"[RECONFIG_ALLOCATED] serial_no={serial['serial_no']}, "
            f"from_dept={serial.get('source_department')}, "
            f"target_item={target_item_code}, doi={new_doi:.2f}, "
            f"dwell_days={serial.get('dwell_days', 0)}"
        )

    return allocations


# =========================
# Inward serial fetch
# =========================
@log_io
def _get_inward_serials_for_department(dept_doc) -> List[Dict]:
    """
    Fetch valid serials for a department where:
    - status NOT in ('Delivered', 'Scrapped', 'Inactive') OR NULL
    - linked item_wizard exists AND its part_list_status = 'Completed'
    - exclude restricted warehouses defined in the department config
    """
    restricted_warehouse: List[str] = []

    for row in dept_doc.get("inventory_details_child", []):
        raw = (row.get("restricted_department_warehouse_list") or "").strip()
        if raw:
            restricted_warehouse.extend([w.strip() for w in raw.split(",") if w.strip()])

    extra_where = ""
    params = {
        "dept": dept_doc.name,
        "igroups": tuple(SELLABLE_ITEM_GROUPS)
    }

    if restricted_warehouse:
        extra_where = " AND sn.warehouse NOT IN %(restricted_whs)s"
        params["restricted_whs"] = tuple(restricted_warehouse)

    rows = frappe.db.sql(
        f"""
        SELECT
            sn.name,
            sn.item_code,
            sn.warehouse,
            sn.department,
            sn.creation,
            sn.purchase_date,
            sn.item_wizard,
            iw.part_list_status,
            iw.docstatus AS iw_docstatus
        FROM `tabSerial No` sn
        INNER JOIN `tabItem` it
            ON sn.item_code = it.name
        LEFT JOIN `tabItem Wizards` iw
            ON sn.item_wizard = iw.name
        WHERE sn.department = %(dept)s
          AND (sn.status IS NULL OR sn.status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
          AND it.item_group IN %(igroups)s
          AND (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '')
          {extra_where}
        """,
        params,
        as_dict=True,
    )

    _prime_item_cache([r["item_code"] for r in rows])
    return rows


@log_io
def _get_reserved_serials_for_department(dept_name: str) -> List[Dict]:
    """
    Fetch serials in this department that are already reserved against
    an active Sales Order (status NOT Closed/Cancelled/Completed).
    These bypass normal allocation logic and are added directly to the plan.
    """
    rows = frappe.db.sql(
        """
        SELECT
            sn.name,
            sn.item_code,
            sn.warehouse,
            sn.department,
            sn.creation,
            sn.purchase_date,
            sn.reserved_sales_order,
            sn.to_make,
            sn.item_wizard,
            iw.part_list_status,
            iw.docstatus AS iw_docstatus,
            (
                SELECT MIN(soi.delivery_date)
                FROM `tabSales Order Item` soi
                WHERE soi.parent = sn.reserved_sales_order
            ) AS delivery_date
        FROM `tabSerial No` sn
        INNER JOIN `tabItem` it ON it.name = sn.item_code
        INNER JOIN `tabSales Order` so ON so.name = sn.reserved_sales_order
        LEFT JOIN `tabItem Wizards` iw ON sn.item_wizard = iw.name
        WHERE sn.department = %(dept)s
          AND (sn.status IS NULL OR sn.status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
          AND it.item_group IN %(igroups)s
          AND sn.reserved_sales_order IS NOT NULL
          AND sn.reserved_sales_order != ''
          AND so.status NOT IN ('Closed', 'Cancelled', 'Completed')
        """,
        {
            "dept": dept_name,
            "igroups": tuple(SELLABLE_ITEM_GROUPS),
        },
        as_dict=True,
    )
    _prime_item_cache([r["item_code"] for r in rows])
    return rows



# =========================
# Item/Attribute machinery
# =========================
@log_io
def _prime_item_cache(item_codes: List[str]):
    if not item_codes:
        return
    needed = [ic for ic in set(item_codes) if ic not in _ITEM_CORE]
    if not needed:
        return

    placeholders = ",".join(["%s"] * len(needed))
    core_rows = frappe.db.sql(
        f"""
        SELECT name, item_group, shopify_product_id, variant_of
        FROM `tabItem`
        WHERE name IN ({placeholders})
        """,
        tuple(needed),
        as_dict=True,
    )
    for r in core_rows:
        _ITEM_CORE[r["name"]] = {
            "name": r["name"],
            "item_group": r["item_group"],
            "shopify_product_id": (r.get("shopify_product_id") or "").strip(),
            "variant_of": r.get("variant_of") or None,
        }

    attr_rows = frappe.db.sql(
        f"""
        SELECT parent AS item_code, attribute, attribute_value
        FROM `tabItem Variant Attribute`
        WHERE parent IN ({placeholders})
        """,
        tuple(needed),
        as_dict=True,
    )
    for r in attr_rows:
        d = _ITEM_ATTRS.setdefault(r["item_code"], {})
        d[r["attribute"]] = r["attribute_value"]

    for ic in needed:
        core = _ITEM_CORE.get(ic) or {}
        template = core.get("variant_of") or ic
        attrs = _ITEM_ATTRS.get(ic, {})
        proc = attrs.get(PROCESSOR_ATTR)
        ram = attrs.get(RAM_ATTR)
        sto = attrs.get(STORAGE_ATTR)

        _ITEM_KEYS[ic] = {
            "model_key": ("MODEL", template, proc),
            "config_key": ("CONFIG", template, proc, ram, sto),
        }


@log_io
def _get_model_key(item_code: str):
    if item_code not in _ITEM_KEYS:
        _prime_item_cache([item_code])
    return _ITEM_KEYS[item_code]["model_key"]


@log_io
def _get_config_key(item_code: str):
    if item_code not in _ITEM_KEYS:
        _prime_item_cache([item_code])
    return _ITEM_KEYS[item_code]["config_key"]


@log_io
def _key_for_grain(item_code: str, grain: str):
    return _get_model_key(item_code) if grain == "model" else _get_config_key(item_code)


@log_io
def _target_item_for_key(key):
    if not key:
        return None
    if key[0] == "MODEL":
        return key[1]
    _, template, proc, ram, sto = key
    variant = _find_variant_by_attributes(
        template,
        {
            PROCESSOR_ATTR: proc,
            RAM_ATTR: ram,
            STORAGE_ATTR: sto,
        },
    )
    return variant or f"{template}::{proc}-{ram}-{sto}"


@log_io
def _resolve_existing_item_for_key(key) -> Optional[str]:
    if not key:
        return None
    if key[0] == "MODEL":
        return key[1]
    _, template, proc, ram, sto = key
    return _find_variant_by_attributes(
        template,
        {
            PROCESSOR_ATTR: proc,
            RAM_ATTR: ram,
            STORAGE_ATTR: sto,
        },
    )

@log_io
def _resolve_target_item_code(key, fallback_pb_code: Optional[str] = None) -> Optional[str]:
    exact_item = _resolve_existing_item_for_key(key)
    if exact_item:
        return exact_item

    if fallback_pb_code:
        return fallback_pb_code

    return None


def _is_blankish_attr(val) -> bool:
    v = (val or "").strip().upper()
    return v in ("", "NONE", "NO RAM", "NO DISK", "UNKNOWN", "N/A", "NA")


def _get_fallback_pb_item_code(item_code: str) -> Optional[str]:
    """
    Return the best sellable/Product Bundle item code for the same model key.

    Priority:
    1. exact config match among sellable items
    2. same model with real RAM + real Storage
    3. same model, alphabetically stable
    """
    if not item_code:
        return None

    if item_code not in _ITEM_KEYS:
        _prime_item_cache([item_code])

    model_key = _ITEM_KEYS[item_code]["model_key"]
    config_key = _ITEM_KEYS[item_code]["config_key"]

    candidates = _MODEL_TO_SELLABLE_ITEMS.get(model_key, [])
    
    # Ensure candidates are primed
    unprimed = [ic for ic in candidates if ic not in _ITEM_KEYS]
    if unprimed:
        _prime_item_cache(unprimed)

    if not candidates:
        return None

    for ic in candidates:
        if _ITEM_KEYS.get(ic, {}).get("config_key") == config_key:
            return ic

    def _rank(ic: str):
        attrs = _ITEM_ATTRS.get(ic, {})
        ram = attrs.get(RAM_ATTR)
        sto = attrs.get(STORAGE_ATTR)
        proc = attrs.get(PROCESSOR_ATTR)

        good_ram = 0 if _is_blankish_attr(ram) else 1
        good_sto = 0 if _is_blankish_attr(sto) else 1
        good_proc = 0 if _is_blankish_attr(proc) else 1

        return (
            good_ram + good_sto + good_proc,
            good_ram,
            good_sto,
            good_proc,
            ic,
        )

    candidates = sorted(candidates, key=_rank, reverse=True)
    return candidates[0] if candidates else None


@log_io
def _find_variant_by_attributes(template_item: str, attr_map: Dict) -> Union[str, None]:
    if not template_item or not attr_map:
        return None
    variants = frappe.get_all("Item", filters={"variant_of": template_item, "disabled": 0}, pluck="name")
    if not variants:
        return None
    _prime_item_cache(variants)
    for v in variants:
        attrs = _ITEM_ATTRS.get(v, {})
        if all(attrs.get(k) == v2 for k, v2 in attr_map.items()):
            return v
    return None


@log_io
def _enrich_serial_from_attrs(snrow: Dict) -> Dict:
    ic = snrow["item_code"]
    if ic not in _ITEM_KEYS:
        _prime_item_cache([ic])

    today = frappe.utils.getdate(frappe.utils.nowdate())
    purchase_date = snrow.get("purchase_date")
    creation = snrow.get("creation")

    if purchase_date:
        base_date = frappe.utils.getdate(purchase_date)
    elif creation:
        base_date = frappe.utils.getdate(creation)
    else:
        base_date = today

    age_days = (today - base_date).days if base_date else 0
    fallback_pb_item_code = _get_fallback_pb_item_code(ic)

    return {
        "serial_no": snrow["name"],
        "item_code": ic,
        "fallback_pb_item_code": fallback_pb_item_code,
        "warehouse": snrow["warehouse"],
        "forward_key_model": _ITEM_KEYS[ic]["model_key"],
        "forward_key_config": _ITEM_KEYS[ic]["config_key"],
        "purchase_date": purchase_date,
        "creation": creation,
        "age_days": age_days,
    }


# =========================
# Part allocation helpers
# =========================
@log_io
def _build_initial_part_stock():
    """
    Build initial virtual stock for parts from all warehouses under department 'Stores - NJ'.

    - For serialized items: COUNT(Serial No)
    - For non-serialized items: SUM(Bin.actual_qty)
    """
    warehouses = frappe.get_all(
        "Warehouse",
        filters=[["department", "=", "Stores - NJ"], ["disabled", "!=", 1]],
        pluck="name",
    )

    if not warehouses:
        logger.warning("No warehouses found under 'Stores - NJ' department for part allocation.")
        return {}, {}

    wh_tuple = tuple(warehouses)

    serial_stock_rows = frappe.db.sql(
        """
        SELECT
            sn.item_code,
            COUNT(*) AS qty
        FROM `tabSerial No` sn
        WHERE sn.warehouse IN %(warehouses)s
          AND (sn.status IS NULL OR sn.status NOT IN ('Delivered','Scrapped','Inactive'))
        GROUP BY sn.item_code
        """,
        {"warehouses": wh_tuple},
        as_dict=True,
    )

    serial_stock = {row["item_code"]: flt(row["qty"] or 0) for row in (serial_stock_rows or [])}
    serialized_set = set(serial_stock.keys())

    bin_rows = frappe.db.sql(
        """
        SELECT
            b.item_code,
            SUM(b.actual_qty) AS total_qty
        FROM `tabBin` b
        INNER JOIN `tabItem` i ON i.name = b.item_code
        WHERE b.warehouse IN %(warehouses)s
          AND IFNULL(i.has_serial_no, 0) = 0
        GROUP BY b.item_code
        """,
        {"warehouses": wh_tuple},
        as_dict=True,
    )

    bin_stock = {row["item_code"]: flt(row["total_qty"] or 0) for row in (bin_rows or [])}

    virtual_stock: Dict[str, float] = {}
    for ic, qty in serial_stock.items():
        virtual_stock[ic] = qty

    for ic, qty in bin_stock.items():
        if ic in serialized_set:
            continue
        virtual_stock[ic] = qty

    planned_alloc: Dict[str, float] = {}
    return virtual_stock, planned_alloc


@log_io
def _maybe_allocate_parts_for_serial(serial_no: str, current_department: str) -> bool:
    """
    Two-phase reservation:
    - Phase 1: check all MR lines are feasible WITHOUT changing globals.
    - Phase 2: only if feasible, commit reservation into _PART_PLANNED_ALLOCATION.
    """
    logger.debug(f"\n\n\n[ALLOCATE_STARTED] serial_no={serial_no}, dept={current_department}")

    if not _DEPT_ALLOCATE_PARTS.get(current_department):
        logger.debug(
            f"\n[ALLOCATE_RESULT] serial_no={serial_no}, dept={current_department}, "
            f"result=ALLOCATED (bypassed, allocate_parts disabled for this dept)"
        )
        return True

    mr_items = _SERIAL_TO_MR_ITEMS.get(serial_no, [])

    mr_names = sorted({row["material_request"] for row in mr_items}) if mr_items else []
    logger.debug(
        f"\n[MR_INFO] serial_no={serial_no}, dept={current_department}, "
        f"mr_count={len(mr_items)}, mr_list={mr_names}"
    )

    if not mr_items:
        logger.debug(
            f"\n[ALLOCATE_RESULT] serial_no={serial_no}, dept={current_department}, "
            f"result=ALLOCATED, reason='no pending Material Requests for this serial'"
        )
        return True

    global _PART_VIRTUAL_STOCK, _PART_PLANNED_ALLOCATION

    to_reserve = defaultdict(float)
    unallocated_lines = []
    involved_item_codes = set()

    for row in mr_items:
        item_code = row["item_code"]
        involved_item_codes.add(item_code)

        mr_qty = flt(row.get("mr_qty") or row.get("stock_qty") or 0)
        if mr_qty <= 0:
            logger.debug(f"\n[MR_SKIP_ZERO_QTY] serial_no={serial_no}, item_code={item_code}, mr_qty={mr_qty}")
            continue

        already_planned = flt(_PART_PLANNED_ALLOCATION.get(item_code, 0.0))
        virtual_stock = flt(_PART_VIRTUAL_STOCK.get(item_code, 0.0))

        available_before = float(virtual_stock - already_planned - to_reserve[item_code])

        if available_before >= mr_qty:
            to_reserve[item_code] += mr_qty
            logger.debug(
                f"\n[LINE_CHECK_OK] serial_no={serial_no}, MR={row['material_request']}, item_code={item_code}, "
                f"required={mr_qty}, available_before={available_before}, would_reserve_total={to_reserve[item_code]}"
            )
        else:
            unallocated_lines.append(
                {
                    "material_request": row["material_request"],
                    "item_code": item_code,
                    "required": mr_qty,
                    "available": available_before,
                }
            )
            logger.debug(
                f"\n[LINE_CHECK_BLOCKED] serial_no={serial_no}, MR={row['material_request']}, item_code={item_code}, "
                f"required={mr_qty}, available={available_before} (insufficient stock)"
            )

    remaining_virtual_stock = {
        item_code: float(_PART_VIRTUAL_STOCK.get(item_code, 0.0) - _PART_PLANNED_ALLOCATION.get(item_code, 0.0))
        for item_code in sorted(involved_item_codes)
    }

    if unallocated_lines:
        logger.debug(
            f"\n[ALLOCATE_RESULT] serial_no={serial_no}, dept={current_department}, "
            f"result=NOT_ALLOCATED, reason='insufficient stock for some MR lines', "
            f"unallocated_lines={unallocated_lines}, remaining_virtual_stock={remaining_virtual_stock}"
        )
        return False

    alloc_rows = []
    for row in mr_items:
        item_code = row["item_code"]
        mr_qty = flt(row.get("mr_qty") or row.get("stock_qty") or 0)
        if mr_qty <= 0:
            continue

        _PART_PLANNED_ALLOCATION[item_code] = flt(_PART_PLANNED_ALLOCATION.get(item_code, 0.0)) + mr_qty
        alloc_rows.append({"material_request": row["material_request"], "item_code": item_code, "allocated_qty": mr_qty})

    remaining_virtual_stock_after = {
        item_code: float(_PART_VIRTUAL_STOCK.get(item_code, 0.0) - _PART_PLANNED_ALLOCATION.get(item_code, 0.0))
        for item_code in sorted(involved_item_codes)
    }

    logger.debug(
        f"\n[ALLOCATE_RESULT] serial_no={serial_no}, dept={current_department}, "
        f"result=ALLOCATED, reason='all MR lines fully allocatable from virtual stock', "
        f"allocated_lines={alloc_rows}, remaining_virtual_stock={remaining_virtual_stock_after}"
    )

    return True


# =========================
# Plan persistence
# =========================
@log_io
def _append_plan_row(
    plan_doc,
    serial_no: str,
    current_warehouse: str,
    current_department: str,
    sales_rate: float,
    doi: float,
    sales_order_number: Optional[str],
    delivery_date,
    item_code_to_make: str,
    reason: str,
    priority_rank: int,
    serial_age_days: Optional[int] = None,
):
    # Log each serial number being processed
    logger.debug(f"processing each and every serial no we need to mention got it: {serial_no}")
    _update_serial_to_make(serial_no, item_code_to_make)

    if reason == "Order" and sales_order_number:
        _update_serial_reserved_sales_order(serial_no, sales_order_number)
    else:
        _update_serial_reserved_sales_order(serial_no, None)

    plan_doc.append(
        "lines",
        {
            "serial_no": serial_no,
            "current_warehouse": current_warehouse,
            "current_department": current_department,
            "sales_rate": float(sales_rate or 0),
            "doi": _round_half_up(doi),
            "sales_order_no": sales_order_number,
            "delivery_date": delivery_date,
            "item_code": item_code_to_make,
            "reason": reason,
            "priority_rank": int(priority_rank),
            "serial_age_days": serial_age_days,
            "allocate_parts": 1,
        },
    )





# Manufacture MR section==================


PP_MR_DEFAULT_SCHEDULE_DAYS = 3
PP_MR_STORES_DEPARTMENT = "Stores - NJ"
PP_MR_CORE_ITEM_GROUPS = ["Laptops", "Chromeboxes", "Chromebooks", "Desktops", "Macbooks"]
PP_MR_MIN_QTY = 0.000001
_PP_MR_WHOLE_NUMBER_UOM_BY_ITEM = {}


def _get_pp_default_mr_schedule_date():
    return add_days(frappe.utils.nowdate(), PP_MR_DEFAULT_SCHEDULE_DAYS)


def _round_pp_qty_for_item_uom(item_code, qty):
    qty = flt(qty, 6)
    if qty <= 0:
        return qty

    if item_code not in _PP_MR_WHOLE_NUMBER_UOM_BY_ITEM:
        stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
        must_be_whole_number = (
            frappe.db.get_value("UOM", stock_uom, "must_be_whole_number")
            if stock_uom else 0
        )
        _PP_MR_WHOLE_NUMBER_UOM_BY_ITEM[item_code] = {
            "stock_uom": stock_uom,
            "must_be_whole_number": flt(must_be_whole_number),
        }

    uom_info = _PP_MR_WHOLE_NUMBER_UOM_BY_ITEM.get(item_code) or {}
    if not uom_info.get("must_be_whole_number"):
        return qty

    rounded_qty = math.ceil(qty - PP_MR_MIN_QTY)
    if abs(rounded_qty - qty) > PP_MR_MIN_QTY:
        print(
            "PP MR rounded fractional qty for whole-number UOM:",
            "item_code:", item_code,
            "stock_uom:", uom_info.get("stock_uom"),
            "original_qty:", qty,
            "rounded_qty:", rounded_qty,
        )

    return rounded_qty


def _split_pp_department_names(departments):
    if not departments:
        return []

    return [d.strip() for d in str(departments).split(",") if d.strip()]


def _get_pp_previous_two_department_names(departments):
    
    departments = _split_pp_department_names(departments)
    if not departments:
        return []

    rows = frappe.db.sql("""
        SELECT DISTINCT
            prev_dept.name,
            prev_dept.department_sequence,
            base_dept.name AS target_department,
            base_dept.department_sequence AS target_department_sequence
        FROM
            `tabDepartment` base_dept
        INNER JOIN
            `tabDepartment` prev_dept
            ON prev_dept.department_sequence > 0
            AND prev_dept.department_sequence < base_dept.department_sequence
        WHERE
            base_dept.name IN %(departments)s
        ORDER BY
            base_dept.department_sequence,
            prev_dept.department_sequence DESC
    """, {
        "departments": tuple(departments),
    }, as_dict=True)

    previous_departments = []
    seen = set()
    for row in rows:
        if row.name not in seen:
            previous_departments.append(row.name)
            seen.add(row.name)

        print(
            "PP MR consumable previous department:",
            "target_department:", row.target_department,
            "target_department_sequence:", row.target_department_sequence,
            "stock_department:", row.name,
            "stock_department_sequence:", row.department_sequence,
        )

    return previous_departments


def _get_pp_schedule_days(source_department, target_department):
    source_sequence = frappe.db.get_value(
        "Department",
        source_department,
        "department_sequence",
    )
    target_sequence = frappe.db.get_value(
        "Department",
        target_department,
        "department_sequence",
    )

    if source_sequence is None or target_sequence is None:
        return PP_MR_DEFAULT_SCHEDULE_DAYS

    source_sequence = int(source_sequence)
    target_sequence = int(target_sequence)

    if target_sequence >= source_sequence:
        result = frappe.db.sql("""
            SELECT SUM(department_sla)
            FROM `tabDepartment`
            WHERE department_sequence >= %(from_sequence)s
                AND department_sequence < %(to_sequence)s
        """, {
            "from_sequence": source_sequence,
            "to_sequence": target_sequence,
        })
    else:
        result = frappe.db.sql("""
            SELECT SUM(department_sla)
            FROM `tabDepartment`
            WHERE department_sequence > %(from_sequence)s
                AND department_sequence <= %(to_sequence)s
        """, {
            "from_sequence": target_sequence,
            "to_sequence": source_sequence,
        })

    if not result or result[0][0] is None:
        return PP_MR_DEFAULT_SCHEDULE_DAYS

    return int(result[0][0] or 0)


def _get_pp_default_company():
    company = (
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
    )

    if not company:
        frappe.throw(_("Default Company is required to create Material Request."))

    return company


def _get_pp_item_skip_reasons(item_codes):
    item_codes = [item_code for item_code in set(item_codes or []) if item_code]
    if not item_codes:
        return {}

    item_rows = frappe.get_all(
        "Item",
        filters={"name": ["in", item_codes]},
        fields=["name", "disabled", "end_of_life"],
    )
    item_by_code = {row.name: row for row in item_rows}

    skip_reasons = {}
    for item_code in item_codes:
        item_doc = item_by_code.get(item_code)
        if not item_doc:
            skip_reasons[item_code] = "item code not found"
            continue

        if flt(item_doc.get("disabled")):
            skip_reasons[item_code] = "item is disabled"
            continue

        end_of_life = item_doc.get("end_of_life")
        if end_of_life and frappe.utils.getdate(end_of_life) <= frappe.utils.getdate(frappe.utils.nowdate()):
            skip_reasons[item_code] = f"item reached end of life on {end_of_life}"

    return skip_reasons


def _get_latest_nj_production_plan_name():
    latest_plan = frappe.get_all(
        "NJ Production Planning",
        filters={"docstatus": ["!=", 2]},
        fields=["name"],
        order_by="creation desc",
        limit=1,
    )
    print("latest_plan=====================", latest_plan)
    return latest_plan[0].name if latest_plan else None


def _get_pp_template_department_qty(plan_name):
    rows = frappe.db.sql("""
        SELECT
            IFNULL(NULLIF(i.variant_of, ''), i.name) AS item_template,
            f.current_department,
            COUNT(*) AS planned_qty
        FROM
            `tabFinal Production Planning Data` f
        INNER JOIN
            `tabItem` i
            ON i.name = f.item_code
        INNER JOIN
            `tabWarehouse` w
            ON w.name = f.current_warehouse
        WHERE
            f.parent = %(plan_name)s
            AND f.item_code IS NOT NULL
           
            AND i.item_group IN %(core_item_groups)s
        GROUP BY
            IFNULL(NULLIF(i.variant_of, ''), i.name),
            f.current_department
    """, {
        "plan_name": plan_name,
        "core_item_groups": tuple(PP_MR_CORE_ITEM_GROUPS),
    }, as_dict=1 ,debug=1)
     # AND IFNULL(w.used_for_consumables_stock, 0) = 1
    print("PP MR template_department_qty count:", len(rows))
    return rows


def _get_pp_consumables_by_template(item_templates):
    rows = frappe.db.sql("""
        SELECT
            iw.name AS item_wizard,
            iw.item_template,
            c.item_code,
            c.quantity,
            c.departments
        FROM
            `tabItem Wizards` iw
        INNER JOIN
            `tabConsumables` c
            ON c.parent = iw.name
        WHERE
            iw.item_template IN %(item_templates)s
    """, {
        "item_templates": tuple(item_templates),
    }, as_dict=1,debug=1)

    consumables_by_template = defaultdict(list)
    for row in rows:
        consumables_by_template[row.item_template].append(row)
        print(
            "PP MR consumable row:",
            "item_wizard:", row.item_wizard,
            "item_template:", row.item_template,
            "item_code:", row.item_code,
            "quantity:", row.quantity,
            "departments:", row.departments,
        )

    print("PP MR item_templates count:", len(item_templates))
    print("PP MR consumables rows count:", len(rows))
    return consumables_by_template


def _get_pp_department_consumable_stock(consumable_item_codes, departments):
    if not consumable_item_codes or not departments:
        print("PP MR consumable stock skipped: item codes or departments empty")
        return {}, {}

    item_group_rows = frappe.get_all(
        "Item",
        filters={"name": ["in", consumable_item_codes]},
        fields=["name", "item_group"],
    )
    item_groups = sorted({
        row.item_group
        for row in item_group_rows
        if row.item_group
    })

    print("PP MR consumable item groups:", item_groups)
    if not item_groups:
        print("PP MR consumable stock skipped: no item groups found for consumable item codes")
        return {}, {}

    rows = frappe.db.sql("""
        SELECT
            b.item_code,
            b.warehouse,
            w.department,
            b.actual_qty
        FROM
            `tabBin` b
        INNER JOIN
            `tabWarehouse` w
            ON w.name = b.warehouse
        INNER JOIN
            `tabItem` i
            ON i.name = b.item_code
        WHERE
            w.department IN %(departments)s
            AND b.item_code IN %(consumable_item_codes)s
            AND i.item_group IN %(item_groups)s
            AND b.actual_qty > 0
        ORDER BY
            w.department,
            b.warehouse,
            b.item_code
    """, {
        "consumable_item_codes": tuple(consumable_item_codes),
        "departments": tuple(departments),
        "item_groups": tuple(item_groups),
    }, as_dict=1,debug=1)

    print("PP MR consumable_item_codes count:", len(consumable_item_codes))
    print("PP MR stock departments:", departments)
    print("PP MR department consumable stock rows count:", len(rows))

    stock_by_item = defaultdict(float)
    stock_details_by_item = defaultdict(list)
    for row in rows:
        stock_by_item[row.item_code] += flt(row.actual_qty)
        stock_details_by_item[row.item_code].append({
            "department": row.department,
            "warehouse": row.warehouse,
            "actual_qty": flt(row.actual_qty),
        })
        print(
            "PP MR department stock detail:",
            "department:", row.department,
            "warehouse:", row.warehouse,
            "item_code:", row.item_code,
            "actual_qty:", flt(row.actual_qty),
        )

    print("PP MR department stock aggregated:", dict(stock_by_item))
    return stock_by_item, stock_details_by_item


def _get_pp_consumable_consumed_stock_details(stock_details, required_qty):
    remaining_qty = flt(required_qty)
    consumed_details = []

    for row in stock_details or []:
        if remaining_qty <= PP_MR_MIN_QTY:
            break

        available_qty = flt(row.get("actual_qty"))
        if available_qty <= 0:
            continue

        consumed_qty = min(available_qty, remaining_qty)
        remaining_qty = flt(remaining_qty - consumed_qty, 6)
        consumed_details.append({
            "department": row.get("department"),
            "warehouse": row.get("warehouse"),
            "available_qty": flt(available_qty, 6),
            "consumed_qty": flt(consumed_qty, 6),
            "remaining_required_qty": remaining_qty,
        })

    return consumed_details


def _get_pp_fully_consumed_departments(consumed_stock_details):
    departments = set()
    for row in consumed_stock_details or []:
        available_qty = flt(row.get("available_qty"))
        consumed_qty = flt(row.get("consumed_qty"))
        if available_qty > 0 and abs(available_qty - consumed_qty) <= PP_MR_MIN_QTY:
            departments.add(row.get("department"))

    return {department for department in departments if department}


def _get_pp_shortage_items(template_department_qty, consumables_by_template):
    required_qty_by_item = defaultdict(float)
    schedule_days_by_item = defaultdict(list)
    item_templates_by_item = defaultdict(set)
    stock_departments = set()
    fully_consumed_qty_departments = set()

    for row in template_department_qty:
        item_template = row.item_template
        current_department = row.current_department
        planned_qty = flt(row.planned_qty)

        for consumable in consumables_by_template.get(item_template, []):
            required_qty_by_item[consumable.item_code] += flt(consumable.quantity) * planned_qty
            if item_template:
                item_templates_by_item[consumable.item_code].add(item_template)

            stock_target_departments = []
            if current_department:
                stock_target_departments = _get_pp_previous_two_department_names(current_department)
                stock_target_departments.insert(0, current_department)
                stock_departments.update(stock_target_departments)

            target_departments = _split_pp_department_names(consumable.departments)
            if not target_departments:
                print(
                    "PP MR consumable departments empty:",
                    "item_template:", item_template,
                    "item_code:", consumable.item_code,
                    "default_schedule_days:", PP_MR_DEFAULT_SCHEDULE_DAYS,
                )
                schedule_days_by_item[consumable.item_code].append(PP_MR_DEFAULT_SCHEDULE_DAYS)

            for target_department in target_departments:
                print(
                    "PP MR consumable parsed department:",
                    "item_template:", item_template,
                    "item_code:", consumable.item_code,
                    "current_department:", current_department,
                    "target_department:", target_department,
                    "stock_departments:", stock_target_departments,
                )
                schedule_days_by_item[consumable.item_code].append(
                    _get_pp_schedule_days(current_department, target_department)
                )

    if not required_qty_by_item:
        return []

    item_skip_reasons = _get_pp_item_skip_reasons(list(required_qty_by_item))
    for item_code, reason in sorted(item_skip_reasons.items()):
        print(
            "PP MR skipped consumable item:",
            "item_code:", item_code,
            "required_qty:", required_qty_by_item.get(item_code, 0),
            "reason:", reason,
        )

    valid_item_codes = [
        item_code
        for item_code in required_qty_by_item
        if item_code not in item_skip_reasons
    ]
    if not valid_item_codes:
        print("PP MR no valid consumable items after lifecycle validation")
        return []

    stock_by_item, stock_details_by_item = _get_pp_department_consumable_stock(
        valid_item_codes,
        sorted(stock_departments),
    )

    shortage_items = []
    for item_code, required_qty in required_qty_by_item.items():
        if item_code in item_skip_reasons:
            continue

        available_qty = stock_by_item.get(item_code, 0)
        shortage_qty = required_qty - available_qty
        consumed_stock_details = _get_pp_consumable_consumed_stock_details(
            stock_details_by_item.get(item_code),
            required_qty,
        )
        fully_consumed_qty_departments.update(
            _get_pp_fully_consumed_departments(consumed_stock_details)
        )
        print(
            "PP MR consumable compare:",
            "item_code:", item_code,
            "required_qty:", required_qty,
            "available_qty:", available_qty,
            "shortage_qty:", shortage_qty,
            "consumed_stock_details:", consumed_stock_details,
        )
        if shortage_qty > PP_MR_MIN_QTY:
            shortage_items.append({
                "item_code": item_code,
                "qty": flt(shortage_qty, 6),
                "item_template": ", ".join(sorted(item_templates_by_item.get(item_code) or [])),
                "schedule_days": schedule_days_by_item.get(
                    item_code,
                    [PP_MR_DEFAULT_SCHEDULE_DAYS],
                ),
            })

    for item in shortage_items:
        item["fully_consumed_qty_departments"] = sorted(fully_consumed_qty_departments)

    print("PP MR required consumable items count:", len(required_qty_by_item))
    print("PP MR fully consumed qty departments:", sorted(fully_consumed_qty_departments))
    print("PP MR shortage items count:", len(shortage_items))
    return shortage_items


def _adjust_pp_shortage_qty_for_existing_mrs(shortage_items, material_request_type="Material Issue"):
    if not shortage_items:
        return []

    existing_mr_items = frappe.db.sql("""
        SELECT
            mri.item_code,
            SUM(mri.qty) AS existing_qty,
            GROUP_CONCAT(DISTINCT mr.name ORDER BY mr.name SEPARATOR ', ') AS mr_names
        FROM
            `tabMaterial Request Item` mri
        INNER JOIN
            `tabMaterial Request` mr
            ON mr.name = mri.parent
        WHERE
            mr.material_request_type = %(material_request_type)s
            AND mr.docstatus < 2
            AND mri.item_code IN %(item_codes)s
        GROUP BY
            mri.item_code
    """, {
        "item_codes": tuple(d["item_code"] for d in shortage_items),
        "material_request_type": material_request_type,
    }, as_dict=1)

    if not existing_mr_items:
        print(f"PP MR existing {material_request_type} MR items count: 0")
        return shortage_items

    existing_qty_by_item = {}
    existing_mr_names_by_item = {}
    for row in existing_mr_items:
        existing_qty_by_item[row.item_code] = flt(row.existing_qty)
        existing_mr_names_by_item[row.item_code] = row.mr_names

    adjusted_items = []
    message_rows = []

    for item in shortage_items:
        existing_qty = existing_qty_by_item.get(item["item_code"], 0)
        if existing_qty <= 0:
            adjusted_items.append(item)
            continue

        required_qty = flt(item["qty"])
        pending_qty = required_qty - existing_qty
        existing_mr_names = existing_mr_names_by_item.get(item["item_code"]) or ""

        print(
            "PP MR existing MR adjustment:",
            "type:", material_request_type,
            "item:", item["item_code"],
            "required:", required_qty,
            "existing_qty:", existing_qty,
            "existing_mr_names:", existing_mr_names,
            "new_qty:", max(pending_qty, 0),
        )

        if pending_qty > PP_MR_MIN_QTY:
            adjusted_item = item.copy()
            adjusted_item["qty"] = flt(pending_qty, 6)
            adjusted_items.append(adjusted_item)

        message_rows.append(
            _("Item Code: {0} | Required: {1} | Existing MR Qty: {2} | Existing MR: {3} | New MR Qty: {4}").format(
                frappe.bold(item["item_code"]),
                frappe.bold(required_qty),
                frappe.bold(existing_qty),
                frappe.bold(existing_mr_names or "N/A"),
                frappe.bold(max(pending_qty, 0)),
            )
        )

    print(f"PP MR existing {material_request_type} MR items count:", len(existing_mr_items))
    print("PP MR adjusted shortage items count:", len(adjusted_items))
    if message_rows:
        frappe.msgprint(
            _("Existing {0} Material Request qty adjusted:<br>{1}").format(
                frappe.bold(material_request_type),
                "<br>".join(message_rows)
            ),
            title=_("Material Request Qty Adjusted"),
            indicator="orange",
        )

    return adjusted_items


def mr_raise_from_priduction_plan(doc=None, method=None):
    print("mr_raise_from_priduction_plan")
    plan_name = _get_latest_nj_production_plan_name()
    print("PP MR latest plan:", plan_name)
    if not plan_name:
        return

    template_department_qty = _get_pp_template_department_qty(plan_name)
    print("PP MR grouped template/department rows:", len(template_department_qty))
    if not template_department_qty:
        return

    item_templates = list({row.item_template for row in template_department_qty if row.item_template})
    print("PP MR unique item templates:", len(item_templates))
    if not item_templates:
        return

    consumables_by_template = _get_pp_consumables_by_template(item_templates)
    print("PP MR templates with consumables:", len(consumables_by_template))
    if not consumables_by_template:
        return

    shortage_items = _get_pp_shortage_items(
        template_department_qty,
        consumables_by_template,
    )
    print("PP MR shortage items before existing MR adjustment:", len(shortage_items))
    if not shortage_items:
        return

    shortage_items = _adjust_pp_shortage_qty_for_existing_mrs(shortage_items)
    print("PP MR shortage items after existing MR adjustment:", len(shortage_items))
    item_skip_reasons = _get_pp_item_skip_reasons([item["item_code"] for item in shortage_items])
    if item_skip_reasons:
        valid_shortage_items = []
        for item in shortage_items:
            skip_reason = item_skip_reasons.get(item["item_code"])
            if skip_reason:
                print(
                    "PP MR skipped MR item after existing adjustment:",
                    "item_code:", item["item_code"],
                    "qty:", item["qty"],
                    "reason:", skip_reason,
                )
                continue

            valid_shortage_items.append(item)

        shortage_items = valid_shortage_items

        print("PP MR shortage items after item lifecycle validation:", len(shortage_items))
        if not shortage_items:
            return

    schedule_date = _get_pp_default_mr_schedule_date()
    print("PP MR schedule days:", PP_MR_DEFAULT_SCHEDULE_DAYS)
    print("PP MR schedule date:", schedule_date)

    item_fru_map = {
        d["name"]: d["fru_number"]
        for d in frappe.get_all(
            "Item",
            filters={"name": ["in", [i["item_code"] for i in shortage_items]]},
            fields=["name", "fru_number"],
        )
    }
    print("PP MR FRU map count:", len(item_fru_map))

    mr = frappe.new_doc("Material Request")
    mr.material_request_type = "Material Issue"
    mr.purpose = "Purchase"
    mr.naming_series = "MREQ-.YYYY.-.MM.-"
    mr.title = f"Production Plan - {plan_name}"
    mr.company = _get_pp_default_company()
    mr.mr_mr_create_reference = plan_name
    mr.schedule_date = schedule_date
    mr.post_order_status = ""
    fully_consumed_qty_departments = sorted({
        department
        for item in shortage_items
        for department in item.get("fully_consumed_qty_departments", [])
        if department
    })
    mr.fully_consumed_qty_departments = ", ".join(fully_consumed_qty_departments)
    print(
        "PP MR fully consumed qty departments for MR:",
        mr.fully_consumed_qty_departments or "N/A",
    )

    for item in shortage_items:
        print(
            "PP MR append item:",
            item["item_code"],
            "qty:",
            item["qty"],
            "item_template:",
            item.get("item_template"),
        )
        mr.append("items", {
            "item_code": item["item_code"],
            "qty": _round_pp_qty_for_item_uom(item["item_code"], item["qty"]),
            "create_reference": plan_name,
            "schedule_date": schedule_date,
            "warehouse": PP_MR_STORES_DEPARTMENT,
            "fru_number": item_fru_map.get(item["item_code"]) or "N/A",
            "mavni_comments": item.get("item_template"),
        })

    mr.insert(ignore_permissions=True)
    mr.submit()
    print("PP MR created:", mr.name, "items:", len(shortage_items))

    frappe.msgprint(
        _("Material Request Created from Production Plan {0}: {1}").format(
            frappe.bold(plan_name),
            frappe.bold(mr.name),
        )
    )



# Section 2: collecting all purpose of Material Issue from MR doc and calculating them with store department stock


STOCK_DEPARTMENT_NAME = "Stores - NJ"
PP_MR_ALWAYS_EXCLUDED_STOCK_DEPARTMENTS = {
    "Inward  - NJ",
    "BG -Spare IQC  - NJ",
}


def cosumables_material_issue_mr(doc=None, method=None):
    print("collect_all_purpose_material_issue")

    material_issues = frappe.db.sql("""
        SELECT
            mri.parent,
            mri.item_code,
            mri.qty,
            mri.schedule_date,
            mri.warehouse,
            mri.mavni_comments,
            w.department AS source_department,
            mr.fully_consumed_qty_departments
        FROM `tabMaterial Request Item` mri
        INNER JOIN `tabMaterial Request` mr
            ON mr.name = mri.parent
        LEFT JOIN `tabWarehouse` w
            ON w.name = mri.warehouse
        WHERE mr.material_request_type = 'Material Issue'
        AND mr.docstatus = 1
        AND mr.status NOT IN ('Stopped', 'Cancelled', 'Completed')
        AND mri.item_code IS NOT NULL
        AND mri.item_code != ''
        AND IFNULL(mri.create_reference, '') LIKE 'All Departments%%'
    """, as_dict=True , debug=True)

    print("material_issues===============", material_issues)

    excluded_stock_departments = {
        department
        for row in material_issues
        for department in _split_pp_department_names(row.get("fully_consumed_qty_departments"))
        if department
    }
    excluded_stock_departments.update(PP_MR_ALWAYS_EXCLUDED_STOCK_DEPARTMENTS)
    excluded_stock_departments = sorted(excluded_stock_departments)
    print("all purpose excluded fully consumed stock departments===============", excluded_stock_departments)

    stock_query = """
        SELECT
            b.item_code,
            b.actual_qty,
            b.warehouse,
            w.department,
            i.item_group,
            i.in_stock
        FROM `tabBin` b
        INNER JOIN `tabWarehouse` w
            ON w.name = b.warehouse
        INNER JOIN `tabItem` i
            ON i.name = b.item_code
        WHERE IFNULL(w.department, '') != ''
        {excluded_department_condition}
        AND i.item_group IN (
            'PORT PLUGS',
            'Consumable',
            'Generic Services',
            'Department Consumable',
            'UPPER BUSH',
            'TOUCHPAD SCREW',
            'LAN PORT PLUG',
            'PAINT LAMINATION',
            'HDMI PORT PLUG',
            'BODY A LOGO',
            'GRADE STICKER',
            'TOUCHPAD STICKER',
            'MASKING STICKER',
            'BODY B LOGO',
            'CAMERA LENS',
            'LOWER BUSH',
            'USB PORT PLUG',
            'AUDIO JACK PLUG'
            'BODY C LOGO',
            'BATTERY BUSH'
        )
        AND b.actual_qty > 0 order by i.in_stock desc
    """
    stock_filters = {}
    excluded_department_condition = ""
    if excluded_stock_departments:
        excluded_department_condition = "AND w.department NOT IN %(excluded_stock_departments)s"
        stock_filters["excluded_stock_departments"] = tuple(excluded_stock_departments)

    stock_data = frappe.db.sql(
        stock_query.format(excluded_department_condition=excluded_department_condition),
        stock_filters,
        as_dict=True,debug=1
    )

    print("stock_data===============", stock_data)

    stock_qty_by_item = defaultdict(float)
    stock_warehouse_by_item = {}
    stock_details_by_item = defaultdict(list)
    for row in stock_data:
        stock_qty_by_item[row.item_code] += flt(row.actual_qty)
        stock_warehouse_by_item.setdefault(row.item_code, row.warehouse)
        stock_details_by_item[row.item_code].append({
            "department": row.department,
            "warehouse": row.warehouse,
            "actual_qty": flt(row.actual_qty),
        })

    print("all purpose stock qty by item===============", dict(stock_qty_by_item))
    print("all purpose stock details by item===============", dict(stock_details_by_item))

    issue_qty_by_item = defaultdict(float)
    issue_mr_names_by_item = defaultdict(set)
    issue_warehouse_by_item = {}
    item_templates_by_item = defaultdict(set)
    schedule_days_by_item = defaultdict(list)
    for row in material_issues:
        issue_qty_by_item[row.item_code] += flt(row.qty)
        issue_mr_names_by_item[row.item_code].add(row.parent)
        for item_template in _split_pp_department_names(row.get("mavni_comments")):
            item_templates_by_item[row.item_code].add(item_template)
        if row.get("warehouse"):
            issue_warehouse_by_item.setdefault(row.item_code, row.warehouse)

        if row.get("source_department") and STOCK_DEPARTMENT_NAME:
            schedule_days = _get_pp_schedule_days(
                row.source_department,
                STOCK_DEPARTMENT_NAME,
            )
        else:
            schedule_days = PP_MR_DEFAULT_SCHEDULE_DAYS

        schedule_days_by_item[row.item_code].append(schedule_days)
        print(
            "all purpose schedule days source:",
            "item_code:", row.item_code,
            "material_issue:", row.parent,
            "source_warehouse:", row.get("warehouse"),
            "source_department:", row.get("source_department"),
            "target_department:", STOCK_DEPARTMENT_NAME,
            "schedule_days:", schedule_days,
        )

    print("all purpose material issue qty by item===============", dict(issue_qty_by_item))

    default_target_warehouse = frappe.db.get_value(
        "Warehouse",
        {
            "department": STOCK_DEPARTMENT_NAME,
            "disabled": 0,
        },
        "name",
    )
    print("all purpose default target warehouse===============", default_target_warehouse)

    shortage_items = []
    for item_code, issue_qty in issue_qty_by_item.items():
        skip_reason = _get_laptop_adaptor_item_skip_reason(item_code)
        if skip_reason:
            print(
                "all purpose skipped purchase MR item:",
                "item_code:", item_code,
                "issue_qty:", issue_qty,
                "reason:", skip_reason,
            )
            continue

        stock_qty = flt(stock_qty_by_item.get(item_code))
        shortage_qty = flt(issue_qty - stock_qty, 6)
        issue_mr_names = ", ".join(sorted(issue_mr_names_by_item.get(item_code) or []))
        consumed_stock_details = _get_pp_consumable_consumed_stock_details(
            stock_details_by_item.get(item_code),
            issue_qty,
        )

        print(
            "all purpose compare:",
            "item_code:", item_code,
            "material_issue_qty:", issue_qty,
            "department_stock_qty:", stock_qty,
            "shortage_qty:", shortage_qty,
            "material_issue_mrs:", issue_mr_names,
            "consumed_stock_details:", consumed_stock_details,
        )

        if shortage_qty <= PP_MR_MIN_QTY:
            print(
                "all purpose no Purchase MR required:",
                "item_code:", item_code,
                "stock_qty:", stock_qty,
                "material_issue_qty:", issue_qty,
            )
            continue

        shortage_items.append({
            "item_code": item_code,
            "qty": shortage_qty,
            "warehouse": (
                stock_warehouse_by_item.get(item_code)
                or issue_warehouse_by_item.get(item_code)
                or default_target_warehouse
            ),
            "material_issue_mrs": issue_mr_names,
            "item_template": ", ".join(sorted(item_templates_by_item.get(item_code) or [])),
            "schedule_days": schedule_days_by_item.get(
                item_code,
                [PP_MR_DEFAULT_SCHEDULE_DAYS],
            ),
        })
        print(
            "all purpose creatable Purchase MR item:",
            "item_code:", item_code,
            "qty:", shortage_qty,
            "schedule_days:", schedule_days_by_item.get(item_code, [PP_MR_DEFAULT_SCHEDULE_DAYS]),
            "source_material_issue_mrs:", issue_mr_names,
        )

    print("all purpose shortage item count===============", len(shortage_items))
    if not shortage_items:
        return

    item_stock_rows = frappe.get_all(
        "Item",
        filters={"name": ["in", [item["item_code"] for item in shortage_items]]},
        fields=["name", "in_stock"],
    )
    in_stock_by_item = {
        row.name: bool(flt(row.get("in_stock")))
        for row in item_stock_rows
    }

    shortage_items_by_mr_type = defaultdict(list)
    for item in shortage_items:
        material_request_type = "Manufacture" if in_stock_by_item.get(item["item_code"]) else "Purchase"
        shortage_items_by_mr_type[material_request_type].append(item)
        print(
            "all purpose MR type selected:",
            "item_code:", item["item_code"],
            "qty:", item["qty"],
            "in_stock:", int(in_stock_by_item.get(item["item_code"], False)),
            "material_request_type:", material_request_type,
        )

    created_mrs = []
    for material_request_type in ("Manufacture", "Purchase"):
        typed_shortage_items = shortage_items_by_mr_type.get(material_request_type) or []
        print(
            "all purpose",
            material_request_type,
            "MR shortage item count===============",
            len(typed_shortage_items),
        )
        if not typed_shortage_items:
            continue

        typed_shortage_items = _adjust_pp_shortage_qty_for_existing_mrs(
            typed_shortage_items,
            material_request_type=material_request_type,
        )
        print(
            "all purpose",
            material_request_type,
            "MR shortage item count after existing adjustment===============",
            len(typed_shortage_items),
        )
        if not typed_shortage_items:
            continue

        schedule_date = _get_pp_default_mr_schedule_date()
        print("all purpose", material_request_type, "MR schedule days===============", PP_MR_DEFAULT_SCHEDULE_DAYS)
        print("all purpose", material_request_type, "MR schedule date===============", schedule_date)

        item_fru_map = {
            d["name"]: d["fru_number"]
            for d in frappe.get_all(
                "Item",
                filters={"name": ["in", [i["item_code"] for i in typed_shortage_items]]},
                fields=["name", "fru_number"],
            )
        }

        mr = frappe.new_doc("Material Request")
        mr.material_request_type = material_request_type
        mr.naming_series = "MREQ-.YYYY.-.MM.-"
        mr.title = f"{material_request_type} Against Material Issue - {frappe.utils.nowdate()}"
        mr.company = _get_pp_default_company()
        mr.schedule_date = schedule_date
        mr.mr_create_reference = "NJ Production Planning ALL Material Issue"
        mr.post_order_status = ""

        for item in typed_shortage_items:
            print(
                "all purpose append",
                material_request_type,
                "MR item:",
                "item_code:", item["item_code"],
                "qty:", item["qty"],
                "warehouse:", item.get("warehouse"),
                "item_template:", item.get("item_template"),
                "schedule_days:", item.get("schedule_days"),
                "source_material_issue_mrs:", item.get("material_issue_mrs"),
            )

            item_row = {
                "item_code": item["item_code"],
                "qty": _round_pp_qty_for_item_uom(item["item_code"], item["qty"]),
                "create_reference": "NJ Production Planning ALL Material Issue",
                "schedule_date": schedule_date,
                "fru_number": item_fru_map.get(item["item_code"]) or "N/A",
                "mavni_comments": item.get("item_template"),
            }
            if item.get("warehouse"):
                item_row["warehouse"] = item.get("warehouse")

            mr.append("items", item_row)

        mr.insert(ignore_permissions=True)
        mr.submit()
        created_mrs.append(mr.name)
        print(
            "all purpose",
            material_request_type,
            "MR created:",
            mr.name,
            "items:",
            len(typed_shortage_items),
        )

    if created_mrs:
        frappe.msgprint(
            _("Material Requests Created against Material Issue shortage: {0}").format(
                frappe.bold(", ".join(created_mrs)),
            )
        )

    return created_mrs


# ================================================================================


# Laptop Adaptos MR Section


PP_MR_LAPTOP_ADAPTOR_DEPARTMENT = "BG - Adaptor QC - NJ"
PP_MR_LAPTOP_ADAPTOR_ITEM_GROUP = "Laptop Adaptors"
PP_MR_LAPTOP_ADAPTOR_GRADE = "Grade A"
PP_MR_LAPTOP_ADAPTOR_ATTRIBUTES = ("Brand", "Wattage Capacity", "Adapter Pin Type")


def _normalize_laptop_adaptor_value(value):
    return "".join(str(value or "").upper().split())


def _get_laptop_adaptor_match_key(values):
    return tuple(_normalize_laptop_adaptor_value(value) for value in values)


def _get_laptop_adaptor_item_code_sort_key(item_code):
    parts = re.split(r"(\d+)", str(item_code or "").upper())
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in parts
        if part
    )


def _get_laptop_adaptor_combination_item_code(combination, grade_a_items_by_key, stock_item_by_key):
    key = combination.get("key")
    return grade_a_items_by_key.get(key) or stock_item_by_key.get(key) or ""


def _get_laptop_adaptor_combination_priority(
    combination,
    stock_by_key,
    grade_a_items_by_key,
    stock_item_by_key,
):
    key = combination.get("key")
    item_code = _get_laptop_adaptor_combination_item_code(
        combination,
        grade_a_items_by_key,
        stock_item_by_key,
    )
    stock_qty = flt(stock_by_key.get(key))

    return (
        0 if stock_qty > 0 else 1,
        _get_laptop_adaptor_item_code_sort_key(item_code),
    )


def _dedupe_laptop_adaptor_values(values):
    seen = set()
    result = []
    for value in values:
        normalized_value = _normalize_laptop_adaptor_value(value)
        if not normalized_value or normalized_value in seen:
            continue

        seen.add(normalized_value)
        result.append(value)

    return result


def _get_laptop_adaptor_combinations(attributes):
    attribute_values = []
    for attr in PP_MR_LAPTOP_ADAPTOR_ATTRIBUTES:
        values = attributes.get(attr) or []
        if not isinstance(values, list):
            values = [values]

        values = _dedupe_laptop_adaptor_values(values)
        if not values:
            return []

        attribute_values.append(values)

    return [
        {
            "values": combination,
            "key": _get_laptop_adaptor_match_key(combination),
        }
        for combination in product(*attribute_values)
    ]


def _get_laptop_adaptor_item_key_from_code(item_code):
    code = str(item_code or "")
    prefix = f"S-{PP_MR_LAPTOP_ADAPTOR_ITEM_GROUP}-"
    suffix = f"-{PP_MR_LAPTOP_ADAPTOR_GRADE}"

    if code.upper().startswith(prefix.upper()):
        code = code[len(prefix):]

    if code.upper().endswith(suffix.upper()):
        code = code[:-len(suffix)]

    return _get_laptop_adaptor_match_key(code.split("-"))


def _get_laptop_adaptor_item_skip_reason(item_code, item_doc=None):
    if not item_code:
        return "item code not found"

    if item_doc is None:
        item_doc = frappe.db.get_value(
            "Item",
            item_code,
            ["name", "disabled", "end_of_life"],
            as_dict=True,
        )

    if not item_doc:
        return "item code not found"

    if flt(item_doc.get("disabled")):
        return "item is disabled"

    end_of_life = item_doc.get("end_of_life")
    if end_of_life and frappe.utils.getdate(end_of_life) <= frappe.utils.getdate(frappe.utils.nowdate()):
        return f"item reached end of life on {end_of_life}"

    return None


def _get_laptop_adaptor_mr_serial_nos(serial_nos, qty):
    if isinstance(serial_nos, str):
        serial_nos = [
            serial_no.strip()
            for serial_no in serial_nos.split(",")
            if serial_no.strip()
        ]

    qty = max(int(flt(qty)), 0)
    return list(serial_nos or [])[:qty]


def _get_laptop_adaptor_grade_a_items():
    rows = frappe.db.sql("""
        SELECT
            i.name AS item_code,
            i.disabled,
            i.end_of_life,
            iva.attribute,
            iva.attribute_value
        FROM `tabItem` i
        INNER JOIN `tabItem Variant Attribute` iva
            ON iva.parent = i.name
        WHERE i.item_group = %(item_group)s
            AND iva.attribute IN %(attributes)s
    """, {
        "item_group": PP_MR_LAPTOP_ADAPTOR_ITEM_GROUP,
        "attributes": tuple(PP_MR_LAPTOP_ADAPTOR_ATTRIBUTES + ("Grade",)),
    }, as_dict=True)

    attributes_by_item = defaultdict(dict)
    item_doc_by_item = {}
    for row in rows:
        attributes_by_item[row.item_code][row.attribute] = row.attribute_value
        item_doc_by_item[row.item_code] = row

    items_by_key = {}
    for item_code, attributes in attributes_by_item.items():
        skip_reason = _get_laptop_adaptor_item_skip_reason(
            item_code,
            item_doc_by_item.get(item_code),
        )
        if skip_reason:
            print(
                "PP MR laptop adaptor skipped item:",
                "item_code:", item_code,
                "reason:", skip_reason,
            )
            continue

        if _normalize_laptop_adaptor_value(attributes.get("Grade")) != _normalize_laptop_adaptor_value(PP_MR_LAPTOP_ADAPTOR_GRADE):
            continue

        if not all(attributes.get(attr) for attr in PP_MR_LAPTOP_ADAPTOR_ATTRIBUTES):
            continue

        key = _get_laptop_adaptor_match_key(
            attributes.get(attr) for attr in PP_MR_LAPTOP_ADAPTOR_ATTRIBUTES
        )
        items_by_key[key] = item_code
        print(
            "PP MR laptop adaptor Grade A item mapping:",
            "key:", key,
            "item_code:", item_code,
            "attributes:", attributes,
        )

    print("PP MR laptop adaptor Grade A item count:", len(items_by_key))
    return items_by_key


def _build_laptop_adaptor_shortage_items(item_wizard_data, department_stock):
    grade_a_items_by_key = _get_laptop_adaptor_grade_a_items()

    stock_by_key = defaultdict(float)
    stock_item_by_key = {}
    stock_details_by_key = defaultdict(list)
    for row in department_stock:
        skip_reason = _get_laptop_adaptor_item_skip_reason(row.item_code, row)
        if skip_reason:
            print(
                "PP MR laptop adaptor skipped stock item:",
                "item_code:", row.item_code,
                "warehouse:", row.warehouse,
                "stock_qty:", flt(row.stock_qty),
                "reason:", skip_reason,
            )
            continue

        key = _get_laptop_adaptor_item_key_from_code(row.item_code)
        stock_by_key[key] += flt(row.stock_qty)
        stock_item_by_key[key] = row.item_code
        stock_details_by_key[key].append({
            "department": row.department,
            "warehouse": row.warehouse,
            "stock_qty": flt(row.stock_qty),
        })
        print(
            "PP MR laptop adaptor stock mapping:",
            "key:", key,
            "item_code:", row.item_code,
            "stock_qty:", flt(row.stock_qty),
            "warehouse:", row.warehouse,
            "department:", row.department,
        )

    shortage_by_item = {}
    schedule_days_by_item = defaultdict(list)
    wizard_candidates = []

    for wizard_row in item_wizard_data:
        attributes = wizard_row.get("attributes") or {}
        missing_attributes = [
            attr for attr in PP_MR_LAPTOP_ADAPTOR_ATTRIBUTES
            if not attributes.get(attr)
        ]
        if missing_attributes:
            print(
                "PP MR laptop adaptor missing attributes:",
                wizard_row.get("item_wizard"),
                missing_attributes,
            )
            continue

        combinations = _get_laptop_adaptor_combinations(attributes)
        print(
            "PP MR laptop adaptor wizard combinations:=========",
            "item_wizard:", wizard_row.get("item_wizard"),
            "serial_no_count:", wizard_row.get("serial_no_count"),
            "combination_count:", len(combinations),
        )
        for combination in combinations:
            print(
                "PP MR laptop adaptor wizard combination:",
                "item_wizard:", wizard_row.get("item_wizard"),
                "values:", combination["values"],
                "key:", combination["key"],
                "item_code:", grade_a_items_by_key.get(combination["key"]) or stock_item_by_key.get(combination["key"]),
                "stock_qty:", flt(stock_by_key.get(combination["key"])),
            )

        valid_combinations = [
            combination for combination in combinations
            if grade_a_items_by_key.get(combination["key"]) or stock_item_by_key.get(combination["key"])
        ]
        print(
            "PP MR laptop adaptor valid combination count:",
            "item_wizard:", wizard_row.get("item_wizard"),
            "count:", len(valid_combinations),
        )

        if not valid_combinations:
            print(
                "PP MR laptop adaptor item not found for wizard combinations:",
                wizard_row.get("item_wizard"),
                attributes,
            )
            continue

        wizard_candidates.append({
            "wizard_row": wizard_row,
            "valid_combinations": valid_combinations,
        })

    wizard_candidates.sort(
        key=lambda row: (
            len(row["valid_combinations"]),
            str(row["wizard_row"].get("item_wizard") or ""),
        )
    )

    for candidate in wizard_candidates:
        wizard_row = candidate["wizard_row"]
        valid_combinations = candidate["valid_combinations"]
        sorted_combinations = sorted(
            valid_combinations,
            key=lambda combination: _get_laptop_adaptor_item_code_sort_key(
                _get_laptop_adaptor_combination_item_code(
                    combination,
                    grade_a_items_by_key,
                    stock_item_by_key,
                )
            ),
        )

        required_qty = flt(wizard_row.get("serial_no_count"))
        remaining_qty = required_qty
        stock_usage = []
        stock_used_departments = set()

        for combination in sorted_combinations:
            key = combination["key"]
            item_code = _get_laptop_adaptor_combination_item_code(
                combination,
                grade_a_items_by_key,
                stock_item_by_key,
            )
            available_qty = flt(stock_by_key.get(key))
            if available_qty <= 0 or remaining_qty <= 0:
                continue

            used_qty = min(available_qty, remaining_qty)
            stock_by_key[key] = flt(available_qty - used_qty, 6)
            remaining_qty = flt(remaining_qty - used_qty, 6)
            stock_after = flt(stock_by_key.get(key), 6)
            remaining_required_qty = flt(remaining_qty, 6)
            detail_remaining_qty = flt(used_qty)
            stock_used_department_details = []
            for stock_detail in stock_details_by_key.get(key, []):
                if detail_remaining_qty <= 0:
                    break

                detail_stock_qty = flt(stock_detail.get("stock_qty"))
                if detail_stock_qty <= 0:
                    continue

                detail_used_qty = min(detail_stock_qty, detail_remaining_qty)
                stock_detail["stock_qty"] = flt(detail_stock_qty - detail_used_qty, 6)
                detail_remaining_qty = flt(detail_remaining_qty - detail_used_qty, 6)
                if stock_detail.get("department"):
                    stock_used_departments.add(stock_detail.get("department"))
                stock_used_department_details.append({
                    "department": stock_detail.get("department"),
                    "warehouse": stock_detail.get("warehouse"),
                    "used_qty": flt(detail_used_qty, 6),
                })

            stock_usage.append({
                "item_code": item_code,
                "combination": combination["values"],
                "key": key,
                "used_qty": flt(used_qty, 6),
                "stock_before": flt(available_qty, 6),
                "stock_after": stock_after,
                "remaining_required_qty": remaining_required_qty,
                "department_details": stock_used_department_details,
            })
            print(
                "PP MR laptop adaptor stock consumed:",
                "item_wizard:", wizard_row.get("item_wizard"),
                "item_wizard_qty:", required_qty,
                "combination_count:", len(valid_combinations),
                "combination:", combination["values"],
                "combo_key:", key,
                "item_code:", item_code,
                "stock_before:", flt(available_qty, 6),
                "consume_qty:", flt(used_qty, 6),
                "stock_after:", stock_after,
                "remaining_required_qty:", remaining_required_qty,
                "stock_used_department_details:", stock_used_department_details,
                "stock_used_departments:", sorted(stock_used_departments),
            )

        if not stock_usage:
            print(
                "PP MR laptop adaptor no stock consumed:",
                "item_wizard:", wizard_row.get("item_wizard"),
                "item_wizard_qty:", required_qty,
                "combination_count:", len(valid_combinations),
                "combinations:", [
                    {
                        "values": combination.get("values"),
                        "key": combination.get("key"),
                        "item_code": _get_laptop_adaptor_combination_item_code(
                            combination,
                            grade_a_items_by_key,
                            stock_item_by_key,
                        ),
                        "available_stock": flt(stock_by_key.get(combination.get("key")), 6),
                    }
                    for combination in sorted_combinations
                ],
            )

        shortage_qty = remaining_qty
        shortage_combination = sorted_combinations[0]
        shortage_item_code = _get_laptop_adaptor_combination_item_code(
            shortage_combination,
            grade_a_items_by_key,
            stock_item_by_key,
        )

        print(
            "PP MR laptop adaptor compare:",
            wizard_row.get("item_wizard"),
            "combination_count:", len(valid_combinations),
            "preferred_shortage_item:", shortage_item_code,
            "required:", required_qty,
            "stock_usage:", stock_usage,
            "shortage:", shortage_qty,
        )

        if shortage_qty > PP_MR_MIN_QTY:
            stock_consumed_qty = flt(required_qty - shortage_qty, 6)
            serial_no_list = list(wizard_row.get("serial_nos") or [])
            shortage_serial_nos = serial_no_list[
                int(stock_consumed_qty):int(stock_consumed_qty + shortage_qty)
            ]
            shortage_item = shortage_by_item.setdefault(shortage_item_code, {
                "item_code": shortage_item_code,
                "qty": 0,
                "schedule_days": [],
                "serial_nos": [],
                "mr_rised_departments": set(),
            })
            shortage_item["qty"] = flt(shortage_item["qty"] + shortage_qty, 6)
            shortage_item["serial_nos"].extend(shortage_serial_nos)
            shortage_item["mr_rised_departments"].update(stock_used_departments)
            print(
                "PP MR laptop adaptor creatable MR item:",
                "item_wizard:", wizard_row.get("item_wizard"),
                "item_code:", shortage_item_code,
                "qty_to_raise:", flt(shortage_qty, 6),
                "serial_nos:", shortage_serial_nos,
                "mr_rised_departments:", sorted(shortage_item["mr_rised_departments"]),
            )
        else:
            print(
                "PP MR laptop adaptor no MR required:",
                "item_wizard:", wizard_row.get("item_wizard"),
                "stock_usage:", stock_usage,
                "required_qty:", required_qty,
            )

        for current_department in wizard_row.get("current_departments") or []:
            schedule_days_by_item[shortage_item_code].append(
                _get_pp_schedule_days(current_department, PP_MR_LAPTOP_ADAPTOR_DEPARTMENT)
            )

    shortage_items = list(shortage_by_item.values())
    for item in shortage_items:
        item["schedule_days"] = schedule_days_by_item.get(
            item["item_code"],
            [PP_MR_DEFAULT_SCHEDULE_DAYS],
        )
        item["serial_nos"] = ", ".join(item.get("serial_nos") or [])
        item["mr_rised_departments"] = ", ".join(sorted(item.get("mr_rised_departments") or []))

    print("PP MR laptop adaptor shortage items count:", len(shortage_items))
    for item in shortage_items:
        print(
            "PP MR laptop adaptor final shortage item:",
            "item_code:", item["item_code"],
            "qty:", item["qty"],
            "schedule_days:", item.get("schedule_days"),
            "serial_nos:", item.get("serial_nos"),
            "mr_rised_departments:", item.get("mr_rised_departments"),
        )
    return shortage_items


def _create_laptop_adaptor_mr(plan_name, shortage_items):
    if not shortage_items:
        return None

    valid_shortage_items = []
    for item in shortage_items:
        skip_reason = _get_laptop_adaptor_item_skip_reason(item.get("item_code"))
        if skip_reason:
            print(
                "PP MR laptop adaptor skipped MR item:",
                "item_code:", item.get("item_code"),
                "qty:", item.get("qty"),
                "reason:", skip_reason,
            )
            continue

        valid_shortage_items.append(item)

    if not valid_shortage_items:
        print("PP MR laptop adaptor no valid shortage items after item lifecycle validation")
        return None

    shortage_items = valid_shortage_items

    schedule_date = _get_pp_default_mr_schedule_date()
    print("PP MR laptop adaptor schedule days:", PP_MR_DEFAULT_SCHEDULE_DAYS)
    print("PP MR laptop adaptor schedule date:", schedule_date)

    item_fru_map = {
        d["name"]: d["fru_number"]
        for d in frappe.get_all(
            "Item",
            filters={"name": ["in", [i["item_code"] for i in shortage_items]]},
            fields=["name", "fru_number"],
        )
    }

    mr = frappe.new_doc("Material Request")
    mr.material_request_type = "Material Issue"
    mr.purpose = "Purchase"
    mr.naming_series = "MREQ-.YYYY.-.MM.-"
    mr.title = f"Laptop Adaptors - {plan_name}"
    mr.company = _get_pp_default_company()
    mr.mr_create_reference = "Laptop Adaptor NJ Production"
    mr.mr_rised_departments = ", ".join(sorted({
        department
        for item in shortage_items
        for department in _split_pp_department_names(item.get("mr_rised_departments"))
        if department
    }))
    mr.schedule_date = schedule_date
    mr.post_order_status = ""

    for item in shortage_items:
        mr_qty = _round_pp_qty_for_item_uom(item["item_code"], item["qty"])
        mr_serial_nos = _get_laptop_adaptor_mr_serial_nos(item.get("serial_nos"), mr_qty)
        print(
            "PP MR laptop adaptor append item:",
            item["item_code"],
            "qty:",
            item["qty"],
            "serial_nos:",
            mr_serial_nos,
        )
        mr.append("items", {
            "item_code": item["item_code"],
            "qty": mr_qty,
            "schedule_date": schedule_date,
            "create_reference": "Laptop Adaptor NJ Production",
            "warehouse": PP_MR_STORES_DEPARTMENT,
            "fru_number": item_fru_map.get(item["item_code"]) or "N/A",
            "mavni_comments": ", ".join(mr_serial_nos),
        })

    mr.insert(ignore_permissions=True)
    mr.submit()
    print("PP MR laptop adaptor created:", mr.name, "items:", len(shortage_items))

    frappe.msgprint(
        _("Laptop Adaptor Material Request Created from Production Plan {0}: {1}").format(
            frappe.bold(plan_name),
            frappe.bold(mr.name),
        )
    )
    return mr.name


def get_stock_from_department():
    stock_data = frappe.db.sql("""
        SELECT      
            b.item_code,
            i.item_name,
            i.item_group,
            i.disabled,
            i.end_of_life,
            SUM(b.actual_qty) AS stock_qty,
            b.warehouse,
            w.department
        FROM `tabBin` AS b
        INNER JOIN `tabWarehouse` AS w
            ON w.name = b.warehouse
        INNER JOIN `tabItem` AS i
            ON i.name = b.item_code
        INNER JOIN `tabItem Variant Attribute` AS iva
            ON iva.parent = i.name
        WHERE w.department = %(department)s
            AND i.item_group = %(item_group)s
            AND iva.attribute = 'Grade'
            AND iva.attribute_value = %(grade)s
            AND b.actual_qty > 0
        GROUP BY b.item_code, i.item_name, i.item_group, i.disabled, i.end_of_life, b.warehouse, w.department
        ORDER BY b.item_code
    """, {
        "department": PP_MR_LAPTOP_ADAPTOR_DEPARTMENT,
        "item_group": PP_MR_LAPTOP_ADAPTOR_ITEM_GROUP,
        "grade": PP_MR_LAPTOP_ADAPTOR_GRADE,
    }, as_dict=True, debug=1)

    print("\nAdaptor Stock Details =====================")

    for row in stock_data:
        print(f"""
Item Code   : {row.item_code}
Item Name   : {row.item_name}
Item Group  : {row.item_group}
Stock Qty   : {row.stock_qty}
Warehouse   : {row.warehouse}
=============================================
""")

    return stock_data


def _get_laptop_adaptor_departments_from_settings():
    departments = (
        frappe.db.get_value("NJ Settings", {"parameter": "adaptore_departments"}, "value")
    )
    print("departmentss========================================",departments)
    return [d.strip() for d in str(departments).split(",") if d.strip()]


def get_laptop_adaptor_serial_nos(production_plan):
    adaptor_departments = _get_laptop_adaptor_departments_from_settings()
    print("Laptop adaptor departments from settings:", adaptor_departments)

    serial_nos = frappe.db.sql("""
        SELECT
            fppd.parent,
            GROUP_CONCAT(fppd.serial_no ORDER BY fppd.serial_no) AS serial_nos,
            GROUP_CONCAT(fppd.current_department) AS current_departments,
            sn.item_wizard,
            COUNT(*) AS serial_no_count
        FROM `tabFinal Production Planning Data` fppd
        INNER JOIN `tabDepartment` d
            ON fppd.current_department = d.name
        INNER JOIN `tabSerial No` AS sn
            ON sn.name = fppd.serial_no
        WHERE fppd.parent = %(production_plan)s
            AND IFNULL(fppd.serial_no, '') != ''
            AND d.department_sequence IN (
                SELECT department_sequence
                FROM `tabDepartment`
                WHERE name IN %(adaptor_departments)s

                UNION

                SELECT department_sequence - 1
                FROM `tabDepartment`
                WHERE name IN %(adaptor_departments)s
            )
            AND NOT EXISTS (
                SELECT 1
                FROM `tabSerial No Component` AS snc
                WHERE snc.parent = fppd.serial_no
                AND snc.item_group = 'Laptop Adaptors'
            )
        GROUP BY sn.item_wizard
    """, {
        "production_plan": production_plan,
        "adaptor_departments": tuple(adaptor_departments),
    }, as_dict=True, debug=1)

    print("Filtered Item Wizards ========")

    item_wizard_data = []

    print("serial_nos======================", serial_nos)

    for row in serial_nos:

        print(f"\nItem Wizard ===== {row.item_wizard}")

        serial_no_list = [
            serial_no.strip()
            for serial_no in str(row.serial_nos or "").split(",")
            if serial_no.strip()
        ]
        department_list = [
            department.strip()
            for department in str(row.current_departments or "").split(",")
            if department.strip()
        ]
        serial_count_by_department = Counter(department_list)
        current_departments = sorted({
            department for department in department_list if department
        })

        print("Production Plan ======================", row.parent)
        # print("Adaptor Department ===================", PP_MR_LAPTOP_ADAPTOR_DEPARTMENT)
        print("Laptop Adaptor Serial Count ==========", int(row.serial_no_count or 0))
        print("Laptop Adaptor Serial Count Map ======", dict(serial_count_by_department))
        print("Laptop Adaptor MR Qty Count ==========", int(row.serial_no_count or 0))
        print("Laptop Adaptor Serial Nos ============", serial_no_list)

        attributes = frappe.db.sql("""
            SELECT 
                c.item_attribute,
                c.attribute_value
            FROM `tabItems Attribute` AS c
            INNER JOIN `tabItem Wizards` AS p
                ON c.parent = p.name
            WHERE p.name = %s
                AND c.item_attribute IN (
                    'Brand',
                    'Wattage Capacity',
                    'Adapter Pin Type'
                )
        """, (row.item_wizard,), as_dict=True, debug=1)

        attribute_dict = defaultdict(list)
        for d in attributes:
            attribute_dict[d.item_attribute].append(d.attribute_value)
        attribute_dict = {
            item_attribute: _dedupe_laptop_adaptor_values(attribute_values)
            for item_attribute, attribute_values in attribute_dict.items()
        }

        print("attribute_dict======================", attribute_dict)

        item_wizard_data.append({
            "item_wizard": row.item_wizard,
            "serial_no_count": int(row.serial_no_count or 0),
            "actual_serial_no_count": len(serial_no_list),
            "serial_nos": serial_no_list,
            "current_departments": current_departments,
            "attributes": attribute_dict
        })

    return item_wizard_data


def mr_raise_for_laptop_adaptors(doc=None, method=None):
    print("mr_raise_for_laptop_adaptors")
    latest_name = _get_latest_nj_production_plan_name()
    print("PP MR latest plan:=======", latest_name)
    if not latest_name:
        return

    laptop_adaptor_serial_nos = get_laptop_adaptor_serial_nos(latest_name)
    print("PP MR laptop adaptor serial nos count:", len(laptop_adaptor_serial_nos))
    if not laptop_adaptor_serial_nos:
        return

    dp_stock =get_stock_from_department()
    print("PP MR department stock count:", dp_stock)

    shortage_items = _build_laptop_adaptor_shortage_items(
        laptop_adaptor_serial_nos,
        dp_stock,
    )
    print("PP MR laptop adaptor shortage items before existing MR adjustment:", len(shortage_items))
    if not shortage_items:
        return

    shortage_items = _adjust_pp_shortage_qty_for_existing_mrs(
        shortage_items,
        material_request_type="Material Issue",
    )
    print("PP MR laptop adaptor shortage items after existing MR adjustment:", len(shortage_items))
    if not shortage_items:
        return

    return _create_laptop_adaptor_mr(latest_name, shortage_items)



# Section 1: collecting all purpose of Material Issue from MR doc and calculating them with store department stock 

PP_MR_ALL_PURPOSE_STOCK_DEPARTMENT = "Stores - NJ"


def _get_all_purpose_adaptor_base_item_code(item_code):
    return re.sub(
        r"-GRADE\s+[A-Z]\s*$",
        "",
        str(item_code or "").strip(),
        flags=re.IGNORECASE,
    ).strip()


def _get_all_purpose_adaptor_grade(item_code):
    match = re.search(r"-GRADE\s+([A-Z])\s*$", str(item_code or "").strip(), flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _get_all_purpose_item_match_keys(item_codes):
    item_codes = [item_code for item_code in item_codes if item_code]
    if not item_codes:
        return {}

    rows = frappe.db.sql("""
        SELECT
            i.name AS item_code,
            i.item_group,
            iva.attribute,
            iva.attribute_value
        FROM `tabItem` i
        LEFT JOIN `tabItem Variant Attribute` iva
            ON iva.parent = i.name
        WHERE i.name IN %(item_codes)s
    """, {
        "item_codes": tuple(item_codes),
    }, as_dict=True)

    item_group_by_item = {}
    attributes_by_item = defaultdict(dict)
    for row in rows:
        item_group_by_item[row.item_code] = row.item_group
        if row.attribute:
            attributes_by_item[row.item_code][row.attribute] = row.attribute_value

    match_key_by_item = {}
    for item_code in item_codes:
        item_group = item_group_by_item.get(item_code) or ""
        normalized_item_group = _normalize_laptop_storage_value(item_group)

        if normalized_item_group == _normalize_laptop_storage_value(PP_MR_LAPTOP_ADAPTOR_ITEM_GROUP):
            match_key_by_item[item_code] = (
                PP_MR_LAPTOP_ADAPTOR_ITEM_GROUP,
                _get_all_purpose_adaptor_base_item_code(item_code),
            )
            continue

        if normalized_item_group == _normalize_laptop_storage_value(PP_MR_LAPTOP_RAM_ITEM_GROUP):
            attributes = attributes_by_item.get(item_code) or {}
            if all(attributes.get(attr) for attr in PP_MR_LAPTOP_RAM_ITEM_ATTRIBUTES):
                ram_key = _get_laptop_ram_match_key(
                    attributes.get(attr)
                    for attr in PP_MR_LAPTOP_RAM_ITEM_ATTRIBUTES
                )
            else:
                ram_key = _get_laptop_ram_key_from_item_code(item_code)

            match_key_by_item[item_code] = (
                PP_MR_LAPTOP_RAM_ITEM_GROUP,
                ram_key or _get_all_purpose_adaptor_base_item_code(item_code),
            )
            continue

        if normalized_item_group == _normalize_laptop_storage_value(PP_MR_LAPTOP_STORAGE_ITEM_GROUP):
            attributes = attributes_by_item.get(item_code) or {}
            if all(attributes.get(attr) for attr in PP_MR_LAPTOP_STORAGE_ITEM_ATTRIBUTES):
                storage_key = _get_laptop_storage_match_key(
                    attributes.get(attr)
                    for attr in PP_MR_LAPTOP_STORAGE_ITEM_ATTRIBUTES
                )
            else:
                storage_key = _get_laptop_storage_key_from_item_code(item_code)

            match_key_by_item[item_code] = (
                PP_MR_LAPTOP_STORAGE_ITEM_GROUP,
                storage_key or _get_all_purpose_adaptor_base_item_code(item_code),
            )

    print("all purpose item match key map===============", match_key_by_item)
    return match_key_by_item


def _add_all_purpose_shortage_item(shortage_by_item, item_code, qty, warehouse, source_item_code, material_issue_mrs, schedule_days):
    if flt(qty) <= PP_MR_MIN_QTY:
        return

    item = shortage_by_item.setdefault(item_code, {
        "item_code": item_code,
        "qty": 0,
        "warehouse": warehouse,
        "source_item_codes": set(),
        "material_issue_mrs": set(),
        "schedule_days": [],
    })
    item["qty"] = flt(item["qty"] + qty, 6)
    if warehouse and not item.get("warehouse"):
        item["warehouse"] = warehouse
    if source_item_code:
        item["source_item_codes"].add(source_item_code)
    item["material_issue_mrs"].update(material_issue_mrs or [])
    item["schedule_days"].extend(schedule_days or [PP_MR_DEFAULT_SCHEDULE_DAYS])


def collect_all_purpose_material_issue(doc=None, method=None):

    
    print("collect_all_purpose_material_issue")

    stock_data = frappe.db.sql("""
        SELECT
            b.item_code,
            b.actual_qty,
            b.warehouse,
            i.item_group
        FROM `tabBin` b
        INNER JOIN `tabItem` i
            ON i.name = b.item_code
        WHERE b.warehouse IN (
            SELECT name
            FROM `tabWarehouse`
            WHERE department IN (
                SELECT name
                FROM `tabDepartment`
            )
        )
        AND i.item_group IN ('Laptop Adaptors', 'Laptop RAM', 'Laptop Storage')
        AND b.actual_qty > 0
        AND (
            b.item_code LIKE '%%GRADE A%%'
            OR b.item_code LIKE '%%GRADE D%%'
            OR (
                i.item_group = 'Laptop Adaptors'
                AND b.item_code LIKE '%%GRADE B%%'
            )
        )
    """, as_dict=True)

    print("stock_data===============", stock_data)

    material_issues = frappe.db.sql("""
        SELECT
            mri.parent,
            mri.item_code,
            mri.qty,
            mri.schedule_date,
            mri.warehouse,
            i.item_group,
            w.department AS source_department
        FROM `tabMaterial Request Item` mri
        INNER JOIN `tabMaterial Request` mr
            ON mr.name = mri.parent
        INNER JOIN `tabItem` i
            ON i.name = mri.item_code
        LEFT JOIN `tabWarehouse` w
            ON w.name = mri.warehouse
        WHERE mr.material_request_type = 'Material Issue'
        AND mr.docstatus = 1
        AND mr.status NOT IN ('Stopped', 'Cancelled', 'Completed')
        AND i.item_group IN ('Laptop Adaptors', 'Laptop RAM', 'Laptop Storage')
        AND mri.item_code IS NOT NULL
        AND mri.item_code != ''
        AND mri.item_code LIKE '%%GRADE A%%'
        AND (
            IFNULL(mri.create_reference, '') LIKE 'Laptop Storage%%'
            OR IFNULL(mri.create_reference, '') LIKE 'Laptop RAM%%'
            OR IFNULL(mri.create_reference, '') LIKE 'Laptop Adaptor%%'
        )
    """, as_dict=True)

    print("material_issues===============", material_issues)

    match_key_by_item = _get_all_purpose_item_match_keys(
        {
            row.item_code
            for row in list(stock_data or []) + list(material_issues or [])
            if row.get("item_code")
        }
    )

    stock_qty_by_item = defaultdict(float)
    stock_warehouse_by_item = {}
    grade_a_stock_by_key = defaultdict(float)
    grade_b_stock_by_key = defaultdict(float)
    grade_d_stock_by_key = defaultdict(float)
    grade_b_item_by_key = {}
    grade_d_item_by_key = {}
    for row in stock_data:
        stock_qty_by_item[row.item_code] += flt(row.actual_qty)
        stock_warehouse_by_item.setdefault(row.item_code, row.warehouse)
        item_key = match_key_by_item.get(row.item_code)
        grade = _get_all_purpose_adaptor_grade(row.item_code)
        if not item_key:
            print(
                "all purpose stock key skipped:",
                "item_code:", row.item_code,
                "item_group:", row.item_group,
                "stock_qty:", flt(row.actual_qty),
                "warehouse:", row.warehouse,
            )
            continue

        if grade == "A":
            grade_a_stock_by_key[item_key] += flt(row.actual_qty)
        elif grade == "B":
            grade_b_stock_by_key[item_key] += flt(row.actual_qty)
            grade_b_item_by_key.setdefault(item_key, row.item_code)
        elif grade == "D":
            grade_d_stock_by_key[item_key] += flt(row.actual_qty)
            grade_d_item_by_key.setdefault(item_key, row.item_code)

    print("all purpose stock qty by item===============", dict(stock_qty_by_item))
    print("all purpose GRADE A stock by key===============", dict(grade_a_stock_by_key))
    print("all purpose GRADE B stock by key===============", dict(grade_b_stock_by_key))
    print("all purpose GRADE D stock by key===============", dict(grade_d_stock_by_key))

    issue_qty_by_item = defaultdict(float)
    issue_mr_names_by_item = defaultdict(set)
    issue_warehouse_by_item = {}
    issue_item_group_by_item = {}
    schedule_days_by_item = defaultdict(list)
    for row in material_issues:
        issue_qty_by_item[row.item_code] += flt(row.qty)
        issue_mr_names_by_item[row.item_code].add(row.parent)
        issue_item_group_by_item[row.item_code] = row.item_group
        if row.get("warehouse"):
            issue_warehouse_by_item.setdefault(row.item_code, row.warehouse)

        if row.get("source_department") and PP_MR_ALL_PURPOSE_STOCK_DEPARTMENT:
            schedule_days = _get_pp_schedule_days(
                row.source_department,
                PP_MR_ALL_PURPOSE_STOCK_DEPARTMENT,
            )
        else:
            schedule_days = PP_MR_DEFAULT_SCHEDULE_DAYS

        schedule_days_by_item[row.item_code].append(schedule_days)
        print(
            "all purpose schedule days source:",
            "item_code:", row.item_code,
            "material_issue:", row.parent,
            "source_warehouse:", row.get("warehouse"),
            "source_department:", row.get("source_department"),
            "target_department:", PP_MR_ALL_PURPOSE_STOCK_DEPARTMENT,
            "schedule_days:", schedule_days,
        )

    print("all purpose material issue qty by item===============", dict(issue_qty_by_item))

    default_target_warehouse = frappe.db.get_value(
        "Warehouse",
        {
            "department": PP_MR_ALL_PURPOSE_STOCK_DEPARTMENT,
            "disabled": 0,
        },
        "name",
    )
    print("all purpose default target warehouse===============", default_target_warehouse)

    manufacture_shortage_by_item = {}
    purchase_shortage_by_item = {}
    for item_code, issue_qty in issue_qty_by_item.items():
        skip_reason = _get_laptop_adaptor_item_skip_reason(item_code)
        if skip_reason:
            print(
                "all purpose skipped adaptor Material Issue item:",
                "item_code:", item_code,
                "item_group:", issue_item_group_by_item.get(item_code),
                "issue_qty:", issue_qty,
                "reason:", skip_reason,
            )
            continue

        item_key = match_key_by_item.get(item_code)
        if not item_key:
            print(
                "all purpose skipped Material Issue item key not found:",
                "item_code:", item_code,
                "item_group:", issue_item_group_by_item.get(item_code),
                "issue_qty:", issue_qty,
            )
            continue

        grade_a_stock_qty = flt(grade_a_stock_by_key.get(item_key))
        remaining_after_grade_a = flt(issue_qty - grade_a_stock_qty, 6)
        is_laptop_adaptor = (
            _normalize_laptop_storage_value(issue_item_group_by_item.get(item_code))
            == _normalize_laptop_storage_value(PP_MR_LAPTOP_ADAPTOR_ITEM_GROUP)
        )
        grade_d_item_code = grade_d_item_by_key.get(item_key)
        grade_d_stock_qty = flt(grade_d_stock_by_key.get(item_key))
        grade_b_item_code = grade_b_item_by_key.get(item_key) if is_laptop_adaptor else None
        grade_b_stock_qty = flt(grade_b_stock_by_key.get(item_key)) if is_laptop_adaptor else 0
        manufacture_qty_from_grade_d = min(max(remaining_after_grade_a, 0), grade_d_stock_qty)
        remaining_after_grade_d = flt(remaining_after_grade_a - manufacture_qty_from_grade_d, 6)
        manufacture_qty_from_grade_b = min(max(remaining_after_grade_d, 0), grade_b_stock_qty)
        purchase_qty = flt(max(remaining_after_grade_d - manufacture_qty_from_grade_b, 0), 6)
        issue_mr_names = sorted(issue_mr_names_by_item.get(item_code) or [])
        schedule_days = schedule_days_by_item.get(item_code, [PP_MR_DEFAULT_SCHEDULE_DAYS])

        print(
            "all purpose adaptor compare:",
            "item_code:", item_code,
            "item_group:", issue_item_group_by_item.get(item_code),
            "item_key:", item_key,
            "material_issue_qty:", issue_qty,
            "grade_a_stock_qty:", grade_a_stock_qty,
            "remaining_after_grade_a:", remaining_after_grade_a,
            "grade_d_item_code:", grade_d_item_code,
            "grade_d_stock_qty:", grade_d_stock_qty,
            "manufacture_qty_from_grade_d:", manufacture_qty_from_grade_d,
            "grade_b_item_code:", grade_b_item_code,
            "grade_b_stock_qty:", grade_b_stock_qty,
            "manufacture_qty_from_grade_b:", manufacture_qty_from_grade_b,
            "purchase_qty_for_grade_a:", purchase_qty,
            "material_issue_mrs:", ", ".join(issue_mr_names),
        )

        if remaining_after_grade_a <= PP_MR_MIN_QTY:
            print(
                "all purpose adaptor no MR required:",
                "item_code:", item_code,
                "item_group:", issue_item_group_by_item.get(item_code),
                "grade_a_stock_qty:", grade_a_stock_qty,
                "material_issue_qty:", issue_qty,
            )
            continue

        if manufacture_qty_from_grade_d > PP_MR_MIN_QTY and grade_d_item_code:
            _add_all_purpose_shortage_item(
                manufacture_shortage_by_item,
                grade_d_item_code,
                manufacture_qty_from_grade_d,
                stock_warehouse_by_item.get(grade_d_item_code) or default_target_warehouse,
                item_code,
                issue_mr_names,
                schedule_days,
            )
            print(
                "all purpose creatable Manufacture MR item from GRADE D:",
                "source_grade_a_item_code:", item_code,
                "item_group:", issue_item_group_by_item.get(item_code),
                "grade_d_item_code:", grade_d_item_code,
                "qty:", manufacture_qty_from_grade_d,
                "schedule_days:", schedule_days,
                "source_material_issue_mrs:", ", ".join(issue_mr_names),
            )

        if manufacture_qty_from_grade_b > PP_MR_MIN_QTY and grade_b_item_code:
            _add_all_purpose_shortage_item(
                manufacture_shortage_by_item,
                grade_b_item_code,
                manufacture_qty_from_grade_b,
                stock_warehouse_by_item.get(grade_b_item_code) or default_target_warehouse,
                item_code,
                issue_mr_names,
                schedule_days,
            )
            print(
                "all purpose creatable Manufacture MR item from GRADE B:",
                "source_grade_a_item_code:", item_code,
                "item_group:", issue_item_group_by_item.get(item_code),
                "grade_b_item_code:", grade_b_item_code,
                "qty:", manufacture_qty_from_grade_b,
                "schedule_days:", schedule_days,
                "source_material_issue_mrs:", ", ".join(issue_mr_names),
            )

        if purchase_qty > PP_MR_MIN_QTY:
            _add_all_purpose_shortage_item(
                purchase_shortage_by_item,
                item_code,
                purchase_qty,
                (
                    stock_warehouse_by_item.get(item_code)
                    or issue_warehouse_by_item.get(item_code)
                    or default_target_warehouse
                ),
                item_code,
                issue_mr_names,
                schedule_days,
            )
            print(
                "all purpose creatable Purchase MR item for GRADE A:",
                "item_code:", item_code,
                "item_group:", issue_item_group_by_item.get(item_code),
                "qty:", purchase_qty,
                "schedule_days:", schedule_days,
                "source_material_issue_mrs:", ", ".join(issue_mr_names),
            )

    shortage_items_by_mr_type = {
        "Manufacture": list(manufacture_shortage_by_item.values()),
        "Purchase": list(purchase_shortage_by_item.values()),
    }

    for material_request_type, items in shortage_items_by_mr_type.items():
        for item in items:
            item["source_item_codes"] = ", ".join(sorted(item.get("source_item_codes") or []))
            item["material_issue_mrs"] = ", ".join(sorted(item.get("material_issue_mrs") or []))

    print("all purpose Manufacture MR shortage item count===============", len(shortage_items_by_mr_type["Manufacture"]))
    print("all purpose Purchase MR shortage item count===============", len(shortage_items_by_mr_type["Purchase"]))
    if not shortage_items_by_mr_type["Manufacture"] and not shortage_items_by_mr_type["Purchase"]:
        return

    created_mrs = []
    for material_request_type in ("Manufacture", "Purchase"):
        shortage_items = shortage_items_by_mr_type.get(material_request_type) or []
        if not shortage_items:
            continue

        shortage_items = _adjust_pp_shortage_qty_for_existing_mrs(
            shortage_items,
            material_request_type=material_request_type,
        )
        print(
            "all purpose",
            material_request_type,
            "MR shortage item count after existing adjustment===============",
            len(shortage_items),
        )
        if not shortage_items:
            continue

        schedule_date = _get_pp_default_mr_schedule_date()
        print("all purpose", material_request_type, "MR schedule days===============", PP_MR_DEFAULT_SCHEDULE_DAYS)
        print("all purpose", material_request_type, "MR schedule date===============", schedule_date)

        item_fru_map = {
            d["name"]: d["fru_number"]
            for d in frappe.get_all(
                "Item",
                filters={"name": ["in", [i["item_code"] for i in shortage_items]]},
                fields=["name", "fru_number"],
            )
        }

        mr = frappe.new_doc("Material Request")
        mr.material_request_type = material_request_type
        mr.naming_series = "MREQ-.YYYY.-.MM.-"
        mr.title = f"{material_request_type} Against Material Issue - {frappe.utils.nowdate()}"
        mr.company = _get_pp_default_company()
        mr.schedule_date = schedule_date
        mr.mr_create_reference = "SRA Item Group NJ Production"
        mr.post_order_status = ""

        for item in shortage_items:
            print(
                "all purpose append",
                material_request_type,
                "MR item:",
                "item_code:", item["item_code"],
                "qty:", item["qty"],
                "warehouse:", item.get("warehouse"),
                "schedule_days:", item.get("schedule_days"),
                "source_item_codes:", item.get("source_item_codes"),
                "source_material_issue_mrs:", item.get("material_issue_mrs"),
            )

            item_row = {
                "item_code": item["item_code"],
                "qty": _round_pp_qty_for_item_uom(item["item_code"], item["qty"]),
                "schedule_date": schedule_date,
                "create_reference": "SRA Item Group NJ Production",
                "fru_number": item_fru_map.get(item["item_code"]) or "N/A",
            }
            if item.get("warehouse"):
                item_row["warehouse"] = item.get("warehouse")

            mr.append("items", item_row)

        mr.insert(ignore_permissions=True)
        mr.submit()
        created_mrs.append(mr.name)
        print(
            "all purpose",
            material_request_type,
            "MR created:",
            mr.name,
            "items:",
            len(shortage_items),
        )

    if created_mrs:
        frappe.msgprint(
            _("Material Requests Created against Material Issue shortage: {0}").format(
                frappe.bold(", ".join(created_mrs)),
            )
        )

    return created_mrs


# ===============================================================
#Laptop Ram MR Section=======

PP_MR_LAPTOP_RAM_ITEM_GROUP = "Laptop RAM"
PP_MR_LAPTOP_RAM_GRADE = "GRADE A"
PP_MR_LAPTOP_RAM_ATTRIBUTES = ("RAM Type", "RAM Speed")
PP_MR_LAPTOP_RAM_ITEM_ATTRIBUTES = ("RAM Type", "RAM Capacity", "RAM Speed")


def get_diff_ram_item_code(production_plan):
    
    print("Laptop RAM MR production_plan:", production_plan)
    if not production_plan:
        print("Laptop RAM MR skipped: production_plan not found")
        return []

    serial_nos = frappe.db.sql("""
        SELECT 
            c.serial_no,
            sn.item_code,
            sn.to_make,
            sn.item_wizard,
            c.current_department,
            d.name AS current_department_name,
            d.department_sequence AS current_department_sequence      

        FROM `tabFinal Production Planning Data` AS c

        INNER JOIN `tabSerial No` AS sn
            ON sn.name = c.serial_no

        INNER JOIN `tabDepartment` AS d
            ON d.name = c.current_department

        WHERE sn.item_code != sn.to_make
            AND c.parent= %(production_plan)s
            AND IFNULL(c.serial_no, '') != ''
            AND d.department_sequence IN (
                SELECT department_sequence
                FROM `tabDepartment`
                WHERE allow_reconfig=1

                UNION

                SELECT department_sequence - 1
                FROM `tabDepartment`
                WHERE allow_reconfig=1
            )
    """, {
        "production_plan": production_plan,
    }, as_dict=True, debug=1)

    print("Laptop RAM MR diff RAM serial count:", len(serial_nos))
    for row in serial_nos:
        print(
            "Laptop RAM MR diff RAM serial:",
            "serial_no:", row.serial_no,
            "current_item_code:", row.item_code,
            "to_make:", row.to_make,
            "item_wizard:", row.item_wizard,
            "current_department:", row.current_department,
            "current_department_sequence:", row.current_department_sequence,

        )

    return serial_nos


def _parse_laptop_ram_capacity(ram_capacity):
    value = str(ram_capacity or "").strip()
    normalized_value = value.upper()
    if normalized_value in ("", "NO RAM", "NONE", "N/A", "NA"):
        return 0.0, ""

    match = re.search(r"(\d+(?:\.\d+)?)", value)
    if not match:
        return 0.0, value

    qty = flt(match.group(1))
    ram_type = value[match.end():].strip()
    return qty, ram_type


def _is_no_laptop_ram_capacity(ram_capacity):
    normalized_value = str(ram_capacity or "").strip().upper()
    return normalized_value in ("", "NO RAM", "NONE", "N/A", "NA")


def _format_laptop_ram_capacity(qty, ram_type):
    if flt(qty) <= 0:
        return ""

    qty_display = int(qty) if float(qty).is_integer() else qty
    return f"{qty_display} {ram_type}".strip()


def _is_standard_laptop_ram_capacity(value):
    qty = _get_laptop_ram_capacity_qty(value)
    if qty < 4 or not float(qty).is_integer():
        return False

    qty = int(qty)
    return qty > 0 and (qty & (qty - 1)) == 0


def _get_required_ram_capacity_diff(current_ram, to_make_ram):
    current_qty, current_type = _parse_laptop_ram_capacity(current_ram)
    to_make_qty, to_make_type = _parse_laptop_ram_capacity(to_make_ram)
    diff_qty = abs(to_make_qty - current_qty)

    if diff_qty <= 0:
        return ""

    ram_type = to_make_type if to_make_qty > current_qty else current_type
    if not ram_type:
        ram_type = to_make_type or current_type

    return _format_laptop_ram_capacity(diff_qty, ram_type)


def _get_required_ram_capacity_for_slots(current_ram, to_make_ram, ram_slots):
    if _is_no_laptop_ram_capacity(to_make_ram):
        return ""

    if ram_slots == "Single Slot":
        to_make_qty, to_make_type = _parse_laptop_ram_capacity(to_make_ram)
        return _format_laptop_ram_capacity(to_make_qty, to_make_type)

    if ram_slots == "Dual Slot":
        return _get_required_ram_capacity_diff(current_ram, to_make_ram)

    return ""


def _get_dual_slot_larger_ram_parts(current_ram, to_make_ram):
    current_qty, current_type = _parse_laptop_ram_capacity(current_ram)
    to_make_qty, to_make_type = _parse_laptop_ram_capacity(to_make_ram)
    larger_qty = max(current_qty, to_make_qty)

    if larger_qty <= 0:
        return 0.0, ""

    if to_make_qty >= current_qty:
        ram_type = to_make_type or current_type
    else:
        ram_type = current_type or to_make_type

    return larger_qty, ram_type


def _get_dual_slot_ram_capacity_options(current_ram, to_make_ram):
    """
    Dual-slot RAM can be satisfied either by one full-size module or two half-size
    modules. Include those real module sizes so the MR does not request fake
    capacities such as 48 GB or 24 GB.
    """
    larger_qty, ram_type = _get_dual_slot_larger_ram_parts(current_ram, to_make_ram)
    if larger_qty <= 0:
        return []

    options = []
    half_qty = larger_qty / 2
    if half_qty > 0:
        options.append({
            "required_ram_capacity": _format_laptop_ram_capacity(half_qty, ram_type),
            "required_ram_qty": 2,
            "choice": "dual_half",
        })

    options.append({
        "required_ram_capacity": _format_laptop_ram_capacity(larger_qty, ram_type),
        "required_ram_qty": 1,
        "choice": "dual_full",
    })

    return [
        option
        for option in options
        if option.get("required_ram_capacity")
        and _is_standard_laptop_ram_capacity(option.get("required_ram_capacity"))
    ]


def _get_matching_laptop_ram_combinations(wizard_combo, required_ram_capacity):
    return [
        combination
        for combination in (wizard_combo or {}).get("valid_combinations") or []
        if _laptop_ram_combination_matches_required(combination, required_ram_capacity)
    ]


def _get_laptop_ram_matching_stock_qty(matching_combinations, stock_by_item_code):
    stock_qty = 0.0
    for combination in matching_combinations or []:
        stock_qty += flt(stock_by_item_code.get(combination.get("item_code")))

    return stock_qty


def _resolve_dual_slot_laptop_ram_requirement(row, wizard_combo, stock_by_item_code):
    original_required_ram_capacity = row.get("required_ram_capacity")
    original_matches = _get_matching_laptop_ram_combinations(
        wizard_combo,
        original_required_ram_capacity,
    )
    if original_matches and _is_standard_laptop_ram_capacity(original_required_ram_capacity):
        return {
            "required_ram_capacity": original_required_ram_capacity,
            "required_ram_qty": 1,
            "choice": "dual_diff",
        }

    options = _get_dual_slot_ram_capacity_options(
        row.get("current_ram_capacity"),
        row.get("to_make_ram_capacity"),
    )
    if not options:
        return {
            "required_ram_capacity": original_required_ram_capacity,
            "required_ram_qty": 1,
            "choice": "dual_original",
        }

    valid_options = []
    for option in options:
        matching_combinations = _get_matching_laptop_ram_combinations(
            wizard_combo,
            option.get("required_ram_capacity"),
        )
        if not matching_combinations:
            continue

        valid_options.append({
            **option,
            "stock_qty": _get_laptop_ram_matching_stock_qty(
                matching_combinations,
                stock_by_item_code,
            ),
        })

    if not valid_options:
        return {
            "required_ram_capacity": original_required_ram_capacity,
            "required_ram_qty": 1,
            "choice": "dual_original",
        }

    half_options = [
        option
        for option in valid_options
        if option.get("choice") == "dual_half"
    ]
    full_options = [
        option
        for option in valid_options
        if option.get("choice") == "dual_full"
    ]

    stocked_half_options = [
        option
        for option in half_options
        if flt(option.get("stock_qty")) > 0
    ]
    if stocked_half_options:
        return stocked_half_options[0]

    if full_options:
        return full_options[0]

    return valid_options[0]


def get_only_ram_diff_item_codes(serial_rows):
    print("Laptop RAM MR RAM Capacity filter started")
    if not serial_rows:
        print("Laptop RAM MR RAM Capacity filter skipped: no serial rows")
        return []

    item_codes = set()
    for row in serial_rows:
        if row.get("item_code"):
            item_codes.add(row.get("item_code"))
        if row.get("to_make"):
            item_codes.add(row.get("to_make"))

    if not item_codes:
        print("Laptop RAM MR RAM Capacity filter skipped: no item codes")
        return []

    serial_nos = [
        row.get("serial_no")
        for row in serial_rows
        if row.get("serial_no")
    ]

    ram_rows = frappe.db.sql("""
        SELECT
            parent AS item_code,
            attribute_value AS ram_capacity
        FROM `tabItem Variant Attribute`
        WHERE parent IN %(item_codes)s
            AND attribute = %(ram_attr)s
    """, {
        "item_codes": tuple(item_codes),
        "ram_attr": RAM_ATTR,
    }, as_dict=True , debug=1)

    ram_by_item_code = {
        row.item_code: (row.ram_capacity or "").strip()
        for row in ram_rows
    }
    print("Laptop RAM MR RAM Capacity map:", ram_by_item_code)

    ram_slot_by_serial_no = {}
    if serial_nos:
        ram_slot_rows = frappe.db.sql("""
            SELECT
                sn.name AS serial_no,
                f.values AS ram_slots
            FROM `tabSerial No` AS sn
            INNER JOIN `tabItem Wizards` AS it
                ON it.name = sn.item_wizard
            INNER JOIN `tabFeatures child table` AS f
                ON f.parent = it.name
            WHERE sn.name IN %(serial_nos)s
                AND f.features_attributes = 'RAM Slots'
        """, {
            "serial_nos": tuple(serial_nos),
        }, as_dict=True)

        ram_slot_by_serial_no = {
            row.serial_no: (row.ram_slots or "").strip()
            for row in ram_slot_rows
        }

    print("Laptop RAM MR RAM Slots map:", ram_slot_by_serial_no)

    valid_ram_slots = {"Single Slot", "Dual Slot"}
    ram_diff_rows = []
    for row in serial_rows:
        current_ram = ram_by_item_code.get(row.get("item_code"), "")
        to_make_ram = ram_by_item_code.get(row.get("to_make"), "")
        ram_slots = ram_slot_by_serial_no.get(row.get("serial_no"), "")
        is_ram_diff = current_ram != to_make_ram
        required_ram_capacity = _get_required_ram_capacity_for_slots(
            current_ram,
            to_make_ram,
            ram_slots,
        )

        print(
            "Laptop RAM MR RAM Capacity compare:",
            "serial_no:", row.get("serial_no"),
            "current_item_code:", row.get("item_code"),
            "current_ram:", current_ram,
            "to_make:", row.get("to_make"),
            "to_make_ram:", to_make_ram,
            "ram_slots:", ram_slots,
            "required_ram_capacity:", required_ram_capacity,
            "is_ram_diff:", int(is_ram_diff),
        )

        if not is_ram_diff:
            continue

        if ram_slots not in valid_ram_slots:
            print(
                "Laptop RAM MR skipped invalid RAM Slots:",
                "serial_no:", row.get("serial_no"),
                "ram_slots:", ram_slots or "N/A",
            )
            continue

        if not required_ram_capacity:
            print(
                "Laptop RAM MR skipped no MR required:",
                "serial_no:", row.get("serial_no"),
                "current_ram:", current_ram,
                "to_make_ram:", to_make_ram,
                "ram_slots:", ram_slots,
            )
            continue

        row["current_ram_capacity"] = current_ram
        row["to_make_ram_capacity"] = to_make_ram
        row["required_ram_capacity"] = required_ram_capacity
        row["ram_slots"] = ram_slots
        ram_diff_rows.append(row)

    print("Laptop RAM MR actual RAM diff serial count:", len(ram_diff_rows))
    return ram_diff_rows


def _normalize_laptop_ram_value(value):
    return "".join(str(value or "").upper().split())


def _normalize_laptop_ram_attr_value(attribute, value):
    if attribute == "RAM Capacity":
        qty = _get_laptop_ram_capacity_qty(value)
        if qty <= 0:
            return ""

        qty_display = int(qty) if float(qty).is_integer() else qty
        return f"{qty_display}GB"

    if attribute == "RAM Speed":
        raw_value = str(value or "").strip()
        match = re.search(r"(\d+(?:\.\d+)?)", raw_value)
        if not match:
            return _normalize_laptop_ram_value(raw_value)

        speed = match.group(1)
        if re.search(r"\b(MHZ|GHZ)\b", raw_value, flags=re.IGNORECASE):
            unit = re.search(r"\b(MHZ|GHZ)\b", raw_value, flags=re.IGNORECASE).group(1).upper()
        else:
            unit = "GHZ"

        return _normalize_laptop_ram_value(f"{speed} {unit}")

    return _normalize_laptop_ram_value(value)


def _get_laptop_ram_match_key(values):
    return tuple(
        _normalize_laptop_ram_attr_value(attribute, value)
        for attribute, value in zip(PP_MR_LAPTOP_RAM_ITEM_ATTRIBUTES, values)
    )


def _get_laptop_ram_key_from_item_code(item_code):
    code = str(item_code or "").strip()
    if not code:
        return None

    cleaned = re.sub(
        rf"-{re.escape(PP_MR_LAPTOP_RAM_GRADE)}$",
        "",
        code,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^S-Laptop\s+RAM[-\s]*", "", cleaned, flags=re.IGNORECASE)

    parts = [part.strip() for part in cleaned.split("-") if part.strip()]
    ram_type = ""
    ram_capacity = ""
    ram_speed = ""

    for part in parts:
        if not ram_type and re.search(r"\b(?:LPDDR|DDR)\w*\b", part, flags=re.IGNORECASE):
            ram_type = part
            continue

        if not ram_capacity and re.search(r"\d+(?:\.\d+)?\s*GB\b", part, flags=re.IGNORECASE):
            ram_capacity = part
            continue

        if not ram_speed and re.search(r"\d+", part):
            ram_speed = part

    if not ram_type or not ram_capacity or not ram_speed:
        return None

    return _get_laptop_ram_match_key((ram_type, ram_capacity, ram_speed))


def _get_laptop_ram_item_code_sort_key(item_code):
    parts = re.split(r"(\d+)", str(item_code or "").upper())
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in parts
        if part
    )


def _dedupe_laptop_ram_values(values):
    seen = set()
    result = []
    for value in values:
        normalized_value = _normalize_laptop_ram_value(value)
        if not normalized_value or normalized_value in seen:
            continue

        seen.add(normalized_value)
        result.append(value)

    return result


def _get_laptop_ram_combinations(attributes):
    attribute_values = []
    for attr in PP_MR_LAPTOP_RAM_ITEM_ATTRIBUTES:
        values = attributes.get(attr) or []
        if not isinstance(values, list):
            values = [values]

        values = _dedupe_laptop_ram_values(values)
        if not values:
            return []

        attribute_values.append(values)

    return [
        {
            "values": combination,
            "key": _get_laptop_ram_match_key(combination),
        }
        for combination in product(*attribute_values)
    ]


def _get_laptop_ram_grade_a_items():
    rows = frappe.db.sql("""
        SELECT
            i.name AS item_code,
            i.disabled,
            i.end_of_life,
            iva.attribute,
            iva.attribute_value
        FROM `tabItem` i
        INNER JOIN `tabItem Variant Attribute` iva
            ON iva.parent = i.name
        WHERE i.item_group = %(item_group)s
            AND iva.attribute IN %(attributes)s
    """, {
        "item_group": PP_MR_LAPTOP_RAM_ITEM_GROUP,
        "attributes": tuple(PP_MR_LAPTOP_RAM_ITEM_ATTRIBUTES + ("Grade",)),
    }, as_dict=True)

    attributes_by_item = defaultdict(dict)
    for row in rows:
        attributes_by_item[row.item_code][row.attribute] = row.attribute_value

    items_by_key = {}
    for item_code, attributes in attributes_by_item.items():
        if _normalize_laptop_ram_value(attributes.get("Grade")) != _normalize_laptop_ram_value(PP_MR_LAPTOP_RAM_GRADE):
            continue

        if all(attributes.get(attr) for attr in PP_MR_LAPTOP_RAM_ITEM_ATTRIBUTES):
            key = _get_laptop_ram_match_key(
                attributes.get(attr) for attr in PP_MR_LAPTOP_RAM_ITEM_ATTRIBUTES
            )
        else:
            key = _get_laptop_ram_key_from_item_code(item_code)

        if not key:
            continue

        items_by_key[key] = item_code
        # print(
        #     "Laptop RAM MR Grade A item mapping:",
        #     "key:", key,
        #     "item_code:", item_code,
        #     "attributes:", attributes,
        # )

    print("Laptop RAM MR Grade A item count:", len(items_by_key))
    return items_by_key


def _get_laptop_ram_capacity_qty(value):
    match = re.search(r"(\d+(?:\.\d+)?)", str(value or ""))
    return flt(match.group(1)) if match else 0.0


def _get_laptop_ram_capacity_item_value(value):
    qty = _get_laptop_ram_capacity_qty(value)
    return _format_laptop_ram_capacity(qty, "GB")


def _get_laptop_ram_type_token(value):
    match = re.search(r"\bDDR\w*\b", str(value or "").upper())
    return _normalize_laptop_ram_value(match.group(0)) if match else ""


def _laptop_ram_combination_matches_required(combination, required_ram_capacity):
    values = combination.get("values") or ()
    if len(values) < 3:
        return False

    combo_ram_type, combo_ram_capacity, _combo_ram_speed = values
    required_qty = _get_laptop_ram_capacity_qty(required_ram_capacity)
    combo_qty = _get_laptop_ram_capacity_qty(combo_ram_capacity)
    if required_qty <= 0 or combo_qty <= 0 or required_qty != combo_qty:
        return False

    required_type = _get_laptop_ram_type_token(required_ram_capacity)
    if required_type and _normalize_laptop_ram_value(combo_ram_type) != required_type:
        return False

    return True


def build_laptop_ram_wizard_combinations(ram_diff_rows, ram_stock_rows):
    print("Laptop RAM MR wizard combination build started")
    if not ram_diff_rows:
        print("Laptop RAM MR wizard combination skipped: no RAM diff rows")
        return []

    item_wizards = sorted({
        row.get("item_wizard")
        for row in ram_diff_rows
        if row.get("item_wizard")
    })
    if not item_wizards:
        print("Laptop RAM MR wizard combination skipped: no item wizards")
        return []

    grade_a_items_by_key = _get_laptop_ram_grade_a_items()
    stock_item_to_key = {
        item_code: key
        for key, item_code in grade_a_items_by_key.items()
    }

    stock_by_key = defaultdict(float)
    stock_details_by_key = defaultdict(list)
    for row in ram_stock_rows or []:
        key = stock_item_to_key.get(row.item_code) or _get_laptop_ram_key_from_item_code(row.item_code)
        if not key:
            print(
                "Laptop RAM MR stock item key not found:",
                "item_code:", row.item_code,
                "stock_qty:", flt(row.stock_qty),
                "warehouse:", row.warehouse,
            )
            continue

        grade_a_items_by_key.setdefault(key, row.item_code)
        stock_by_key[key] += flt(row.stock_qty)
        stock_details_by_key[key].append({
            "department": row.department,
            "warehouse": row.warehouse,
            "stock_qty": flt(row.stock_qty),
        })

    wizard_attr_rows = frappe.db.sql("""
        SELECT
            parent AS item_wizard,
            item_attribute,
            attribute_value
        FROM `tabItems Attribute`
        WHERE parent IN %(item_wizards)s
            AND item_group = %(item_group)s
            AND item_attribute IN %(attributes)s
    """, {
        "item_wizards": tuple(item_wizards),
        "item_group": PP_MR_LAPTOP_RAM_ITEM_GROUP,
        "attributes": tuple(PP_MR_LAPTOP_RAM_ATTRIBUTES),
    }, as_dict=True)

    attributes_by_wizard = defaultdict(lambda: defaultdict(list))
    for row in wizard_attr_rows:
        attributes_by_wizard[row.item_wizard][row.item_attribute].append(row.attribute_value)

    serial_rows_by_wizard = defaultdict(list)
    for row in ram_diff_rows:
        if row.get("item_wizard"):
            serial_rows_by_wizard[row.get("item_wizard")].append(row)

    wizard_combinations = []
    for item_wizard in item_wizards:
        serial_rows = serial_rows_by_wizard.get(item_wizard, [])
        attributes = {
            attr: _dedupe_laptop_ram_values(values)
            for attr, values in attributes_by_wizard.get(item_wizard, {}).items()
        }
        required_ram_capacity_values = []
        for row in serial_rows:
            if row.get("required_ram_capacity") and (
                row.get("ram_slots") != "Dual Slot"
                or _is_standard_laptop_ram_capacity(row.get("required_ram_capacity"))
            ):
                required_ram_capacity_values.append(
                    _get_laptop_ram_capacity_item_value(row.get("required_ram_capacity"))
                )

            if row.get("ram_slots") == "Dual Slot":
                required_ram_capacity_values.extend(
                    _get_laptop_ram_capacity_item_value(option.get("required_ram_capacity"))
                    for option in _get_dual_slot_ram_capacity_options(
                        row.get("current_ram_capacity"),
                        row.get("to_make_ram_capacity"),
                    )
                    if option.get("required_ram_capacity")
                )

        required_ram_capacities = _dedupe_laptop_ram_values(required_ram_capacity_values)
        if required_ram_capacities:
            attributes["RAM Capacity"] = required_ram_capacities
        combinations = _get_laptop_ram_combinations(attributes)

        print(
            "Laptop RAM MR wizard combinations:=========",
            "item_wizard:", item_wizard,
            "serial_no_count:", len(serial_rows),
            "combination_count:", len(combinations),
            "attributes:", attributes,
        )

        valid_combinations = []
        for combination in combinations:
            item_code = grade_a_items_by_key.get(combination["key"])
            stock_qty = flt(stock_by_key.get(combination["key"]))
            print(
                "Laptop RAM MR wizard combination:",
                "item_wizard:", item_wizard,
                "values:", combination["values"],
                "key:", combination["key"],
                "item_code:", item_code,
                "stock_qty:", stock_qty,
            )

            if item_code:
                valid_combinations.append({
                    "values": combination["values"],
                    "key": combination["key"],
                    "item_code": item_code,
                    "stock_qty": stock_qty,
                    "stock_details": stock_details_by_key.get(combination["key"], []),
                })

        print(
            "Laptop RAM MR valid combination count:",
            "item_wizard:", item_wizard,
            "count:", len(valid_combinations),
        )

        wizard_combinations.append({
            "item_wizard": item_wizard,
            "serial_no_count": len(serial_rows),
            "serial_nos": [row.get("serial_no") for row in serial_rows],
            "ram_slots": sorted({
                row.get("ram_slots")
                for row in serial_rows
                if row.get("ram_slots")
            }),
            "attributes": attributes,
            "combinations": combinations,
            "valid_combinations": valid_combinations,
        })

    return wizard_combinations


def build_laptop_ram_shortage_items(diff_ram_serials, ram_wizard_combinations):
    print("Laptop RAM MR shortage build started")
    if not diff_ram_serials:
        print("Laptop RAM MR shortage skipped: no RAM diff serials")
        return []

    wizard_combo_by_name = {
        row["item_wizard"]: row
        for row in ram_wizard_combinations or []
        if row.get("item_wizard")
    }

    stock_by_item_code = defaultdict(float)
    stock_details_by_item_code = {}
    for wizard_row in ram_wizard_combinations or []:
        for combination in wizard_row.get("valid_combinations") or []:
            item_code = combination.get("item_code")
            if not item_code:
                continue
            stock_by_item_code[item_code] = max(
                stock_by_item_code[item_code],
                flt(combination.get("stock_qty")),
            )
            stock_details_by_item_code.setdefault(item_code, [
                dict(detail)
                for detail in combination.get("stock_details") or []
            ])

    print("Laptop RAM MR virtual stock by item:", dict(stock_by_item_code))

    resolved_diff_ram_serials = []
    for row in diff_ram_serials:
        resolved_row = dict(row)
        resolved_row["required_ram_qty"] = flt(resolved_row.get("required_ram_qty") or 1)

        if row.get("ram_slots") == "Dual Slot":
            wizard_combo = wizard_combo_by_name.get(row.get("item_wizard")) or {}
            resolved_requirement = _resolve_dual_slot_laptop_ram_requirement(
                row,
                wizard_combo,
                stock_by_item_code,
            )
            resolved_row["required_ram_capacity"] = resolved_requirement.get("required_ram_capacity")
            resolved_row["required_ram_qty"] = flt(resolved_requirement.get("required_ram_qty") or 1)
            resolved_row["dual_slot_choice"] = resolved_requirement.get("choice")
            print(
                "Laptop RAM MR dual slot resolved:",
                "serial_no:", row.get("serial_no"),
                "current_ram:", row.get("current_ram_capacity"),
                "to_make_ram:", row.get("to_make_ram_capacity"),
                "original_required_ram_capacity:", row.get("required_ram_capacity"),
                "resolved_required_ram_capacity:", resolved_row.get("required_ram_capacity"),
                "required_ram_qty:", resolved_row.get("required_ram_qty"),
                "choice:", resolved_row.get("dual_slot_choice"),
            )

        resolved_diff_ram_serials.append(resolved_row)

    grouped_serials = defaultdict(list)
    for row in resolved_diff_ram_serials:
        group_key = (
            row.get("ram_slots"),
            row.get("item_wizard"),
            row.get("required_ram_capacity"),
        )
        grouped_serials[group_key].append(row)

    slot_priority = {"Single Slot": 0, "Dual Slot": 1}
    shortage_by_item_code = {}

    for group_key, serial_rows in sorted(
        grouped_serials.items(),
        key=lambda item: (
            slot_priority.get(item[0][0], 99),
            str(item[0][1] or ""),
            str(item[0][2] or ""),
        ),
    ):
        ram_slots, item_wizard, required_ram_capacity = group_key
        required_qty = flt(sum(flt(row.get("required_ram_qty") or 1) for row in serial_rows), 6)
        remaining_qty = required_qty
        group_stock_used_departments = set()
        wizard_combo = wizard_combo_by_name.get(item_wizard) or {}
        matching_combinations = _get_matching_laptop_ram_combinations(
            wizard_combo,
            required_ram_capacity,
        )
        matching_combinations.sort(
            key=lambda combination: (
                0 if stock_by_item_code.get(combination.get("item_code"), 0) > 0 else 1,
                _get_laptop_ram_item_code_sort_key(combination.get("item_code")),
            )
        )

        print(
            "Laptop RAM MR demand group:",
            "ram_slots:", ram_slots,
            "item_wizard:", item_wizard,
            "required_ram_capacity:", required_ram_capacity,
            "serial_count:", len(serial_rows),
            "required_qty:", required_qty,
            "matching_combination_count:", len(matching_combinations),
            "serial_nos:", [row.get("serial_no") for row in serial_rows],
        )

        for combination in matching_combinations:
            if remaining_qty <= 0:
                break

            item_code = combination.get("item_code")
            available_qty = flt(stock_by_item_code.get(item_code))
            if available_qty <= 0:
                continue

            consumed_qty = min(available_qty, remaining_qty)
            stock_by_item_code[item_code] = flt(available_qty - consumed_qty, 6)
            remaining_qty = flt(remaining_qty - consumed_qty, 6)
            detail_remaining_qty = flt(consumed_qty)
            stock_used_department_details = []
            for stock_detail in stock_details_by_item_code.get(item_code, []):
                if detail_remaining_qty <= 0:
                    break

                detail_stock_qty = flt(stock_detail.get("stock_qty"))
                if detail_stock_qty <= 0:
                    continue

                detail_consumed_qty = min(detail_stock_qty, detail_remaining_qty)
                stock_detail["stock_qty"] = flt(detail_stock_qty - detail_consumed_qty, 6)
                detail_remaining_qty = flt(detail_remaining_qty - detail_consumed_qty, 6)
                if stock_detail.get("department"):
                    group_stock_used_departments.add(stock_detail.get("department"))
                stock_used_department_details.append({
                    "department": stock_detail.get("department"),
                    "warehouse": stock_detail.get("warehouse"),
                    "deducted_qty": flt(detail_consumed_qty, 6),
                })

            print(
                "Laptop RAM MR stock consumed:",
                "ram_slots:", ram_slots,
                "item_wizard:", item_wizard,
                "required_ram_capacity:", required_ram_capacity,
                "item_code:", item_code,
                "stock_before:", available_qty,
                "consume_qty:", consumed_qty,
                "stock_after:", stock_by_item_code[item_code],
                "remaining_required_qty:", remaining_qty,
                "stock_used_department_details:", stock_used_department_details,
                "stock_used_departments:", sorted(group_stock_used_departments),
            )

        if remaining_qty <= 0:
            print(
                "Laptop RAM MR no shortage:",
                "ram_slots:", ram_slots,
                "item_wizard:", item_wizard,
                "required_ram_capacity:", required_ram_capacity,
            )
            continue

        if not matching_combinations:
            print(
                "Laptop RAM MR shortage skipped no matching item code:",
                "ram_slots:", ram_slots,
                "item_wizard:", item_wizard,
                "required_ram_capacity:", required_ram_capacity,
                "shortage_qty:", remaining_qty,
            )
            continue

        shortage_item_code = matching_combinations[0].get("item_code")
        shortage_item = shortage_by_item_code.setdefault(shortage_item_code, {
            "item_code": shortage_item_code,
            "qty": 0,
            "ram_slots": set(),
            "item_wizards": set(),
            "required_ram_capacities": set(),
            "serial_nos": [],
            "department_serial_counts": Counter(),
            "mr_rised_departments": set(),
        })
        shortage_item["qty"] = flt(shortage_item["qty"] + remaining_qty, 6)
        shortage_item["ram_slots"].add(ram_slots)
        shortage_item["item_wizards"].add(item_wizard)
        shortage_item["required_ram_capacities"].add(required_ram_capacity)
        required_serial_nos = []
        for row in serial_rows:
            serial_no = row.get("serial_no")
            if not serial_no:
                continue

            required_ram_qty = max(int(flt(row.get("required_ram_qty") or 1)), 1)
            required_serial_nos.extend([serial_no] * required_ram_qty)

        stock_consumed_qty = flt(required_qty - remaining_qty, 6)
        shortage_serial_nos = required_serial_nos[
            int(stock_consumed_qty):int(stock_consumed_qty + remaining_qty)
        ]
        shortage_item["serial_nos"].extend(shortage_serial_nos)
        shortage_item["mr_rised_departments"].update(group_stock_used_departments)
        for row in serial_rows:
            current_department = row.get("current_department")
            if current_department:
                shortage_item["department_serial_counts"][current_department] += 1
            print(
                "Laptop RAM MR schedule department source:",
                "item_code:", shortage_item_code,
                "serial_no:", row.get("serial_no"),
                "source_department:", current_department or "N/A",
            )

        print(
            "Laptop RAM MR shortage item:",
            "item_code:", shortage_item_code,
            "qty_to_raise:", remaining_qty,
            "ram_slots:", ram_slots,
            "item_wizard:", item_wizard,
            "required_ram_capacity:", required_ram_capacity,
            "serial_nos:", shortage_serial_nos,
        )

    shortage_items = []
    for item in shortage_by_item_code.values():
        department_serial_counts = dict(item["department_serial_counts"])
        shortage_items.append({
            "item_code": item["item_code"],
            "qty": flt(item["qty"], 6),
            "ram_slots": ", ".join(sorted(item["ram_slots"])),
            "item_wizards": ", ".join(sorted(item["item_wizards"])),
            "required_ram_capacities": ", ".join(sorted(item["required_ram_capacities"])),
            "serial_nos": ", ".join(item["serial_nos"]),
            "schedule_departments": ", ".join(sorted(department_serial_counts)),
            "department_serial_counts": department_serial_counts,
            "mr_rised_departments": ", ".join(sorted(item["mr_rised_departments"])),
        })

    print("Laptop RAM MR shortage item count:", len(shortage_items))
    for item in shortage_items:
        print(
            "Laptop RAM MR final shortage item:",
            "item_code:", item["item_code"],
            "qty:", item["qty"],
            "ram_slots:", item["ram_slots"],
            "item_wizards:", item["item_wizards"],
            "required_ram_capacities:", item["required_ram_capacities"],
            "serial_nos:", item["serial_nos"],
            "schedule_departments:", item.get("schedule_departments"),
            "department_serial_counts:", item.get("department_serial_counts"),
            "mr_rised_departments:", item.get("mr_rised_departments"),
        )

    return shortage_items


def _get_laptop_ram_schedule_days_from_shortage_items(shortage_items):
    department_serial_counts = Counter()
    for item in shortage_items or []:
        department_serial_counts.update(item.get("department_serial_counts") or {})

    departments = sorted(department_serial_counts)
    if not departments:
        print(
            "Laptop RAM MR schedule department SLA skipped: no departments,",
            "default_schedule_days:", PP_MR_DEFAULT_SCHEDULE_DAYS,
        )
        return PP_MR_DEFAULT_SCHEDULE_DAYS

    rows = frappe.db.sql("""
        SELECT
            name AS department,
            IFNULL(department_sla, 0) AS department_sla
        FROM `tabDepartment`
        WHERE name IN %(departments)s
    """, {
        "departments": tuple(departments),
    }, as_dict=True)

    department_sla_by_name = {
        row.department: flt(row.department_sla)
        for row in rows
    }

    total_schedule_days = 0.0
    for department in departments:
        department_sla = flt(department_sla_by_name.get(department))
        total_schedule_days += department_sla
        print(
            "Laptop RAM MR schedule department SLA:",
            "department:", department,
            "serial_count:", department_serial_counts.get(department, 0),
            "department_sla:", department_sla,
        )

    print(
        "Laptop RAM MR schedule department SLA total:",
        "departments:", departments,
        "total_schedule_days:", total_schedule_days,
    )
    return int(total_schedule_days or 0)


def create_laptop_ram_material_issue_mr(plan_name, shortage_items):
    if not shortage_items:
        print("Laptop RAM MR create skipped: no shortage items")
        return None

    shortage_items = _adjust_pp_shortage_qty_for_existing_mrs(
        shortage_items,
        material_request_type="Material Issue",
    )
    print("Laptop RAM MR shortage items after existing MR adjustment:", len(shortage_items))
    if not shortage_items:
        return None

    schedule_date = _get_pp_default_mr_schedule_date()
    print("Laptop RAM MR schedule days:", PP_MR_DEFAULT_SCHEDULE_DAYS)
    print("Laptop RAM MR schedule date:", schedule_date)
    item_fru_map = {
        d["name"]: d["fru_number"]
        for d in frappe.get_all(
            "Item",
            filters={"name": ["in", [i["item_code"] for i in shortage_items]]},
            fields=["name", "fru_number"],
        )
    }

    mr = frappe.new_doc("Material Request")
    mr.material_request_type = "Material Issue"
    mr.purpose = "Purchase"
    mr.naming_series = "MREQ-.YYYY.-.MM.-"
    mr.title = f"Laptop RAM - {plan_name}"
    mr.company = _get_pp_default_company()
    mr.schedule_date = schedule_date
    mr.mr_create_reference = "Laptop RAM NJ Production"
    mr.mr_rised_departments = ", ".join(sorted({
        department
        for item in shortage_items
        for department in _split_pp_department_names(item.get("mr_rised_departments"))
        if department
    }))
    mr.post_order_status = ""

    for item in shortage_items:
        mr_qty = _round_pp_qty_for_item_uom(item["item_code"], item["qty"])
        mr_serial_nos = _get_laptop_adaptor_mr_serial_nos(item.get("serial_nos"), mr_qty)
        print(
            "Laptop RAM MR append item:",
            "item_code:", item["item_code"],
            "qty:", mr_qty,
            "ram_slots:", item.get("ram_slots"),
            "item_wizards:", item.get("item_wizards"),
            "required_ram_capacities:", item.get("required_ram_capacities"),
            "serial_nos:", mr_serial_nos,
        )
        mr.append("items", {
            "item_code": item["item_code"],
            "qty": mr_qty,
            "schedule_date": schedule_date,
            "create_reference": "Laptop RAM NJ Production",
            "warehouse": PP_MR_STORES_DEPARTMENT,
            "fru_number": item_fru_map.get(item["item_code"]) or "N/A",
            "mavni_comments": ", ".join(mr_serial_nos),
        })

    mr.insert(ignore_permissions=True)
    mr.submit()
    print("Laptop RAM MR created:", mr.name, "items:", len(shortage_items))
    frappe.msgprint(
        _("Laptop RAM Material Request Created from Production Plan {0}: {1}").format(
            frappe.bold(plan_name),
            frappe.bold(mr.name),
        )
    )
    return mr.name


def get_laptop_ram_stock_from_reconfig_departments():
    print("Laptop RAM MR stock fetch started")
    stock_rows = frappe.db.sql("""
        SELECT
            b.item_code,
            i.item_name,
            i.item_group,
            i.disabled,
            i.end_of_life,
            SUM(b.actual_qty) AS stock_qty,
            b.warehouse,
            w.department
        FROM `tabBin` AS b
        INNER JOIN `tabWarehouse` AS w
            ON w.name = b.warehouse
        INNER JOIN `tabItem` AS i
            ON i.name = b.item_code
        INNER JOIN `tabItem Variant Attribute` AS iva
            ON iva.parent = i.name
        WHERE w.department IN (
                SELECT name
                FROM `tabDepartment`
                WHERE allow_reconfig = 1
            )
            AND i.item_group = 'Laptop RAM'
            AND iva.attribute = 'Grade'
            AND iva.attribute_value = 'GRADE A'
            AND b.actual_qty > 0
        GROUP BY
            b.item_code,
            i.item_name,
            i.item_group,
            i.disabled,
            i.end_of_life,
            b.warehouse,
            w.department
        ORDER BY b.item_code
    """, as_dict=True)

    print("Laptop RAM MR stock rows count:", len(stock_rows))
    for row in stock_rows:
        print(
            "Laptop RAM MR stock row:",
            "item_code:", row.item_code,
            "item_name:", row.item_name,
            "item_group:", row.item_group,
            "disabled:", row.disabled,
            "end_of_life:", row.end_of_life,
            "stock_qty:", flt(row.stock_qty),
            "warehouse:", row.warehouse,
            "department:", row.department,
        )

    return stock_rows


def laptop_ram_mr_via_production_plan(doc=None, method=None):
    
    print("laptop_ram_mr_via_production_plan")
    latest_name = _get_latest_nj_production_plan_name()
    print("Laptop RAM MR latest plan:", latest_name)
    if not latest_name:
        return []

    diff_item_serials = get_diff_ram_item_code(latest_name)
    print("Laptop RAM MR diff item rows returned:", len(diff_item_serials))

    diff_ram_serials = get_only_ram_diff_item_codes(diff_item_serials)
    print("Laptop RAM MR filtered RAM diff rows returned:", len(diff_ram_serials))

    ram_stock_rows = get_laptop_ram_stock_from_reconfig_departments()
    print("Laptop RAM MR stock rows returned:", len(ram_stock_rows))

    ram_wizard_combinations = build_laptop_ram_wizard_combinations(
        diff_ram_serials,
        ram_stock_rows,
    )
    print("Laptop RAM MR wizard combinations returned:", len(ram_wizard_combinations))

    ram_shortage_items = build_laptop_ram_shortage_items(
        diff_ram_serials,
        ram_wizard_combinations,
    )
    print("Laptop RAM MR shortage items returned:", len(ram_shortage_items))

    laptop_ram_mr = create_laptop_ram_material_issue_mr(
        latest_name,
        ram_shortage_items,
    )
    print("Laptop RAM MR created name:", laptop_ram_mr)

    return {
        "diff_ram_serials": diff_ram_serials,
        "ram_stock_rows": ram_stock_rows,
        "ram_wizard_combinations": ram_wizard_combinations,
        "ram_shortage_items": ram_shortage_items,
        "laptop_ram_mr": laptop_ram_mr,
    }



# Laptop Storage MR Section===================================

PP_MR_LAPTOP_STORAGE_ITEM_GROUP = "Laptop Storage"
PP_MR_LAPTOP_STORAGE_GRADE = "GRADE A"
PP_MR_LAPTOP_STORAGE_ATTRIBUTES = ("Storage Type", "Storage Interface", "Storage Length")
PP_MR_LAPTOP_STORAGE_ITEM_ATTRIBUTES = (
    "Storage Type",
    "Storage Interface",
    "Storage Capacity",
    "Storage Length",
)



def get_diff_storage_item_code(production_plan):
    
    print("Laptop Storage MR production_plan:", production_plan)
    if not production_plan:
        print("Laptop Storage MR skipped: production_plan not found")
        return []

    serial_nos = frappe.db.sql("""
        SELECT 
            c.serial_no,
            sn.item_code,
            sn.to_make,
            sn.item_wizard,
            c.current_department,
            d.name AS current_department_name,
            d.department_sequence AS current_department_sequence      

        FROM `tabFinal Production Planning Data` AS c

        INNER JOIN `tabSerial No` AS sn
            ON sn.name = c.serial_no

        INNER JOIN `tabDepartment` AS d
            ON d.name = c.current_department

        WHERE sn.item_code != sn.to_make
            AND c.parent= %(production_plan)s
            AND IFNULL(c.serial_no, '') != ''
            AND d.department_sequence IN (
                SELECT department_sequence
                FROM `tabDepartment`
                WHERE allow_reconfig=1

                UNION

                SELECT department_sequence - 1
                FROM `tabDepartment`
                WHERE allow_reconfig=1
            )
    """, {
        "production_plan": production_plan,
    }, as_dict=True, debug=1)

    print("Laptop Storage MR diff item serial count:", len(serial_nos))
    for row in serial_nos:
        print(
            "Laptop Storage MR diff item serial:",
            "serial_no:", row.serial_no,
            "current_item_code:", row.item_code,
            "to_make:", row.to_make,
            "item_wizard:", row.item_wizard,
            "current_department:", row.current_department,
            "current_department_sequence:", row.current_department_sequence,

        )

    return serial_nos


def _normalize_laptop_storage_value(value):
    return " ".join(str(value or "").upper().split())


def _normalize_laptop_storage_attr_value(attribute, value):
    normalized_value = _normalize_laptop_storage_value(value)
    if attribute == "Storage Capacity":
        match = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB)", normalized_value, flags=re.IGNORECASE)
        if not match:
            return normalized_value

        qty = flt(match.group(1))
        qty_display = int(qty) if float(qty).is_integer() else qty
        return f"{qty_display}{match.group(2).upper()}"

    return "".join(normalized_value.split())


def _get_laptop_storage_match_key(values):
    return tuple(
        _normalize_laptop_storage_attr_value(attribute, value)
        for attribute, value in zip(PP_MR_LAPTOP_STORAGE_ITEM_ATTRIBUTES, values)
    )


def _get_laptop_storage_key_from_item_code(item_code):
    code = str(item_code or "").strip()
    if not code:
        return None

    cleaned = re.sub(
        rf"-{re.escape(PP_MR_LAPTOP_STORAGE_GRADE)}$",
        "",
        code,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^S-LAPTOP\s+STORAGE[-\s]*", "", cleaned, flags=re.IGNORECASE)

    parts = [part.strip() for part in cleaned.split("-") if part.strip()]
    storage_type = ""
    storage_interface = ""
    storage_capacity = ""
    storage_length = ""

    for part in parts:
        if not storage_capacity and re.search(r"\d+(?:\.\d+)?\s*(?:TB|GB)\b", part, flags=re.IGNORECASE):
            storage_capacity = part
            continue

        if not storage_length and re.fullmatch(r"\d{4}", part.strip()):
            storage_length = part
            continue

        if not storage_type:
            storage_type = part
            continue

        if not storage_interface:
            storage_interface = part
            continue

        storage_interface = f"{storage_interface} {part}".strip()

    if not storage_type or not storage_interface or not storage_capacity or not storage_length:
        return None

    return _get_laptop_storage_match_key((
        storage_type,
        storage_interface,
        storage_capacity,
        storage_length,
    ))


def _dedupe_laptop_storage_values(values):
    seen = set()
    result = []
    for value in values:
        normalized_value = _normalize_laptop_storage_value(value)
        if not normalized_value or normalized_value in seen:
            continue

        seen.add(normalized_value)
        result.append(value)

    return result


def _get_laptop_storage_combinations(attributes):
    attribute_values = []
    for attr in PP_MR_LAPTOP_STORAGE_ITEM_ATTRIBUTES:
        values = attributes.get(attr) or []
        if not isinstance(values, list):
            values = [values]

        values = _dedupe_laptop_storage_values(values)
        if not values:
            return []

        attribute_values.append(values)

    return [
        {
            "values": combination,
            "key": _get_laptop_storage_match_key(combination),
        }
        for combination in product(*attribute_values)
    ]


def _get_laptop_storage_grade_a_items():
    rows = frappe.db.sql("""
        SELECT
            i.name AS item_code,
            iva.attribute,
            iva.attribute_value
        FROM `tabItem` i
        INNER JOIN `tabItem Variant Attribute` iva
            ON iva.parent = i.name
        WHERE i.item_group = %(item_group)s
            AND iva.attribute IN %(attributes)s
    """, {
        "item_group": PP_MR_LAPTOP_STORAGE_ITEM_GROUP,
        "attributes": tuple(PP_MR_LAPTOP_STORAGE_ITEM_ATTRIBUTES + ("Grade",)),
    }, as_dict=True)

    attributes_by_item = defaultdict(dict)
    for row in rows:
        attributes_by_item[row.item_code][row.attribute] = row.attribute_value

    items_by_key = {}
    for item_code, attributes in attributes_by_item.items():
        if _normalize_laptop_storage_value(attributes.get("Grade")) != _normalize_laptop_storage_value(PP_MR_LAPTOP_STORAGE_GRADE):
            continue

        if all(attributes.get(attr) for attr in PP_MR_LAPTOP_STORAGE_ITEM_ATTRIBUTES):
            key = _get_laptop_storage_match_key(
                attributes.get(attr) for attr in PP_MR_LAPTOP_STORAGE_ITEM_ATTRIBUTES
            )
        else:
            key = _get_laptop_storage_key_from_item_code(item_code)

        if key:
            items_by_key[key] = item_code

    print("Laptop Storage MR Grade A item count:", len(items_by_key))
    return items_by_key


def _laptop_storage_combination_matches_required(combination, required_storage_capacity):
    values = combination.get("values") or ()
    if len(values) < 4:
        return False

    _storage_type, _storage_interface, storage_capacity, _storage_length = values
    return (
        _normalize_laptop_storage_attr_value("Storage Capacity", storage_capacity)
        == _normalize_laptop_storage_attr_value("Storage Capacity", required_storage_capacity)
    )


def get_only_storage_diff_item_codes(serial_rows):
    print("Laptop Storage MR Storage Capacity filter started")
    if not serial_rows:
        print("Laptop Storage MR Storage Capacity filter skipped: no serial rows")
        return []

    item_codes = set()
    item_wizards = set()
    for row in serial_rows:
        if row.get("item_code"):
            item_codes.add(row.get("item_code"))
        if row.get("to_make"):
            item_codes.add(row.get("to_make"))
        if row.get("item_wizard"):
            item_wizards.add(row.get("item_wizard"))

    if not item_codes:
        print("Laptop Storage MR Storage Capacity filter skipped: no item codes")
        return []

    storage_rows = frappe.db.sql("""
        SELECT
            parent AS item_code,
            attribute_value AS storage_capacity
        FROM `tabItem Variant Attribute`
        WHERE parent IN %(item_codes)s
            AND attribute = %(storage_attr)s
    """, {
        "item_codes": tuple(item_codes),
        "storage_attr": STORAGE_ATTR,
    }, as_dict=True)

    storage_by_item_code = {
        row.item_code: (row.storage_capacity or "").strip()
        for row in storage_rows
    }
    print("Laptop Storage MR Storage Capacity map:", storage_by_item_code)

    inbuilt_item_wizards = set()
    if item_wizards:
        inbuilt_rows = frappe.db.sql("""
            SELECT
                parent AS item_wizard,
                `values` AS storage_type
            FROM `tabFeatures child table`
            WHERE parent IN %(item_wizards)s
                AND features_attributes = 'Storage Type'
                AND UPPER(TRIM(IFNULL(`values`, ''))) = 'INBUILT'
        """, {
            "item_wizards": tuple(item_wizards),
        }, as_dict=True)

        inbuilt_item_wizards = {
            row.item_wizard
            for row in inbuilt_rows
            if row.item_wizard
        }

    print("Laptop Storage MR InBuilt item wizards:", sorted(inbuilt_item_wizards))

    storage_diff_rows = []
    for row in serial_rows:
        if row.get("item_wizard") in inbuilt_item_wizards:
            print(
                "Laptop Storage MR skipped InBuilt storage wizard:",
                "serial_no:", row.get("serial_no"),
                "item_wizard:", row.get("item_wizard"),
            )
            continue

        current_storage = storage_by_item_code.get(row.get("item_code"), "")
        to_make_storage = storage_by_item_code.get(row.get("to_make"), "")
        is_storage_diff = current_storage != to_make_storage
        required_storage_capacity = to_make_storage

        print(
            "Laptop Storage MR Storage Capacity compare:",
            "serial_no:", row.get("serial_no"),
            "current_item_code:", row.get("item_code"),
            "current_storage:", current_storage,
            "to_make:", row.get("to_make"),
            "to_make_storage:", to_make_storage,
            "required_storage_capacity:", required_storage_capacity,
            "is_storage_diff:", int(is_storage_diff),
        )

        if not is_storage_diff:
            continue

        if not required_storage_capacity:
            print(
                "Laptop Storage MR skipped no required storage capacity:",
                "serial_no:", row.get("serial_no"),
                "current_storage:", current_storage,
                "to_make_storage:", to_make_storage,
            )
            continue

        row["current_storage_capacity"] = current_storage
        row["to_make_storage_capacity"] = to_make_storage
        row["required_storage_capacity"] = required_storage_capacity
        storage_diff_rows.append(row)

    print("Laptop Storage MR actual Storage diff serial count:", len(storage_diff_rows))
    return storage_diff_rows


def get_laptop_storage_stock_from_reconfig_departments():
    print("Laptop Storage MR stock fetch started")
    stock_rows = frappe.db.sql("""
        SELECT
            b.item_code,
            i.item_name,
            i.item_group,
            i.disabled,
            i.end_of_life,
            SUM(b.actual_qty) AS stock_qty,
            b.warehouse,
            w.department
        FROM `tabBin` AS b
        INNER JOIN `tabWarehouse` AS w
            ON w.name = b.warehouse
        INNER JOIN `tabItem` AS i
            ON i.name = b.item_code
        INNER JOIN `tabItem Variant Attribute` AS iva
            ON iva.parent = i.name
        WHERE w.department IN (
                SELECT name
                FROM `tabDepartment`
                WHERE allow_reconfig = 1
            )
            AND i.item_group = %(item_group)s
            AND iva.attribute = 'Grade'
            AND iva.attribute_value = %(grade)s
            AND b.actual_qty > 0
        GROUP BY
            b.item_code,
            i.item_name,
            i.item_group,
            i.disabled,
            i.end_of_life,
            b.warehouse,
            w.department
        ORDER BY b.item_code
    """, {
        "item_group": PP_MR_LAPTOP_STORAGE_ITEM_GROUP,
        "grade": PP_MR_LAPTOP_STORAGE_GRADE,
    }, as_dict=True)

    print("Laptop Storage MR stock rows count:", len(stock_rows))
    for row in stock_rows:
        print(
            "Laptop Storage MR stock row:",
            "item_code:", row.item_code,
            "item_name:", row.item_name,
            "item_group:", row.item_group,
            "disabled:", row.disabled,
            "end_of_life:", row.end_of_life,
            "stock_qty:", flt(row.stock_qty),
            "warehouse:", row.warehouse,
            "department:", row.department,
        )

    return stock_rows


def build_laptop_storage_wizard_combinations(storage_diff_rows, storage_stock_rows):
    print("Laptop Storage MR wizard combination build started")
    if not storage_diff_rows:
        print("Laptop Storage MR wizard combination skipped: no Storage diff rows")
        return []

    item_wizards = sorted({
        row.get("item_wizard")
        for row in storage_diff_rows
        if row.get("item_wizard")
    })
    if not item_wizards:
        print("Laptop Storage MR wizard combination skipped: no item wizards")
        return []

    grade_a_items_by_key = _get_laptop_storage_grade_a_items()
    stock_item_to_key = {
        item_code: key
        for key, item_code in grade_a_items_by_key.items()
    }

    stock_by_key = defaultdict(float)
    stock_details_by_key = defaultdict(list)
    for row in storage_stock_rows or []:
        key = stock_item_to_key.get(row.item_code) or _get_laptop_storage_key_from_item_code(row.item_code)
        if not key:
            print(
                "Laptop Storage MR stock item key not found:",
                "item_code:", row.item_code,
                "stock_qty:", flt(row.stock_qty),
                "warehouse:", row.warehouse,
            )
            continue

        grade_a_items_by_key.setdefault(key, row.item_code)
        stock_by_key[key] += flt(row.stock_qty)
        stock_details_by_key[key].append({
            "department": row.department,
            "warehouse": row.warehouse,
            "stock_qty": flt(row.stock_qty),
        })

    wizard_attr_rows = frappe.db.sql("""
        SELECT
            parent AS item_wizard,
            item_attribute,
            attribute_value
        FROM `tabItems Attribute`
        WHERE parent IN %(item_wizards)s
            AND item_group = %(item_group)s
            AND item_attribute IN %(attributes)s
    """, {
        "item_wizards": tuple(item_wizards),
        "item_group": PP_MR_LAPTOP_STORAGE_ITEM_GROUP,
        "attributes": tuple(PP_MR_LAPTOP_STORAGE_ATTRIBUTES),
    }, as_dict=True)

    attributes_by_wizard = defaultdict(lambda: defaultdict(list))
    for row in wizard_attr_rows:
        attributes_by_wizard[row.item_wizard][row.item_attribute].append(row.attribute_value)

    serial_rows_by_wizard = defaultdict(list)
    for row in storage_diff_rows:
        if row.get("item_wizard"):
            serial_rows_by_wizard[row.get("item_wizard")].append(row)

    wizard_combinations = []
    for item_wizard in item_wizards:
        serial_rows = serial_rows_by_wizard.get(item_wizard, [])
        attributes = {
            attr: _dedupe_laptop_storage_values(values)
            for attr, values in attributes_by_wizard.get(item_wizard, {}).items()
        }
        required_storage_capacities = _dedupe_laptop_storage_values(
            row.get("required_storage_capacity")
            for row in serial_rows
            if row.get("required_storage_capacity")
        )
        if required_storage_capacities:
            attributes["Storage Capacity"] = required_storage_capacities

        combinations = _get_laptop_storage_combinations(attributes)

        print(
            "Laptop Storage MR wizard combinations:",
            "item_wizard:", item_wizard,
            "serial_no_count:", len(serial_rows),
            "combination_count:", len(combinations),
            "attributes:", attributes,
        )

        valid_combinations = []
        for combination in combinations:
            item_code = grade_a_items_by_key.get(combination["key"])
            stock_qty = flt(stock_by_key.get(combination["key"]))
            print(
                "Laptop Storage MR wizard combination:",
                "item_wizard:", item_wizard,
                "values:", combination["values"],
                "key:", combination["key"],
                "item_code:", item_code,
                "stock_qty:", stock_qty,
            )

            if item_code:
                valid_combinations.append({
                    "values": combination["values"],
                    "key": combination["key"],
                    "item_code": item_code,
                    "stock_qty": stock_qty,
                    "stock_details": stock_details_by_key.get(combination["key"], []),
                })

        print(
            "Laptop Storage MR valid combination count:",
            "item_wizard:", item_wizard,
            "count:", len(valid_combinations),
        )

        wizard_combinations.append({
            "item_wizard": item_wizard,
            "serial_no_count": len(serial_rows),
            "serial_nos": [row.get("serial_no") for row in serial_rows],
            "attributes": attributes,
            "combinations": combinations,
            "valid_combinations": valid_combinations,
        })

    return wizard_combinations


def build_laptop_storage_shortage_items(diff_storage_serials, storage_wizard_combinations):
    print("Laptop Storage MR shortage build started")
    if not diff_storage_serials:
        print("Laptop Storage MR shortage skipped: no Storage diff serials")
        return []

    wizard_combo_by_name = {
        row["item_wizard"]: row
        for row in storage_wizard_combinations or []
        if row.get("item_wizard")
    }

    stock_by_item_code = defaultdict(float)
    stock_details_by_item_code = {}
    for wizard_row in storage_wizard_combinations or []:
        for combination in wizard_row.get("valid_combinations") or []:
            item_code = combination.get("item_code")
            if not item_code:
                continue
            stock_by_item_code[item_code] = max(
                stock_by_item_code[item_code],
                flt(combination.get("stock_qty")),
            )
            stock_details_by_item_code.setdefault(item_code, [
                dict(detail)
                for detail in combination.get("stock_details") or []
            ])

    print("Laptop Storage MR virtual stock by item:", dict(stock_by_item_code))
    initial_stock_by_item_code = dict(stock_by_item_code)

    grouped_serials = defaultdict(list)
    for row in diff_storage_serials:
        group_key = (
            row.get("item_wizard"),
            row.get("required_storage_capacity"),
        )
        grouped_serials[group_key].append(row)

    shortage_by_item_code = {}
    group_details = []
    for group_key, serial_rows in grouped_serials.items():
        item_wizard, required_storage_capacity = group_key
        wizard_combo = wizard_combo_by_name.get(item_wizard) or {}
        matching_combinations = [
            combination
            for combination in wizard_combo.get("valid_combinations") or []
            if _laptop_storage_combination_matches_required(
                combination,
                required_storage_capacity,
            )
        ]
        matching_combinations.sort(
            key=lambda combination: (
                0 if stock_by_item_code.get(combination.get("item_code"), 0) > 0 else 1,
                _get_laptop_ram_item_code_sort_key(combination.get("item_code")),
            )
        )
        group_details.append({
            "item_wizard": item_wizard,
            "required_storage_capacity": required_storage_capacity,
            "serial_rows": serial_rows,
            "matching_combinations": matching_combinations,
            "combination_count": len(matching_combinations),
        })

    group_details.sort(
        key=lambda row: (
            row["combination_count"] if row["combination_count"] else 999999,
            str(row["item_wizard"] or ""),
            str(row["required_storage_capacity"] or ""),
        )
    )

    for group in group_details:
        item_wizard = group["item_wizard"]
        required_storage_capacity = group["required_storage_capacity"]
        serial_rows = group["serial_rows"]
        matching_combinations = group["matching_combinations"]
        required_serial_count = len(serial_rows)
        remaining_qty = flt(len(serial_rows))
        group_stock_deducted_qty = 0.0
        group_stock_used_items = []
        group_stock_used_departments = set()

        print(
            "Laptop Storage MR demand group:",
            "item_wizard:", item_wizard,
            "required_storage_capacity:", required_storage_capacity,
            "serial_count:", len(serial_rows),
            "matching_combination_count:", len(matching_combinations),
            "serial_nos:", [row.get("serial_no") for row in serial_rows],
        )

        for combination in matching_combinations:
            if remaining_qty <= 0:
                break

            item_code = combination.get("item_code")
            available_qty = flt(stock_by_item_code.get(item_code))
            if available_qty <= 0:
                continue

            consumed_qty = min(available_qty, remaining_qty)
            stock_by_item_code[item_code] = flt(available_qty - consumed_qty, 6)
            remaining_qty = flt(remaining_qty - consumed_qty, 6)
            group_stock_deducted_qty = flt(group_stock_deducted_qty + consumed_qty, 6)
            detail_remaining_qty = flt(consumed_qty)
            stock_used_department_details = []
            for stock_detail in stock_details_by_item_code.get(item_code, []):
                if detail_remaining_qty <= 0:
                    break

                detail_stock_qty = flt(stock_detail.get("stock_qty"))
                if detail_stock_qty <= 0:
                    continue

                detail_consumed_qty = min(detail_stock_qty, detail_remaining_qty)
                stock_detail["stock_qty"] = flt(detail_stock_qty - detail_consumed_qty, 6)
                detail_remaining_qty = flt(detail_remaining_qty - detail_consumed_qty, 6)
                if stock_detail.get("department"):
                    group_stock_used_departments.add(stock_detail.get("department"))
                stock_used_department_details.append({
                    "department": stock_detail.get("department"),
                    "warehouse": stock_detail.get("warehouse"),
                    "deducted_qty": flt(detail_consumed_qty, 6),
                })

            group_stock_used_items.append({
                "item_code": item_code,
                "stock_before": available_qty,
                "deducted_qty": consumed_qty,
                "stock_after": stock_by_item_code[item_code],
                "department_details": stock_used_department_details,
            })

            print(
                "Laptop Storage MR stock consumed:",
                "item_wizard:", item_wizard,
                "required_storage_capacity:", required_storage_capacity,
                "item_code:", item_code,
                "stock_before:", available_qty,
                "consume_qty:", consumed_qty,
                "stock_after:", stock_by_item_code[item_code],
                "remaining_required_qty:", remaining_qty,
                "stock_used_departments:", sorted(group_stock_used_departments),
            )

        if remaining_qty <= 0:
            print(
                "Laptop Storage MR no shortage:",
                "item_wizard:", item_wizard,
                "required_storage_capacity:", required_storage_capacity,
                "serial_no_count:", required_serial_count,
                "serial_nos:", [row.get("serial_no") for row in serial_rows],
                "stock_deducted_qty:", group_stock_deducted_qty,
                "stock_used_items:", group_stock_used_items,
                "qty_to_raise_after_deducted:", 0,
            )
            continue

        if not matching_combinations:
            print(
                "Laptop Storage MR shortage skipped no matching item code:",
                "item_wizard:", item_wizard,
                "required_storage_capacity:", required_storage_capacity,
                "shortage_qty:", remaining_qty,
            )
            continue

        shortage_item_code = matching_combinations[0].get("item_code")
        shortage_item = shortage_by_item_code.setdefault(shortage_item_code, {
            "item_code": shortage_item_code,
            "qty": 0,
            "required_serial_count": 0,
            "stock_deducted_qty": 0,
            "initial_stock_qty": flt(initial_stock_by_item_code.get(shortage_item_code), 6),
            "calculation_rows": [],
            "item_wizards": set(),
            "required_storage_capacities": set(),
            "serial_nos": [],
            "department_serial_counts": Counter(),
            "mr_rised_departments": set(),
        })
        shortage_item["qty"] = flt(shortage_item["qty"] + remaining_qty, 6)
        shortage_item["required_serial_count"] += required_serial_count
        shortage_item["stock_deducted_qty"] = flt(shortage_item["stock_deducted_qty"] + group_stock_deducted_qty, 6)
        shortage_item["calculation_rows"].append({
            "item_wizard": item_wizard,
            "required_storage_capacity": required_storage_capacity,
            "serial_no_count": required_serial_count,
            "stock_deducted_qty": group_stock_deducted_qty,
            "qty_to_raise_after_deducted": remaining_qty,
            "serial_nos": [row.get("serial_no") for row in serial_rows],
            "stock_used_items": group_stock_used_items,
        })
        shortage_item["item_wizards"].add(item_wizard)
        shortage_item["required_storage_capacities"].add(required_storage_capacity)
        shortage_item["serial_nos"].extend(row.get("serial_no") for row in serial_rows)
        shortage_item["mr_rised_departments"].update(group_stock_used_departments)
        for row in serial_rows:
            current_department = row.get("current_department")
            if current_department:
                shortage_item["department_serial_counts"][current_department] += 1
            print(
                "Laptop Storage MR schedule department source:",
                "item_code:", shortage_item_code,
                "serial_no:", row.get("serial_no"),
                "source_department:", current_department or "N/A",
            )

        print(
            "Laptop Storage MR shortage item:",
            "item_code:", shortage_item_code,
            "serial_no_count:", required_serial_count,
            "serial_nos:", [row.get("serial_no") for row in serial_rows],
            "initial_stock_qty_for_item:", flt(initial_stock_by_item_code.get(shortage_item_code), 6),
            "stock_deducted_qty:", group_stock_deducted_qty,
            "qty_to_raise:", remaining_qty,
            "item_wizard:", item_wizard,
            "required_storage_capacity:", required_storage_capacity,
        )

    shortage_items = []
    for item in shortage_by_item_code.values():
        department_serial_counts = dict(item["department_serial_counts"])
        shortage_items.append({
            "item_code": item["item_code"],
            "qty": flt(item["qty"], 6),
            "required_serial_count": item["required_serial_count"],
            "stock_deducted_qty": flt(item["stock_deducted_qty"], 6),
            "initial_stock_qty": flt(item["initial_stock_qty"], 6),
            "calculation_rows": item["calculation_rows"],
            "item_wizards": ", ".join(sorted(item["item_wizards"])),
            "required_storage_capacities": ", ".join(sorted(item["required_storage_capacities"])),
            "serial_nos": ", ".join(sorted(set(item["serial_nos"]))),
            "schedule_departments": ", ".join(sorted(department_serial_counts)),
            "department_serial_counts": department_serial_counts,
            "mr_rised_departments": ", ".join(sorted(item["mr_rised_departments"])),
        })

    print("Laptop Storage MR shortage item count:", len(shortage_items))
    for item in shortage_items:
        print(
            "Laptop Storage MR final shortage item:",
            "item_code:", item["item_code"],
            "serial_no_count:", item["required_serial_count"],
            "initial_stock_qty:", item["initial_stock_qty"],
            "stock_deducted_qty:", item["stock_deducted_qty"],
            "qty:", item["qty"],
            "calculation_rows:", item["calculation_rows"],
            "item_wizards:", item["item_wizards"],
            "required_storage_capacities:", item["required_storage_capacities"],
            "serial_nos:", item["serial_nos"],
            "schedule_departments:", item.get("schedule_departments"),
            "department_serial_counts:", item.get("department_serial_counts"),
            "mr_rised_departments:", item.get("mr_rised_departments"),
        )

    return shortage_items


def _get_laptop_storage_schedule_days_from_shortage_items(shortage_items):
    return _get_laptop_ram_schedule_days_from_shortage_items(shortage_items)


def create_laptop_storage_material_issue_mr(plan_name, shortage_items):
    if not shortage_items:
        print("Laptop Storage MR create skipped: no shortage items")
        return None

    shortage_items = _adjust_pp_shortage_qty_for_existing_mrs(
        shortage_items,
        material_request_type="Material Issue",
    )
    print("Laptop Storage MR shortage items after existing MR adjustment:", len(shortage_items))
    if not shortage_items:
        return None

    schedule_date = _get_pp_default_mr_schedule_date()
    print("Laptop Storage MR schedule days:", PP_MR_DEFAULT_SCHEDULE_DAYS)
    print("Laptop Storage MR schedule date:", schedule_date)
    item_fru_map = {
        d["name"]: d["fru_number"]
        for d in frappe.get_all(
            "Item",
            filters={"name": ["in", [i["item_code"] for i in shortage_items]]},
            fields=["name", "fru_number"],
        )
    }

    mr = frappe.new_doc("Material Request")
    mr.material_request_type = "Material Issue"
    mr.purpose = "Purchase"
    mr.naming_series = "MREQ-.YYYY.-.MM.-"
    mr.title = f"Laptop Storage - {plan_name}"
    mr.company = _get_pp_default_company()
    mr.schedule_date = schedule_date
    mr.mr_create_reference = "Laptop Storage NJ Production"
    mr.mr_rised_departments = ", ".join(sorted({
        department
        for item in shortage_items
        for department in _split_pp_department_names(item.get("mr_rised_departments"))
        if department
    }))
    mr.post_order_status = ""

    for item in shortage_items:
        mr_qty = _round_pp_qty_for_item_uom(item["item_code"], item["qty"])
        mr_serial_nos = _get_laptop_adaptor_mr_serial_nos(item.get("serial_nos"), mr_qty)
        print(
            "Laptop Storage MR append item:",
            "item_code:", item["item_code"],
            "qty:", mr_qty,
            "item_wizards:", item.get("item_wizards"),
            "required_storage_capacities:", item.get("required_storage_capacities"),
            "serial_nos:", mr_serial_nos,
        )
        mr.append("items", {
            "item_code": item["item_code"],
            "qty": mr_qty,
            "schedule_date": schedule_date,
            "create_reference": "Laptop Storage NJ Production",
            "warehouse": PP_MR_STORES_DEPARTMENT,
            "fru_number": item_fru_map.get(item["item_code"]) or "N/A",
            "mavni_comments": ", ".join(mr_serial_nos),
        })

    mr.insert(ignore_permissions=True)
    mr.submit()
    print("Laptop Storage MR created:", mr.name, "items:", len(shortage_items))
    frappe.msgprint(
        _("Laptop Storage Material Request Created from Production Plan {0}: {1}").format(
            frappe.bold(plan_name),
            frappe.bold(mr.name),
        )
    )
    return mr.name


def laptop_storage_mr_via_production_plan(doc=None, method=None):
    
    print("laptop_storage_mr_via_production_plan=======")
    latest_name = _get_latest_nj_production_plan_name()
    print("Laptop Storage MR latest plan:", latest_name)
    if not latest_name:
        return []
    
    diff_item_serials = get_diff_storage_item_code(latest_name)
    print("Laptop Storage MR diff item rows returned:", len(diff_item_serials))

    diff_storage_serials = get_only_storage_diff_item_codes(diff_item_serials)
    print("Laptop Storage MR filtered Storage diff rows returned:", len(diff_storage_serials))

    storage_stock_rows = get_laptop_storage_stock_from_reconfig_departments()
    print("Laptop Storage MR stock rows returned:", len(storage_stock_rows))

    storage_wizard_combinations = build_laptop_storage_wizard_combinations(
        diff_storage_serials,
        storage_stock_rows,
    )
    print("Laptop Storage MR wizard combinations returned:", len(storage_wizard_combinations))

    storage_shortage_items = build_laptop_storage_shortage_items(
        diff_storage_serials,
        storage_wizard_combinations,
    )
    print("Laptop Storage MR shortage items returned:", len(storage_shortage_items))

    laptop_storage_mr = create_laptop_storage_material_issue_mr(
        latest_name,
        storage_shortage_items,
    )
    print("Laptop Storage MR created name:", laptop_storage_mr)

    return {
        "diff_storage_serials": diff_storage_serials,
        "storage_stock_rows": storage_stock_rows,
        "storage_wizard_combinations": storage_wizard_combinations,
        "storage_shortage_items": storage_shortage_items,
        "laptop_storage_mr": laptop_storage_mr,
    }

