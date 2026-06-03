# nj_planning/plan_all.py

import math
import frappe
import random
import logging
import functools
from frappe import _
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
    LOOKBACK_DAYS = 50

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

            (so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.dn_qty, 0)))
                                                                AS qty_pending,

            CONCAT(COALESCE(it2.variant_of, it2.name), ' ', COALESCE(proc.attribute_value, ''))
                                                                AS variant_processor,

            SUM(so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.dn_qty, 0)))
                OVER (
                    PARTITION BY CONCAT(COALESCE(it2.variant_of, it2.name), ' ', COALESCE(proc.attribute_value, ''))
                )                                               AS total_pending_by_variant,

            SUM(so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.dn_qty, 0)))
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
                AND so.creation > CURDATE() - INTERVAL %(lookback)s DAY

                AND soi.item_group IN ('Laptops','Chromebooks', 'MacBooks')
                AND so.sale_type != 'Amazon'
                AND so.sale_type in ('NJ-Website-B2C','NJ-Direct-B2C')
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
                AND dni.creation >= CURDATE() - INTERVAL %(lookback)s DAY
                AND dni.item_group IN ('Laptops', 'Chromebooks')
            GROUP BY dni.against_sales_order, dni.item_code
        ) AS dn_data
            ON so_data.sales_order = dn_data.against_sales_order
           AND so_data.item_code   = dn_data.item_code

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

        WHERE (so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.dn_qty, 0))) > 0
        ORDER BY so_data.so_creation DESC, so_data.sales_order, so_data.item_code
        """,
        {"lookback": LOOKBACK_DAYS},
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
        SELECT item_code, IFNULL(to_make_ratio, 0) AS to_make_ratio
        FROM `tabShopify Item List`
        WHERE item_code IS NOT NULL AND item_code != ''
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

        rates.setdefault(km, default_rate)
        rates.setdefault(kc, default_rate)

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
            order_ref = ref_list[-1]

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

            ref_list.pop()

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
          {extra_where}
        """,
        params,
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


