# nj_planning/plan_all.py

import math
import random
import logging
import functools
import frappe
from frappe import _
from typing import Dict, List, Optional, Union
from frappe.model.document import Document
from datetime import timedelta
from collections import defaultdict, Counter
from frappe.utils import flt  # NEW


# -------------------------
# Logger setup
# -------------------------
logger = frappe.logger("nj_planning", allow_site=True, file_count=5, max_size=10_000_000)


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
SELLABLE_ITEM_GROUPS = {"Laptops", "Chromebooks", "Chromeboxes"}

# Take only the last 15 days for sales rate calc
RECENCY_WINDOW_DAYS = 15
RECENCY_MAX_WEIGHT = 30

REQUIRE_SHOPIFY_IDS_FOR_SELLABLE = True

PROCESSOR_ATTR = "Processor Type1"
RAM_ATTR = "RAM Capacity"
STORAGE_ATTR = "Storage Capacity"

ALLOWED_ITEM_MODELS = set()

# =========================
# Global caches

_ITEM_CORE: Dict[str, Dict] = {}
_ITEM_ATTRS: Dict[str, Dict] = {}
_ITEM_KEYS: Dict[str, Dict] = {}

# =========================
# Part allocation global state (virtual stock)

_PART_VIRTUAL_STOCK: Dict[str, float] = {}       # item_code -> physical stock in Stores - NJ
_PART_PLANNED_ALLOCATION: Dict[str, float] = {}  # item_code -> qty already virtually allocated in this run
_DEPT_ALLOCATE_PARTS: Dict[str, bool] = {}       # department_name -> allocate_parts flag


# =========================
# Helpers for ordering serials
# =========================
def _oldest_first(lst: List[Dict]) -> List[Dict]:
    """
    Age-aware sort:
    - prefer items with higher age_days (older first)
    - fallback to purchase_date
    - fallback to creation
    """

    def _key(s):
        if s.get("age_days") is not None:
            # older first -> negative age
            return (-int(s.get("age_days") or 0), s.get("purchase_date") or s.get("creation") or "")
        return (0, s.get("purchase_date") or s.get("creation") or "")

    return sorted(lst, key=_key)


def _same_config(serial: Dict, target_cfg: tuple) -> bool:
    return (
        serial.get("template") == target_cfg[0]
        and serial.get("ram") == target_cfg[1]
        and serial.get("storage") == target_cfg[2]
    )


def _same_storage_diff_ram(serial: Dict, target_cfg: tuple) -> bool:
    return (
        serial.get("template") == target_cfg[0]
        and serial.get("storage") == target_cfg[2]
        and serial.get("ram") != target_cfg[1]
    )


def _cfg_tuple_from_item(item_code: str) -> tuple:
    if item_code not in _ITEM_KEYS:
        _prime_item_cache([item_code])
    _, template, _proc, ram, sto = _ITEM_KEYS[item_code]["config_key"]
    return (template, ram, sto)


