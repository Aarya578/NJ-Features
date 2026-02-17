# nj_planning/plan_all.py

import math
import frappe
import random
import logging
import functools
from frappe import _
from frappe.utils import flt
from typing import Dict, List, Optional, Union
from frappe.model.document import Document
from datetime import timedelta
from collections import defaultdict, Counter

# -------------------------
# Logger setup
# -------------------------
logger = frappe.logger("NJProductionPlanningAllocationLog", allow_site=True, file_count=5)
part_logger = frappe.logger("part_allocation", allow_site=True, file_count=10)


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

# Control whether planner writes to Serial No.to_make
UPDATE_SERIAL_TO_MAKE = True  # set to True if you really want to update Serial No in this run


# =========================
# Global caches
_ITEM_CORE: Dict[str, Dict] = {}
_ITEM_ATTRS: Dict[str, Dict] = {}
_ITEM_KEYS: Dict[str, Dict] = {}

# =========================
# Part allocation global state (virtual stock)
_PART_VIRTUAL_STOCK: Dict[str, float] = {}       # item_code -> physical stock in Stores - NJ (virtual snapshot)
_PART_PLANNED_ALLOCATION: Dict[str, float] = {}  # item_code -> qty already virtually allocated in this run
_DEPT_ALLOCATE_PARTS: Dict[str, bool] = {}       # department_name -> allocate_parts flag


# =========================
# Helpers
# =========================
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