def _split_pp_department_names(departments):
    if not departments:
        return []

    return [d.strip() for d in str(departments).split(",") if d.strip()]


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
        if end_of_life and frappe.utils.getdate(end_of_life) <= frappe.utils.getdate(nowdate()):
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
            AND IFNULL(w.used_for_consumables_stock, 0) = 1
            AND i.item_group IN %(core_item_groups)s
        GROUP BY
            IFNULL(NULLIF(i.variant_of, ''), i.name),
            f.current_department
    """, {
        "plan_name": plan_name,
        "core_item_groups": tuple(PP_MR_CORE_ITEM_GROUPS),
    }, as_dict=1)

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
        return {}

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
        return {}

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
    for row in rows:
        stock_by_item[row.item_code] += flt(row.actual_qty)
        print(
            "PP MR department stock detail:",
            "department:", row.department,
            "warehouse:", row.warehouse,
            "item_code:", row.item_code,
            "actual_qty:", flt(row.actual_qty),
        )

    print("PP MR department stock aggregated:", dict(stock_by_item))
    return stock_by_item


def _get_pp_shortage_items(template_department_qty, consumables_by_template):
    required_qty_by_item = defaultdict(float)
    schedule_days_by_item = defaultdict(list)
    stock_departments = set()

    for row in template_department_qty:
        item_template = row.item_template
        current_department = row.current_department
        planned_qty = flt(row.planned_qty)

        for consumable in consumables_by_template.get(item_template, []):
            required_qty_by_item[consumable.item_code] += flt(consumable.quantity) * planned_qty

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
                )
                stock_departments.add(target_department)
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

    stock_by_item = _get_pp_department_consumable_stock(
        valid_item_codes,
        sorted(stock_departments),
    )

    shortage_items = []
    for item_code, required_qty in required_qty_by_item.items():
        if item_code in item_skip_reasons:
            continue

        available_qty = stock_by_item.get(item_code, 0)
        shortage_qty = required_qty - available_qty
        print(
            "PP MR consumable compare:",
            "item_code:", item_code,
            "required_qty:", required_qty,
            "available_qty:", available_qty,
            "shortage_qty:", shortage_qty,
        )
        if shortage_qty > PP_MR_MIN_QTY:
            shortage_items.append({
                "item_code": item_code,
                "qty": flt(shortage_qty, 6),
                "schedule_days": schedule_days_by_item.get(
                    item_code,
                    [PP_MR_DEFAULT_SCHEDULE_DAYS],
                ),
            })

    print("PP MR required consumable items count:", len(required_qty_by_item))
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

    schedule_days = max(
        days
        for item in shortage_items
        for days in item.get("schedule_days", [PP_MR_DEFAULT_SCHEDULE_DAYS])
    )
    schedule_date = add_days(nowdate(), schedule_days)
    print("PP MR schedule days:", schedule_days)
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
    mr.schedule_date = schedule_date
    mr.post_order_status = ""

    for item in shortage_items:
        print("PP MR append item:", item["item_code"], "qty:", item["qty"])
        mr.append("items", {
            "item_code": item["item_code"],
            "qty": item["qty"],
            "schedule_date": schedule_date,
            "warehouse": PP_MR_STORES_DEPARTMENT,
            "fru_number": item_fru_map.get(item["item_code"]) or "N/A",
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
def cosumables_material_issue_mr(doc=None, method=None):
    print("collect_all_purpose_material_issue")

    stock_data = frappe.db.sql("""
        SELECT
            b.item_code,
            b.actual_qty,
            b.warehouse,
            i.item_group,
            i.in_stock
            
        FROM `tabBin` b
        INNER JOIN `tabItem` i
            ON i.name = b.item_code
        WHERE b.warehouse IN (
            SELECT name
            FROM `tabWarehouse`
            WHERE department = %(stock_department)s
        )
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
        )
        AND b.actual_qty > 0 order by i.in_stock desc
    """, {
        "stock_department": STOCK_DEPARTMENT_NAME,
    }, as_dict=True)

    print("stock_data===============", stock_data)

    material_issues = frappe.db.sql("""
        SELECT
            mri.parent,
            mri.item_code,
            mri.qty,
            mri.schedule_date,
            mri.warehouse,
            w.department AS source_department
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
    """, as_dict=True)

    print("material_issues===============", material_issues)

    stock_qty_by_item = defaultdict(float)
    stock_warehouse_by_item = {}
    for row in stock_data:
        stock_qty_by_item[row.item_code] += flt(row.actual_qty)
        stock_warehouse_by_item.setdefault(row.item_code, row.warehouse)

    print("all purpose stock qty by item===============", dict(stock_qty_by_item))

    issue_qty_by_item = defaultdict(float)
    issue_mr_names_by_item = defaultdict(set)
    issue_warehouse_by_item = {}
    schedule_days_by_item = defaultdict(list)
    for row in material_issues:
        issue_qty_by_item[row.item_code] += flt(row.qty)
        issue_mr_names_by_item[row.item_code].add(row.parent)
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

        print(
            "all purpose compare:",
            "item_code:", item_code,
            "material_issue_qty:", issue_qty,
            "department_stock_qty:", stock_qty,
            "shortage_qty:", shortage_qty,
            "material_issue_mrs:", issue_mr_names,
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

        max_schedule_days = max(
            days
            for item in typed_shortage_items
            for days in item.get("schedule_days", [PP_MR_DEFAULT_SCHEDULE_DAYS])
        )
        schedule_date = add_days(nowdate(), max_schedule_days)
        print("all purpose", material_request_type, "MR schedule days===============", max_schedule_days)
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
        mr.title = f"{material_request_type} Against Material Issue - {nowdate()}"
        mr.company = _get_pp_default_company()
        mr.schedule_date = schedule_date
        mr.post_order_status = ""

        for item in typed_shortage_items:
            print(
                "all purpose append",
                material_request_type,
                "MR item:",
                "item_code:", item["item_code"],
                "qty:", item["qty"],
                "warehouse:", item.get("warehouse"),
                "schedule_days:", item.get("schedule_days"),
                "source_material_issue_mrs:", item.get("material_issue_mrs"),
            )

            item_row = {
                "item_code": item["item_code"],
                "qty": item["qty"],
                "schedule_date": schedule_date,
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
    if end_of_life and frappe.utils.getdate(end_of_life) <= frappe.utils.getdate(nowdate()):
        return f"item reached end of life on {end_of_life}"

    return None



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
        print(
            "PP MR laptop adaptor stock mapping:",
            "key:", key,
            "item_code:", row.item_code,
            "stock_qty:", flt(row.stock_qty),
            "warehouse:", row.warehouse,
        )

    shortage_by_item = {}
    schedule_days_by_item = defaultdict(list)

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
            "PP MR laptop adaptor wizard combinations:",
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

        selected_combination = max(
            valid_combinations,
            key=lambda combination: flt(stock_by_key.get(combination["key"])),
        )
        key = selected_combination["key"]
        item_code = grade_a_items_by_key.get(key) or stock_item_by_key.get(key)
        required_qty = flt(wizard_row.get("serial_no_count"))
        available_qty = flt(stock_by_key.get(key))
        shortage_qty = required_qty - available_qty

        print(
            "PP MR laptop adaptor compare:",
            wizard_row.get("item_wizard"),
            "combination:", selected_combination["values"],
            "item:", item_code,
            "required:", required_qty,
            "available:", available_qty,
            "shortage:", shortage_qty,
        )

        if shortage_qty > PP_MR_MIN_QTY:
            shortage_item = shortage_by_item.setdefault(item_code, {
                "item_code": item_code,
                "qty": 0,
                "schedule_days": [],
            })
            shortage_item["qty"] = flt(shortage_item["qty"] + shortage_qty, 6)
            print(
                "PP MR laptop adaptor creatable MR item:",
                "item_wizard:", wizard_row.get("item_wizard"),
                "item_code:", item_code,
                "qty_to_raise:", flt(shortage_qty, 6),
            )
        else:
            print(
                "PP MR laptop adaptor no MR required:",
                "item_wizard:", wizard_row.get("item_wizard"),
                "item_code:", item_code,
                "stock_sufficient_qty:", available_qty,
                "required_qty:", required_qty,
            )

        stock_by_key[key] = max(available_qty - required_qty, 0)

        for current_department in wizard_row.get("current_departments") or []:
            schedule_days_by_item[item_code].append(
                _get_pp_schedule_days(current_department, PP_MR_LAPTOP_ADAPTOR_DEPARTMENT)
            )

    shortage_items = list(shortage_by_item.values())
    for item in shortage_items:
        item["schedule_days"] = schedule_days_by_item.get(
            item["item_code"],
            [PP_MR_DEFAULT_SCHEDULE_DAYS],
        )

    print("PP MR laptop adaptor shortage items count:", len(shortage_items))
    for item in shortage_items:
        print(
            "PP MR laptop adaptor final shortage item:",
            "item_code:", item["item_code"],
            "qty:", item["qty"],
            "schedule_days:", item.get("schedule_days"),
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

    schedule_days = max(
        days
        for item in shortage_items
        for days in item.get("schedule_days", [PP_MR_DEFAULT_SCHEDULE_DAYS])
    )
    schedule_date = add_days(nowdate(), schedule_days)
    print("PP MR laptop adaptor schedule days:", schedule_days)
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
    mr.schedule_date = schedule_date
    mr.post_order_status = ""

    for item in shortage_items:
        print("PP MR laptop adaptor append item:", item["item_code"], "qty:", item["qty"])
        mr.append("items", {
            "item_code": item["item_code"],
            "qty": item["qty"],
            "schedule_date": schedule_date,
            "warehouse": PP_MR_STORES_DEPARTMENT,
            "fru_number": item_fru_map.get(item["item_code"]) or "N/A",
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
            b.warehouse
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
        GROUP BY b.item_code, i.item_name, i.item_group, i.disabled, i.end_of_life, b.warehouse
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

def get_laptop_adaptor_serial_nos(production_plan):
    serial_nos = frappe.db.sql("""
        SELECT 
            cd.serial_no,
            sn.item_wizard
        FROM `tabFinal Production Planning Data` AS cd
        INNER JOIN `tabNJ Production Planning` AS pp
            ON cd.parent = pp.name
        INNER JOIN `tabSerial No` AS sn
            ON sn.name = cd.serial_no
        WHERE pp.name = %s
            AND IFNULL(cd.serial_no, '') != ''
            AND NOT EXISTS (
                SELECT 1
                FROM `tabSerial No Component` AS snc
                WHERE snc.parent = cd.serial_no
                AND snc.item_group = 'Laptop Adaptors'
            )
        GROUP BY sn.item_wizard
    """, (production_plan,), as_dict=True, debug=1)

    print("Filtered Item Wizards ========")

    item_wizard_data = []

    print("serial_nos======================", serial_nos)

    for row in serial_nos:

        print(f"\nItem Wizard ===== {row.item_wizard}")

        serial_no_details = frappe.db.sql("""
            SELECT 
                cd.serial_no,
                cd.current_department,
                d1.name AS current_department_name,
                d1.department_sla AS current_department_sla,
                (
                    SELECT d2.name
                    FROM `tabDepartment` d2
                    WHERE d2.department_sla = (d1.department_sla - 1)
                    ORDER BY d2.name
                    LIMIT 1
                ) AS previous_department_name,
                (
                    SELECT d2.department_sla
                    FROM `tabDepartment` d2
                    WHERE d2.department_sla = (d1.department_sla - 1)
                    ORDER BY d2.name
                    LIMIT 1
                ) AS previous_department_sla
            FROM `tabFinal Production Planning Data` AS cd
            INNER JOIN `tabNJ Production Planning` AS pp
                ON cd.parent = pp.name
            INNER JOIN `tabSerial No` AS sn
                ON sn.name = cd.serial_no
            LEFT JOIN `tabDepartment` AS d1
                ON d1.name = cd.current_department
            WHERE pp.name = %s
                AND sn.item_wizard = %s
                AND IFNULL(cd.serial_no, '') != ''
                AND NOT EXISTS (
                    SELECT 1
                    FROM `tabSerial No Component` AS snc
                    WHERE snc.parent = cd.serial_no
                    AND snc.item_group = 'Laptop Adaptors'
                )
        """, (production_plan, row.item_wizard), as_dict=True)

        serial_no_list = [d.serial_no for d in serial_no_details]
        weighted_serial_count = 0
        current_departments = sorted({
            d.current_department for d in serial_no_details
            if d.current_department
        })

        print("Serial No Count ======================", len(serial_no_list))
        print("Serial Nos ===========================")

        for serial in serial_no_details:
            has_previous_department = bool(
                serial.current_department_name and serial.previous_department_name
            )
            qty_weight = 2 if has_previous_department else 1
            weighted_serial_count += qty_weight
            print(
                "Laptop adaptor serial:",
                "serial_no:", serial.serial_no,
                "current_department:", serial.current_department_name,
                "current_department_sla:", serial.current_department_sla,
                "previous_department:", serial.previous_department_name,
                "previous_department_sla:", serial.previous_department_sla,
                "qty_weight:", qty_weight,
            )

        print("Weighted Serial No Count =============", weighted_serial_count)

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
            "serial_no_count": weighted_serial_count,
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
            WHERE department = %(stock_department)s
        )
        AND i.item_group = 'Laptop Adaptors'
        AND b.actual_qty > 0
    """, {
        "stock_department": PP_MR_ALL_PURPOSE_STOCK_DEPARTMENT,
    }, as_dict=True)

    print("stock_data===============", stock_data)

    material_issues = frappe.db.sql("""
        SELECT
            mri.parent,
            mri.item_code,
            mri.qty,
            mri.schedule_date,
            mri.warehouse,
            w.department AS source_department
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
    """, as_dict=True)

    print("material_issues===============", material_issues)

    stock_qty_by_item = defaultdict(float)
    stock_warehouse_by_item = {}
    for row in stock_data:
        stock_qty_by_item[row.item_code] += flt(row.actual_qty)
        stock_warehouse_by_item.setdefault(row.item_code, row.warehouse)

    print("all purpose stock qty by item===============", dict(stock_qty_by_item))

    issue_qty_by_item = defaultdict(float)
    issue_mr_names_by_item = defaultdict(set)
    issue_warehouse_by_item = {}
    schedule_days_by_item = defaultdict(list)
    for row in material_issues:
        issue_qty_by_item[row.item_code] += flt(row.qty)
        issue_mr_names_by_item[row.item_code].add(row.parent)
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

        print(
            "all purpose compare:",
            "item_code:", item_code,
            "material_issue_qty:", issue_qty,
            "department_stock_qty:", stock_qty,
            "shortage_qty:", shortage_qty,
            "material_issue_mrs:", issue_mr_names,
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

    print("all purpose Purchase MR shortage item count===============", len(shortage_items))
    if not shortage_items:
        return

    shortage_items = _adjust_pp_shortage_qty_for_existing_mrs(
        shortage_items,
        material_request_type="Purchase",
    )
    print("all purpose Purchase MR shortage item count after existing Purchase adjustment===============", len(shortage_items))
    if not shortage_items:
        return

    max_schedule_days = max(
        days
        for item in shortage_items
        for days in item.get("schedule_days", [PP_MR_DEFAULT_SCHEDULE_DAYS])
    )
    schedule_date = add_days(nowdate(), max_schedule_days)
    print("all purpose Purchase MR schedule days===============", max_schedule_days)
    print("all purpose Purchase MR schedule date===============", schedule_date)
    item_fru_map = {
        d["name"]: d["fru_number"]
        for d in frappe.get_all(
            "Item",
            filters={"name": ["in", [i["item_code"] for i in shortage_items]]},
            fields=["name", "fru_number"],
        )
    }

    mr = frappe.new_doc("Material Request")
    mr.material_request_type = "Purchase"
    mr.naming_series = "MREQ-.YYYY.-.MM.-"
    mr.title = f"Purchase Against Material Issue - {nowdate()}"
    mr.company = _get_pp_default_company()
    mr.schedule_date = schedule_date
    mr.post_order_status = ""

    for item in shortage_items:
        print(
            "all purpose append Purchase MR item:",
            "item_code:", item["item_code"],
            "qty:", item["qty"],
            "warehouse:", item.get("warehouse"),
            "schedule_days:", item.get("schedule_days"),
            "source_material_issue_mrs:", item.get("material_issue_mrs"),
        )

        item_row = {
            "item_code": item["item_code"],
            "qty": item["qty"],
            "schedule_date": schedule_date,
            "fru_number": item_fru_map.get(item["item_code"]) or "N/A",
        }
        if item.get("warehouse"):
            item_row["warehouse"] = item.get("warehouse")

        mr.append("items", item_row)

    mr.insert(ignore_permissions=True)
    mr.submit()
    print("all purpose Purchase MR created:", mr.name, "items:", len(shortage_items))

    frappe.msgprint(
        _("Purchase Material Request Created against Material Issue shortage: {0}").format(
            frappe.bold(mr.name),
        )
    )

    return mr.name