# =========================
# Public API (batch run)
# =========================
@frappe.whitelist()
@log_io
def nj_run_unified_production_plan(planning_horizon_days: int = 30) -> Dict:
    # -------- Load departments with SLA and group by sequence --------
    # CHANGE: Exclude departments where run_production_planning != 1
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
            "allocate_parts",  # NEW
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

    # NEW: build lookup for allocate_parts per department
    global _DEPT_ALLOCATE_PARTS, _PART_VIRTUAL_STOCK, _PART_PLANNED_ALLOCATION
    _DEPT_ALLOCATE_PARTS = {d["name"]: bool(d.get("allocate_parts")) for d in depts}

    # If any department uses allocate_parts, build initial virtual stock from Stores - NJ
    if any(_DEPT_ALLOCATE_PARTS.values()):
        _PART_VIRTUAL_STOCK, _PART_PLANNED_ALLOCATION = _build_initial_part_stock()
    else:
        _PART_VIRTUAL_STOCK = {}
        _PART_PLANNED_ALLOCATION = {}

    cum_sla = _build_cumulative_sla_multi(depts_by_seq, sequences)

    forward_grain_per_seq: Dict[int, str] = {}
    for s in sequences:
        forward_grain_per_seq[s] = "config" if any(bool(d.get("forwarded_config")) for d in depts_by_seq[s]) else "model"

    # -------- Sales Orders → per-sequence order queues --------
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

    # -------- Sales-rate & portfolio --------
    sellable_items = _get_sellable_items()
    if not sellable_items:
        logger.warning("SELLABLE portfolio is empty. Check REQUIRE_SHOPIFY_IDS_FOR_SELLABLE and item groups.")

    sales_rate = _compute_recency_weighted_sales_rates_SO_union(sellable_items)
    if not sales_rate:
        logger.warning("No sales_rate computed.")
    random.seed(42)

    # -------- Create ONE unified plan doc --------
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

    # Per-sequence forward-key universe
    forward_keys_per_seq: Dict[int, List] = {}
    for s in sequences:
        fwd_grain = forward_grain_per_seq[s]
        forward_keys_per_seq[s] = _build_forward_keys(sellable_items, fwd_grain, sales_rate)

    # -------- Build per-dept inward pools (STRICT to serial.department) --------
    inward_serials_per_dept: Dict[str, List[Dict]] = {}
    for s in sequences:
        for d in depts_by_seq[s]:
            dept_name = d["name"]
            dept_doc = frappe.get_doc("Department", dept_name)
            # CHANGE: fetch ALL serials that belong to this department (independent of warehouse)
            inward_serials_per_dept[dept_name] = _get_inward_serials_for_department(dept_doc)

    priority_per_dept: Dict[str, int] = defaultdict(lambda: 1)

    for s in sorted(sequences, reverse=True):
        seq_forward_grain = forward_grain_per_seq[s]
        forward_keys = forward_keys_per_seq[s]
        seq_order_queues = order_demand_by_seq.get(s, defaultdict(list))

        for dept in sorted(depts_by_seq[s], key=lambda x: x["name"]):
            dept_name = dept["name"]

            # Even though we filtered upstream, keep this guard (no-op if all are 1)
            if not dept.get("run_production_planning"):
                continue

            allow_reconfig = bool(dept.get("allow_reconfig"))
            inward_grain = "config" if dept.get("inwarded_config") else "model"
            forward_grain = seq_forward_grain

            # serials strictly for THIS department (department-centric intake)
            serial_rows = inward_serials_per_dept.get(dept_name, [])
            serial_map = [_enrich_serial_from_attrs(sn) for sn in serial_rows]

            # 1) Orders
            order_allocs, remaining_serials = _match_inventory_to_order_queues_for_sequence(
                seq=s,
                serial_map=serial_map,
                seq_order_queues=seq_order_queues,
                allow_reconfig=allow_reconfig,
                inward_grain=inward_grain,
                forward_grain=forward_grain,
            )

            # DOI snapshot after including order allocations
            fwd_inventory = _estimate_forward_inventory(forward_keys, remaining_serials, forward_grain)
            for alloc in order_allocs:
                k = alloc["forward_key"]
                fwd_inventory[k] = fwd_inventory.get(k, 0) + 1

            doi_snapshot = {
                k: (float(fwd_inventory.get(k, 0)) / max(1.0, float(sales_rate.get(k, 1.0)))) for k in forward_keys
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
                    serial_age_days=alloc.get("age_days"),  # show age on plan row
                )
                priority_per_dept[dept_name] += 1

            # 2) Forecast
            forecast_allocs = _allocate_forecast_to_balance_doi(
                remaining_serials=remaining_serials,
                forward_grain=forward_grain,
                allow_reconfig=allow_reconfig,
                forward_keys=forward_keys,
                sales_rate=sales_rate,
                current_doi=doi_snapshot,
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
                    serial_age_days=alloc.get("age_days"),  # show age on plan row
                )
                priority_per_dept[dept_name] += 1

            consumed_serial_nos = {a["serial_no"] for a in order_allocs + forecast_allocs}
            inward_serials_per_dept[dept_name] = [
                sn for sn in inward_serials_per_dept[dept_name] if sn["name"] not in consumed_serial_nos
            ]

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
    # NOTE: current behavior = MAX SLA per sequence (unchanged)
    max_sla_per_seq = {}
    for s in sequences:
        max_sla_per_seq[s] = max(float(d.get("sla") or 0.0) for d in depts_by_seq[s]) if depts_by_seq[s] else 0.0
    cum_sla = {}
    for i, s in enumerate(sorted(sequences)):
        tail = sum(max_sla_per_seq[t] for t in sequences if t >= s)
        cum_sla[s] = tail
    return cum_sla


