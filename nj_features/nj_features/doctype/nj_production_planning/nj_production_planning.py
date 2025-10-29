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

RECENCY_WINDOW_DAYS = 60
RECENCY_MAX_WEIGHT = 30

REQUIRE_SHOPIFY_IDS_FOR_SELLABLE = True

PROCESSOR_ATTR = "Processor Type1"
RAM_ATTR = "RAM Capacity"
STORAGE_ATTR = "Storage Capacity"

ALLOWED_ITEM_MODELS = set()

# =========================
# Global caches
# =========================
_ITEM_CORE: Dict[str, Dict] = {}
_ITEM_ATTRS: Dict[str, Dict] = {}
_ITEM_KEYS: Dict[str, Dict] = {}

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
        fields=["name", "department_sequence", "sla", "allow_reconfig",
                "inwarded_model", "forwarded_model", "inwarded_config", "forwarded_config", "run_production_planning"],
        order_by="department_sequence asc, name asc"
    )
    if not depts:
        frappe.throw("No departments with SLA found.")

    depts_by_seq: Dict[int, List[Dict]] = defaultdict(list)
    for d in depts:
        depts_by_seq[d["department_sequence"]].append(d)

    sequences = sorted(depts_by_seq.keys())
    max_seq = max(sequences)

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
        max_seq=max_seq
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
    now_stamp = frappe.utils.now_datetime().strftime('%Y-%m-%d %H:%M:%S')

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
        forward_keys_per_seq[s] = _build_forward_keys(
            sellable_items, fwd_grain, sales_rate
        )

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
                forward_grain=forward_grain
            )

            # DOI snapshot after including order allocations
            fwd_inventory = _estimate_forward_inventory(forward_keys, remaining_serials, forward_grain)
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
                    priority_rank=priority_per_dept[dept_name]
                )
                priority_per_dept[dept_name] += 1

            # 2) Forecast
            forecast_allocs = _allocate_forecast_to_balance_doi(
                remaining_serials=remaining_serials,
                forward_grain=forward_grain,
                allow_reconfig=allow_reconfig,
                forward_keys=forward_keys,
                sales_rate=sales_rate,
                current_doi=doi_snapshot
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
                    priority_rank=priority_per_dept[dept_name]
                )
                priority_per_dept[dept_name] += 1

            consumed_serial_nos = {a["serial_no"] for a in order_allocs + forecast_allocs}
            inward_serials_per_dept[dept_name] = [sn for sn in inward_serials_per_dept[dept_name] if sn["name"] not in consumed_serial_nos]

    plan_doc.save(ignore_permissions=True)
    total_rows = len(plan_doc.get("lines") or [])
    frappe.db.commit()

    return {
        "total_departments": 1,
        "total_rows": total_rows,
        "plans": [{
            "department": "All Departments",
            "plan_name": plan_doc.name,
            "title": getattr(plan_doc, "plan_title", plan_doc.name),
            "total_rows": total_rows
        }],
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

# =========================
# Sales Orders → demand placement
# =========================
@log_io
def _get_pending_sales_orders(horizon_end) -> List[Dict]:
    # NOTE: Keep existing logic as per discussion (revisit later)
    soi = frappe.db.sql(
        """
        SELECT
            so.name AS so_name, soi.name AS soi_name, so.customer, so.transaction_date,
            soi.item_code, (soi.qty - IFNULL(soi.delivered_qty,0)) AS qty_pending,
            soi.delivery_date
        FROM `tabSales Order` so
        JOIN `tabSales Order Item` soi ON soi.parent = so.name
        WHERE so.docstatus = 1
          AND (soi.qty - IFNULL(soi.delivered_qty,0)) > 0
          AND (soi.delivery_date IS NULL OR soi.delivery_date >= %s)
          AND soi.item_group IN ('Laptops', 'Chromebooks', 'Chromeboxes')
        """,
        (frappe.utils.add_days(frappe.utils.nowdate(), -60),),
        as_dict=True
    )
    return soi

@log_io
def _allocate_orders_to_sequences_multi(pending_orders, sequences, cum_sla, today, forward_grain_per_seq, max_seq):
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
            as_dict=True
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
            as_dict=True
        )

    sellable = [{"name": r["item_code"]} for r in (rows or [])]
    if not sellable:
        logger.warning("No sellable Product Bundle components found with current filters.")
    _prime_item_cache([r["name"] for r in sellable])
    print("sellable ------------ ", sellable)
    return sellable

