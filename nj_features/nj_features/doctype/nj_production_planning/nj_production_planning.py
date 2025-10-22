# File: nj_planning/plan_all.py
import math
import random
import frappe
from frappe import _
from typing import Dict, List
from frappe.model.document import Document
from datetime import timedelta
from collections import defaultdict, Counter

class NJProductionPlanning(Document):
    pass

# =========================
# Tunables / Constants
# =========================
SELLABLE_ITEM_GROUPS = {"Laptops", "Chromebooks", "Macbooks"}
RECENCY_WINDOW_DAYS = 15
RECENCY_MAX_WEIGHT = 30         # newest day has weight 30; oldest (15th) has weight 1
MAX_VARIANTS_PER_TEMPLATE = 4   # Top-N variants by sales-rate per template
PROCESSOR_ATTR = "Processor Type1"
RAM_ATTR = "Ram Capacity"
STORAGE_ATTR = "Storage Capacity"

# =========================
# Global caches (minimize DB trips)
# =========================
_ITEM_CORE = {}     # item_code -> {name,item_group,shopify_product_id,variant_of}
_ITEM_ATTRS = {}    # item_code -> {attr: value}
_ITEM_KEYS = {}     # item_code -> {"model_key":("MODEL", template), "config_key":("CONFIG", template, proc, ram, sto)}