@log_io
def _get_pending_sales_orders(horizon_end) -> List[Dict]:
    # NOTE: The WHERE clause has been updated to reflect new filtering rules:
    # 1. Use explicit status checks instead of docstatus=1.
    # 2. Filter orders created in the last 40 days.
    # 3. Use the updated list of item groups (Laptops, Chromebooks, MacBooks).
    # 4. Exclude 'Amazon' sales type and 'King Technologies' customer.

    soi = frappe.db.sql(
        """
        SELECT
            so.name AS so_name, soi.name AS soi_name, so.customer, so.transaction_date,
            soi.item_code, (soi.qty - IFNULL(soi.delivered_qty,0)) AS qty_pending,
            soi.delivery_date
        FROM `tabSales Order` so
        JOIN `tabSales Order Item` soi ON soi.parent = so.name
        WHERE 
            -- New Status Filter for Active Orders
            so.status NOT IN ('Closed','Completed','Draft','Cancelled')
            -- Critical: Only show items with pending quantity
            AND (soi.qty - IFNULL(soi.delivered_qty,0)) > 0
            -- New Creation Date Filter (Last 40 Days)
            AND so.creation > CURDATE() - INTERVAL 40 DAY
            -- Original Delivery Date Filter (uses passed 'horizon_end')
            AND (soi.delivery_date IS NULL OR soi.delivery_date >= %s)
            -- Updated Item Group Filter
            AND soi.item_group IN ('Laptops', 'Chromebooks', 'MacBooks')
            -- New Exclusions
            AND so.sale_type != 'Amazon'
            AND so.customer != 'King Technologies'
        ORDER BY
            soi.parent, soi.item_code;
        """,
        (horizon_end,),  # Pass the delivery date floor as the parameter
        as_dict=True,
    )
    return soi


@log_io
def _allocate_orders_to_sequences_multi(
    pending_orders, sequences, cum_sla, today, forward_grain_per_seq, max_seq
):
    demand_by_seq = {s: defaultdict(list) for s in sequences}
    for row in pending_orders:
        ic = row["item_code"]
        qty = int(math.ceil(row["qty_pending"]))
        delivery_date = row.get("delivery_date")
        due = frappe.utils.getdate(delivery_date) if delivery_date else None
        days_to_due = (due - today).days if due else None

        if days_to_due is None or days_to_due < 0:
            place_seq = max_seq
        else:
            candidates = [s for s in sequences if cum_sla[s] <= days_to_due]
            place_seq = min(candidates) if candidates else max_seq

        fgrain = forward_grain_per_seq[place_seq]
        key = _key_for_grain(ic, fgrain)

        ref = {
            "so_name": row["so_name"],
            "delivery_date": delivery_date,
            "order_item_code": ic,
        }
        for _ in range(qty):
            demand_by_seq[place_seq][key].append(ref)

    return demand_by_seq