@log_io
def _compute_recency_weighted_sales_rates_SO_union(sellable_items: List[Dict]) -> Dict:
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
        as_dict=True
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
        daily[km][d] += float(r["daily_sales"])
        daily[kc][d] += float(r["daily_sales"])

    for key in daily:
        num = 0.0
        den = 0.0
        for dd in range(RECENCY_WINDOW_DAYS, 0, -1):
            day = today - timedelta(days=(dd - 1))
            w = max(1, min(RECENCY_MAX_WEIGHT, 31 - dd))  # 1..30
            qty = daily[key].get(day, 0.0)
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
def _match_inventory_to_order_queues_for_sequence(seq, serial_map, seq_order_queues, allow_reconfig, inward_grain, forward_grain):
    """
    Greedy match serials to order queues for this sequence.
    serial_map is already restricted to THIS department's serials.
    """
    allocations = []
    remaining = serial_map[:]
    if not seq_order_queues:
        return allocations, remaining

    if inward_grain == "model":
        idx = defaultdict(list)
        for s in serial_map:
            idx[s["forward_key_model"]].append(s)
    else:
        idx = defaultdict(list)
        for s in serial_map:
            idx[s["forward_key_config"]].append(s)

    for key, ref_list in sorted(seq_order_queues.items(), key=lambda kv: len(kv[1]), reverse=True):
        while ref_list:
            chosen = None
            if inward_grain == "config":
                pool = idx.get(key, [])
                if pool:
                    chosen = pool.pop()
                elif allow_reconfig:
                    model_key = ("MODEL", key[1])
                    pool2 = idx.get(model_key, [])
                    if pool2:
                        chosen = pool2.pop()
            else:
                model_key = ("MODEL", key[1])
                pool = idx.get(model_key, [])
                if pool:
                    chosen = pool.pop()

            if not chosen:
                break

            order_ref = ref_list.pop()

            # When reconfig is NOT allowed, we must keep the serial's current item_code.
            if allow_reconfig:
                target_item_code = _target_item_for_key(key)
            else:
                target_item_code = chosen["item_code"]

            allocations.append({
                "serial_no": chosen["serial_no"],
                "warehouse": chosen["warehouse"],
                "target_item_code": target_item_code,
                "forward_key": key,
                "order_name": order_ref.get("so_name"),
                "required_by": order_ref.get("delivery_date"),
            })
            remaining.remove(chosen)

    empty_keys = [k for k, lst in list(seq_order_queues.items()) if not lst]
    for k in empty_keys:
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