# =========================
# Public API (batch run)
# =========================
@frappe.whitelist()
def nj_run_unified_production_plan(planning_horizon_days: int = 30) -> Dict:
    print("nj_run_unified_production_plan =========")
    """
    Batch-run unified production planning (single document for the whole run).
    - Supports multiple departments per sequence.
    - Walks sequences FG->start; within a sequence, iterates all departments.
    - Allocates Orders first (shared sequence-level demand with per-order refs), then Forecast.
    """
    # -------- Load departments with SLA and group by sequence --------
    depts = frappe.get_all(
        "Department",
        filters=[["sla", ">", 0]],
        fields=["name", "department_sequence", "sla", "allow_reconfig",
                "inwarded_model", "forwarded_model", "inwarded_config", "forwarded_config"],
        order_by="department_sequence asc, name asc"
    )
    if not depts:
        frappe.throw("No departments with SLA found.")

    # Group by sequence
    depts_by_seq = defaultdict(List)
    for d in depts:
        depts_by_seq[d["department_sequence"]].append(d)

    sequences = sorted(depts_by_seq.keys())      # ASC
    max_seq = max(sequences)                     # FG sequence

    # Build cumulative SLA per sequence using MAX SLA at each sequence (conservative)
    cum_sla = _build_cumulative_sla_multi(depts_by_seq, sequences)

    # Sequence-level forward granularity:
    #   'config' if ANY dept at that sequence forwards config; else 'model'
    forward_grain_per_seq = {}
    for s in sequences:
        if any(bool(d.get("forwarded_config")) for d in depts_by_seq[s]):
            forward_grain_per_seq[s] = "config"
        else:
            forward_grain_per_seq[s] = "model"

    # -------- Sales Orders → per-sequence order queues --------
    today = frappe.utils.getdate(frappe.utils.nowdate())
    horizon_end = today + timedelta(days=int(planning_horizon_days or 30))
    pending_orders = _get_pending_sales_orders(horizon_end=horizon_end)

    # Prime item cache with order items
    _prime_item_cache([r["item_code"] for r in pending_orders])

    # Demand is now: demand_by_seq[seq][key] = List of {"so_name":..., "delivery_date":...}
    order_demand_by_seq = _allocate_orders_to_sequences_multi(
        pending_orders=pending_orders,
        sequences=sequences,
        cum_sla=cum_sla,
        today=today,
        forward_grain_per_seq=forward_grain_per_seq,
        max_seq=max_seq
    )

    # -------- Sales-rate (15d recency-weighted) & sellable portfolio (Top-4 per template) --------
    sellable_items = _get_sellable_items()  # primes cache
    sales_rate = _compute_recency_weighted_sales_rates(sellable_items)
    random.seed(42)  # deterministic tie-breakers

    # Per-sequence forward-key universe (limited to Top-4 per template when config-grain)
    forward_keys_per_seq = {}
    for s in sequences:
        fwd_grain = forward_grain_per_seq[s]
        forward_keys_per_seq[s] = _build_forward_keys(
            sellable_items, fwd_grain, MAX_VARIANTS_PER_TEMPLATE, sales_rate
        )

    # -------- Create plan doc --------
    plan_doc = frappe.new_doc("NJ Production Planning")
    plan_doc.plan_date = frappe.utils.nowdate()
    plan_doc.plan_title = f"NJ Production Plan - {frappe.utils.now_datetime().strftime('%Y-%m-%d %H:%M:%S')}"
    plan_doc.flags.ignore_mandatory = True
    plan_doc.set("lines", [])

    # -------- Build per-dept inward pools upfront --------
    inward_serials_per_dept = {}
    for s in sequences:
        for d in depts_by_seq[s]:
            dept_doc = frappe.get_doc("Department", d["name"])
            inward_serials_per_dept[d["name"]] = _get_inward_serials_for_department(dept_doc)

    # -------- Run allocation FG->start; within each sequence iterate all depts --------
    prio = 1
    for s in sorted(sequences, reverse=True):
        seq_forward_grain = forward_grain_per_seq[s]
        forward_keys = forward_keys_per_seq[s]
        seq_order_queues = order_demand_by_seq.get(s, defaultdict(List))  # key -> List[refs]

        # Process departments at this sequence in deterministic order
        for dept in sorted(depts_by_seq[s], key=lambda x: x["name"]):
            dept_name = dept["name"]
            allow_reconfig = bool(dept.get("allow_reconfig"))
            inward_grain   = "config" if dept.get("inwarded_config") else "model"
            forward_grain  = seq_forward_grain  # sequence-level forward granularity

            # Build serial map for THIS department’s inward warehouses
            serial_rows = inward_serials_per_dept.get(dept_name, [])
            serial_map = [_enrich_serial_from_attrs(sn) for sn in serial_rows]

            # 1) Orders: allocate against the SHARED sequence order queues (mutated in-place)
            order_allocs, remaining_serials = _match_inventory_to_order_queues_for_sequence(
                seq=s,
                serial_map=serial_map,
                seq_order_queues=seq_order_queues,   # Dict: key -> List of refs (so_name, delivery_date)
                allow_reconfig=allow_reconfig,
                inward_grain=inward_grain,
                forward_grain=forward_grain
            )

            # Append plan rows for Orders (with SO# and delivery date)
            for alloc in order_allocs:
                k = alloc["forward_key"]
                rate_display = float(sales_rate.get(k, 1.0))
                _append_plan_row(
                    plan_doc,
                    serial_no=alloc["serial_no"],
                    current_warehouse=alloc["warehouse"],
                    current_department=dept_name,
                    sales_rate=rate_display,
                    sales_order_number=alloc.get("order_name"),
                    delivery_date=alloc.get("required_by"),
                    item_code_to_make=alloc["target_item_code"],
                    reason="Order",
                    priority_rank=prio
                )
                prio += 1

            # 2) Forecast: balance DOI for THIS department with its remaining pool
            # Estimate forward inventory (remaining + just-allocated orders)
            fwd_inventory = _estimate_forward_inventory(forward_keys, remaining_serials, forward_grain)
            for alloc in order_allocs:
                fwd_inventory[alloc["forward_key"]] = fwd_inventory.get(alloc["forward_key"], 0) + 1

            doi = {k: (float(fwd_inventory.get(k, 0)) / max(1.0, float(sales_rate.get(k, 1.0)) )) for k in forward_keys}

            forecast_allocs = _allocate_forecast_to_balance_doi(
                remaining_serials=remaining_serials,
                forward_grain=forward_grain,
                allow_reconfig=allow_reconfig,
                forward_keys=forward_keys,
                sales_rate=sales_rate,
                current_doi=doi
            )

            # Append plan rows for Forecast
            for alloc in forecast_allocs:
                k = alloc["forward_key"]
                rate_display = float(sales_rate.get(k, 1.0))
                _append_plan_row(
                    plan_doc,
                    serial_no=alloc["serial_no"],
                    current_warehouse=alloc["warehouse"],
                    current_department=dept_name,
                    sales_rate=rate_display,
                    sales_order_number=None,
                    delivery_date=None,
                    item_code_to_make=alloc["target_item_code"],
                    reason="Forecast",
                    priority_rank=prio
                )
                prio += 1

            # Update THIS department's inward pool after consumption
            consumed_serial_nos = {a["serial_no"] for a in order_allocs + forecast_allocs}
            inward_serials_per_dept[dept_name] = [sn for sn in inward_serials_per_dept[dept_name] if sn["name"] not in consumed_serial_nos]

    # -------- Save the unified plan --------
    plan_doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "plan_name": plan_doc.name,
        "title": getattr(plan_doc, "plan_title", plan_doc.name),
        "total_rows": len(plan_doc.get("lines") or []),
    }