# =========================
# Sellable portfolio & sales-rate
# =========================
@log_io
def _get_sellable_items() -> List[Dict]:
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
            INNER JOIN `tabProduct Bundle Item` pbi ON i.name = pbi.parent
            INNER JOIN `tabItem` ci ON pbi.item_code = ci.name
            WHERE
                1=1
                {where_shopify}
                AND i.item_model IN ({",".join(["%s"] * len(placeholders_list))})
                AND ci.item_group IN %s
                AND i.has_variants = 0
            """,
            tuple(placeholders_list) + (tuple(SELLABLE_ITEM_GROUPS),),
            as_dict=True,
        )
    else:
        rows = frappe.db.sql(
            f"""
            SELECT DISTINCT pbi.item_code AS item_code
            FROM `tabItem` i
            INNER JOIN `tabProduct Bundle Item` pbi ON i.name = pbi.parent
            INNER JOIN `tabItem` ci ON pbi.item_code = ci.name
            WHERE
                1=1
                {where_shopify}
                AND ci.item_group IN %(igroups)s
                AND i.has_variants = 0
            """,
            {"igroups": tuple(SELLABLE_ITEM_GROUPS)},
            as_dict=True,
        )

    sellable = [{"name": r["item_code"]} for r in (rows or [])]
    if not sellable:
        logger.warning("No sellable Product Bundle components found with current filters.")
    _prime_item_cache([r["name"] for r in sellable])
    print("sellable ------------ ", sellable)
    return sellable


@log_io
def _compute_recency_weighted_sales_rates_SO_union(sellable_items: List[Dict]) -> Dict:
    """
    Compute recency-weighted sales rates over the last 15 days.
    IMPORTANT: Days with zero sales are COMPLETELY ignored (no weight contribution).
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

    from collections import defaultdict as _dd

    daily = _dd(lambda: _dd(float))
    today = frappe.utils.getdate(frappe.utils.nowdate())

    for r in rows:
        ic = r["item_code"]
        km = _get_model_key(ic)
        kc = _get_config_key(ic)
        d = frappe.utils.getdate(r["sale_date"])
        qty = float(r["daily_sales"])
        # accumulate raw daily sales; we'll ignore zero later
        daily[km][d] += qty
        daily[kc][d] += qty

    # NEW LOGIC: 15-day window, skip zero-sales days (no weight contribution)
    for key in daily:
        num = 0.0
        den = 0.0
        for dd in range(RECENCY_WINDOW_DAYS, 0, -1):
            day = today - timedelta(days=(dd - 1))
            qty = float(daily[key].get(day, 0.0))
            if qty <= 0.0:
                continue  # do NOT add weight for zero-sales days
            # recency weight increases toward "today"; cap at RECENCY_MAX_WEIGHT
            w = max(1, min(RECENCY_MAX_WEIGHT, RECENCY_WINDOW_DAYS - dd + 1))
            num += w * qty
            den += w
        rate = (num / den) if den else 0.0
        rates[key] = (rate if rate > 0 else 1.0)

    # Ensure all sellable models/configs at least get a baseline of 1.0
    for it in (sellable_items or []):
        km = _get_model_key(it["name"])
        kc = _get_config_key(it["name"])
        rates.setdefault(km, 1.0)
        rates.setdefault(kc, 1.0)

    return rates