@log_io
def _allocate_forecast_to_balance_doi(remaining_serials, forward_grain, allow_reconfig, forward_keys, sales_rate, current_doi):
    """
    Greedy equalization: keep allocating while there is inventory available for any target.
    - In CONFIG grain:
        * try exact CONFIG pool first
        * if allow_reconfig, fallback to MODEL-level pool
    - In MODEL grain:
        * only MODEL pools are used
    Returns allocations with per-allocation 'doi'.
    """
    allocations = []

    # Build buckets once
    if forward_grain == "config":
        buckets = defaultdict(list)        # ("CONFIG", template, proc, ram, sto) -> [serials]
        any_by_model = defaultdict(list)   # ("MODEL", template) -> [serials]
        for s in remaining_serials:
            buckets[s["forward_key_config"]].append(s)
            any_by_model[s["forward_key_model"]].append(s)
    else:
        buckets = defaultdict(list)        # ("MODEL", template) -> [serials]
        for s in remaining_serials:
            buckets[s["forward_key_model"]].append(s)

    # Helper: which targets are currently serviceable (have inventory now)
    def available_targets():
        avail = []
        for k in forward_keys:
            if forward_grain == "config":
                if buckets.get(k):  # exact config pool has stock
                    avail.append(k)
                elif allow_reconfig:
                    mk = ("MODEL", k[1])
                    if any_by_model.get(mk):  # model fallback has stock
                        avail.append(k)
            else:
                if buckets.get(k):  # model pool has stock
                    avail.append(k)
        return avail

    # Main loop: run while any target has inventory (direct or fallback)
    while True:
        work = available_targets()
        if not work:
            break

        # Lowest DOI wins (add small randomness to break ties fairly)
        work.sort(key=lambda k: (current_doi.get(k, 0.0), random.random()))
        target = work[0]

        chosen = None
        # Pick from exact pool first
        pool = buckets.get(target, [])
        if pool:
            chosen = pool.pop()
        elif forward_grain == "config" and allow_reconfig:
            # Fallback to model-level inventory
            model_key = ("MODEL", target[1])
            pool2 = any_by_model.get(model_key, [])
            if pool2:
                chosen = pool2.pop()

        # If nothing was chosen (should be rare due to available_targets filtering), continue
        if not chosen:
            # Recompute in next iteration
            continue

        # Item to make:
        # - allow_reconfig=True -> best-selling forward suggestion via _target_item_for_key(target)
        # - allow_reconfig=False -> keep serial's own item_code
        target_item_code = _target_item_for_key(target) if allow_reconfig else chosen["item_code"]

        # DOI update for the chosen target (sales_rate clamped to >= 1.0)
        rate = max(1.0, float(sales_rate.get(target, 1.0)))
        inv_now = current_doi.get(target, 0.0) * rate
        new_doi = (inv_now + 1.0) / rate
        current_doi[target] = new_doi

        allocations.append({
            "serial_no": chosen["serial_no"],
            "warehouse": chosen["warehouse"],
            "target_item_code": target_item_code,
            "forward_key": target,
            "doi": new_doi,
        })

    return allocations

# =========================
# Departments / inventory helpers
# =========================
@log_io
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
                names = frappe.get_all(
                    "Warehouse",
                    filters={"department": dept_for_wh},
                    pluck="name"
                )
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
    """
    rows = frappe.db.sql(
        """
        SELECT name, item_code, warehouse, department
        FROM `tabSerial No`
        WHERE department = %s
          AND (status IS NULL OR status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
        """,
        (dept_doc.name,),
        as_dict=True
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
        as_dict=True
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
        as_dict=True
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
            "config_key": ("CONFIG", template, proc, ram, sto)
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
    variant = _find_variant_by_attributes(template, {
        PROCESSOR_ATTR: proc,
        RAM_ATTR: ram,
        STORAGE_ATTR: sto
    })
    return variant or f"{template}::{proc}-{ram}-{sto}"

def _resolve_existing_item_for_key(key) -> Optional[str]:
    if not key:
        return None
    if key[0] == "MODEL":
        return key[1]
    _, template, proc, ram, sto = key
    return _find_variant_by_attributes(template, {
        PROCESSOR_ATTR: proc,
        RAM_ATTR: ram,
        STORAGE_ATTR: sto
    })

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
    ic = snrow["item_code"]
    if ic not in _ITEM_KEYS:
        _prime_item_cache([ic])
    return {
        "serial_no": snrow["name"],
        "item_code": ic,
        "warehouse": snrow["warehouse"],
        "forward_key_model": _ITEM_KEYS[ic]["model_key"],
        "forward_key_config": _ITEM_KEYS[ic]["config_key"],
    }

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
    priority_rank: int
):
    plan_doc.append("lines", {
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
    })