# =========================
# SLA helpers (multi-dept per seq)
# =========================
def _build_cumulative_sla_multi(depts_by_seq: Dict, sequences: List[int]) -> Dict:
    """
    cum_sla[seq] = max_sla_at_seq(seq) + sum_{t>seq} max_sla_at_seq(t)
    This is conservative when multiple depts share the same sequence.
    """
    max_sla_per_seq = {}
    for s in sequences:
        max_sla_per_seq[s] = max(float(d.get("sla_days") or 0.0) for d in depts_by_seq[s]) if depts_by_seq[s] else 0.0

    cum_sla = {}
    for i, s in enumerate(sorted(sequences)):
        tail = sum(max_sla_per_seq[t] for t in sequences if t >= s)
        cum_sla[s] = tail
    return cum_sla

# =========================
# Sales Orders → demand placement
# =========================
def _get_pending_sales_orders(horizon_end) -> List[Dict]:
    # Pull open items; include reasonable window; adjust if needed
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
        """,
        (frappe.utils.add_days(frappe.utils.nowdate(), -60),),
        as_dict=True
    )
    return soi

def _allocate_orders_to_sequences_multi(pending_orders, sequences, cum_sla, today, forward_grain_per_seq, max_seq):
    """
    For each pending SO line:
      - If delivery_date is NULL → allocate to FG (max_seq).
      - Else, place at the furthest sequence s.t. cum_sla[s] <= days_to_due; else FG.
    Demand structure: demand_by_seq[seq][key] = List of {so_name, delivery_date}
    """
    demand_by_seq = {s: defaultdict(List) for s in sequences}
    for row in pending_orders:
        ic = row["item_code"]
        qty = int(math.ceil(row["qty_pending"]))
        delivery_date = row.get("delivery_date")
        due = frappe.utils.getdate(delivery_date) if delivery_date else None
        days_to_due = (due - today).days if due else None

        # choose placement sequence
        if days_to_due is None or days_to_due < 0:
            place_seq = max_seq
        else:
            candidates = [s for s in sequences if cum_sla[s] <= days_to_due]
            place_seq = min(candidates) if candidates else max_seq

        # build key using that sequence's forward-grain
        fgrain = forward_grain_per_seq[place_seq]
        key = _key_for_grain(ic, fgrain)

        # push 'qty' copies of the order ref
        ref = {"so_name": row["so_name"], "delivery_date": delivery_date}
        for _ in range(qty):
            demand_by_seq[place_seq][key].append(ref)

    return demand_by_seq

# =========================
# Sellable portfolio & sales-rate
# =========================
def _get_sellable_items() -> List[Dict]:
    rows = frappe.get_all(
        "Item",
        filters={"disabled": 0, "is_stock_item": 1},
        fields=["name", "item_group", "shopify_product_id", "variant_of"],
        limit=0
    )
    sellable = []
    for r in rows:
        if r["item_group"] in SELLABLE_ITEM_GROUPS and (r["shopify_product_id"] or "").strip():
            sellable.append(r)
    _prime_item_cache([r["name"] for r in sellable])
    return sellable

def _compute_recency_weighted_sales_rates(sellable_items: List[Dict]) -> Dict:
    """
    Return {key: rate/day} for both MODEL and CONFIG keys.
    If no sales in window → 1/day.
    """
    rates = {}
    if not sellable_items:
        return rates

    item_names = [it["name"] for it in sellable_items]
    placeholders = ",".join(["%s"] * len(item_names))
    start_date = frappe.utils.getdate(frappe.utils.add_days(frappe.utils.nowdate(), -RECENCY_WINDOW_DAYS + 1))
    rows = frappe.db.sql(
        f"""
        SELECT sii.item_code, si.posting_date, SUM(sii.qty) AS qty
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.docstatus = 1
          AND sii.item_code IN ({placeholders})
          AND si.posting_date >= %s
        GROUP BY sii.item_code, si.posting_date
        """,
        tuple(item_names) + (start_date,),
        as_dict=True
    )
    _prime_item_cache([r["item_code"] for r in rows])

    # Aggregate per day per key
    from collections import defaultdict as _dd
    daily = _dd(lambda: _dd(float))
    today = frappe.utils.getdate(frappe.utils.nowdate())

    for r in rows:
        ic = r["item_code"]
        km = _get_model_key(ic)
        kc = _get_config_key(ic)
        d = frappe.utils.getdate(r["posting_date"])
        daily[km][d] += float(r["qty"])
        daily[kc][d] += float(r["qty"])

    # Weighted average (oldest 1 → newest 30)
    for key in daily:
        num = 0.0
        den = 0.0
        for dd in range(RECENCY_WINDOW_DAYS, 0, -1):
            day = today - timedelta(days=(dd - 1))
            w = max(1, min(RECENCY_MAX_WEIGHT, 31 - dd))
            qty = daily[key].get(day, 0.0)
            num += w * qty
            den += w
        rate = (num / den) if den else 0.0
        rates[key] = (rate if rate > 0 else 1.0)

    # Baseline 1/day for items with no invoices in window
    for it in sellable_items:
        km = _get_model_key(it["name"])
        kc = _get_config_key(it["name"])
        rates.setdefault(km, 1.0)
        rates.setdefault(kc, 1.0)

    return rates

def _build_forward_keys(sellable_items, forward_grain, max_per_template, sales_rate):
    """
    Build forward key universe limited to Top-N configs per template (if config-grain),
    or just the template List (if model-grain).
    """
    variants_by_template = defaultdict(List)
    templates = set()

    for it in sellable_items:
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
        return List(templates or variants_by_template.keys())

    # config-grain → pick Top-N per template by sales-rate, tie-break random
    keys = []
    for model_key, configs in variants_by_template.items():
        configs.sort(key=lambda ck: (-(sales_rate.get(ck, 1.0)), random.random()))
        keys.extend(configs[:max_per_template or 4])

    # de-dup while preserving order
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
def _match_inventory_to_order_queues_for_sequence(seq, serial_map, seq_order_queues, allow_reconfig, inward_grain, forward_grain):
    """
    Greedy match serials to order queues for this sequence.
    - seq_order_queues is mutated in-place (we pop one ref per allocation).
    - Returns (allocations, remaining_serials).
    """
    allocations = []
    remaining = serial_map[:]
    if not seq_order_queues:
        return allocations, remaining

    # Build index by inward grain
    if inward_grain == "model":
        idx = defaultdict(List)
        for s in serial_map:
            idx[s["forward_key_model"]].append(s)
    else:
        idx = defaultdict(List)
        for s in serial_map:
            idx[s["forward_key_config"]].append(s)

    # Iterate keys by largest queue length first for better fill
    # (note: seq_order_queues is Dict: key -> List[refs])
    for key, ref_list in sorted(seq_order_queues.items(), key=lambda kv: len(kv[1]), reverse=True):
        # keep allocating while we have pending refs and compatible serials
        while ref_list:
            chosen = None
            if inward_grain == "config":
                # exact config first
                pool = idx.get(key, [])
                if pool:
                    chosen = pool.pop()
                elif allow_reconfig:
                    # same model any config
                    model_key = ("MODEL", key[1])
                    pool2 = idx.get(model_key, [])
                    if pool2:
                        chosen = pool2.pop()
            else:
                # inward-grain model
                model_key = ("MODEL", key[1])
                pool = idx.get(model_key, [])
                if pool:
                    chosen = pool.pop()

            if not chosen:
                break  # cannot satisfy more for this key in this dept

            order_ref = ref_list.pop()  # {"so_name":..., "delivery_date":...}
            target_item_code = _target_item_for_key(key)

            allocations.append({
                "serial_no": chosen["serial_no"],
                "warehouse": chosen["warehouse"],
                "target_item_code": target_item_code,
                "forward_key": key,
                "order_name": order_ref.get("so_name"),
                "required_by": order_ref.get("delivery_date"),
            })
            remaining.remove(chosen)

    # cleanup empty keys (optional)
    empty_keys = [k for k, lst in seq_order_queues.items() if not lst]
    for k in empty_keys:
        del seq_order_queues[k]

    return allocations, remaining

def _estimate_forward_inventory(forward_keys, serials, forward_grain):
    inv = Counter()
    for s in serials:
        k = s["forward_key_config"] if forward_grain == "config" else s["forward_key_model"]
        if k in forward_keys:
            inv[k] += 1
    return Dict(inv)

def _allocate_forecast_to_balance_doi(remaining_serials, forward_grain, allow_reconfig, forward_keys, sales_rate, current_doi):
    """
    Greedy equalization: send next unit to the key with the lowest DOI.
    """
    allocations = []

    # Buckets for quick pick
    if forward_grain == "config":
        buckets = defaultdict(List)
        any_by_model = defaultdict(List)
        for s in remaining_serials:
            buckets[s["forward_key_config"]].append(s)
            any_by_model[s["forward_key_model"]].append(s)
    else:
        buckets = defaultdict(List)
        for s in remaining_serials:
            buckets[s["forward_key_model"]].append(s)

    work = List(forward_keys)
    for _ in range(len(remaining_serials)):
        if not work:
            break
        # pick key with min DOI
        work.sort(key=lambda k: current_doi.get(k, 0.0))
        target = work[0]

        # choose a compatible serial
        chosen = None
        if forward_grain == "config":
            pool = buckets.get(target, [])
            if pool:
                chosen = pool.pop()
            elif allow_reconfig:
                # any config of same model
                model_key = ("MODEL", target[1])
                pool2 = any_by_model.get(model_key, [])
                if pool2:
                    chosen = pool2.pop()
        else:
            pool = buckets.get(target, [])
            if pool:
                chosen = pool.pop()

        if not chosen:
            # cannot progress on this key; drop it and try next
            work.pop(0)
            continue

        target_item_code = _target_item_for_key(target)
        allocations.append({
            "serial_no": chosen["serial_no"],
            "warehouse": chosen["warehouse"],
            "target_item_code": target_item_code,
            "forward_key": target
        })

        # Update DOI (inv += 1)
        rate = max(1.0, float(sales_rate.get(target, 1.0)))
        inv_now = current_doi.get(target, 0.0) * rate
        current_doi[target] = (inv_now + 1.0) / rate

    return allocations

# =========================
# Departments / inventory helpers
# =========================
def _get_inward_warehouses_for_department(dept_doc) -> List[str]:
    whs = set()
    for row in getattr(dept_doc, "inventory_details", []) or []:
        raw = (row.get("inwarded_warehouse_list") or "").strip()
        if not raw:
            continue
        for w in [x.strip() for x in raw.split(",") if x.strip()]:
            whs.add(w)
    return sorted(whs)

def _get_inward_serials_for_department(dept_doc) -> List[Dict]:
    warehouses = _get_inward_warehouses_for_department(dept_doc)
    if not warehouses:
        return []
    placeholders = ",".join(["%s"] * len(warehouses))
    rows = frappe.db.sql(
        f"""
        SELECT name, item_code, warehouse
        FROM `tabSerial No`
        WHERE warehouse IN ({placeholders})
          AND (status IS NULL OR status NOT IN ('Delivered', 'Scrapped'))
        """,
        tuple(warehouses),
        as_dict=True
    )
    _prime_item_cache([r["item_code"] for r in rows])
    return rows

# =========================
# Item/Attribute machinery
# =========================
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

    # build keys
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

def _get_model_key(item_code: str):
    if item_code not in _ITEM_KEYS:
        _prime_item_cache([item_code])
    return _ITEM_KEYS[item_code]["model_key"]

def _get_config_key(item_code: str):
    if item_code not in _ITEM_KEYS:
        _prime_item_cache([item_code])
    return _ITEM_KEYS[item_code]["config_key"]

def _key_for_grain(item_code: str, grain: str):
    return _get_model_key(item_code) if grain == "model" else _get_config_key(item_code)

def _target_item_for_key(key):
    """
    Resolve existing variant for CONFIG, else return a canonical hint string.
    MODEL returns the template item_code (variant_of).
    """
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

def _find_variant_by_attributes(template_item: str, attr_map: Dict) -> str | None:
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
def _append_plan_row(plan_doc,
                     serial_no: str,
                     current_warehouse: str,
                     current_department: str,
                     sales_rate: float,
                     sales_order_number: str | None,
                     delivery_date,
                     item_code_to_make: str,
                     reason: str,
                     priority_rank: int):
    """
    Child table fields expected on NJ Production Planning:
      - serial_no (Link/Serial No)
      - current_warehouse (Link/Warehouse)
      - current_department (Link/Department)
      - sales_rate (Float)
      - sales_order_number (Data or Link/Sales Order)
      - delivery_date (Date)
      - item_code_to_make (Link/Item)
      - reason (Select: Order/Forecast)
      - priority_rank (Int)
    """
    plan_doc.append("lines", {
        "serial_no": serial_no,
        "current_warehouse": current_warehouse,
        "current_department": current_department,
        "sales_rate": sales_rate,
        "sales_order_number": sales_order_number,
        "delivery_date": delivery_date,
        "item_code_to_make": item_code_to_make,
        "reason": reason,
        "priority_rank": int(priority_rank),
    })