@log_io
def _build_forward_keys(sellable_items, forward_grain, sales_rate):
    variants_by_template = defaultdict(list)
    templates = set()

    for it in sellable_items or []:
        ic = it["name"]
        core = _ITEM_CORE.get(ic, {})
        template = core.get("variant_of") or ic
        km = _get_model_key(ic)
        kc = _get_config_key(ic)
        if template == ic:
            templates.add(km)
        else:
            variants_by_template[km].append(kc)

    if forward_grain == "model":
        return list(templates or variants_by_template.keys())

    keys = []
    for model_key, configs in variants_by_template.items():
        configs.sort(key=lambda ck: (-(sales_rate.get(ck, 1.0)), random.random()))
        # Include ALL configs (no max variants per template)
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
    seq, serial_map, seq_order_queues, allow_reconfig, inward_grain, forward_grain
):
    allocations = []
    remaining = serial_map[:]
    if not seq_order_queues:
        return allocations, remaining

    from collections import defaultdict

    by_model = defaultdict(list)
    by_config = defaultdict(list)
    for s in remaining:
        by_model[s["forward_key_model"]].append(s)
        by_config[s["forward_key_config"]].append(s)

    # sort pools by AGE (via _oldest_first)
    for k in by_model:
        by_model[k] = _oldest_first(by_model[k])
    for k in by_config:
        by_config[k] = _oldest_first(by_config[k])

    # Sort queues by size descending for mild batching
    for key, ref_list in sorted(list(seq_order_queues.items()), key=lambda kv: len(kv[1]), reverse=True):
        while ref_list:
            order_ref = ref_list.pop()
            chosen = None

            target_cfg_tuple = None
            if order_ref.get("order_item_code"):
                target_cfg_tuple = _cfg_tuple_from_item(order_ref["order_item_code"])

            # Ensure we have the model key for the pool
            model_key = ("MODEL", key[1]) if key and key[0] == "CONFIG" else key
            model_pool = by_model.get(model_key, [])

            # 1) Exact config first (even if forward_grain == 'model')
            if target_cfg_tuple:
                exact = [s for s in model_pool if _same_config(s, target_cfg_tuple)]
                exact = _oldest_first(exact)
                if exact:
                    chosen = exact.pop(0)

            # 2) Same storage, different RAM
            if not chosen and target_cfg_tuple:
                near = [s for s in model_pool if _same_storage_diff_ram(s, target_cfg_tuple)]
                near = _oldest_first(near)
                if near:
                    chosen = near.pop(0)

            # 3) Any same model (oldest first)
            if not chosen and model_pool:
                chosen = _oldest_first(model_pool)[0]

            if not chosen:
                break

            target_item_code = _target_item_for_key(key) if allow_reconfig else chosen["item_code"]

            allocations.append(
                {
                    "serial_no": chosen["serial_no"],
                    "warehouse": chosen["warehouse"],
                    "target_item_code": target_item_code,
                    "forward_key": key,
                    "order_name": order_ref.get("so_name"),
                    "required_by": order_ref.get("delivery_date"),
                    "age_days": chosen.get("age_days"),  # NEW
                }
            )

            # Remove chosen from structures
            remaining = [x for x in remaining if x["serial_no"] != chosen["serial_no"]]
            by_model[chosen["forward_key_model"]] = [
                x for x in by_model[chosen["forward_key_model"]] if x["serial_no"] != chosen["serial_no"]
            ]
            by_config[chosen["forward_key_config"]] = [
                x for x in by_config[chosen["forward_key_config"]] if x["serial_no"] != chosen["serial_no"]
            ]

    # Cleanup emptied queues
    for k in [k for k, v in list(seq_order_queues.items()) if not v]:
        del seq_order_queues[k]

    return allocations, remaining


def _estimate_forward_inventory(forward_keys, serials, forward_grain):
    inv = Counter()
    for s in serials:
        k = s["forward_key_config"] if forward_grain == "config" else s["forward_key_model"]
        if k in forward_keys:
            inv[k] += 1
    return dict(inv)


@log_io
def _allocate_forecast_to_balance_doi(
    remaining_serials, forward_grain, allow_reconfig, forward_keys, sales_rate, current_doi
):
    allocations = []

    from collections import defaultdict

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
        work.sort(key=lambda k: current_doi.get(k, 0.0))
        target = work[0]

        chosen = None
        if forward_grain == "config":
            pool = buckets.get(target, [])
            if pool:
                chosen = pool.pop(0)
            elif allow_reconfig:
                model_key = ("MODEL", target[1])
                pool2 = any_by_model.get(model_key, [])
                if pool2:
                    _, template, _p, ram, sto = target
                    target_cfg_tuple = (template, ram, sto)
                    near = [s for s in pool2 if _same_storage_diff_ram(s, target_cfg_tuple)]
                    near = _oldest_first(near)
                    if near:
                        chosen = near.pop(0)
                    else:
                        chosen = _oldest_first(pool2)[0] if pool2 else None
        else:
            pool = buckets.get(target, [])
            if pool:
                chosen = pool.pop(0)

        if not chosen:
            work.pop(0)
            continue

        target_item_code = _target_item_for_key(target) if allow_reconfig else chosen["item_code"]

        rate = max(1.0, float(sales_rate.get(target, 1.0)))
        inv_now = current_doi.get(target, 0.0) * rate
        new_doi = (inv_now + 1.0) / rate
        current_doi[target] = new_doi

        allocations.append(
            {
                "serial_no": chosen["serial_no"],
                "warehouse": chosen["warehouse"],
                "target_item_code": target_item_code,
                "forward_key": target,
                "doi": new_doi,
                "age_days": chosen.get("age_days"),  # NEW
            }
        )

        # Remove chosen from buckets
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