# -------------------------
# ✅ NEW helpers: enforce processor lock
# -------------------------
def _serial_cfg(serial: Dict) -> tuple:
    """
    Extract (template, proc, ram, sto) from serial['forward_key_config'].

    NOTE: serial dict does NOT have template/proc/ram/sto fields directly.
    We must read them from forward_key_config = ("CONFIG", template, proc, ram, sto).
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


def _cfg_tuple_from_item(item_code: str) -> tuple:
    """
    ✅ FIXED:
    Return (template, processor, ram, storage) so we NEVER cross processor.
    """
    if item_code not in _ITEM_KEYS:
        _prime_item_cache([item_code])
    _, template, proc, ram, sto = _ITEM_KEYS[item_code]["config_key"]
    return (template, proc, ram, sto)


# =========================
# Public API (batch run)
# =========================
@frappe.whitelist()
@log_io
def nj_run_unified_production_plan(planning_horizon_days: int = 30) -> Dict:
    # -------- Load departments with SLA and group by sequence --------
    # Exclude departments where run_production_planning != 1
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

    # build lookup for allocate_parts per department
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
        forward_grain = forward_grain_per_seq[s]
        forward_keys_per_seq[s] = _build_forward_keys(sellable_items, forward_grain, sales_rate)

    # -------- Build per-dept inward pools (STRICT to serial.department) --------
    inward_serials_per_dept: Dict[str, List[Dict]] = {}
    for s in sequences:
        for d in depts_by_seq[s]:
            dept_name = d["name"]
            dept_doc = frappe.get_doc("Department", dept_name)
            inward_serials_per_dept[dept_name] = _get_inward_serials_for_department(dept_doc)

    priority_per_dept: Dict[str, int] = defaultdict(lambda: 1)

    for s in sorted(sequences, reverse=True):
        seq_forward_grain = forward_grain_per_seq[s]
        forward_keys = forward_keys_per_seq[s]
        seq_order_queues = order_demand_by_seq.get(s, defaultdict(list))

        for dept in sorted(depts_by_seq[s], key=lambda x: x["name"]):
            dept_name = dept["name"]

            if not dept.get("run_production_planning"):
                continue

            allow_reconfig = bool(dept.get("allow_reconfig"))
            inward_grain = "config" if dept.get("inwarded_config") else "model"
            forward_grain = seq_forward_grain

            serial_rows = inward_serials_per_dept.get(dept_name, [])
            serial_map = [_enrich_serial_from_attrs(sn) for sn in serial_rows]

            # 1) Orders (parts-gate is enforced DURING selection now)
            order_allocs, remaining_serials = _match_inventory_to_order_queues_for_sequence(
                seq=s,
                serial_map=serial_map,
                seq_order_queues=seq_order_queues,
                allow_reconfig=allow_reconfig,
                inward_grain=inward_grain,
                forward_grain=forward_grain,
                current_department=dept_name,
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
                    serial_age_days=alloc.get("age_days"),
                )
                priority_per_dept[dept_name] += 1

            # 2) Forecast (parts-gate is enforced DURING selection now)
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
    # current behavior = MAX SLA per sequence
    max_sla_per_seq = {}
    for s in sequences:
        max_sla_per_seq[s] = max(float(d.get("sla") or 0.0) for d in depts_by_seq[s]) if depts_by_seq[s] else 0.0
    cum_sla = {}
    for s in sorted(sequences):
        tail = sum(max_sla_per_seq[t] for t in sequences if t >= s)
        cum_sla[s] = tail
    return cum_sla

import frappe
from typing import List, Dict

# Assuming @log_io is a custom decorator defined in your app
# from nj_features.utils import log_io 

@log_io
def _get_pending_sales_orders(horizon_end=None) -> List[Dict]:
    """
    Pending SO lines computed using Delivery Note Item quantities (SO vs DN).
    Expands Product Bundles into stock-item components (pbi.qty * soi.qty).

    ✅ DELIVERY DATE LOGIC REMOVED:
    - No filtering on soi.delivery_date (overdue + future + any date included).
    """

    LOOKBACK_DAYS = 50

    # Note: Use %% for SQL LIKE patterns to escape the Python % formatter
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

                AND soi.item_group IN ('Laptops','Chromebooks')
                AND so.sale_type != 'Amazon'
                AND so.customer != 'King Technologies'

                AND (
                    IFNULL(it_so.is_stock_item, 0) = 1
                    OR pbi.item_code IS NOT NULL
                )

                AND (
                    IFNULL(it_so.is_stock_item, 0) = 1
                    OR it_comp.item_group IN ('Laptops','Chromebooks')
                )
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
    ✅ DELIVERY DATE / DUE DATE LOGIC REMOVED:
    - No days_to_due calculation
    - All order demand is placed into max_seq
    """
    demand_by_seq = {s: defaultdict(list) for s in sequences}

    for row in pending_orders:
        ic = row["item_code"]
        qty = int(math.ceil(row["qty_pending"]))

        # Always place orders into last sequence (no due-date based sequencing)
        place_seq = max_seq

        fgrain = forward_grain_per_seq[place_seq]
        key = _key_for_grain(ic, fgrain)

        ref = {
            "so_name": row["so_name"],
            "delivery_date": row.get("delivery_date"),  # kept only for display/debug
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
    """
    UPDATED:
    - Enforces parts allocation gate DURING selection.
    - If a serial is blocked by parts:
        - update Serial No.to_make
        - do NOT add it to allocations
        - remove it from pools
        - try next serial for the same order_ref

    ✅ FIXED:
    - NEVER change processor (CPU).
    - allow_reconfig allows only RAM/storage changes within SAME template + SAME processor.
    """

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

    for k in by_model:
        by_model[k] = _oldest_first(by_model[k])
    for k in by_config:
        by_config[k] = _oldest_first(by_config[k])

    for key, ref_list in sorted(list(seq_order_queues.items()), key=lambda kv: len(kv[1]), reverse=True):
        while ref_list:
            order_ref = ref_list[-1]  # PEEK (only pop when successfully fulfilled)

            target_cfg_tuple = None
            if order_ref.get("order_item_code"):
                # (template, proc, ram, sto)
                target_cfg_tuple = _cfg_tuple_from_item(order_ref["order_item_code"])

            chosen = None

            # ------------------------------
            # If demand is CONFIG
            # ------------------------------
            if key and key[0] == "CONFIG":
                if not allow_reconfig:
                    # STRICT: must match exact config
                    cfg_pool = by_config.get(key, [])
                    if not cfg_pool:
                        break
                    chosen = _oldest_first(cfg_pool)[0] if cfg_pool else None
                else:
                    # Reconfig allowed: choose from same MODEL but MUST match processor
                    model_key = ("MODEL", key[1])  # template
                    model_pool = by_model.get(model_key, [])
                    if not model_pool:
                        break

                    # 🔒 Enforce CPU match
                    if target_cfg_tuple:
                        _t_template, _t_proc, _t_ram, _t_sto = target_cfg_tuple
                        model_pool = [s for s in model_pool if _serial_cfg(s)[1] == _t_proc]
                        if not model_pool:
                            break

                    # Prefer exact config
                    if target_cfg_tuple:
                        exact = [s for s in model_pool if _same_config(s, target_cfg_tuple)]
                        exact = _oldest_first(exact)
                        if exact:
                            chosen = exact[0]

                    # Else same storage diff ram
                    if not chosen and target_cfg_tuple:
                        near = [s for s in model_pool if _same_storage_diff_ram(s, target_cfg_tuple)]
                        near = _oldest_first(near)
                        if near:
                            chosen = near[0]

                    # Else fallback oldest within SAME processor
                    if not chosen and model_pool:
                        chosen = _oldest_first(model_pool)[0]

            # ------------------------------
            # If demand is MODEL
            # ------------------------------
            else:
                model_pool = by_model.get(key, [])
                if not model_pool:
                    break

                # If order item known, still enforce CPU match (never cross CPU)
                if target_cfg_tuple:
                    _t_template, _t_proc, _t_ram, _t_sto = target_cfg_tuple
                    model_pool = [s for s in model_pool if _serial_cfg(s)[1] == _t_proc]
                    if not model_pool:
                        break

                chosen = _oldest_first(model_pool)[0] if model_pool else None

            if not chosen:
                break

            # Resolve target item to make
            if allow_reconfig and key and key[0] == "CONFIG":
                target_item_code = _target_item_for_key(key)
            else:
                target_item_code = chosen["item_code"]

            # Parts gate (if enabled for dept)
            if _DEPT_ALLOCATE_PARTS.get(current_department):
                ok = _maybe_allocate_parts_for_serial(chosen["serial_no"], current_department)
                if not ok:
                    # Required behavior: update to_make, but do NOT add to plan lines
                    _update_serial_to_make(chosen["serial_no"], target_item_code)

                    # Remove blocked serial from pools so we don't keep retrying it
                    remaining = [x for x in remaining if x["serial_no"] != chosen["serial_no"]]
                    by_model[chosen["forward_key_model"]] = [
                        x for x in by_model[chosen["forward_key_model"]] if x["serial_no"] != chosen["serial_no"]
                    ]
                    by_config[chosen["forward_key_config"]] = [
                        x for x in by_config[chosen["forward_key_config"]] if x["serial_no"] != chosen["serial_no"]
                    ]
                    continue  # retry SAME order_ref with a different serial

            # Success: consume the order ref and record allocation
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


def _estimate_forward_inventory(forward_keys, serials, forward_grain):
    inv = Counter()
    for s in serials:
        k = s["forward_key_config"] if forward_grain == "config" else s["forward_key_model"]
        if k in forward_keys:
            inv[k] += 1
    return dict(inv)


@log_io
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
    UPDATED:
    - Enforces parts allocation gate DURING selection.
    - If a serial is blocked by parts:
        - update Serial No.to_make
        - do NOT add to allocations
        - remove it from pools
        - continue

    ✅ FIXED:
    - NEVER change processor (CPU).
    - allow_reconfig allows only RAM/storage changes within SAME template + SAME processor.
    """
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
                chosen = pool[0]
            elif allow_reconfig:
                model_key = ("MODEL", target[1])
                pool2 = any_by_model.get(model_key, [])
                if pool2:
                    _, template, proc, ram, sto = target

                    # 🔒 DO NOT cross processor
                    pool2 = [s for s in pool2 if _serial_cfg(s)[1] == proc]
                    if not pool2:
                        chosen = None
                    else:
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

        if allow_reconfig and target and target[0] == "CONFIG":
            target_item_code = _target_item_for_key(target)
        else:
            target_item_code = chosen["item_code"]

        # Parts gate (if enabled for dept)
        if _DEPT_ALLOCATE_PARTS.get(current_department):
            ok = _maybe_allocate_parts_for_serial(chosen["serial_no"], current_department)
            if not ok:
                _update_serial_to_make(chosen["serial_no"], target_item_code)

                # Remove blocked serial from pools/remaining
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
                continue  # do not change DOI, do not add allocation

        # Update DOI for successful forecast allocation
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
                "age_days": chosen.get("age_days"),
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
    params = {"dept": dept_doc.name}

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
            iw.part_list_status
        FROM `tabSerial No` sn
        INNER JOIN `tabItem Wizards` iw
            ON sn.item_wizard = iw.name
        WHERE sn.department = %(dept)s
          AND (sn.status IS NULL OR sn.status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
          AND sn.item_wizard IS NOT NULL
          AND sn.item_wizard != ''
          AND iw.part_list_status = 'Completed'
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
    make every serial carry age_days so allocation can prefer older ones.
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

    - For serialized items: COUNT(Serial No)
    - For non-serialized items: SUM(Bin.actual_qty)

    Returns:
        (virtual_stock_dict, planned_allocation_dict)
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
    UPDATED (two-phase reservation):
    - Phase 1: check all MR lines are feasible WITHOUT changing globals.
    - Phase 2: only if feasible, commit reservation into _PART_PLANNED_ALLOCATION.

    Returns:
        True  -> all MR lines allocatable (reserved)
        False -> not allocatable (no reservation committed)
    """

    part_logger.debug(f"\n\n\n[ALLOCATE_STARTED] serial_no={serial_no}, dept={current_department}")

    if not _DEPT_ALLOCATE_PARTS.get(current_department):
        part_logger.debug(
            f"\n[ALLOCATE_RESULT] serial_no={serial_no}, dept={current_department}, "
            f"result=ALLOCATED (bypassed, allocate_parts disabled for this dept)"
        )
        return True

    mr_items = frappe.db.sql(
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
        {"serial_list": (serial_no,)},
        as_dict=True,
    )

    mr_names = sorted({row["material_request"] for row in mr_items}) if mr_items else []
    part_logger.debug(
        f"\n[MR_INFO] serial_no={serial_no}, dept={current_department}, "
        f"mr_count={len(mr_items)}, mr_list={mr_names}"
    )

    if not mr_items:
        part_logger.debug(
            f"\n[ALLOCATE_RESULT] serial_no={serial_no}, dept={current_department}, "
            f"result=ALLOCATED, reason='no pending Material Requests for this serial'"
        )
        return True

    global _PART_VIRTUAL_STOCK, _PART_PLANNED_ALLOCATION

    from collections import defaultdict as _dd

    to_reserve = _dd(float)
    unallocated_lines = []
    involved_item_codes = set()

    # Phase 1: feasibility check
    for row in mr_items:
        item_code = row["item_code"]
        involved_item_codes.add(item_code)

        mr_qty = flt(row.get("mr_qty") or row.get("stock_qty") or 0)
        if mr_qty <= 0:
            part_logger.debug(f"\n[MR_SKIP_ZERO_QTY] serial_no={serial_no}, item_code={item_code}, mr_qty={mr_qty}")
            continue

        already_planned = flt(_PART_PLANNED_ALLOCATION.get(item_code, 0.0))
        virtual_stock = flt(_PART_VIRTUAL_STOCK.get(item_code, 0.0))

        available_before = float(virtual_stock - already_planned - to_reserve[item_code])

        if available_before >= mr_qty:
            to_reserve[item_code] += mr_qty
            part_logger.debug(
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
            part_logger.debug(
                f"\n[LINE_CHECK_BLOCKED] serial_no={serial_no}, MR={row['material_request']}, item_code={item_code}, "
                f"required={mr_qty}, available={available_before} (insufficient stock)"
            )

    remaining_virtual_stock = {
        item_code: float(_PART_VIRTUAL_STOCK.get(item_code, 0.0) - _PART_PLANNED_ALLOCATION.get(item_code, 0.0))
        for item_code in sorted(involved_item_codes)
    }

    if unallocated_lines:
        part_logger.debug(
            f"\n[ALLOCATE_RESULT] serial_no={serial_no}, dept={current_department}, "
            f"result=NOT_ALLOCATED, reason='insufficient stock for some MR lines', "
            f"unallocated_lines={unallocated_lines}, remaining_virtual_stock={remaining_virtual_stock}"
        )
        return False

    # Phase 2: commit reservation
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

    part_logger.debug(
        f"\n[ALLOCATE_RESULT] serial_no={serial_no}, dept={current_department}, "
        f"result=ALLOCATED, reason='all MR lines fully allocatable from virtual stock', "
        f"allocated_lines={alloc_rows}, remaining_virtual_stock={remaining_virtual_stock_after}"
    )

    # If you want to persist "part lines child table", do it here (ONLY when allocated).

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
    # For included rows, update to_make as usual
    _update_serial_to_make(serial_no, item_code_to_make)

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
            "serial_age_days": serial_age_days,
            "allocate_parts": 1,  # only rows that passed parts-gate get appended
        },
    )