def _get_inward_warehouses_for_department(dept_doc) -> List[str]:
    """
    Retained for reference; not used by _get_inward_serials_for_department anymore.
    """
    whs: set = set()

    for row in (getattr(dept_doc, "inventory_details_child", None) or []):
        raw = (row.get("inwarded_warehouse_list") or "").strip()
        if not raw:
            dept_for_wh = row.get("inwarded_inventory")
            if dept_for_wh:
                names = frappe.get_all("Warehouse", filters={"department": dept_for_wh}, pluck="name")
                whs.update(names or [])
        else:
            for w in [x.strip() for x in raw.split(",") if x.strip()]:
                whs.add(w)

    return sorted(whs)


@log_io
def _get_inward_serials_for_department(dept_doc) -> List[Dict]:
    """
    CHANGE: Department-centric intake — fetch ALL active serials that belong to this department,
    regardless of which warehouse they sit in. Active = not Delivered/Scrapped (or status is NULL).
    ALSO: fetch purchase_date so we can compute age_days.
    """
    rows = frappe.db.sql(
        """
        SELECT
            name,
            item_code,
            warehouse,
            department,
            creation,
            purchase_date
        FROM `tabSerial No`
        WHERE department = %s
          AND (status IS NULL OR status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
          AND (item_wizard IS NOT NULL OR item_wizard != '')
        """,
        (dept_doc.name,),
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
            "model_key": ("MODEL", template),
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
def _find_variant_by_attributes(template_item: str, attr_map: Dict) -> Union[str, None]:
    if not template_item or not attr_map:
        return None
    variants = frappe.get_all("Item", filters={"variant_of": template_item}, pluck="name")
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
    """
    NEW: make every serial carry age_days so allocation can prefer older ones.
    """
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

    return {
        "serial_no": snrow["name"],
        "item_code": ic,
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

    Returns:
        (virtual_stock_dict, planned_allocation_dict)
    """
    warehouses = frappe.get_all(
        "Warehouse",
        filters={"department": "Stores - NJ"},
        pluck="name",
    )

    if not warehouses:
        logger.warning("No warehouses found under 'Stores - NJ' department for part allocation.")
        # No stock, but we still run with empty virtual stock
        return {}, {}

    stock_results = frappe.db.sql(
        """
        SELECT item_code, SUM(actual_qty) AS total_qty
        FROM `tabBin`
        WHERE warehouse IN %(warehouses)s
        GROUP BY item_code
        """,
        {"warehouses": tuple(warehouses)},
        as_dict=True,
    )

    stock_data = {row["item_code"]: flt(row["total_qty"] or 0) for row in stock_results}

    # planned_allocation starts at 0 for every item
    return stock_data, {}


@log_io
def _maybe_allocate_parts_for_serial(serial_no: str, current_department: str) -> bool:
    """
    Part allocation gate for a serial.

    - If allocate_parts is NOT enabled for this department -> always True (no gating).
    - If no open MR exists for this serial -> True (we can show it in plan).
    - If open MR exists:
        * Try to allocate from Stores - NJ virtual stock.
        * For each MR line we can fully satisfy, reserve stock in _PART_PLANNED_ALLOCATION
          and create a row in Serial No's production_planning_allocation child table (for reference).
        * If ANY MR line remains unallocated (insufficient stock) -> return False (skip this serial in plan).
        * If all MR lines are allocated -> return True (serial can appear in plan).

    Returns:
        True  -> caller should append the plan row.
        False -> caller should SKIP appending the plan row.
    """
    # If this department doesn't use allocate_parts, nothing to do
    if not _DEPT_ALLOCATE_PARTS.get(current_department):
        return True

    # Fetch open Material Requests for this serial
    mr_items = frappe.db.sql(
        """
        SELECT 
            MRI.parent AS material_request,
            MRI.item_code,
            Sr.serial_no AS against_serial_no,
            MRI.stock_qty,
            MRI.qty AS mr_qty,
            Sr.item_group
        FROM `tabMaterial Request Item` MRI
        INNER JOIN `tabMaterial Request` MR 
            ON MRI.parent = MR.name 
            AND MR.docstatus = 1 
            AND IFNULL(MR.post_order_status, '') != 'Completed'
        INNER JOIN `tabSerial No` Sr 
            ON Sr.serial_no = MRI.serial_no 
            AND Sr.item_group = 'Laptops' 
            AND Sr.status = 'Active'
        WHERE Sr.serial_no IN %(serial_list)s
        ORDER BY Sr.serial_no
        """,
        {"serial_list": (serial_no,)},
        as_dict=True,
    )

    # No MR at all -> free to plan
    if not mr_items:
        return True

    has_unallocated = False
    serial_doc = None

    global _PART_VIRTUAL_STOCK, _PART_PLANNED_ALLOCATION

    for row in mr_items:
        item_code = row["item_code"]
        mr_qty = flt(row.get("mr_qty") or row.get("stock_qty") or 0)
        if mr_qty <= 0:
            continue

        # Available = physical snapshot - already planned across all departments in this run
        already_planned = _PART_PLANNED_ALLOCATION.get(item_code, 0.0)
        available = float(_PART_VIRTUAL_STOCK.get(item_code, 0.0) - already_planned)

        if available >= mr_qty:
            # We can allocate this MR line
            _PART_PLANNED_ALLOCATION[item_code] = already_planned + mr_qty

            # Persist reference on Serial No -> production_planning_allocation child table
            try:
                if serial_doc is None:
                    serial_doc = frappe.get_doc("Serial No", serial_no)

                # *** Remove existing rows in child table ***
                serial_doc.set("production_planning_allocation", [])
                
                serial_doc.append(
                    "production_planning_allocation",
                    {
                        # TODO: adjust fieldnames to match your child doctype
                        # Example:
                        "material_request": row["material_request"],  # MR No
                        "item_code": item_code,                       # Part code
                        "allocated_qty": mr_qty,                      # Allocated qty
                    },
                )
            except Exception as e:
                logger.warning("Could not append production_planning_allocation for serial %s: %s", serial_no, e)
        else:
            # Not enough stock for this MR line -> serial should NOT appear in plan
            has_unallocated = True

    if serial_doc is not None:
        try:
            serial_doc.flags.ignore_mandatory = True
            serial_doc.save(ignore_permissions=True)
        except Exception as e:
            logger.warning("Could not save Serial No %s for part allocation: %s", serial_no, e)

    # If any MR line is still unallocated, this serial is blocked by parts
    return not has_unallocated


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
    serial_age_days: Optional[int] = None,  # NEW
):
    # Default: assume row is allowed
    allowed = True

    # NEW: Part allocation gate
    # If allocate_parts is enabled for this department:
    #   - If MR is missing or fully allocated -> row is appended.
    #   - If any MR remains unallocated -> row is SKIPPED.
    try:
        if _DEPT_ALLOCATE_PARTS and _DEPT_ALLOCATE_PARTS.get(current_department):
            allowed = _maybe_allocate_parts_for_serial(serial_no, current_department)
            if not allowed:
                # Do NOT append this row; the serial is still waiting on parts.
                return
    except Exception as e:
        # Fail safe: log and continue without blocking planning
        logger.exception("Part allocation check failed for serial %s: %s", serial_no, e)
        allowed = True  # on error, don't block the plan

    # NEW: push suggested to_make into Serial No
    try:
        sn_doc = frappe.get_doc("Serial No", serial_no)
        sn_doc.to_make = item_code_to_make   # <-- your field on Serial No
        sn_doc.flags.ignore_mandatory = True
        sn_doc.save(ignore_permissions=True)
    except Exception as e:
        logger.warning("Could not update Serial No.to_make for %s: %s", serial_no, e)

    # Append the plan row
    plan_doc.append(
        "lines",
        {
            "serial_no": serial_no,
            "current_warehouse": current_warehouse,
            "current_department": current_department,
            "sales_rate": sales_rate,
            "doi": doi,
            "sales_order_no": sales_order_number,
            "delivery_date": delivery_date,
            "item_code": item_code_to_make,
            "reason": reason,
            "priority_rank": int(priority_rank),
            # add only if your Doctype has this field; else remove
            "serial_age_days": serial_age_days,
            # will always be 1 for any row that survives the gate
            "allocate_parts": 1 if allowed else 0,
        },
    )
