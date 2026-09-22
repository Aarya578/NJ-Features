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
from .part_allocation import PartAllocationRun

# -------------------------
# Logger setup
# -------------------------
logger = frappe.logger("new_Production_planning", allow_site=True, max_size=10_000_000, file_count=5)

# Ensure handlers gracefully handle rollover race conditions across concurrent processes
for _h in getattr(logger, "handlers", []):
    if isinstance(_h, logging.handlers.RotatingFileHandler):
        _orig_rollover = _h.doRollover
        def _make_safe_rollover(handler=_h, orig=_orig_rollover):
            def _safe_rollover():
                try:
                    orig()
                except (FileNotFoundError, OSError):
                    if handler.stream:
                        try:
                            handler.stream.close()
                        except Exception:
                            pass
                        handler.stream = None
                    if not getattr(handler, "delay", False):
                        try:
                            handler.stream = handler._open()
                        except Exception:
                            pass
            return _safe_rollover
        _h.doRollover = _make_safe_rollover()



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
            return fn(*args, **kwargs)
        except Exception as e:
            logger.exception("ERROR %s: %s", fn.__name__, e)
            raise

    return wrapper


class NJProductionPlanning(Document):
    pass


SELLABLE_ITEM_GROUPS = {
    "Laptops", "Chromebooks", "MacBooks", "Desktops", "AIO", "Full Set Desktops", "Chromeboxes",
    "Laptops(Bundle)", "Chromebooks(Bundle)", "MacBooks(Bundle)", "Desktops(Bundle)", "AIO(Bundle)", "Full Set Desktops(Bundle)", "Chromeboxes(Bundle)"
}

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

# Control whether planner writes to Serial No.remarks
UPDATE_SERIAL_REMARKS = True



# =========================
# Global caches
# =========================
_ITEM_CORE: Dict[str, Dict] = {}
_ITEM_ATTRS: Dict[str, Dict] = {}
_ITEM_KEYS: Dict[str, Dict] = {}
_MODEL_TO_SELLABLE_ITEMS: Dict[tuple, List[str]] = defaultdict(list)
_SELLABLE_ITEM_CODES: Set[str] = set()
_SHOPIFY_VARIANT_ID_CACHE: Dict[str, Optional[str]] = {}
_SHOPIFY_VARIANT_ITEMS_CACHE: Dict[str, List[str]] = {}


def _get_shopify_variant_id(item_code: str) -> Optional[str]:
    """Retrieve shopify_variant_id for item_code or its Product Bundle."""
    if not item_code:
        return None
    if item_code in _SHOPIFY_VARIANT_ID_CACHE:
        return _SHOPIFY_VARIANT_ID_CACHE[item_code]

    # Verify item is in a sellable machine group, strictly excluding Warranty, Consumable, etc.
    item_grp = frappe.db.get_value("Item", item_code, "item_group")
    if not item_grp or item_grp not in SELLABLE_ITEM_GROUPS:
        _SHOPIFY_VARIANT_ID_CACHE[item_code] = None
        return None

    variant_id = None
    # 0. Check if item_code is SKU with embedded /ID-<variant_id>
    if "/ID-" in item_code:
        variant_id = item_code.split("/ID-")[-1].strip()

    if not variant_id:
        # 1. Check tabNJ Inventory Sync Main with exact word / comma matching
        res = frappe.db.sql(
            """
            SELECT shopify_variant_id FROM `tabNJ Inventory Sync Main`
            WHERE (item_code = %s OR item_code LIKE %s OR item_code LIKE %s OR item_code LIKE %s)
            LIMIT 1
            """,
            (item_code, f"{item_code}, %", f"%, {item_code}, %", f"%, {item_code}"),
            as_dict=False,
        )
        if res and res[0] and res[0][0]:
            variant_id = str(res[0][0]).strip()

    if not variant_id:
        # 2. Check tabProduct Bundle
        res = frappe.db.sql(
            """
            SELECT shopify_variant_id
            FROM `tabProduct Bundle`
            WHERE (new_item_code = %s OR name = %s)
              AND shopify_variant_id IS NOT NULL AND shopify_variant_id != ''
            LIMIT 1
            """,
            (item_code, item_code),
        )
        if res and res[0] and res[0][0]:
            variant_id = str(res[0][0]).strip()

    if not variant_id:
        # 3. Check tabItem
        res_item = frappe.db.get_value("Item", item_code, "shopify_variant_id")
        if res_item:
            variant_id = str(res_item).strip()

    variant_id_str = str(variant_id).strip() if variant_id else None
    _SHOPIFY_VARIANT_ID_CACHE[item_code] = variant_id_str
    return variant_id_str


from nj_features.services.model_compatibility import is_screen_type_compatible

_TOUCH_SCREEN_MARKER_WORDS = {'touch', 'nt'}


def _is_same_model_family(tmpl_a: str, tmpl_b: str) -> bool:
    """Validate that two model templates belong strictly to the same brand and base model series."""
    if not tmpl_a or not tmpl_b:
        return False
    if tmpl_a.strip().lower() == tmpl_b.strip().lower():
        return True
    
    clean_a = tmpl_a.lower().replace('s-', '').replace('fba-', '').strip()
    clean_b = tmpl_b.lower().replace('s-', '').replace('fba-', '').strip()
    
    words_a = clean_a.split()
    words_b = clean_b.split()
    if not words_a or not words_b:
        return False
    
    brand_a = words_a[0]
    brand_b = words_b[0]
    if brand_a != brand_b:
        return False
    
    ignore_words = {
        'win', 'kbd', 'wtb', 'sml', 'big', 'ir', 'fba',
        'refurbished', 'sff', 'tiny', 'tower', 'fullset', 'full', 'set', 'pro',
        'elitebook', 'thinkpad', 'latitude', 'optiplex', 'workstation', 'eb', 'pb', 'thinkcentre'
    }
    tokens_a = [w for w in re.findall(r'[a-z0-9]+', clean_a) if w not in ignore_words and w != brand_a]
    tokens_b = [w for w in re.findall(r'[a-z0-9]+', clean_b) if w not in ignore_words and w != brand_b]

    if not tokens_a or not tokens_b:
        return False

    # Touch and Non-Touch (NT) screens are physically different, incompatible
    # parts - the token-position checks below don't examine every token, so
    # this has to be an explicit hard gate rather than relying on them.
    touch_markers_a = {t for t in tokens_a if t in _TOUCH_SCREEN_MARKER_WORDS}
    touch_markers_b = {t for t in tokens_b if t in _TOUCH_SCREEN_MARKER_WORDS}
    if touch_markers_a != touch_markers_b:
        return False

    # PIR models have a physically different chassis (body, motherboard) and
    # cannot be rebuilt into non-PIR units or vice-versa.
    pir_a = 'pir' in tokens_a
    pir_b = 'pir' in tokens_b
    if pir_a != pir_b:
        return False

    if tokens_a[0] != tokens_b[0]:
        return False
    
    gen_a = [t for t in tokens_a if t.startswith('g') and len(t) <= 3]
    gen_b = [t for t in tokens_b if t.startswith('g') and len(t) <= 3]
    if gen_a and gen_b and gen_a != gen_b:
        return False

    return True


def _is_rebuild_compatible(physical_item_code: str, target_item_code: str) -> bool:
    """Can a unit physically be rebuilt from its current item into the target?

    RAM and storage are swapped on the bench every day, so those may differ
    freely. The screen and the chassis cannot: a Touch panel is not an NT
    panel, and a PIR body/motherboard is not a non-PIR one.

    `_is_same_model_family` and `is_screen_type_compatible` already enforce
    this when a donor unit is *chosen*, but the pre-reserved path honours a
    stored `to_make` without consulting either, so a value written before
    those gates existed - or by hand - is planned unchecked. This is that
    check, usable from any path.

    Conservative on purpose: when either template is unknown the pair is
    allowed, so a naming gap strands no real stock.
    """
    if not physical_item_code or not target_item_code:
        return False
    if str(physical_item_code).strip() == str(target_item_code).strip():
        return True

    if not is_screen_type_compatible(physical_item_code, target_item_code):
        return False

    tmpl_a = frappe.db.get_value("Item", physical_item_code, "variant_of")
    tmpl_b = frappe.db.get_value("Item", target_item_code, "variant_of")
    if not tmpl_a or not tmpl_b:
        return True

    return _is_same_model_family(tmpl_a, tmpl_b)


def _clear_serial_to_make(serial_no: str, bad_to_make: str) -> None:
    """Drop a to_make the unit cannot physically be rebuilt into.

    `_append_plan_row` writes to_make back on every run, so without clearing
    it the planner re-reads the same impossible value each night and the unit
    never recovers on its own.
    """
    if not serial_no or not bad_to_make:
        return
    try:
        frappe.db.sql(
            """
            UPDATE `tabSerial No`
            SET to_make = NULL
            WHERE name = %s AND to_make = %s
            """,
            (serial_no, bad_to_make),
        )
    except Exception as e:
        logger.warning("Could not clear Serial No.to_make for %s: %s", serial_no, e)


_EQUIVALENT_PARENT_MODELS_CACHE: Dict[str, Set[str]] = {}


def _get_equivalent_parent_models(template_name: str) -> Set[str]:
    """Retrieve all equivalent parent templates grouped together in tabNJ Inventory Sync Main, strictly matching brand and model family."""
    if not template_name:
        return set()
    if template_name in _EQUIVALENT_PARENT_MODELS_CACHE:
        return _EQUIVALENT_PARENT_MODELS_CACHE[template_name]

    sync_rows = frappe.db.sql(
        """
        SELECT item_code FROM `tabNJ Inventory Sync Main`
        WHERE item_code LIKE %s
        """,
        (f"%{template_name}%",),
        as_dict=True
    )
    equivalent = {template_name}
    for r in sync_rows:
        raw = r.get("item_code") or ""
        for code in raw.split(","):
            code = code.strip()
            if code:
                v_of = frappe.db.get_value("Item", code, "variant_of")
                if v_of and _is_same_model_family(template_name, v_of):
                    equivalent.add(v_of)
    _EQUIVALENT_PARENT_MODELS_CACHE[template_name] = equivalent
    return equivalent


def _get_variant_bundle_item_codes(variant_id: str) -> List[str]:
    """Retrieve all Laptop/Chromebook item_codes under a shopify_variant_id from Product Bundles, Items, and Sync Main."""
    if not variant_id:
        return []
    variant_id_str = str(variant_id).strip()
    if variant_id_str in _SHOPIFY_VARIANT_ITEMS_CACHE:
        return _SHOPIFY_VARIANT_ITEMS_CACHE[variant_id_str]

    item_codes = set()
    # 1. Product Bundle
    rows = frappe.db.sql(
        """
        SELECT DISTINCT tpbi.item_code
        FROM `tabProduct Bundle` tpb
        INNER JOIN `tabProduct Bundle Item` tpbi ON tpb.name = tpbi.parent
        INNER JOIN `tabItem` ti ON tpbi.item_code = ti.name
        WHERE TRIM(tpb.shopify_variant_id) = %s
          AND ti.item_group IN ('Laptops', 'Chromebooks', 'MacBooks', 'Desktops', 'AIO', 'Full Set Desktops', 'Chromeboxes')
        """,
        (variant_id_str,)
    )
    for r in (rows or []):
        if r and r[0]:
            item_codes.add(str(r[0]).strip())

    # 2. tabItem shopify_variant_id
    rows2 = frappe.db.sql(
        """
        SELECT name FROM `tabItem`
        WHERE TRIM(shopify_variant_id) = %s
          AND item_group IN ('Laptops', 'Chromebooks', 'MacBooks', 'Desktops', 'AIO', 'Full Set Desktops', 'Chromeboxes')
        """,
        (variant_id_str,)
    )
    for r in (rows2 or []):
        if r and r[0]:
            item_codes.add(str(r[0]).strip())

    # 3. tabNJ Inventory Sync Main
    sync_rows = frappe.db.sql(
        """
        SELECT item_code FROM `tabNJ Inventory Sync Main`
        WHERE TRIM(shopify_variant_id) = %s
        """,
        (variant_id_str,),
        as_dict=True
    )
    for s in sync_rows:
        raw = s.get("item_code") or ""
        for code in raw.split(","):
            c = code.strip()
            if c:
                c_grp = frappe.db.get_value("Item", c, "item_group")
                if c_grp and c_grp in SELLABLE_ITEM_GROUPS:
                    item_codes.add(c)

    res = sorted(list(item_codes))
    _SHOPIFY_VARIANT_ITEMS_CACHE[variant_id_str] = res
    return res


def _is_dept_applicable(dept_row, item_grp):
    """Check if a department applies to an item based on its sla_item_groups configuration."""
    dept_name = str(dept_row.get("name") or "").lower()
    if "packing & dispatch" in dept_name:
        return True
    if not item_grp:
        return False
    groups_str = str(dept_row.get("sla_item_groups") or "").strip()
    if not groups_str or groups_str.lower() in ("none", "null"):
        return False  # Strictly ignore if empty
    allowed = [g.strip().lower() for g in groups_str.split(",") if g.strip()]
    return item_grp.strip().lower() in allowed


def _get_sla_department_search_order(depts: List[Dict], delivery_date, current_date, item_grp: str = None, promise_date=None) -> List[Dict]:
    """
    Given active departments sorted by (department_sequence DESC, name ASC),
    compute Remaining Delivery Days and determine SLA-based department search order.
    Phase A: Eligible departments starting from earliest eligible upstream department to Packing & Dispatch.
    Phase B: Remaining lower-sequence departments (downward).
    """
    if not depts:
        return []

    # Filter applicable departments by item_grp if provided
    if item_grp:
        depts = [d for d in depts if _is_dept_applicable(d, item_grp)]

    # Sort depts deterministically by sequence DESC, name ASC
    sorted_depts = sorted(depts, key=lambda d: (-int(d.get("department_sequence") or 0), d.get("name") or ""))

    if delivery_date:
        rem_days = (frappe.utils.getdate(delivery_date) - current_date).days
        rem_days = max(0, rem_days)
    else:
        rem_days = 0

    # Same allocation horizon the hourly allocator uses - the two must agree, or
    # an order falls out of one and not the other and the reservations flap.
    # Imported inside the function: overrides.sales_order pulls from this module.
    from nj_features.overrides.sales_order import ALLOCATION_HORIZON_DAYS

    # Judged against the customer promise, never against soi.delivery_date - that
    # is the exact field the "Update Items" dialog writes, so gating on it let a
    # user moving the date onto the system's own estimate drop the order out of
    # production planning for good. See the matching note in overrides/sales_order.py.
    # rem_days above is untouched and still drives the department ladder below.
    horizon_src = promise_date or delivery_date
    horizon_days = (
        (frappe.utils.getdate(horizon_src) - current_date).days if horizon_src else 0
    )
    if horizon_days > ALLOCATION_HORIZON_DAYS:
        return []

    starting_dept_idx = len(sorted_depts) - 1  # Default to last (lowest sequence)
    cum_sla = 0
    for idx, d in enumerate(sorted_depts):
        d_name = (d.get("name") or "").lower()
        if "packing & dispatch" in d_name or "sales" in d_name:
            sla_val = 1
        elif "inward" in d_name:
            sla_val = 45
        else:
            sla_val = min(max(int(d.get("sla") or d.get("department_sla") or 1), 1), 15)

        cum_sla += sla_val
        if cum_sla >= rem_days:
            starting_dept_idx = idx
            break

    # Phase A: Eligible departments reversed (earliest eligible upstream -> Packing & Dispatch)
    phase_a = list(reversed(sorted_depts[:starting_dept_idx + 1]))
    # Phase B: Remaining lower sequence departments
    phase_b = sorted_depts[starting_dept_idx + 1:]

    return phase_a + phase_b

# Part allocation global state (virtual stock)
# =========================
_PART_VIRTUAL_STOCK: Dict[str, float] = {}       # item_code -> physical stock in Stores - NJ (virtual snapshot)
_PART_PLANNED_ALLOCATION: Dict[str, float] = {}  # item_code -> qty already virtually allocated in this run
_PART_ENGINE = None
_DEPT_ALLOCATE_PARTS: Dict[str, bool] = {}       # department_name -> allocate_parts flag
_SERIAL_TO_MR_ITEMS: Dict[str, List[Dict]] = defaultdict(list)
_SERIAL_TO_BAG_ITEMS: Dict[str, List[Dict]] = defaultdict(list)


# =========================
# Helpers
# =========================
def _resolve_stock_item_from_pb_or_item(item_code_or_pb: str) -> str:
    """If item_code_or_pb is a Product Bundle (pb.name or pb.new_item_code), resolve to component stock item_code."""
    if not item_code_or_pb:
        return item_code_or_pb

    stock_item = frappe.db.sql(
        """
        SELECT pbi.item_code
        FROM `tabProduct Bundle Item` pbi
        INNER JOIN `tabProduct Bundle` pb ON pbi.parent = pb.name
        LEFT JOIN `tabItem` i ON pbi.item_code = i.name
        WHERE pb.name = %s OR pb.new_item_code = %s
        ORDER BY
            CASE
                WHEN i.item_group IN %s THEN 0
                WHEN pbi.item_code LIKE 'S-%%' THEN 1
                ELSE 2
            END,
            pbi.idx ASC
        LIMIT 1
        """,
        (item_code_or_pb, item_code_or_pb, tuple(SELLABLE_ITEM_GROUPS)),
        as_dict=False,
    )
    if stock_item and stock_item[0][0]:
        return stock_item[0][0]

    return item_code_or_pb


_get_stock_item_code_from_to_make = _resolve_stock_item_from_pb_or_item


@log_io
def _update_serial_to_make(serial_no: str, item_code_to_make: str, expected_so: Optional[str] = None) -> None:
    """Update Serial No.to_make (lightweight db write).

    A serial already reserved to a DIFFERENT sales order may already have
    physical rework (kitting) committed against its current to_make - this
    must never be silently overwritten. Only write when the serial is
    unreserved, or already reserved to the same order this call is for.
    """
    if not UPDATE_SERIAL_TO_MAKE or not item_code_to_make:
        return

    item_code_to_make = _resolve_stock_item_from_pb_or_item(item_code_to_make)

    # Guard every writer, not just the allocation gates: a to_make the unit
    # cannot physically become would otherwise be replayed by the pre-reserved
    # path on every subsequent run.
    sn_item_code = frappe.db.get_value("Serial No", serial_no, "item_code")
    if sn_item_code and not _is_rebuild_compatible(sn_item_code, item_code_to_make):
        logger.warning(
            "Refusing to set to_make=%s on %s (physical item %s is not rebuild-compatible)",
            item_code_to_make, serial_no, sn_item_code,
        )
        return

    so_val = (expected_so or "").strip()
    try:
        frappe.db.sql(
            """
            UPDATE `tabSerial No`
            SET to_make = %s
            WHERE name = %s
              AND (reserved_sales_order IS NULL OR reserved_sales_order = '' OR reserved_sales_order = %s)
            """,
            (item_code_to_make, serial_no, so_val),
        )
    except Exception as e:
        logger.warning("Could not update Serial No.to_make for %s: %s", serial_no, e)



@log_io
def _update_serial_reserved_sales_order(serial_no: str, sales_order_no: Optional[str]) -> bool:
    """Update Serial No.reserved_sales_order atomically with checked result."""
    if not UPDATE_SERIAL_RESERVED_SO:
        return True

    # Imported inside the function: reservation_service imports overrides.sales_order
    # at module level, so a top-level import here risks an import cycle.
    from nj_features.services.reservation_service import get_effective_order_source

    so_val = (sales_order_no or "").strip()
    try:
        if so_val:
            current, current_source = frappe.db.get_value(
                "Serial No", serial_no, ["reserved_sales_order", "order_source"]
            ) or (None, None)

            # order_source has to be written here as well as in the Sales Order
            # allocator. It is the only record of where a reservation came from,
            # and a planner-made reservation that omits it is indistinguishable
            # from one that was never attributed - which is exactly how a wrong
            # reservation stayed untraceable.
            effective_source = get_effective_order_source(so_val)

            if (current or "").strip() == so_val:
                # Already reserved to this order. Backfill the attribution if an
                # earlier run (before this wrote order_source) left it empty.
                if effective_source and not (current_source or "").strip():
                    frappe.db.sql("""
                        UPDATE `tabSerial No`
                        SET order_source = %s, modified = NOW()
                        WHERE name = %s AND reserved_sales_order = %s
                          AND (order_source IS NULL OR order_source = '')
                    """, (effective_source, serial_no, so_val))
                return True

            frappe.db.sql("""
                UPDATE `tabSerial No`
                SET reserved_sales_order = %s,
                    order_source = %s,
                    modified = NOW()
                WHERE name = %s
                  AND (reserved_sales_order IS NULL OR reserved_sales_order = '')
                  AND status = 'Active'
                  AND is_replace = 0
                  AND (return_reason IS NULL OR return_reason = '' OR return_reason NOT IN ('Repair', 'Replace'))
            """, (so_val, effective_source, serial_no))
            if getattr(frappe.db, "_cursor", None) and frappe.db._cursor.rowcount <= 0:
                logger.warning("Could not reserve Serial No %s for %s: already reserved or ineligible", serial_no, so_val)
                return False
            return True
        else:
            frappe.db.sql("""
                UPDATE `tabSerial No`
                SET reserved_sales_order = NULL,
                    order_source = NULL,
                    modified = NOW()
                WHERE name = %s
                  AND (return_reason IS NULL OR return_reason = '' OR return_reason NOT IN ('Repair', 'Replace'))
            """, (serial_no,))
            return True
    except Exception as e:
        logger.warning("Could not update Serial No.reserved_sales_order for %s: %s", serial_no, e)
        return False


@log_io
def _update_serial_remarks(serial_no: str, remarks: str) -> None:
    """Update Serial No.remarks (lightweight db write)."""
    if not UPDATE_SERIAL_REMARKS or not serial_no:
        return

    remarks_val = (remarks or "").strip()
    try:
        frappe.db.set_value(
            "Serial No",
            serial_no,
            "remarks",
            remarks_val if remarks_val else None,
            update_modified=False,
        )
    except Exception as e:
        logger.warning("Could not update Serial No.remarks for %s: %s", serial_no, e)


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
    if not item_code:
        return (None, None, None, None)

    lookup_code = item_code
    if lookup_code not in _ITEM_KEYS:
        _prime_item_cache([lookup_code])
    if lookup_code in _ITEM_KEYS and "config_key" in _ITEM_KEYS[lookup_code]:
        _, template, proc, ram, sto = _ITEM_KEYS[lookup_code]["config_key"]
        return (template, proc, ram, sto)

    # If item_code is a Product Bundle / SKU, resolve to the laptop item
    bundle_items = frappe.db.sql(
        """
        SELECT pbi.item_code FROM `tabProduct Bundle Item` pbi
        INNER JOIN `tabItem` ti ON pbi.item_code = ti.name
        WHERE pbi.parent = %s
          AND ti.item_group IN ('Laptops', 'Chromebooks', 'MacBooks', 'Desktops', 'AIO', 'Full Set Desktops', 'Chromeboxes')
        LIMIT 1
        """,
        (item_code,)
    )
    if bundle_items and bundle_items[0] and bundle_items[0][0]:
        lookup_code = bundle_items[0][0]
    else:
        var_id = _get_shopify_variant_id(item_code)
        if var_id:
            vcodes = _get_variant_bundle_item_codes(var_id)
            if vcodes:
                lookup_code = vcodes[0]

    if lookup_code not in _ITEM_KEYS:
        _prime_item_cache([lookup_code])
    if lookup_code in _ITEM_KEYS and "config_key" in _ITEM_KEYS[lookup_code]:
        _, template, proc, ram, sto = _ITEM_KEYS[lookup_code]["config_key"]
        return (template, proc, ram, sto)
    return (lookup_code, None, None, None)


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
def enqueue_unified_production_plan(planning_horizon_days: int = 30, **kwargs):
    """Safely enqueue unified production planning to the long queue to avoid scheduler/HTTP timeouts."""
    frappe.enqueue(
        "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.nj_run_unified_production_plan",
        queue="long",
        timeout=3600,
        planning_horizon_days=planning_horizon_days,
        **kwargs,
    )
    return {"message": "Unified production plan enqueued successfully", "status": "queued"}


@frappe.whitelist()
@log_io
def nj_run_unified_production_plan(planning_horizon_days: int = 30, **kwargs) -> Dict:
    # return {"message": "Unified production plan ran successfully", "status": "success"}
    print("Running unified production plan...=============")

    # -------------------------------------------------------
    # CLEANUP: Release any over-allocated or invalid serial reservations
    try:
        from nj_features.overrides.sales_order import trim_over_allocated_serials
        trim_over_allocated_serials()
    except Exception as e:
        logger.warning("[CLEANUP] trim_over_allocated_serials failed during plan startup: %s", e)


    depts = frappe.get_all(
        "Department",
        filters=[["department_sequence", ">", 0]],
        fields=[
            "name",
            "department_sequence",
            "sla",
            "sla_item_groups",
            "allow_reconfig",
            "inwarded_model",
            "forwarded_model",
            "inwarded_config",
            "forwarded_config",
            "run_production_planning",
            "allocate_parts",
        ],
        order_by="department_sequence desc, name asc",
    )
    if not depts:
        frappe.throw("No valid departments found.")

    depts_by_seq: Dict[int, List[Dict]] = defaultdict(list)
    for d in depts:
        depts_by_seq[d["department_sequence"]].append(d)

    sequences = sorted(depts_by_seq.keys())
    max_seq = max(sequences)

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
    plan_doc.set("missing_sales_order", [])

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

            eligible_names = {r["name"] for r in rows}
            excluded_rows = _get_return_excluded_serials_for_department(dept_doc, eligible_names)
            for ex in excluded_rows:
                reason_bits = []
                if ex.get("return_reason"):
                    reason_bits.append(f"return_reason={ex['return_reason']}")
                if int(ex.get("is_replace") or 0) == 1:
                    reason_bits.append("is_replace=1")
                reason_text = "Excluded: " + (", ".join(reason_bits) if reason_bits else "not yet reprocessed")
                plan_doc.append("missing_serial_nos", {
                    "serial_no": ex["name"],
                    "current_department": dept_name,
                    "current_warehouse": ex.get("warehouse"),
                    "reason": reason_text
                })

    priority_per_dept: Dict[str, int] = defaultdict(lambda: 1)

    # -------------------------------------------------------------
    # 1. PRE-PLANNING & RESERVED SERIALS PHASE (per department)
    # -------------------------------------------------------------
    avail_serials_by_dept: Dict[str, List[Dict]] = {}
    _today = frappe.utils.getdate(frappe.utils.nowdate())

    for s in sorted(sequences, reverse=True):
        for dept in sorted(depts_by_seq[s], key=lambda x: x["name"]):
            dept_name = dept["name"]

            serial_rows = inward_serials_per_dept.get(dept_name, [])

            # Process Pre-Reserved serials (already locked to SOs)
            reserved_rows = _get_reserved_serials_for_department(dept_name)
            for res_row in reserved_rows:
                sn_id = res_row['name']
                wh = res_row['warehouse']

                if not res_row.get("item_wizard"):
                    skip_reason = "Reserved for SO - Item Wizard not found"
                    _update_serial_remarks(sn_id, f"Not Allocated: {skip_reason}")
                    plan_doc.append("missing_serial_nos", {
                        "serial_no": sn_id,
                        "current_department": dept_name,
                        "current_warehouse": wh,
                        "reason": skip_reason
                    })
                    continue

                if res_row.get("part_list_status") != "Completed" or res_row.get("iw_docstatus") != 1:
                    reason = (
                        "Reserved for SO - Item Wizard not Completed"
                        if res_row.get("part_list_status") != "Completed"
                        else "Reserved for SO - Item Wizard not Submitted"
                    )
                    _update_serial_remarks(sn_id, f"Not Allocated: {reason}")
                    plan_doc.append("missing_serial_nos", {
                        "serial_no": sn_id,
                        "current_department": dept_name,
                        "current_warehouse": wh,
                        "reason": reason
                    })
                    continue

                item_code_to_make = res_row.get("to_make") or _get_fallback_pb_item_code(res_row["item_code"])
                if not item_code_to_make:
                    skip_reason = "Reserved for SO - Product Bundle not found"
                    _update_serial_remarks(sn_id, f"Not Allocated: {skip_reason}")
                    plan_doc.append("missing_serial_nos", {
                        "serial_no": sn_id,
                        "current_department": dept_name,
                        "current_warehouse": wh,
                        "reason": skip_reason
                    })
                    continue

                # This path honours a stored to_make and never ran the screen
                # and chassis gates the SO allocation phase applies, so a value
                # written before those gates existed (or by hand) was planned
                # unchecked - e.g. a (PIR) unit targeted at an (IR-KBD WTB)
                # build, which cannot be done: different body and motherboard.
                if not _is_rebuild_compatible(res_row["item_code"], item_code_to_make):
                    skip_reason = (
                        f"Reserved for SO - to_make '{item_code_to_make}' is not physically "
                        f"buildable from '{res_row['item_code']}'"
                    )
                    _clear_serial_to_make(sn_id, item_code_to_make)
                    _update_serial_remarks(sn_id, f"Not Allocated: {skip_reason}")
                    plan_doc.append("missing_serial_nos", {
                        "serial_no": sn_id,
                        "current_department": dept_name,
                        "current_warehouse": wh,
                        "reason": skip_reason
                    })
                    continue

                purchase_date = res_row.get("purchase_date")
                creation = res_row.get("creation")
                base_date = frappe.utils.getdate(purchase_date or creation or frappe.utils.nowdate())
                age_days = (_today - base_date).days if base_date else 0

                remarks_text = f"Allocated: Pre-reserved for Sales Order {res_row['reserved_sales_order']} | to_make: {item_code_to_make}"
                _append_plan_row(
                    plan_doc,
                    serial_no=sn_id,
                    current_warehouse=wh,
                    current_department=dept_name,
                    sales_rate=1.0,
                    doi=0.0,
                    sales_order_number=res_row["reserved_sales_order"],
                    delivery_date=res_row.get("delivery_date"),
                    item_code_to_make=item_code_to_make,
                    reason="Order",
                    priority_rank=priority_per_dept[dept_name],
                    serial_age_days=age_days,
                    remarks=remarks_text,
                )
                priority_per_dept[dept_name] += 1

            serial_map = []
            for row in serial_rows:
                enriched = _enrich_serial_from_attrs(row)
                serial_map.append(enriched)

            avail_serials_by_dept[dept_name] = serial_map

    # -------------------------------------------------------------
    # 2. SALES ORDER ALLOCATION PHASE (SLA Search & 5-Tier Priority)
    # -------------------------------------------------------------
    _SHOPIFY_VARIANT_ID_CACHE.clear()
    _SHOPIFY_VARIANT_ITEMS_CACHE.clear()
    _EQUIVALENT_PARENT_MODELS_CACHE.clear()

    # For SO allocation, search ALL departments with department_sequence > 0
    all_eligible_depts = [d for d in depts if int(d.get("department_sequence") or 0) > 0]
    # For DOI/Forecast, only use departments with run_production_planning enabled
    active_depts = [d for d in depts if d.get("run_production_planning")]

    for order_row in pending_orders:
        so_name = order_row.get("so_name") or order_row.get("sales_order")
        deliv_date = order_row.get("delivery_date")
        target_ic = order_row["item_code"]
        needed_qty = int(math.ceil(order_row.get("qty_pending") or order_row.get("qty") or 0))

        if needed_qty <= 0:
            continue

        original_needed_qty = needed_qty
        item_grp = frappe.db.get_value("Item", target_ic, "item_group")
        search_order = _get_sla_department_search_order(
            all_eligible_depts, deliv_date, today, item_grp=item_grp,
            promise_date=order_row.get("promise_date"),
        )

        variant_id = _get_shopify_variant_id(target_ic)
        p2_codes = set(_get_variant_bundle_item_codes(variant_id)) - {target_ic} if variant_id else set()

        target_cfg_tuple = None
        model_key = None
        try:
            target_cfg_tuple = _cfg_tuple_from_item(target_ic)
            if target_cfg_tuple:
                model_key = ("MODEL", target_cfg_tuple[0], target_cfg_tuple[1])
        except Exception:
            pass

        parent_variant_id = _get_shopify_variant_id(target_ic)
        p4_codes = set()
        if parent_variant_id:
            p4_codes = set(_get_variant_bundle_item_codes(parent_variant_id)) - {target_ic} - p2_codes

        def _try_assign_sn(s, dept_name, remarks_text):
            nonlocal needed_qty
            # A Non-Touch panel cannot be rebuilt into a Touch one. _is_same_model_family
            # already enforces this for C3, but C1b matches on to_make and C2/C4 on
            # Shopify variant grouping - none of them look at the screen, so all three
            # can pair a Touch order with an NT machine.
            if not is_screen_type_compatible(s.get("item_code"), target_ic):
                return False

            # Part allocation is recalculated by run_latest_production_plan_part_allocation.
            part_allocation = False
            success = _append_plan_row(
                plan_doc,
                serial_no=s["serial_no"],
                current_warehouse=s["warehouse"],
                current_department=dept_name,
                sales_rate=1.0,
                doi=0.0,
                sales_order_number=so_name,
                delivery_date=deliv_date,
                item_code_to_make=target_ic,
                reason="Order",
                priority_rank=priority_per_dept[dept_name],
                serial_age_days=s.get("age_days"),
                remarks=remarks_text,
                part_allocation=part_allocation,
            )
            dept_pool = avail_serials_by_dept.get(dept_name, [])
            if s in dept_pool:
                dept_pool.remove(s)
            if success:
                needed_qty -= 1
                priority_per_dept[dept_name] += 1
                return True
            return False

        # -------------------------------------------------------------------------
        # ALLOCATION LOGIC: Department-first, condition-second.
        #
        # For each department (highest seq → lowest seq, i.e. closest to dispatch first):
        #   Check condition 1 (exact item_code)
        #   Check condition 1b (to_make == target_ic)
        #   Check condition 2 (same Shopify variant)
        #   Check condition 3 (same parent model + CPU)
        #   Check condition 4 (parent's Shopify variant)
        #   → If ANY condition found a serial → allocated. Move to next qty needed.
        #   → If NOTHING found in this dept → move to next dept.
        # -------------------------------------------------------------------------
        downstream_search = list(search_order)

        target_tmpl, target_proc = None, None
        equiv_templates = set()
        if target_cfg_tuple:
            target_tmpl, target_proc = target_cfg_tuple[0], target_cfg_tuple[1]
            equiv_templates = _get_equivalent_parent_models(target_tmpl)

        for d in downstream_search:
            if needed_qty <= 0:
                break

            dept_name = d["name"]
            dept_pool = avail_serials_by_dept.get(dept_name, [])
            if not dept_pool:
                continue

            # -- Condition 1: Exact physical item_code match in THIS department --
            p1_matches = [
                s for s in list(dept_pool)
                if s.get("item_code") == target_ic or s.get("fallback_pb_item_code") == target_ic
            ]
            p1_matches = _oldest_first(p1_matches)
            for s in p1_matches:
                if needed_qty <= 0:
                    break
                remarks_text = f"Allocated to SO {so_name} (C1: Exact item_code match in {dept_name}) | to_make: {target_ic}"
                _try_assign_sn(s, dept_name, remarks_text)

            if needed_qty <= 0:
                break

            # -- Condition 1b: Active WIP reconfig (to_make == target_ic) in THIS department --
            p1b_matches = [
                s for s in list(dept_pool)
                if s.get("to_make") == target_ic
            ]
            p1b_matches = _oldest_first(p1b_matches)
            for s in p1b_matches:
                if needed_qty <= 0:
                    break
                remarks_text = f"Allocated to SO {so_name} (C1b: WIP reconfig to_make match in {dept_name}) | to_make: {target_ic}"
                _try_assign_sn(s, dept_name, remarks_text)

            if needed_qty <= 0:
                break

            # -- Condition 2: Same Shopify Variant ID in THIS department --
            if p2_codes:
                p2_matches = [
                    s for s in list(dept_pool)
                    if s.get("item_code") in p2_codes or s.get("fallback_pb_item_code") in p2_codes or s.get("to_make") in p2_codes
                ]
                p2_matches = _oldest_first(p2_matches)
                for s in p2_matches:
                    if needed_qty <= 0:
                        break
                    curr_ic = s.get("item_code") or s.get("fallback_pb_item_code") or ""
                    remarks_text = f"Allocated to SO {so_name} (C2: Shopify Variant ID {variant_id}, current '{curr_ic}' in {dept_name}) | to_make: {target_ic}"
                    _try_assign_sn(s, dept_name, remarks_text)

            if needed_qty <= 0:
                break

            # -- Condition 3: Same Parent Reconfiguration (Model + Processor) in THIS department --
            if target_cfg_tuple and equiv_templates:
                p3_matches = []
                for s in list(dept_pool):
                    fkm = s.get("forward_key_model")
                    if fkm and fkm[0] == "MODEL":
                        if fkm[2] == target_proc and fkm[1] in equiv_templates:
                            p3_matches.append(s)
                p3_matches = _oldest_first(p3_matches)
                for s in p3_matches:
                    if needed_qty <= 0:
                        break
                    curr_ic = s.get("item_code") or s.get("fallback_pb_item_code") or ""
                    remarks_text = f"Allocated to SO {so_name} (C3: Parent model '{target_tmpl}' CPU '{target_proc}' match in {dept_name}, current '{curr_ic}') | to_make: {target_ic}"
                    _try_assign_sn(s, dept_name, remarks_text)

            if needed_qty <= 0:
                break

            # -- Condition 4: Parent's Shopify Variant ID Item Codes in THIS department --
            if p4_codes:
                p4_matches = [
                    s for s in list(dept_pool)
                    if s.get("item_code") in p4_codes or s.get("fallback_pb_item_code") in p4_codes or s.get("to_make") in p4_codes
                ]
                p4_matches = _oldest_first(p4_matches)
                for s in p4_matches:
                    if needed_qty <= 0:
                        break
                    curr_ic = s.get("item_code") or s.get("fallback_pb_item_code") or ""
                    remarks_text = f"Allocated to SO {so_name} (C4: Parent Shopify Variant ID {parent_variant_id}, current '{curr_ic}' in {dept_name}) | to_make: {target_ic}"
                    _try_assign_sn(s, dept_name, remarks_text)

            if needed_qty <= 0:
                break

        # Track unallocated / shortage quantity in Missing Sales Order child table
        if needed_qty > 0:
            allocated_qty = original_needed_qty - needed_qty
            plan_doc.append("missing_sales_order", {
                "sales_order": so_name,
                "item_code": target_ic,
                "delivery_date": deliv_date,
                "ordered_qty": original_needed_qty,
                "allocated_qty": allocated_qty,
                "missing_qty": needed_qty,
            })

    # -------------------------------------------------------------
    # 3. FORECAST / DOI BALANCE PHASE (Remaining Serials per Dept)
    # -------------------------------------------------------------
    for s in sorted(sequences, reverse=True):
        seq_forward_grain = forward_grain_per_seq[s]
        forward_keys = forward_keys_per_seq[s]

        for dept in sorted(depts_by_seq[s], key=lambda x: x["name"]):
            dept_name = dept["name"]
            if not dept.get("run_production_planning"):
                continue

            allow_reconfig = bool(dept.get("allow_reconfig"))
            forward_grain = seq_forward_grain
            remaining_serials = avail_serials_by_dept.get(dept_name, [])
            serials_before_forecast = {r['serial_no']: r for r in remaining_serials}
            initial_serial_count = len(inward_serials_per_dept.get(dept_name, []))

            fwd_inventory = _get_forward_inventory_excluding_current_dept(
                inward_serials_per_dept=inward_serials_per_dept,
                current_department=dept_name,
                forward_keys=forward_keys,
                forward_grain=forward_grain,
            )

            doi_snapshot = {
                k: (float(fwd_inventory.get(k, 0)) / max(1.0, float(sales_rate.get(k, 1.0))))
                for k in forward_keys
            }

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
                remarks_text = f"Allocated for Forecast Replenishment (Target: {alloc['target_item_code']} to balance DOI | Sales Rate: {rate_display:.2f}/day, DOI: {doi_display:.1f} days) | to_make: {alloc['target_item_code']}"
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
                    remarks=remarks_text,
                    part_allocation=alloc.get("part_allocation", False),
                )
                priority_per_dept[dept_name] += 1


            # Identify serials dropped due to parts in Forecast or no demand
            allocated_in_forecast = {a['serial_no'] for a in forecast_allocs}
            remaining_after_forecast = {r['serial_no'] for r in remaining_serials}
            
            dropped_in_forecast = set(serials_before_forecast.keys()) - allocated_in_forecast - remaining_after_forecast
            for sn in dropped_in_forecast:
                info = serials_before_forecast[sn]
                reason_text = "Part allocation failed (Forecast)"
                _update_serial_remarks(sn, f"Not Allocated: {reason_text}")
                plan_doc.append("missing_serial_nos", {
                    "serial_no": sn,
                    "current_department": dept_name,
                    "current_warehouse": info['warehouse'],
                    "reason": reason_text
                })

            for sn in remaining_after_forecast:
                info = serials_before_forecast[sn]
                ic = info.get("item_code")
                sn_reason = None

                fallback_pb = info.get("fallback_pb_item_code")
                if not fallback_pb or fallback_pb not in _SELLABLE_ITEM_CODES:
                    sn_reason = _get_pb_missing_reason(ic)

                if sn_reason:
                    _update_serial_remarks(sn, f"Not Allocated: {sn_reason}")
                    plan_doc.append("missing_serial_nos", {
                        "serial_no": sn,
                        "current_department": dept_name,
                        "current_warehouse": info['warehouse'],
                        "reason": sn_reason
                    })
                else:
                    target_item_code = fallback_pb or ic

                    # Part allocation is recalculated by run_latest_production_plan_part_allocation.
                    part_allocation = False

                    fb_ic = target_item_code
                    k = None
                    if fb_ic and fb_ic in _ITEM_KEYS:
                        k = _ITEM_KEYS[fb_ic].get("config_key") or _ITEM_KEYS[fb_ic].get("model_key")
                    if not k:
                        k = info.get("forward_key_config") or info.get("forward_key_model")
                    rate_display = float(sales_rate.get(k, 1.0)) if (sales_rate and k) else 1.0
                    doi_display = float(doi_snapshot.get(k, 0.0)) if (doi_snapshot and k) else 0.0
                    remarks_text = f"Allocated for Forecast Replenishment (Target: {target_item_code} | Sales Rate: {rate_display:.2f}/day, DOI: {doi_display:.1f} days) | to_make: {target_item_code}"

                    _append_plan_row(
                        plan_doc,
                        serial_no=sn,
                        current_warehouse=info['warehouse'],
                        current_department=dept_name,
                        sales_rate=rate_display,
                        doi=doi_display,
                        sales_order_number=None,
                        delivery_date=None,
                        item_code_to_make=target_item_code,
                        reason="Forecast",
                        priority_rank=priority_per_dept[dept_name],
                        serial_age_days=info.get("age_days"),
                        remarks=remarks_text,
                        part_allocation=part_allocation,
                    )
                    priority_per_dept[dept_name] += 1

            consumed_serial_nos = {row.serial_no for row in plan_doc.lines if row.current_department == dept_name}
            
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
                    remarks_text = f"Allocated for Reconfig Rescue (Stale stock dwelling >{reconfig_aging_days} days in {dept_name}) | to_make: {alloc['target_item_code']}"
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
                        remarks=remarks_text,
                        part_allocation=alloc.get("part_allocation", False),
                    )
                    priority_per_dept[dept_name] += 1

                # Log serials that failed part allocation during reconfig
                allocated_sns = {a["serial_no"] for a in reconfig_allocs}
                for serial in stale_serials:
                    if serial["serial_no"] not in allocated_sns:
                        skip_reason = "No matching reconfig target found"
                        _update_serial_remarks(serial["serial_no"], f"Not Allocated: {skip_reason}")
                        plan_doc.append("missing_serial_nos", {
                            "serial_no": serial["serial_no"],
                            "current_department": serial.get("source_department", ""),
                            "current_warehouse": serial["warehouse"],
                            "reason": skip_reason,
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

    # Every plan row is written with part_allocation = 0, so the checkboxes stay
    # blank until the allocation run recalculates them. The scheduler only fires
    # that job once a day (15 0 * * *) while plans are rebuilt twice a day, which
    # left the midday plan showing no ticks at all. Enqueue it here so it always
    # follows the plan that was just built, whatever triggered the plan.
    try:
        frappe.enqueue(
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.run_latest_production_plan_part_allocation",
            queue="long",
            timeout=1800,
            plan_name=plan_doc.name,
            now=frappe.flags.in_test,
        )
    except Exception as part_alloc_err:
        logger.warning("Part allocation recalculation after production plan failed: %s", part_alloc_err)

    # Safely refresh dispatch ETAs for all newly allocated serials and sales orders in background
    try:
        frappe.enqueue(
            "nj_features.overrides.sales_order.calculate_dispatch_eta_for_sales_order",
            queue="long",
            timeout=1800,
            now=frappe.flags.in_test,
        )
    except Exception as eta_err:
        logger.warning("Dispatch ETA recalculation after production plan failed: %s", eta_err)

    return {
        "allocation_audit": None,
        "audit_storage": "Enqueued: run_latest_production_plan_part_allocation",
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
    LOOKBACK_DAYS_B2C = 100
    LOOKBACK_DAYS_B2B = 100

    rows = frappe.db.sql(
        """
        SELECT
            so_data.sales_order                                   AS so_name,
            so_data.soi_name                                      AS soi_name,
            so_data.customer                                      AS customer,
            so_data.transaction_date                              AS transaction_date,
            so_data.delivery_date                                 AS delivery_date,
            so_data.promise_date                                  AS promise_date,

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
                so.committed_delivery_date     AS promise_date,

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
                ON (pb.new_item_code = soi.item_code OR pb.name = soi.item_code)
            LEFT JOIN `tabProduct Bundle Item` pbi
                ON pbi.parent = pb.name
            LEFT JOIN `tabItem` it_comp
                ON it_comp.name = pbi.item_code

            WHERE
                so.status NOT IN ('Closed', 'Completed', 'Draft', 'Cancelled')
                AND so.docstatus = 1
                AND so.name NOT IN (
                    SELECT DISTINCT sales_order
                    FROM `tabNJ Refund`
                    WHERE refund_status IN ('Paid', 'Refunded', 'Initiated', 'Debit Failed', 'Returned')
                      AND docstatus = 1
                      AND sales_order IS NOT NULL
                      AND sales_order != ''
                )
                AND so.name NOT IN (
                    SELECT DISTINCT dni.against_sales_order
                    FROM `tabDelivery Note Item` dni
                    JOIN `tabDelivery Note` dn ON dn.name = dni.parent
                    WHERE dn.docstatus = 1 AND dn.is_return = 1 
                      AND (dn.cause_of_return IN ('Repair', 'Refund') OR dn.return_reason IN ('Repair', 'In-House Repair', 'Refund'))
                      AND dni.against_sales_order IS NOT NULL AND dni.against_sales_order != ''
                )
                -- An RTO'd order is not demand: the parcel came back, so the sale
                -- did not happen. Kept in step with RTO_EXCLUSION_SQL in
                -- reservation_service - the planner reserves units too
                -- (_update_serial_reserved_sales_order), so excluding these orders
                -- in the Sales Order allocator alone would leave the planner
                -- re-reserving exactly what the allocator had stopped taking.
                -- Latest submitted DN wins, so a deliberate re-ship lifts it.
                AND so.name NOT IN (
                    SELECT DISTINCT dni.against_sales_order
                    FROM `tabDelivery Note Item` dni
                    JOIN `tabDelivery Note` dn ON dn.name = dni.parent
                    WHERE dn.docstatus = 1 AND dn.is_return = 1
                      AND dn.cause_of_return IN ('RTO Customer', 'RTO Delivery Partner')
                      AND dni.against_sales_order IS NOT NULL AND dni.against_sales_order != ''
                      AND NOT EXISTS (
                          SELECT 1
                          FROM `tabDelivery Note Item` dni2
                          JOIN `tabDelivery Note` dn2 ON dn2.name = dni2.parent
                          WHERE dni2.against_sales_order = dni.against_sales_order
                            AND dn2.docstatus = 1
                            AND dn2.creation > dn.creation
                      )
                )
                AND (
                    (so.sale_type IN ('NJ-Website-B2C', 'NJ-Direct-B2C') AND so.creation > CURDATE() - INTERVAL %(lookback_b2c)s DAY)
                    OR
                    (so.sale_type IN ('NJ-Website-B2B', 'NJ-Direct-B2B', 'Distributor', 'Franchisee', 'Educational Institutes') AND so.creation > CURDATE() - INTERVAL %(lookback_b2b)s DAY)
                    OR
                    (so.name IN (
                        SELECT DISTINCT dni.against_sales_order
                        FROM `tabDelivery Note Item` dni
                        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
                        WHERE dn.docstatus = 1 AND dn.is_return = 1 AND dn.posting_date > CURDATE() - INTERVAL %(lookback_max)s DAY
                    ))
                )

                AND soi.item_group IN ('Laptops', 'Chromebooks', 'MacBooks', 'Desktops', 'AIO', 'Full Set Desktops', 'Chromeboxes', 'Laptops(Bundle)', 'Chromebooks(Bundle)', 'MacBooks(Bundle)', 'Desktops(Bundle)', 'AIO(Bundle)', 'Full Set Desktops(Bundle)', 'Chromeboxes(Bundle)')
                AND so.customer != 'King Technologies'

                AND (
                    IFNULL(it_so.is_stock_item, 0) = 1
                    OR pbi.item_code IS NOT NULL
                )

                AND (
                    IFNULL(it_so.is_stock_item, 0) = 1
                    OR it_comp.item_group IN ('Laptops', 'Chromebooks', 'MacBooks', 'Desktops', 'AIO', 'Full Set Desktops', 'Chromeboxes')
                )
                AND IFNULL(it_so.disabled, 0) = 0
                AND (IFNULL(it_so.is_stock_item, 0) = 1 OR IFNULL(it_comp.disabled, 0) = 0)
        ) AS so_data

        LEFT JOIN (
            SELECT
                dni.against_sales_order       AS against_sales_order,
                CASE 
                    WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                    ELSE pbi.item_code
                END                           AS item_code,
                SUM(
                    CASE
                        WHEN IFNULL(dn.is_return, 0) = 0 THEN dni.qty
                        WHEN dn.is_return = 1 AND dn.cause_of_return IN ('Repair', 'Replace') THEN dni.qty
                        ELSE 0
                    END
                )                             AS dn_qty
            FROM `tabDelivery Note Item` dni
            INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            INNER JOIN `tabSales Order Item` soi ON dni.so_detail = soi.name
            INNER JOIN `tabItem` it_so ON it_so.name = soi.item_code
            LEFT JOIN `tabProduct Bundle` pb ON (pb.new_item_code = soi.item_code OR pb.name = soi.item_code)
                AND IFNULL(it_so.is_stock_item, 0) = 0
            LEFT JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
            WHERE
                dni.docstatus = 1
                AND dni.creation >= CURDATE() - INTERVAL %(lookback_max)s DAY
            GROUP BY dni.against_sales_order, 
                CASE 
                    WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                    ELSE pbi.item_code
                END
        ) AS dn_data
            ON so_data.sales_order = dn_data.against_sales_order
           AND so_data.item_code   = dn_data.item_code

        LEFT JOIN (
            SELECT
                sn.reserved_sales_order    AS sales_order,
                -- Robustly resolve the stock item code from to_make.
                -- If to_make is a Product Bundle code, resolve it to the component stock item code.
                -- Otherwise, use to_make (which is a stock item) or fallback to sn.item_code.
                COALESCE(
                    (
                        SELECT pbi.item_code 
                        FROM `tabProduct Bundle Item` pbi 
                        INNER JOIN `tabProduct Bundle` pb ON pbi.parent = pb.name 
                        WHERE (pb.new_item_code = sn.to_make OR pb.name = sn.to_make)
                        LIMIT 1
                    ),
                    NULLIF(sn.to_make, ''),
                    sn.item_code
                )                          AS item_code,
                COUNT(*)                   AS reserved_qty
            FROM `tabSerial No` sn
            WHERE
                -- Location-blind: see sales_order.adjust_serial_allocations().
                sn.reserved_sales_order IS NOT NULL
                AND sn.reserved_sales_order != ''
                AND (sn.status IS NULL OR sn.status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
            GROUP BY sn.reserved_sales_order, 
                COALESCE(
                    (
                        SELECT pbi.item_code 
                        FROM `tabProduct Bundle Item` pbi 
                        INNER JOIN `tabProduct Bundle` pb ON pbi.parent = pb.name 
                        WHERE (pb.new_item_code = sn.to_make OR pb.name = sn.to_make)
                        LIMIT 1
                    ),
                    NULLIF(sn.to_make, ''),
                    sn.item_code
                )
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
            "promise_date": row.get("promise_date"),
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
    # Reconfiguration is always allowed for Sales Order allocations
    allow_reconfig = True
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

            # Part allocation is recalculated by run_latest_production_plan_part_allocation.
            part_allocation = False

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
                    "part_allocation": part_allocation,
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

        # Part allocation is recalculated by run_latest_production_plan_part_allocation.
        part_allocation = False

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
                "part_allocation": part_allocation,
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
            w.department,
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
        INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
        INNER JOIN `tabDepartment` dp ON w.department = dp.name
        WHERE w.department IN %(depts)s
          AND (sn.status IS NULL OR sn.status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
          AND it.item_group IN %(igroups)s
          AND IFNULL(dp.department_sequence, 0) != 0
          AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
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

        # Part allocation is recalculated by run_latest_production_plan_part_allocation.
        part_allocation = False

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
            "part_allocation": part_allocation,
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
            w.department,
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
        INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
        INNER JOIN `tabDepartment` dp ON w.department = dp.name
        WHERE w.department = %(dept)s
          AND (sn.status IS NULL OR sn.status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
          AND it.item_group IN %(igroups)s
          AND (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '')
          AND IFNULL(dp.department_sequence, 0) != 0
          AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
          AND (sn.return_reason IS NULL OR sn.return_reason NOT IN ('Repair', 'Replace'))
          AND (sn.order_source IS NULL OR sn.order_source NOT LIKE '%%- Repair%%')
          -- Keep the SO candidate rule identical to assign_serials in
          -- overrides/sales_order.py. Returned/replacement stock is sellable only
          -- after it has reached the reprocessed portion of the pipeline.
          AND (
              (IFNULL(sn.is_replace, 0) = 0 AND (sn.return_reason IS NULL OR sn.return_reason = ''))
              OR (sn.sales_order_id IS NOT NULL AND sn.sales_order_id != '')
              OR IFNULL(dp.department_sequence, 0) >= 10
          )
          {extra_where}
        """,
        params,
        as_dict=True,
    )

    _prime_item_cache([r["item_code"] for r in rows])
    return rows


@log_io
def _get_return_excluded_serials_for_department(dept_doc, eligible_names) -> List[Dict]:
    """
    Reporting-only: serials that pass the same base filters as
    _get_inward_serials_for_department() but are excluded by the return/replace
    eligibility rule (return unit not yet reprocessed far enough downstream).
    Lets a plan run log *why* a serial isn't included, instead of it silently
    looking like a vanished/lost serial.
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
            sn.return_reason,
            sn.is_replace
        FROM `tabSerial No` sn
        INNER JOIN `tabItem` it
            ON sn.item_code = it.name
        INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
        INNER JOIN `tabDepartment` dp ON w.department = dp.name
        WHERE w.department = %(dept)s
          AND (sn.status IS NULL OR sn.status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
          AND it.item_group IN %(igroups)s
          AND (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '')
          AND IFNULL(dp.department_sequence, 0) != 0
          AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
          AND (sn.return_reason IS NULL OR sn.return_reason NOT IN ('Repair', 'Replace'))
          AND (sn.order_source IS NULL OR sn.order_source NOT LIKE '%%- Repair%%')
          AND NOT (
              (IFNULL(sn.is_replace, 0) = 0 AND (sn.return_reason IS NULL OR sn.return_reason = ''))
              OR (sn.sales_order_id IS NOT NULL AND sn.sales_order_id != '')
              OR IFNULL(dp.department_sequence, 0) >= 10
          )
          {extra_where}
        """,
        params,
        as_dict=True,
    )
    return [r for r in rows if r["name"] not in eligible_names]


@log_io
def _get_reserved_serials_for_department(dept_name: str) -> List[Dict]:
    """
    Fetch serials in this department that are already reserved against
    an active Sales Order (status NOT Closed/Cancelled/Completed).
    These bypass normal allocation logic and are added directly to the plan.
    """
    # Imported inside the function: reservation_service imports
    # overrides.sales_order at module level, so a top-level import here risks an
    # import cycle.
    from nj_features.services.reservation_service import RTO_EXCLUSION_SQL

    rows = frappe.db.sql(
        f"""
        SELECT
            sn.name,
            sn.item_code,
            sn.warehouse,
            w.department,
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
        INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
        INNER JOIN `tabDepartment` dp ON w.department = dp.name
        WHERE w.department = %(dept)s
          AND (sn.status IS NULL OR sn.status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
          AND it.item_group IN %(igroups)s
          AND sn.reserved_sales_order IS NOT NULL
          AND sn.reserved_sales_order != ''
          AND so.status NOT IN ('Closed', 'Cancelled', 'Completed')
          AND so.name NOT IN (
              SELECT DISTINCT sales_order
              FROM `tabNJ Refund`
              WHERE refund_status IN ('Paid', 'Refunded', 'Initiated', 'Debit Failed', 'Returned')
                AND docstatus = 1
                AND sales_order IS NOT NULL
                AND sales_order != ''
          )
          -- A unit still reserved to an RTO'd order must not be planned for it
          -- either: the parcel came back, so the build has no customer waiting.
          -- release_rto_dead_order_reservations() frees these, but this keeps
          -- the plan correct for any that are still held when it runs.
          {RTO_EXCLUSION_SQL}
          AND IFNULL(dp.department_sequence, 0) != 0
          AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
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

    def _normalize_proc_val(proc: Optional[str]) -> Optional[str]:
        if not proc or not isinstance(proc, str):
            return proc
        p = re.sub(r"\s+", " ", proc.strip().upper())
        p_norm = re.sub(r"^(AMD|INTEL)\s+", "", p)
        return p_norm if p_norm else p

    for ic in needed:
        core = _ITEM_CORE.get(ic) or {}
        # Derive accurate model prefix from item_code if formatted as Model-CPU-...
        model_match = re.split(r"-(CORE|RYZEN|CELERON|ATHLON|PENTIUM|AMD|INTEL|M1|M2|M3|I3|I5|I7|I9|XEON)", ic, maxsplit=1, flags=re.IGNORECASE)
        if model_match and len(model_match) > 1 and model_match[0].strip():
            template = model_match[0].strip()
        else:
            template = core.get("variant_of") or ic
        attrs = _ITEM_ATTRS.get(ic, {})
        proc = attrs.get(PROCESSOR_ATTR)
        ram = attrs.get(RAM_ATTR)
        sto = attrs.get(STORAGE_ATTR)

        proc_clean = _normalize_proc_val(proc)
        template_clean = template.strip() if isinstance(template, str) else template
        ram_clean = ram.strip().upper() if isinstance(ram, str) else ram
        sto_clean = sto.strip().upper() if isinstance(sto, str) else sto

        _ITEM_KEYS[ic] = {
            "model_key": ("MODEL", template_clean, proc_clean),
            "config_key": ("CONFIG", template_clean, proc_clean, ram_clean, sto_clean),
        }


def _normalize_processor(proc: Optional[str]) -> Optional[str]:
    if not proc or not isinstance(proc, str):
        return proc
    p = re.sub(r"\s+", " ", proc.strip().upper())
    p_norm = re.sub(r"^(AMD|INTEL)\s+", "", p)
    return p_norm if p_norm else p


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
    2. same model with matching RAM + real Storage
    3. same model, alphabetically stable
    """
    if not item_code:
        return None

    if item_code not in _ITEM_KEYS:
        _prime_item_cache([item_code])

    model_key = _ITEM_KEYS[item_code]["model_key"]
    config_key = _ITEM_KEYS[item_code]["config_key"]

    candidates = list(_MODEL_TO_SELLABLE_ITEMS.get(model_key, []))

    # Fallback to same template if exact model_key yielded no candidates
    if not candidates and model_key and len(model_key) > 1:
        template_clean = model_key[1]
        for mk, c_list in _MODEL_TO_SELLABLE_ITEMS.items():
            if mk and len(mk) > 1 and mk[1] == template_clean:
                candidates.extend(c_list)

    # Ensure candidates are primed
    unprimed = [ic for ic in candidates if ic not in _ITEM_KEYS]
    if unprimed:
        _prime_item_cache(unprimed)

    if not candidates:
        return None

    for ic in candidates:
        if _ITEM_KEYS.get(ic, {}).get("config_key") == config_key:
            return ic

    sn_attrs = _ITEM_ATTRS.get(item_code, {})
    sn_ram = (sn_attrs.get(RAM_ATTR) or "").strip().upper()
    sn_proc = _normalize_processor(sn_attrs.get(PROCESSOR_ATTR))

    def _rank(ic: str):
        attrs = _ITEM_ATTRS.get(ic, {})
        ram = (attrs.get(RAM_ATTR) or "").strip().upper()
        sto = attrs.get(STORAGE_ATTR)
        proc = _normalize_processor(attrs.get(PROCESSOR_ATTR))

        same_proc = 1 if (sn_proc and proc == sn_proc) else 0
        same_ram = 1 if (sn_ram and ram == sn_ram and not _is_blankish_attr(ram)) else 0
        good_ram = 0 if _is_blankish_attr(ram) else 1
        good_sto = 0 if _is_blankish_attr(sto) else 1
        good_proc = 0 if _is_blankish_attr(proc) else 1

        return (
            same_proc,
            same_ram,
            good_ram + good_sto + good_proc,
            good_ram,
            good_sto,
            good_proc,
            ic,
        )

    candidates = sorted(candidates, key=_rank, reverse=True)
    return candidates[0] if candidates else None


def _get_pb_missing_reason(item_code: str) -> str:
    """Return specific reason why no sellable Product Bundle was found for item_code."""
    if not item_code:
        return "Product Bundle not found"

    item_status = frappe.db.get_value("Item", item_code, ["disabled"], as_dict=True)
    if item_status and item_status.get("disabled"):
        return "Item is Disabled"

    pb_rows = frappe.db.sql("""
        SELECT pb.name, pb.disable, i.shopify_product_id, i.disabled AS item_disabled, ci.disabled AS comp_disabled
        FROM `tabProduct Bundle` pb
        INNER JOIN `tabItem` i ON i.name = pb.new_item_code
        INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
        INNER JOIN `tabItem` ci ON pbi.item_code = ci.name
        WHERE pb.new_item_code = %s OR pbi.item_code = %s
        LIMIT 5
    """, (item_code, item_code), as_dict=True)

    if not pb_rows:
        template = _ITEM_CORE.get(item_code, {}).get("variant_of")
        if template:
            pb_rows = frappe.db.sql("""
                SELECT pb.name, pb.disable, i.shopify_product_id, i.disabled AS item_disabled, ci.disabled AS comp_disabled
                FROM `tabProduct Bundle` pb
                INNER JOIN `tabItem` i ON i.name = pb.new_item_code
                INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
                INNER JOIN `tabItem` ci ON pbi.item_code = ci.name
                WHERE ci.variant_of = %s
                LIMIT 5
            """, (template,), as_dict=True)

    if not pb_rows:
        return "Product Bundle not found"

    for r in pb_rows:
        if r.get("disable") == 1:
            return "Product Bundle is Disabled"
        if r.get("item_disabled") == 1 or r.get("comp_disabled") == 1:
            return "Product Bundle Item is Disabled"
        if REQUIRE_SHOPIFY_IDS_FOR_SELLABLE and not (r.get("shopify_product_id") or "").strip():
            return "Product Bundle missing Shopify Product ID"

    return "Product Bundle not found"


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
        match = True
        for k, v2 in attr_map.items():
            val = attrs.get(k)
            if k == PROCESSOR_ATTR:
                if _normalize_processor(val) != _normalize_processor(v2):
                    match = False
                    break
            else:
                if (val or "").strip().upper() != (v2 or "").strip().upper():
                    match = False
                    break
        if match:
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
        "to_make": snrow.get("to_make"),
    }


# =========================
# Part allocation helpers
# =========================
@log_io
def _build_initial_part_stock():
    """Compatibility helper; main planning uses the run-owned stock snapshot."""
    run = PartAllocationRun({"Stores - NJ": True})
    return run.stock, run.planned


@log_io
def _maybe_allocate_parts_for_serial(serial_no: str, current_department: str, planning_reason=None, target_item_code=None) -> bool:
    if _PART_ENGINE is None:
        raise RuntimeError("Part allocation must be initialized by the production planning run")
    return _PART_ENGINE.allocate(serial_no, current_department, planning_reason, target_item_code)


@frappe.whitelist()
@log_io
def run_latest_production_plan_part_allocation(plan_name: Optional[str] = None) -> Dict:
    """
    Recalculate Part Allocation checkboxes for an NJ Production Planning document.

    This runs after the production plan is already created. It only touches child
    rows whose current Department has Allocate Parts enabled, and it processes
    them by numeric Priority Rank so the virtual deductions follow the same
    order visible in the plan. A row qualifies when either its NJPP current
    department or its physical Serial No warehouse department is configured.

    When plan_name is given the allocation is pinned to that plan. The production
    plan run passes the plan it just built so the recalculation cannot drift onto
    a different document if another plan is created while this job is queued.
    Called with no argument (the scheduler) it falls back to the newest plan.
    """
    # This rewrites plan checkboxes and consumes virtual Stores stock, so restrict
    # direct HTTP callers to System Manager. Background callers (the scheduler and
    # the production plan run) have no request and are unaffected -- important
    # because an enqueued job inherits the session user of whoever triggered the
    # plan, which is not necessarily a System Manager.
    if frappe.request:
        frappe.only_for("System Manager")

    latest_plan = plan_name or frappe.db.get_value(
        "NJ Production Planning",
        filters={},
        fieldname="name",
        order_by="creation desc",
    )
    print("[PART_ALLOC_SCHEDULE] Started latest production plan part allocation")
    if not latest_plan:
        print("[PART_ALLOC_SCHEDULE] No NJ Production Planning record found")
        return {"status": "No NJ Production Planning found"}
    print(f"[PART_ALLOC_SCHEDULE] Latest NJ Production Planning: {latest_plan}")

    allocate_parts_departments = _get_allocate_parts_department_names_from_settings()
    allocate_parts_department_keys = tuple(
        sorted({_compact_pp_name(dept) for dept in allocate_parts_departments if dept})
    )
    print(f"[PART_ALLOC_SCHEDULE] Allocate Parts departments from NJ Settings: {allocate_parts_departments}")
    if not allocate_parts_department_keys:
        print("[PART_ALLOC_SCHEDULE] No allocate_parts_departments configured in NJ Settings")
        return {"status": "No Allocate Parts departments configured", "production_plan": latest_plan}

    rows = frappe.db.sql(
        """
        SELECT
            pp.name AS row_name,
            pp.serial_no,
            pp.current_department,
            pp.item_code,
            pp.reason,
            pp.priority_rank,
            sn.warehouse AS serial_warehouse,
            wh.department AS serial_warehouse_department,
            CAST(IFNULL(NULLIF(pp.priority_rank, ''), '0') AS UNSIGNED) AS priority_rank_no
        FROM `tabFinal Production Planning Data` pp
        LEFT JOIN `tabSerial No` sn ON sn.name = pp.serial_no
        LEFT JOIN `tabWarehouse` wh ON wh.name = sn.warehouse
        WHERE pp.parent = %(parent)s
          AND (
              LOWER(REPLACE(pp.current_department, ' ', '')) IN %(department_keys)s
              OR LOWER(REPLACE(IFNULL(wh.department, ''), ' ', '')) IN %(department_keys)s
          )
          AND IFNULL(pp.serial_no, '') != ''
        ORDER BY priority_rank_no ASC, pp.idx ASC
        """,
        {"parent": latest_plan, "department_keys": allocate_parts_department_keys},
        as_dict=True,
    )
    print(f"[PART_ALLOC_SCHEDULE] Allocate Parts child rows fetched: {len(rows)}")
    if not rows:
        print(f"[PART_ALLOC_SCHEDULE] No child rows found for Allocate Parts departments in plan {latest_plan}")
        return {"status": "No Allocate Parts rows found", "production_plan": latest_plan}

    department_flags = {
        row.name: _is_allocate_parts_department(row.name, allocate_parts_departments)
        for row in frappe.get_all("Department", fields=["name"])
    }
    # Google Sheet eligibility is based on the physical Serial No warehouse
    # department.  A plan row can therefore still have a different NJPP
    # current_department (for example Paint/L2) while its serial is physically
    # in a configured Part Waiting warehouse.  Enable only those fetched plan
    # departments; the normal NJPP department remains in the audit output.
    for row in rows:
        if _is_allocate_parts_department(
            row.get("serial_warehouse_department"), allocate_parts_departments
        ):
            department_flags[row.current_department] = True
            print(
                "[PART_ALLOC_SCHEDULE] Physical warehouse department enables "
                f"serial={row.serial_no} warehouse={row.get('serial_warehouse')} "
                f"warehouse_department={row.get('serial_warehouse_department')} "
                f"njpp_department={row.current_department}"
            )
    enabled_departments = sorted([dept for dept, enabled in department_flags.items() if enabled])
    print(f"[PART_ALLOC_SCHEDULE] Allocate Parts matched departments: {enabled_departments}")
    run = PartAllocationRun(department_flags)
    run.load_inputs([row.serial_no for row in rows])
    print(f"[PART_ALLOC_SCHEDULE] Loaded serial input data for {len(run.serials)} serials")
    print(f"[PART_ALLOC_SCHEDULE] Initial Stores stock item count: {len(run.stock)}")

    for row in rows:
        if row.serial_no in run.serials:
            run.serials[row.serial_no]["planning_department"] = row.current_department

    checked = 0
    allocated = 0
    failed = 0
    for row in rows:
        checked += 1
        target_item_code = row.item_code or (run.serials.get(row.serial_no) or {}).get("item_code")
        print(
            "[PART_ALLOC_SCHEDULE] Checking "
            f"priority={row.priority_rank} row={row.row_name} serial={row.serial_no} "
            f"department={row.current_department} target={target_item_code} reason={row.reason}"
        )
        success = run.allocate(
            row.serial_no,
            row.current_department,
            row.reason or "Part Allocation",
            target_item_code,
        )
        frappe.db.set_value(
            "Final Production Planning Data",
            row.row_name,
            "part_allocation",
            1 if success else 0,
            update_modified=False,
        )
        if success:
            allocated += 1
            print(
                "[PART_ALLOC_SCHEDULE] ALLOCATED "
                f"serial={row.serial_no} priority={row.priority_rank} checkbox=1"
            )
        else:
            failed += 1
            audit = run.audits.get(row.serial_no, {})
            attempts = audit.get("attempts") or []
            last_attempt = attempts[-1] if attempts else {}
            print(
                "[PART_ALLOC_SCHEDULE] NOT ALLOCATED "
                f"serial={row.serial_no} priority={row.priority_rank} checkbox=0 "
                f"result={last_attempt.get('result')} reason={last_attempt.get('reason')}"
            )
            for req in last_attempt.get("requirements") or []:
                if flt(req.get("shortage")) <= 0:
                    continue
                required_item = req.get("requested_item")
                print(
                    "[PART_ALLOC_SCHEDULE] SHORTAGE "
                    f"serial={row.serial_no} required_item={required_item} "
                    f"required_qty={req.get('required_stock_qty')} bag_qty={req.get('bag_qty_used')} "
                    f"shortage={req.get('shortage')}"
                )
                for candidate in req.get("candidate_checks") or []:
                    print(
                        "[PART_ALLOC_SCHEDULE] CANDIDATE "
                        f"serial={row.serial_no} required_item={required_item} "
                        f"candidate_item={candidate.get('item_code')} "
                        f"initial_stock={candidate.get('initial_stock')} "
                        f"earlier_reserved_qty={candidate.get('earlier_reserved_qty')} "
                        f"available_before_serial={candidate.get('available_before_serial')} "
                        f"tentative_qty={candidate.get('tentative_qty_for_requirement')}"
                    )
                combo = req.get("combination_search") or {}
                if combo:
                    print(
                        "[PART_ALLOC_SCHEDULE] COMBINATIONS "
                        f"serial={row.serial_no} required_item={required_item} "
                        f"eligible_item_codes={combo.get('eligible_item_codes')} "
                        f"reason={combo.get('reason')}"
                    )

    plan_doc = frappe.get_doc("NJ Production Planning", latest_plan)
    plan_doc.flags.ignore_validate_update_after_submit = True
    allocation_audit = run.persist_to_plan_child(plan_doc, serial_nos=[row.serial_no for row in rows])
    print(
        "[PART_ALLOC_SCHEDULE] Part Allocation Details child rows stored "
        f"run_id={allocation_audit.get('run_id')} "
        f"child_rows={allocation_audit.get('child_rows')} "
        f"plan={latest_plan}"
    )
    # Keep the visible plan checkbox synchronized with the persisted allocation
    # detail rows.  The detail table is the source of truth for this standalone
    # allocation run, so this also repairs any stale checkbox values if a run is
    # repeated for the same plan.
    detail_rows = frappe.get_all(
        "NJ Production Planning Part Allocation Detail",
        filters={
            "parent": latest_plan,
            "serial_no": ["in", [row.serial_no for row in rows]],
        },
        fields=["serial_no", "part_allocation"],
    )
    for detail in detail_rows:
        frappe.db.sql(
            """
            UPDATE `tabFinal Production Planning Data`
            SET part_allocation = %(part_allocation)s
            WHERE parent = %(parent)s AND serial_no = %(serial_no)s
            """,
            {
                "part_allocation": 1 if detail.part_allocation else 0,
                "parent": latest_plan,
                "serial_no": detail.serial_no,
            },
        )
    print(
        "[PART_ALLOC_SCHEDULE] Final Production Planning Data checkboxes synchronized "
        f"from detail_rows={len(detail_rows)} plan={latest_plan}"
    )
    frappe.db.commit()
    print(
        "[PART_ALLOC_SCHEDULE] Completed "
        f"plan={latest_plan} checked={checked} allocated={allocated} failed={failed}"
    )

    return {
        "status": "Completed",
        "production_plan": latest_plan,
        "checked": checked,
        "allocated": allocated,
        "failed": failed,
        "allocation_audit": allocation_audit,
    }


# =========================
# Hourly Priority Rank refresh
# =========================

# Ordering the hourly re-rank applies inside one department queue. Anything with
# an unrecognised reason sorts after the three the production plan writes.
PP_RANK_REASON_ORDER = {"Order": 0, "Reconfig": 1, "Forecast": 2}
PP_RANK_DEAD_SERIAL_STATUSES = ("Delivered", "Scrapped", "Inactive")
PP_RANK_FAR_FUTURE_DATE = "9999-12-31"


@frappe.whitelist()
def enqueue_latest_production_plan_priority_rank(plan_name: Optional[str] = None):
    """Enqueue the Priority Rank refresh so the hourly scheduler tick never blocks on it."""
    frappe.enqueue(
        "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning"
        ".refresh_latest_production_plan_priority_rank",
        queue="long",
        timeout=1800,
        plan_name=plan_name,
    )
    return {"message": "Priority rank refresh enqueued successfully", "status": "queued"}


def _get_priority_rank_sort_key(row: Dict) -> tuple:
    """Sort key for one plan row inside its department queue. Lowest sorts to rank 1."""
    # A serial that has left the floor (delivered, scrapped, deleted) keeps its plan
    # row until the next full plan run. Ranking it first would park a permanent
    # blocker at the top of the queue, so dead rows are pushed to the end instead.
    dead = 1 if row.get("is_dead") else 0

    # Stock Movement refuses every other serial while a part allocated one is still
    # pending in the same scope, so the rank order mirrors the rule it enforces.
    part_allocated = 0 if int(flt(row.get("part_allocation") or 0)) else 1

    reason_order = PP_RANK_REASON_ORDER.get(row.get("reason"), len(PP_RANK_REASON_ORDER))

    # Only Order rows carry a delivery date worth ranking on; the rest sort neutrally.
    # delivery_date is a real DATE column, so the driver hands back a date or None --
    # never a string needing parsing. getdate() does return None for a zero date
    # though, and str(None) sorts after 9999-12-31, which would quietly bury the row
    # at the bottom of its queue instead of treating it as "no date".
    delivery_date = row.get("delivery_date") if row.get("reason") == "Order" else None
    parsed_delivery_date = frappe.utils.getdate(delivery_date) if delivery_date else None
    delivery_key = (
        parsed_delivery_date.isoformat() if parsed_delivery_date else PP_RANK_FAR_FUTURE_DATE
    )

    # FIFO tiebreak: the oldest serial (largest age in days) moves first.
    age_days = int(flt(row.get("serial_age_days") or 0))

    return (dead, part_allocated, reason_order, delivery_key, -age_days, row.get("serial_no") or "")


@frappe.whitelist()
@log_io
def refresh_latest_production_plan_priority_rank(plan_name: Optional[str] = None) -> Dict:
    """
    Re-rank the serials in the latest NJ Production Planning document, hourly.

    Stock Movement re-reads priority_rank, part_allocation and current_department
    straight off `tabFinal Production Planning Data` on every submit, so rewriting
    the rank column is enough to change what the floor is allowed to move next --
    the 12 hourly plan rebuild is not needed for that.

    This job never touches item_code (the to make item), sales_order_no,
    delivery_date, reason, or anything on the Serial No: what to build stays
    exactly as the 12 hourly plan decided it. It rewrites priority_rank, and
    refreshes current_department / current_warehouse to where the serial actually
    is now -- the rank scope for a Rack/Transit move is the stored
    current_department, so a stale value compares a serial against the wrong queue.
    """
    # Same guard as the part allocation job: this rewrites plan rows, so direct
    # HTTP callers must be System Manager. The scheduler has no request and is
    # unaffected.
    if frappe.request:
        frappe.only_for("System Manager")

    latest_plan = plan_name or _get_latest_nj_production_plan_name()
    if not latest_plan:
        print("[RANK_REFRESH] No NJ Production Planning record found")
        return {"status": "No NJ Production Planning found"}

    print(f"[RANK_REFRESH] Started priority rank refresh plan={latest_plan}")

    rows = frappe.db.sql(
        """
        SELECT
            pp.name AS row_name,
            pp.serial_no,
            pp.current_department,
            pp.current_warehouse,
            pp.reason,
            pp.delivery_date,
            pp.serial_age_days,
            CAST(IFNULL(NULLIF(pp.priority_rank, ''), '0') AS UNSIGNED) AS priority_rank,
            IFNULL(pp.part_allocation, 0) AS part_allocation,
            sn.name AS live_serial_no,
            sn.status AS serial_status,
            sn.warehouse AS live_warehouse,
            wh.department AS live_department
        FROM `tabFinal Production Planning Data` pp
        LEFT JOIN `tabSerial No` sn ON sn.name = pp.serial_no
        LEFT JOIN `tabWarehouse` wh ON wh.name = sn.warehouse
        WHERE pp.parent = %(parent)s
          AND pp.parenttype = 'NJ Production Planning'
          AND pp.parentfield = 'lines'
        ORDER BY pp.idx
        """,
        {"parent": latest_plan},
        as_dict=True,
    )

    if not rows:
        print(f"[RANK_REFRESH] No plan rows found plan={latest_plan}")
        return {"status": "No plan rows found", "production_plan": latest_plan}

    rows_by_dept: Dict[str, List[Dict]] = defaultdict(list)
    dead_rows = 0

    for row in rows:
        row["is_dead"] = (
            not row.get("live_serial_no")
            or not row.get("live_warehouse")
            or (row.get("serial_status") or "") in PP_RANK_DEAD_SERIAL_STATUSES
        )
        if row["is_dead"]:
            dead_rows += 1

        # Queue the serial where it physically is now, falling back to the planned
        # department when the serial has no live warehouse/department any more.
        dept_name = row.get("live_department") or row.get("current_department")
        if not dept_name:
            print(
                "[RANK_REFRESH] SKIPPED serial=%s row=%s reason=no department to rank in"
                % (row.get("serial_no"), row.get("row_name"))
            )
            continue

        rows_by_dept[dept_name].append(row)

    rank_updates = 0
    position_updates = 0

    for dept_name in sorted(rows_by_dept):
        dept_rows = sorted(rows_by_dept[dept_name], key=_get_priority_rank_sort_key)

        for new_rank, row in enumerate(dept_rows, start=1):
            changes = {}

            if int(flt(row.get("priority_rank") or 0)) != new_rank:
                changes["priority_rank"] = str(new_rank)

            if row.get("live_department") and row["live_department"] != row.get("current_department"):
                changes["current_department"] = row["live_department"]

            if row.get("live_warehouse") and row["live_warehouse"] != row.get("current_warehouse"):
                changes["current_warehouse"] = row["live_warehouse"]

            if not changes:
                continue

            if "priority_rank" in changes:
                rank_updates += 1
            if "current_department" in changes or "current_warehouse" in changes:
                position_updates += 1

            frappe.db.set_value(
                "Final Production Planning Data",
                row["row_name"],
                changes,
                update_modified=False,
            )
            # Per row detail goes to the rotating plan log, not the scheduler log:
            # this runs 24 times a day over a few thousand rows.
            logger.debug(
                "[RANK_REFRESH] UPDATED serial=%s department=%s old_rank=%s new_rank=%s changes=%s",
                *(
                    row.get("serial_no"),
                    dept_name,
                    row.get("priority_rank"),
                    new_rank,
                    ", ".join(sorted(changes)),
                )
            )

    frappe.db.commit()
    print(
        "[RANK_REFRESH] Completed plan=%s departments=%s rows=%s rank_updates=%s "
        "position_updates=%s dead_rows=%s"
        % (latest_plan, len(rows_by_dept), len(rows), rank_updates, position_updates, dead_rows)
    )

    return {
        "status": "Completed",
        "production_plan": latest_plan,
        "departments": len(rows_by_dept),
        "rows": len(rows),
        "rank_updates": rank_updates,
        "position_updates": position_updates,
        "dead_rows": dead_rows,
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
    priority_rank: int,
    serial_age_days: Optional[int] = None,
    remarks: Optional[str] = None,
    part_allocation: Union[int, bool] = False,
):
    # Log each serial number being processed
    logger.debug(f"processing each and every serial no we need to mention got it: {serial_no}")

    if reason == "Order" and sales_order_number:
        success = _update_serial_reserved_sales_order(serial_no, sales_order_number)
        if not success:
            logger.warning(
                "[ALLOCATION_REJECTED] Serial %s could not be reserved for SO %s: already reserved or modified concurrently.",
                serial_no, sales_order_number
            )
            return False
        logger.debug(
            "[ALLOCATION] SO: %s, Item: %s, Serial: %s, Dept: %s, Wh: %s, Reason: %s",
            sales_order_number, item_code_to_make, serial_no, current_department, current_warehouse, remarks
        )

    _update_serial_to_make(serial_no, item_code_to_make, expected_so=sales_order_number)

    if remarks:
        _update_serial_remarks(serial_no, remarks)

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
            "part_allocation": int(bool(part_allocation)),
        },
    )
    return True





# Manufacture MR section==================


PP_MR_DEFAULT_SCHEDULE_DAYS = 3
PP_MR_STORES_DEPARTMENT = "Stores - NJ"
PP_MR_CORE_ITEM_GROUPS = ["Laptops", "Chromebooks", "Desktops", "Macbooks"]
PP_MR_MIN_QTY = 0.000001
_PP_MR_WHOLE_NUMBER_UOM_BY_ITEM = {}


def _get_pp_default_mr_schedule_date():
    return add_days(frappe.utils.nowdate(), PP_MR_DEFAULT_SCHEDULE_DAYS)
    from nj_features.overrides.sales_order import add_working_days
    return add_working_days(frappe.utils.nowdate(), PP_MR_DEFAULT_SCHEDULE_DAYS)


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


def _get_pp_nj_setting_csv_values(parameter):
    value = frappe.db.get_value("NJ Settings", {"parameter": parameter}, "value")
    values = _split_pp_department_names(value)
    print("PP MR NJ Settings CSV values:", "parameter:", parameter, "values:", values)
    return values


def _normalize_pp_department_name(department):
    return " ".join(str(department or "").split())


def _compact_pp_name(value):
    return "".join(str(value or "").lower().split())


def _get_allocate_parts_department_names_from_settings():
    return _get_pp_nj_setting_csv_values("allocate_parts_departments")


def _is_allocate_parts_department(current_department, configured_departments):
    configured_keys = {_compact_pp_name(dept) for dept in configured_departments if dept}
    return _compact_pp_name(current_department) in configured_keys


def _get_pp_consumable_stock_department_map():
    rows = frappe.get_all(
        "Warehouse",
        filters={"used_for_consumables_stock": 1},
        fields=["department"],
    )
    department_map = {}
    for row in rows:
        department = row.get("department")
        if not department:
            continue

        department_map[_normalize_pp_department_name(department)] = department

    print("PP MR allowed consumable stock departments:", sorted(department_map.values()))
    return department_map


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
            IFNULL(NULLIF(i.variant_of, ''), i.name)
    """, {
        "plan_name": plan_name,
        "core_item_groups": tuple(PP_MR_CORE_ITEM_GROUPS),
    }, as_dict=1 ,debug=1)
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
    required_qty_by_dept_item = defaultdict(float)
    schedule_days_by_dept_item = defaultdict(list)
    item_templates_by_dept_item = defaultdict(set)
    dept_item_order = []
    previous_departments_by_dept = {}
    stock_departments = set()
    allowed_department_map = _get_pp_consumable_stock_department_map()

    for row in template_department_qty:
        item_template = row.item_template
        planned_qty = flt(row.planned_qty)

        for consumable in consumables_by_template.get(item_template, []):
            target_departments = _split_pp_department_names(consumable.departments)
            if not target_departments:
                print(
                    "PP MR consumable departments empty:",
                    "item_template:", item_template,
                    "item_code:", consumable.item_code,
                    "default_schedule_days:", PP_MR_DEFAULT_SCHEDULE_DAYS,
                )
                continue

            for target_department in target_departments:
                current_department = allowed_department_map.get(
                    _normalize_pp_department_name(target_department)
                )
                if not current_department:
                    print(
                        "PP MR skipped child table department:",
                        "item_template:", item_template,
                        "item_code:", consumable.item_code,
                        "target_department:", target_department,
                        "reason:", "department not enabled for consumables stock",
                    )
                    continue

                dept_item_key = (current_department, consumable.item_code)
                if dept_item_key not in required_qty_by_dept_item:
                    dept_item_order.append(dept_item_key)

                required_qty_by_dept_item[dept_item_key] += flt(consumable.quantity) * planned_qty
                if item_template:
                    item_templates_by_dept_item[dept_item_key].add(item_template)

                previous_departments = previous_departments_by_dept.setdefault(
                    current_department,
                    _get_pp_previous_two_department_names(current_department),
                )
                stock_departments.add(current_department)
                stock_departments.update(previous_departments)

                print(
                    "PP MR consumable parsed department:",
                    "item_template:", item_template,
                    "item_code:", consumable.item_code,
                    "planned_qty:", planned_qty,
                    "target_department:", target_department,
                    "current_stock_department:", current_department,
                    "previous_stock_departments:", previous_departments,
                )
                schedule_days_by_dept_item[dept_item_key].append(
                    _get_pp_schedule_days(current_department, current_department)
                )

    if not required_qty_by_dept_item:
        return []

    item_codes = sorted({item_code for _department, item_code in required_qty_by_dept_item})
    item_skip_reasons = _get_pp_item_skip_reasons(item_codes)
    for item_code, reason in sorted(item_skip_reasons.items()):
        print(
            "PP MR skipped consumable item:",
            "item_code:", item_code,
            "reason:", reason,
        )

    valid_item_codes = [
        item_code
        for item_code in item_codes
        if item_code not in item_skip_reasons
    ]
    if not valid_item_codes:
        print("PP MR no valid consumable items after lifecycle validation")
        return []

    _stock_by_item, stock_details_by_item = _get_pp_department_consumable_stock(
        valid_item_codes,
        sorted(stock_departments),
    )

    shortage_items = []
    raised_item_codes = set()
    for current_department, item_code in dept_item_order:
        if item_code in item_skip_reasons:
            continue

        required_qty = required_qty_by_dept_item[(current_department, item_code)]
        stock_details = stock_details_by_item.get(item_code) or []
        current_stock_details = [
            detail
            for detail in stock_details
            if detail.get("department") == current_department
        ]
        previous_departments = previous_departments_by_dept.get(current_department) or []
        previous_stock_details = [
            detail
            for detail in stock_details
            if detail.get("department") in previous_departments
        ]
        current_department_qty = flt(
            sum(flt(detail.get("actual_qty")) for detail in current_stock_details),
            6,
        )
        previous_department_qty = flt(
            sum(flt(detail.get("actual_qty")) for detail in previous_stock_details),
            6,
        )
        shortage_qty = flt(required_qty - current_department_qty, 6)
        mr_qty_before_existing = flt(shortage_qty + previous_department_qty, 6)
        previous_department_qty_rows = [
            {
                "department": detail.get("department"),
                "warehouse": detail.get("warehouse"),
                "qty": flt(detail.get("actual_qty"), 6),
            }
            for detail in previous_stock_details
        ]

        print(
            "PP MR current dept item qty:",
            "department:", current_department,
            "item_code:", item_code,
            "qty:", current_department_qty,
        )
        print(
            "PP MR previous dept names with qty:",
            "current_department:", current_department,
            "item_code:", item_code,
            "previous_departments:", previous_department_qty_rows,
        )
        print(
            "PP MR consumable compare:",
            "current_department:", current_department,
            "item_code:", item_code,
            "required_qty:", flt(required_qty, 6),
            "current_department_qty:", current_department_qty,
            "shortage_qty:", shortage_qty,
            "previous_department_qty:", previous_department_qty,
            "mr_qty_before_existing_adjustment:", mr_qty_before_existing,
        )

        if shortage_qty <= PP_MR_MIN_QTY:
            print(
                "PP MR no shortage after current department stock:",
                "current_department:", current_department,
                "item_code:", item_code,
                "required_qty:", flt(required_qty, 6),
                "current_department_qty:", current_department_qty,
            )
            continue

        if item_code in raised_item_codes:
            print(
                "PP MR skipped duplicate child department item:",
                "current_department:", current_department,
                "item_code:", item_code,
                "reason:", "item already raised for earlier child table department",
            )
            continue

        if mr_qty_before_existing > PP_MR_MIN_QTY:
            raised_item_codes.add(item_code)
            shortage_items.append({
                "current_department": current_department,
                "item_code": item_code,
                "qty": mr_qty_before_existing,
                "required_qty": flt(required_qty, 6),
                "current_department_qty": current_department_qty,
                "shortage_qty": shortage_qty,
                "previous_department_qty": previous_department_qty,
                "previous_department_qty_rows": previous_department_qty_rows,
                "item_template": ", ".join(sorted(item_templates_by_dept_item.get((current_department, item_code)) or [])),
                "schedule_days": schedule_days_by_dept_item.get(
                    (current_department, item_code),
                    [PP_MR_DEFAULT_SCHEDULE_DAYS],
                ),
                "fully_consumed_qty_departments": [current_department],
            })

    print("PP MR required consumable dept/item count:", len(required_qty_by_dept_item))
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
            AND mr.docstatus = 1
            AND mr.status NOT IN ('Stopped', 'Cancelled', 'Completed')
            AND mri.item_code IN %(item_codes)s
            AND IFNULL(mri.post_order_status, '') != 'Completed'
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
        adjusted_existing_qty = min(required_qty, existing_qty)
        existing_qty_by_item[item["item_code"]] = flt(existing_qty - adjusted_existing_qty, 6)

        print(
            "PP MR existing MR adjustment:",
            "type:", material_request_type,
            "item:", item["item_code"],
            "required:", required_qty,
            "existing_qty_available_before_row:", existing_qty,
            "existing_qty_used_for_row:", adjusted_existing_qty,
            "existing_qty_remaining_after_row:", existing_qty_by_item[item["item_code"]],
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

    shortage_items_by_department = defaultdict(list)
    for item in shortage_items:
        shortage_items_by_department[item.get("current_department") or "Unknown Department"].append(item)

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

    created_mrs = []
    for current_department, department_shortage_items in sorted(shortage_items_by_department.items()):
        mr = frappe.new_doc("Material Request")
        mr.material_request_type = "Material Issue"
        mr.purpose = "Purchase"
        mr.naming_series = "MREQ-.YYYY.-.MM.-"
        mr.title = f"Production Plan - {current_department} - {plan_name}"
        mr.company = _get_pp_default_company()
        mr.mr_mr_create_reference = plan_name
        mr.schedule_date = schedule_date
        mr.post_order_status = ""
        mr.fully_consumed_qty_departments = current_department
        print(
            "PP MR creating department-wise MR:",
            "department:", current_department,
            "item_count:", len(department_shortage_items),
            "fully_consumed_qty_departments:", mr.fully_consumed_qty_departments,
        )

        for item in department_shortage_items:
            print(
                "PP MR append item:",
                "department:", current_department,
                "item_code:", item["item_code"],
                "qty:", item["qty"],
                "required_qty:", item.get("required_qty"),
                "current_department_qty:", item.get("current_department_qty"),
                "shortage_qty:", item.get("shortage_qty"),
                "previous_department_qty:", item.get("previous_department_qty"),
                "previous_department_qty_rows:", item.get("previous_department_qty_rows"),
                "item_template:", item.get("item_template"),
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
        created_mrs.append(mr.name)
        print(
            "PP MR created:",
            mr.name,
            "department:",
            current_department,
            "items:",
            len(department_shortage_items),
        )

    if created_mrs:
        frappe.msgprint(
            _("Material Requests Created from Production Plan {0}: {1}").format(
                frappe.bold(plan_name),
                frappe.bold(", ".join(created_mrs)),
            )
        )

    return created_mrs



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
        AND IFNULL(mri.post_order_status, '') != 'Completed'
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

    excluded_stock_warehouses = sorted(
        frappe.get_all(
            "Warehouse",
            filters={"used_for_consumables_stock": 1},
            pluck="name",
        )
    )
    print("all purpose excluded consumables stock warehouses===============", excluded_stock_warehouses)

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
        {excluded_warehouse_condition}
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
    excluded_warehouse_condition = ""
    if excluded_stock_departments:
        excluded_department_condition = "AND w.department NOT IN %(excluded_stock_departments)s"
        stock_filters["excluded_stock_departments"] = tuple(excluded_stock_departments)
    if excluded_stock_warehouses:
        excluded_warehouse_condition = "AND b.warehouse NOT IN %(excluded_stock_warehouses)s"
        stock_filters["excluded_stock_warehouses"] = tuple(excluded_stock_warehouses)

    stock_data = frappe.db.sql(
        stock_query.format(
            excluded_department_condition=excluded_department_condition,
            excluded_warehouse_condition=excluded_warehouse_condition,
        ),
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


def _get_laptop_adaptor_previous_departments(item_wizard_data):
    previous_departments_by_wizard = {}
    all_previous_departments = set()

    for wizard_row in item_wizard_data:
        previous_departments = []
        seen_departments = set()
        for current_department in wizard_row.get("current_departments") or []:
            for previous_department in _get_pp_previous_two_department_names(current_department):
                if previous_department in seen_departments:
                    continue

                previous_departments.append(previous_department)
                seen_departments.add(previous_department)
                all_previous_departments.add(previous_department)

        previous_departments_by_wizard[wizard_row.get("item_wizard")] = previous_departments
        print(
            "PP MR laptop adaptor previous departments:",
            "item_wizard:", wizard_row.get("item_wizard"),
            "current_departments:", wizard_row.get("current_departments"),
            "previous_departments:", previous_departments,
        )

    return previous_departments_by_wizard, sorted(all_previous_departments)


def get_laptop_adaptor_previous_department_stock(item_wizard_data):
    _previous_departments_by_wizard, previous_departments = _get_laptop_adaptor_previous_departments(item_wizard_data)
    if not previous_departments:
        print("PP MR laptop adaptor previous department stock skipped: no previous departments")
        return []

    previous_department_grades = ("Grade A", "Grade B", "Grade D", "UNKNOWN")
    stock_data = frappe.db.sql("""
        SELECT
            b.item_code,
            i.item_name,
            i.item_group,
            i.disabled,
            i.end_of_life,
            iva.attribute_value AS grade,
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
        WHERE w.department IN %(previous_departments)s
            AND i.item_group = %(item_group)s
            AND iva.attribute = 'Grade'
            AND iva.attribute_value IN %(grades)s
            AND b.actual_qty > 0
        GROUP BY b.item_code, i.item_name, i.item_group, i.disabled, i.end_of_life, iva.attribute_value, b.warehouse, w.department
        ORDER BY w.department, b.item_code, iva.attribute_value
    """, {
        "previous_departments": tuple(previous_departments),
        "item_group": PP_MR_LAPTOP_ADAPTOR_ITEM_GROUP,
        "grades": previous_department_grades,
    }, as_dict=True, debug=1)

    print("PP MR laptop adaptor previous stock departments:", previous_departments)
    print("PP MR laptop adaptor previous stock grades:", previous_department_grades)
    for row in stock_data:
        print(
            "PP MR laptop adaptor previous department stock:",
            "department:", row.department,
            "warehouse:", row.warehouse,
            "item_code:", row.item_code,
            "grade:", row.grade,
            "stock_qty:", flt(row.stock_qty),
        )

    return stock_data


def _build_laptop_adaptor_shortage_items(item_wizard_data, department_stock, previous_department_stock=None):
    grade_a_items_by_key = _get_laptop_adaptor_grade_a_items()
    previous_departments_by_wizard, _all_previous_departments = _get_laptop_adaptor_previous_departments(item_wizard_data)

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

    previous_stock_details_by_key = defaultdict(list)
    for row in previous_department_stock or []:
        skip_reason = _get_laptop_adaptor_item_skip_reason(row.item_code, row)
        if skip_reason:
            print(
                "PP MR laptop adaptor skipped previous stock item:",
                "item_code:", row.item_code,
                "warehouse:", row.warehouse,
                "stock_qty:", flt(row.stock_qty),
                "reason:", skip_reason,
            )
            continue

        key = _get_laptop_adaptor_item_key_from_code(row.item_code)
        previous_stock_details_by_key[key].append({
            "department": row.department,
            "warehouse": row.warehouse,
            "stock_qty": flt(row.stock_qty),
            "item_code": row.item_code,
            "grade": row.get("grade"),
        })
        stock_item_by_key.setdefault(key, row.item_code)
        print(
            "PP MR laptop adaptor previous stock mapping:",
            "key:", key,
            "item_code:", row.item_code,
            "grade:", row.get("grade"),
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
        shortage_key = shortage_combination["key"]
        shortage_item_code = _get_laptop_adaptor_combination_item_code(
            shortage_combination,
            grade_a_items_by_key,
            stock_item_by_key,
        )
        previous_departments = set(previous_departments_by_wizard.get(wizard_row.get("item_wizard")) or [])
        previous_department_qty = 0
        previous_department_qty_rows = []
        for previous_stock_detail in previous_stock_details_by_key.get(shortage_key, []):
            if previous_stock_detail.get("department") not in previous_departments:
                continue

            previous_stock_qty = flt(previous_stock_detail.get("stock_qty"))
            if previous_stock_qty <= 0:
                continue

            previous_department_qty = flt(previous_department_qty + previous_stock_qty, 6)
            previous_department_qty_rows.append({
                "department": previous_stock_detail.get("department"),
                "warehouse": previous_stock_detail.get("warehouse"),
                "qty": flt(previous_stock_qty, 6),
            })
            previous_stock_detail["stock_qty"] = 0

        mr_qty_before_existing = flt(shortage_qty + previous_department_qty, 6)

        print(
            "PP MR laptop adaptor compare:",
            wizard_row.get("item_wizard"),
            "combination_count:", len(valid_combinations),
            "preferred_shortage_item:", shortage_item_code,
            "required:", required_qty,
            "stock_usage:", stock_usage,
            "shortage:", shortage_qty,
            "previous_department_names_with_qty:", previous_department_qty_rows,
            "previous_department_qty:", previous_department_qty,
            "mr_qty_before_existing_adjustment:", mr_qty_before_existing,
        )

        if mr_qty_before_existing > PP_MR_MIN_QTY:
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
            shortage_item["qty"] = flt(shortage_item["qty"] + mr_qty_before_existing, 6)
            shortage_item["serial_nos"].extend(shortage_serial_nos)
            shortage_item["mr_rised_departments"].update(stock_used_departments)
            shortage_item["mr_rised_departments"].update(
                row.get("department")
                for row in previous_department_qty_rows
                if row.get("department")
            )
            print(
                "PP MR laptop adaptor creatable MR item:",
                "item_wizard:", wizard_row.get("item_wizard"),
                "item_code:", shortage_item_code,
                "shortage_qty:", flt(shortage_qty, 6),
                "previous_department_qty:", previous_department_qty,
                "qty_to_raise:", flt(mr_qty_before_existing, 6),
                "serial_nos:", shortage_serial_nos,
                "previous_department_names_with_qty:", previous_department_qty_rows,
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
            AND d.department_sequence < (
                SELECT department_sequence
                FROM `tabDepartment`
                WHERE name = 'BG - Adaptor QC - NJ'           
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
    previous_department_stock = get_laptop_adaptor_previous_department_stock(laptop_adaptor_serial_nos)
    print("PP MR laptop adaptor previous department stock count:", len(previous_department_stock))

    shortage_items = _build_laptop_adaptor_shortage_items(
        laptop_adaptor_serial_nos,
        dp_stock,
        previous_department_stock,
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


def _get_pp_enabled_warehouse(warehouse):
    if not warehouse:
        return None

    cache = getattr(_get_pp_enabled_warehouse, "_cache", {})
    if warehouse in cache:
        return cache[warehouse]

    row = frappe.db.get_value(
        "Warehouse",
        warehouse,
        ["name", "disabled"],
        as_dict=True,
    )
    enabled_warehouse = row.name if row and not flt(row.disabled) else None
    if not enabled_warehouse:
        print("PP MR skipped disabled/missing warehouse:", warehouse)

    cache[warehouse] = enabled_warehouse
    _get_pp_enabled_warehouse._cache = cache
    return enabled_warehouse


def _get_first_pp_enabled_warehouse(*warehouses):
    for warehouse in warehouses:
        enabled_warehouse = _get_pp_enabled_warehouse(warehouse)
        if enabled_warehouse:
            return enabled_warehouse

    return None


def _add_all_purpose_shortage_item(shortage_by_item, item_code, qty, warehouse, source_item_code, material_issue_mrs, schedule_days, stock_warehouses=None):
    if flt(qty) <= PP_MR_MIN_QTY:
        return

    warehouse = _get_pp_enabled_warehouse(warehouse)
    stock_warehouses = {
        enabled_warehouse
        for enabled_warehouse in (
            _get_pp_enabled_warehouse(stock_warehouse)
            for stock_warehouse in (stock_warehouses or [])
        )
        if enabled_warehouse
    }

    item = shortage_by_item.setdefault(item_code, {
        "item_code": item_code,
        "qty": 0,
        "warehouse": warehouse,
        "source_item_codes": set(),
        "material_issue_mrs": set(),
        "schedule_days": [],
        "stock_warehouses": set(),
    })
    item["qty"] = flt(item["qty"] + qty, 6)
    if warehouse and not item.get("warehouse"):
        item["warehouse"] = warehouse
    if source_item_code:
        item["source_item_codes"].add(source_item_code)
    item["material_issue_mrs"].update(material_issue_mrs or [])
    item["schedule_days"].extend(schedule_days or [PP_MR_DEFAULT_SCHEDULE_DAYS])
    item["stock_warehouses"].update(stock_warehouses or [])


def _get_all_purpose_manufacture_serial_nos(item_code, warehouses, qty):
    serial_qty = int(flt(qty))
    if not item_code or not warehouses or serial_qty <= 0:
        return []

    serial_rows = frappe.db.sql("""
        SELECT sn.name
        FROM `tabSerial No` sn
        WHERE sn.item_code = %(item_code)s
        AND sn.warehouse IN %(warehouses)s
        AND (sn.status IS NULL OR sn.status NOT IN ('Delivered', 'Scrapped', 'Inactive'))
        ORDER BY sn.creation, sn.name
    """, {
        "item_code": item_code,
        "warehouses": tuple(sorted(set(warehouses))),
    }, as_dict=True)

    serial_nos = [row.name for row in serial_rows[:serial_qty]]
    print(
        "all purpose Manufacture MR selected serial nos:",
        "item_code:", item_code,
        "qty:", qty,
        "warehouses:", ", ".join(sorted(set(warehouses))),
        "serial_nos:", ", ".join(serial_nos),
        "serial_count:", len(serial_nos),
    )
    return serial_nos


def collect_all_purpose_material_issue(doc=None, method=None):

    
    print("collect_all_purpose_material_issue")

    restricted_adaptor_warehouses = _get_pp_nj_setting_csv_values("restricting_wh_for_laptop_adaptors")
    restricted_adaptor_warehouse_condition = ""
    stock_filters = {}
    if restricted_adaptor_warehouses:
        restricted_adaptor_warehouse_condition = """
        AND NOT (
            i.item_group = 'Laptop Adaptors'
            AND b.warehouse IN %(restricted_adaptor_warehouses)s
        )
        """
        stock_filters["restricted_adaptor_warehouses"] = tuple(restricted_adaptor_warehouses)

    print("all purpose restricted adaptor warehouses===============", restricted_adaptor_warehouses)

    stock_data = frappe.db.sql("""
        SELECT
            b.item_code,
            b.actual_qty,
            b.warehouse,
            i.item_group
        FROM `tabBin` b
        INNER JOIN `tabWarehouse` w
            ON w.name = b.warehouse
        INNER JOIN `tabItem` i
            ON i.name = b.item_code
        WHERE w.department IN (
            SELECT name
            FROM `tabDepartment`
        )
        AND IFNULL(w.disabled, 0) = 0
        AND i.item_group IN ('Laptop Adaptors', 'Laptop RAM', 'Laptop Storage')
        AND NOT (
            i.item_group = 'Laptop Adaptors'
            AND w.department = 'BG - Adaptor QC - NJ'
        )
        {restricted_adaptor_warehouse_condition}
        AND b.actual_qty > 0
        AND (
            b.item_code LIKE '%%GRADE A%%'
            OR b.item_code LIKE '%%GRADE D%%'
            OR (
                i.item_group = 'Laptop Adaptors'
                AND b.item_code LIKE '%%GRADE B%%'
            )
        )
    """.format(
        restricted_adaptor_warehouse_condition=restricted_adaptor_warehouse_condition,
    ), stock_filters, as_dict=True)

    print("stock_data===============", stock_data)

    material_issues = frappe.db.sql("""
        SELECT
            mri.parent,
            mri.item_code,
            mri.qty,
            mri.schedule_date,
            mri.warehouse,
            i.item_group,
            w.department AS source_department,
            w.disabled AS source_warehouse_disabled
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
        AND IFNULL(mri.post_order_status, '') != 'Completed'
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
    stock_warehouses_by_item = defaultdict(set)
    grade_a_stock_by_key = defaultdict(float)
    grade_b_stock_by_key = defaultdict(float)
    grade_d_stock_by_key = defaultdict(float)
    grade_b_item_by_key = {}
    grade_d_item_by_key = {}
    for row in stock_data:
        stock_qty_by_item[row.item_code] += flt(row.actual_qty)
        stock_warehouse_by_item.setdefault(row.item_code, row.warehouse)
        stock_warehouses_by_item[row.item_code].add(row.warehouse)
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
        if row.get("warehouse") and not flt(row.get("source_warehouse_disabled")):
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
                _get_first_pp_enabled_warehouse(
                    stock_warehouse_by_item.get(grade_d_item_code),
                    default_target_warehouse,
                ),
                item_code,
                issue_mr_names,
                schedule_days,
                stock_warehouses_by_item.get(grade_d_item_code),
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
                _get_first_pp_enabled_warehouse(
                    stock_warehouse_by_item.get(grade_b_item_code),
                    default_target_warehouse,
                ),
                item_code,
                issue_mr_names,
                schedule_days,
                stock_warehouses_by_item.get(grade_b_item_code),
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
                _get_first_pp_enabled_warehouse(
                    stock_warehouse_by_item.get(item_code),
                    issue_warehouse_by_item.get(item_code),
                    default_target_warehouse,
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
            if material_request_type == "Manufacture":
                serial_nos = _get_all_purpose_manufacture_serial_nos(
                    item["item_code"],
                    item.get("stock_warehouses"),
                    item_row["qty"],
                )
                item_row["mavni_comments"] = ", ".join(serial_nos)
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


@frappe.whitelist()
def nj_clear_stale_reservations():
    """Clear stale reserved_sales_order on Serial Nos linked to Closed/Cancelled/Completed/Refunded Sales Orders."""
    stale_serials = frappe.db.sql_list("""
        SELECT sn.name
        FROM `tabSerial No` sn
        INNER JOIN `tabSales Order` so ON so.name = sn.reserved_sales_order
        LEFT JOIN `tabNJ Refund` njr ON njr.sales_order = so.name AND njr.refund_status IN ('Paid', 'Refunded', 'Initiated', 'Debit Failed', 'Returned') AND njr.docstatus = 1
        WHERE (so.status IN ('Closed', 'Cancelled', 'Completed') OR njr.name IS NOT NULL)
          AND sn.reserved_sales_order IS NOT NULL
          AND sn.reserved_sales_order != ''
    """)
    if stale_serials:
        frappe.db.sql("""
            UPDATE `tabSerial No`
            SET reserved_sales_order = NULL,
                remarks = NULL
            WHERE name IN %(serials)s
        """, {"serials": tuple(stale_serials)})
        frappe.db.commit()
    print(f"Stale cleared count: {len(stale_serials)}")
    return len(stale_serials)


@frappe.whitelist()
def nj_check_stale_reservations():
    """Check for remaining stale reserved_sales_order on Serial Nos."""
    results = frappe.db.sql("""
        select sn.name, sn.reserved_sales_order, so.status, njr.refund_status 
        from `tabSerial No` sn 
        inner join `tabSales Order` so on sn.reserved_sales_order = so.name  
        left join `tabNJ Refund` njr on njr.sales_order = so.name and njr.refund_status in ('Paid', 'Refunded', 'Initiated', 'Debit Failed', 'Returned') and njr.docstatus = 1
        where (so.status in ('Closed', 'Cancelled', 'Completed') or njr.name is not null)
          and sn.reserved_sales_order is not null
          and sn.reserved_sales_order != ''
    """, as_dict=True)
    print("STALE RESERVATIONS REMAINING:", results)
    return results


@frappe.whitelist()
def nj_inspect_so_allocations(so_name):
    """Inspect items and serial reservations for a specific Sales Order."""
    so_items = frappe.db.sql("""
        select item_code, qty from `tabSales Order Item` where parent = %s
    """, (so_name,), as_dict=True)

    serials = frappe.db.sql("""
        select name, item_code, status, warehouse from `tabSerial No` where reserved_sales_order = %s
    """, (so_name,), as_dict=True)

    return {
        "so_items": so_items,
        "serials": serials
    }


@frappe.whitelist()
def nj_clear_mismatching_reservations():
    """Find and clear serial reservations where the Serial No's item code 
    does not match any item or bundle component in the reserved Sales Order."""
    reservations = frappe.db.sql("""
        SELECT name, item_code, reserved_sales_order 
        FROM `tabSerial No` 
        WHERE reserved_sales_order IS NOT NULL 
          AND reserved_sales_order != ''
    """, as_dict=True)

    cleared_count = 0
    cleared_details = []

    for r in reservations:
        sn_name = r["name"]
        sn_item = r["item_code"]
        so_name = r["reserved_sales_order"]

        so_exists = frappe.db.exists("Sales Order", so_name)
        if not so_exists:
            frappe.db.set_value("Serial No", sn_name, "reserved_sales_order", None)
            cleared_count += 1
            cleared_details.append(f"{sn_name}: SO {so_name} does not exist")
            continue

        direct_match = frappe.db.exists("Sales Order Item", {"parent": so_name, "item_code": sn_item})
        if direct_match:
            continue

        bundle_match = frappe.db.sql("""
            SELECT 1 
            FROM `tabSales Order Item` soi
            INNER JOIN `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code
            INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
            WHERE soi.parent = %s AND pbi.item_code = %s
            LIMIT 1
        """, (so_name, sn_item))

        if bundle_match:
            continue

        # If we got here, it's a mismatch!
        frappe.db.set_value("Serial No", sn_name, "reserved_sales_order", None)
        cleared_count += 1
        cleared_details.append(f"{sn_name} ({sn_item}): Mismatch for SO {so_name}")

    frappe.db.commit()
    print(f"Cleared {cleared_count} mismatching reservations.")
    for detail in cleared_details:
        print(" -", detail)
    
    return cleared_details


@frappe.whitelist()
def nj_trim_over_allocations():
    """Run the trim_over_allocated_serials safety net from sales_order.py."""
    from nj_features.overrides.sales_order import trim_over_allocated_serials
    trim_over_allocated_serials()
    print("Done.")


@frappe.whitelist()
def nj_check_over_allocations():
    """Check ALL Sales Orders system-wide for over-allocation."""
    results = frappe.db.sql("""
        SELECT
            res.reserved_sales_order AS so_name,
            res.item_code,
            res.reserved_count,
            IFNULL(soi_data.so_qty, 0) AS so_qty,
            IFNULL(dn_data.dn_qty, 0) AS dn_qty,
            GREATEST(0, CASE WHEN so.name IS NULL OR so.status IN ('Closed', 'Cancelled', 'Completed') THEN 0 ELSE IFNULL(soi_data.so_qty, 0) - IFNULL(dn_data.dn_qty, 0) END) AS net_pending,
            (res.reserved_count - GREATEST(0, CASE WHEN so.name IS NULL OR so.status IN ('Closed', 'Cancelled', 'Completed') THEN 0 ELSE IFNULL(soi_data.so_qty, 0) - IFNULL(dn_data.dn_qty, 0) END)) AS excess
        FROM (
            SELECT sn.reserved_sales_order,
                COALESCE(NULLIF(sn.to_make, ''), sn.item_code) AS item_code,
                COUNT(*) AS reserved_count
            FROM `tabSerial No` sn
            -- Location-blind: see sales_order.adjust_serial_allocations().
            WHERE sn.reserved_sales_order IS NOT NULL AND sn.reserved_sales_order != '' AND sn.status = 'Active'
            GROUP BY sn.reserved_sales_order, COALESCE(NULLIF(sn.to_make, ''), sn.item_code)
        ) res
        LEFT JOIN `tabSales Order` so ON so.name = res.reserved_sales_order
        LEFT JOIN (
            SELECT soi.parent AS sales_order,
                CASE WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code ELSE pbi.item_code END AS item_code,
                SUM(CASE WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.qty ELSE IFNULL(pbi.qty, 0) * soi.qty END) AS so_qty
            FROM `tabSales Order Item` soi
            INNER JOIN `tabSales Order` so ON so.name = soi.parent
            INNER JOIN `tabItem` it_so ON it_so.name = soi.item_code
            LEFT JOIN `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code AND IFNULL(it_so.is_stock_item, 0) = 0
            LEFT JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
            WHERE so.docstatus = 1
            GROUP BY soi.parent, CASE WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code ELSE pbi.item_code END
        ) soi_data ON soi_data.sales_order = res.reserved_sales_order AND soi_data.item_code = res.item_code
        LEFT JOIN (
            SELECT 
                dni.against_sales_order AS sales_order, 
                CASE 
                    WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                    ELSE pbi.item_code
                END AS item_code,
                SUM(
                    CASE
                        WHEN IFNULL(dn.is_return, 0) = 0 THEN dni.qty
                        WHEN dn.is_return = 1 AND dn.cause_of_return IN ('Repair', 'Replace') THEN dni.qty
                        ELSE 0
                    END
                ) AS dn_qty
            FROM `tabDelivery Note Item` dni 
            INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            INNER JOIN `tabSales Order Item` soi ON dni.so_detail = soi.name
            INNER JOIN `tabItem` it_so ON it_so.name = soi.item_code
            LEFT JOIN `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code
                AND IFNULL(it_so.is_stock_item, 0) = 0
            LEFT JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
            WHERE dni.docstatus = 1
            GROUP BY dni.against_sales_order, 
                CASE 
                    WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                    ELSE pbi.item_code
                END
        ) dn_data ON dn_data.sales_order = res.reserved_sales_order AND dn_data.item_code = res.item_code
        HAVING reserved_count > net_pending
        ORDER BY excess DESC
    """, as_dict=True)

    if results:
        print(f"OVER-ALLOCATED SOs FOUND: {len(results)}")
        for r in results:
            print(f"  SO: {r['so_name']} | Item: {r['item_code'][:50]} | Reserved: {int(r['reserved_count'])} | Net Pending: {int(r['net_pending'])} | EXCESS: {int(r['excess'])}")
    else:
        print("✅ NO over-allocated SOs found. All clean!")

    return results


@frappe.whitelist()
def nj_check_over_allocations_fast():
    """Rapid check for over-allocated SOs, focusing only on active reserved SOs."""
    active_reserved_sos = frappe.db.sql_list("""
        SELECT DISTINCT reserved_sales_order 
        FROM `tabSerial No` 
        WHERE reserved_sales_order IS NOT NULL 
          AND reserved_sales_order != ''
          AND status = 'Active'
    """)
    if not active_reserved_sos:
        print("✅ NO active reservations found in the system.")
        return []

    so_list_str = ", ".join(f"'{so}'" for so in active_reserved_sos)

    results = frappe.db.sql(f"""
        SELECT
            res.reserved_sales_order AS so_name,
            res.item_code,
            res.reserved_count,
            IFNULL(soi_data.so_qty, 0) AS so_qty,
            IFNULL(dn_data.dn_qty, 0) AS dn_qty,
            GREATEST(0, CASE WHEN so.name IS NULL OR so.status IN ('Closed', 'Cancelled', 'Completed') THEN 0 ELSE IFNULL(soi_data.so_qty, 0) - IFNULL(dn_data.dn_qty, 0) END) AS net_pending,
            (res.reserved_count - GREATEST(0, CASE WHEN so.name IS NULL OR so.status IN ('Closed', 'Cancelled', 'Completed') THEN 0 ELSE IFNULL(soi_data.so_qty, 0) - IFNULL(dn_data.dn_qty, 0) END)) AS excess
        FROM (
            SELECT sn.reserved_sales_order,
                COALESCE(NULLIF(sn.to_make, ''), sn.item_code) AS item_code,
                COUNT(*) AS reserved_count
            FROM `tabSerial No` sn
            -- Location-blind: see sales_order.adjust_serial_allocations().
            WHERE sn.reserved_sales_order IN ({so_list_str}) AND sn.status = 'Active'
            GROUP BY sn.reserved_sales_order, COALESCE(NULLIF(sn.to_make, ''), sn.item_code)
        ) res
        LEFT JOIN `tabSales Order` so ON so.name = res.reserved_sales_order
        LEFT JOIN (
            SELECT soi.parent AS sales_order,
                CASE WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code ELSE pbi.item_code END AS item_code,
                SUM(CASE WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.qty ELSE IFNULL(pbi.qty, 0) * soi.qty END) AS so_qty
            FROM `tabSales Order Item` soi
            INNER JOIN `tabSales Order` so ON so.name = soi.parent
            INNER JOIN `tabItem` it_so ON it_so.name = soi.item_code
            LEFT JOIN `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code AND IFNULL(it_so.is_stock_item, 0) = 0
            LEFT JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
            WHERE so.name IN ({so_list_str})
            GROUP BY soi.parent, CASE WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code ELSE pbi.item_code END
        ) soi_data ON soi_data.sales_order = res.reserved_sales_order AND soi_data.item_code = res.item_code
        LEFT JOIN (
            SELECT 
                dni.against_sales_order AS sales_order, 
                CASE 
                    WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                    ELSE pbi.item_code
                END AS item_code,
                SUM(
                    CASE
                        WHEN IFNULL(dn.is_return, 0) = 0 THEN dni.qty
                        WHEN dn.is_return = 1 AND dn.cause_of_return IN ('Repair', 'Replace') THEN dni.qty
                        ELSE 0
                    END
                ) AS dn_qty
            FROM `tabDelivery Note Item` dni 
            INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            INNER JOIN `tabSales Order Item` soi ON dni.so_detail = soi.name
            INNER JOIN `tabItem` it_so ON it_so.name = soi.item_code
            LEFT JOIN `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code
                AND IFNULL(it_so.is_stock_item, 0) = 0
            LEFT JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
            WHERE dni.docstatus = 1 AND dni.against_sales_order IN ({so_list_str})
            GROUP BY dni.against_sales_order, 
                CASE 
                    WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                    ELSE pbi.item_code
                END
        ) dn_data ON dn_data.sales_order = res.reserved_sales_order AND dn_data.item_code = res.item_code
        HAVING reserved_count > net_pending
        ORDER BY excess DESC
    """, as_dict=True)

    if results:
        print(f"OVER-ALLOCATED SOs FOUND: {len(results)}")
        for r in results:
            print(f"  SO: {r['so_name']} | Item: {r['item_code'][:50]} | Reserved: {int(r['reserved_count'])} | Net Pending: {int(r['net_pending'])} | EXCESS: {int(r['excess'])}")
    else:
        print("✅ NO over-allocated SOs found. All clean!")

    return results


@frappe.whitelist()
def nj_detailed_allocation_audit():
    """Perform a detailed audit of allocations for all active reserved Sales Orders."""
    active_reserved_sos = frappe.db.sql_list("""
        SELECT DISTINCT reserved_sales_order 
        FROM `tabSerial No` 
        WHERE reserved_sales_order IS NOT NULL 
          AND reserved_sales_order != ''
          AND status = 'Active'
    """)
    if not active_reserved_sos:
        print("✅ No active reservations in the system.")
        return []

    so_list_str = ", ".join(f"'{so}'" for so in active_reserved_sos)

    # Fetch SO items
    so_items = frappe.db.sql(f"""
        SELECT 
            soi.parent AS so_name,
            CASE WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code ELSE pbi.item_code END AS item_code,
            SUM(CASE WHEN so.status IN ('Closed', 'Cancelled', 'Completed') THEN 0
                     WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.qty 
                     ELSE IFNULL(pbi.qty, 0) * soi.qty 
                END) AS so_qty
        FROM `tabSales Order Item` soi
        INNER JOIN `tabSales Order` so ON so.name = soi.parent
        INNER JOIN `tabItem` it_so ON it_so.name = soi.item_code
        LEFT JOIN `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code AND IFNULL(it_so.is_stock_item, 0) = 0
        LEFT JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
        WHERE so.name IN ({so_list_str})
        GROUP BY soi.parent, CASE WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code ELSE pbi.item_code END
    """, as_dict=True)

    # Fetch DN deliveries
    dn_items = frappe.db.sql(f"""
        SELECT 
            dni.against_sales_order AS so_name, 
            CASE 
                WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                ELSE pbi.item_code
            END AS item_code,
            SUM(
                CASE
                    WHEN IFNULL(dn.is_return, 0) = 0 THEN dni.qty
                    WHEN dn.is_return = 1 AND dn.cause_of_return IN ('Repair', 'Replace') THEN dni.qty
                    ELSE 0
                END
            ) AS dn_qty
        FROM `tabDelivery Note Item` dni 
        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        INNER JOIN `tabSales Order Item` soi ON dni.so_detail = soi.name
        INNER JOIN `tabItem` it_so ON it_so.name = soi.item_code
        LEFT JOIN `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code
            AND IFNULL(it_so.is_stock_item, 0) = 0
        LEFT JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
        WHERE dni.docstatus = 1 AND dni.against_sales_order IN ({so_list_str})
        GROUP BY dni.against_sales_order, 
            CASE 
                WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                ELSE pbi.item_code
            END
    """, as_dict=True)

    # Fetch Serial Reservations (including to_make)
    serial_reservations = frappe.db.sql(f"""
        SELECT 
            sn.reserved_sales_order AS so_name,
            COALESCE(NULLIF(sn.to_make, ''), sn.item_code) AS item_code,
            COUNT(*) AS reserved_count
        FROM `tabSerial No` sn
        -- Location-blind: see sales_order.adjust_serial_allocations().
        WHERE sn.reserved_sales_order IN ({so_list_str}) AND sn.status = 'Active'
        GROUP BY sn.reserved_sales_order, COALESCE(NULLIF(sn.to_make, ''), sn.item_code)
    """, as_dict=True)

    # Map the results
    so_map = {}
    for item in so_items:
        so_map.setdefault(item["so_name"], {})[item["item_code"]] = {
            "so_qty": float(item["so_qty"]),
            "dn_qty": 0.0,
            "reserved_count": 0
        }

    for item in dn_items:
        if item["so_name"] in so_map and item["item_code"] in so_map[item["so_name"]]:
            so_map[item["so_name"]][item["item_code"]]["dn_qty"] = float(item["dn_qty"])

    for item in serial_reservations:
        if item["so_name"] in so_map and item["item_code"] in so_map[item["so_name"]]:
            so_map[item["so_name"]][item["item_code"]]["reserved_count"] = int(item["reserved_count"])
        else:
            # Reservation for an item that is NOT in the SO (mismatch)
            so_map.setdefault(item["so_name"], {}).setdefault(item["item_code"], {
                "so_qty": 0.0,
                "dn_qty": 0.0,
                "reserved_count": int(item["reserved_count"])
            })

    # Generate audit report
    print(f"\n========================================================")
    print(f"📊 SYSTEM-WIDE ALLOCATION AUDIT REPORT (ACTIVE SOs)")
    print(f"========================================================")
    
    total_sos = len(so_map)
    clean_sos = 0
    mismatches_count = 0
    over_allocated_count = 0
    under_allocated_count = 0

    for so_name, items in sorted(so_map.items()):
        so_is_clean = True
        so_summary_lines = []
        
        for item_code, data in items.items():
            net_pending = max(0.0, data["so_qty"] - data["dn_qty"])
            res_count = data["reserved_count"]
            diff = res_count - net_pending

            status_str = "OK"
            if data["so_qty"] == 0.0 and res_count > 0:
                status_str = "❌ MISMATCH (Item not in SO)"
                so_is_clean = False
                mismatches_count += 1
            elif diff > 0:
                status_str = f"⚠️ OVER-ALLOCATED (Excess: +{int(diff)})"
                so_is_clean = False
                over_allocated_count += 1
            elif diff < 0:
                status_str = f"ℹ️ Under-allocated (Pending: {int(abs(diff))} more needed)"
                under_allocated_count += 1
                so_is_clean = False

            item_str = str(item_code or '')
            so_summary_lines.append(
                f"    - Item: {item_str[:45]:<45} | Net Pending: {int(net_pending):<3} | Reserved: {res_count:<3} | {status_str}"
            )

        if so_is_clean:
            clean_sos += 1
            print(f"✅ {so_name}: Fully & Correctly Allocated")
        else:
            print(f"🔍 {so_name}: Action Required")
            for line in so_summary_lines:
                print(line)

    print(f"\n========================================================")
    print(f"AUDIT SUMMARY:")
    print(f"  Total Active Reserved SOs: {total_sos}")
    print(f"  Perfect / Correctly Allocated SOs: {clean_sos}")
    print(f"  Mismatching Reservations (Item not in SO): {mismatches_count}")
    print(f"  Over-allocated Items: {over_allocated_count}")
    print(f"  Under-allocated Items (still waiting for stock): {under_allocated_count}")
    print(f"========================================================\n")

    return so_map


# ===============================================================
# Laptop Storage MR section From Store Dept TO Packing & Dispatch
# ===============================================================



PP_MR_LAPTOP_STORAGE_BG_LOCATION = "BG"
PP_MR_LAPTOP_STORAGE_STORE_TO_PACKING_ITEM_GROUP_SETTING = (
    "store_to_packing_and_dispatch_serial_no_item_group"
)
PP_MR_LAPTOP_STORAGE_STORE_TO_PACKING_STOCK_DEPARTMENTS = (
    "Stores - NJ",
    "BG - Grade A Line - NJ",
)


def get_laptop_storage_diff_serials_store_to_packing():
    print("Laptop Storage Store-to-Packing serial fetch started")
    allowed_item_groups = _get_pp_nj_setting_csv_values(
        PP_MR_LAPTOP_STORAGE_STORE_TO_PACKING_ITEM_GROUP_SETTING
    )
    print(
        "Laptop Storage Store-to-Packing serial filters:",
        "from_department:", "Stores - NJ",
        "to_department:", "Packing & Dispatch - NJ",
        "warehouse_location:", PP_MR_LAPTOP_STORAGE_BG_LOCATION,
        "serial_status:", "Active",
        "allowed_item_groups:", allowed_item_groups,
        "condition:", "item_code != to_make",
    )
    if not allowed_item_groups:
        print(
            "Laptop Storage Store-to-Packing serial fetch skipped:",
            "NJ Settings item groups not configured for parameter:",
            PP_MR_LAPTOP_STORAGE_STORE_TO_PACKING_ITEM_GROUP_SETTING,
        )
        return []

    serial_rows = frappe.db.sql("""
        SELECT
            sn.name AS serial_no,
            sn.item_code,
            sn.to_make,
            sn.item_wizard,
            w.name AS warehouse,
            w.department AS current_department,
            d.name AS current_department_name,
            d.department_sequence AS current_department_sequence
        FROM `tabSerial No` AS sn
        INNER JOIN `tabItem` AS i
            ON i.name = sn.item_code
        INNER JOIN `tabWarehouse` AS w
            ON w.name = sn.warehouse
        INNER JOIN `tabDepartment` AS d
            ON d.name = w.department
        WHERE d.department_sequence BETWEEN
            (SELECT department_sequence FROM `tabDepartment` WHERE name = 'Stores - NJ')
            AND
            (SELECT department_sequence FROM `tabDepartment` WHERE name = 'Packing & Dispatch - NJ')
            AND w.location = %(location)s
            AND sn.status = 'Active'
            AND i.item_group IN %(allowed_item_groups)s
            AND IFNULL(sn.item_code, '') != ''
            AND IFNULL(sn.to_make, '') != ''
            AND sn.item_code != sn.to_make
        ORDER BY d.department_sequence, d.name, w.name, sn.name
    """, {
        "location": PP_MR_LAPTOP_STORAGE_BG_LOCATION,
        "allowed_item_groups": tuple(allowed_item_groups),
    }, as_dict=True)

    serial_count_by_department = Counter(
        row.current_department for row in serial_rows if row.current_department
    )
    serial_count_by_warehouse = Counter(
        row.warehouse for row in serial_rows if row.warehouse
    )
    print("Laptop Storage Store-to-Packing diff serial count:", len(serial_rows))
    print(
        "Laptop Storage Store-to-Packing serial count by department:",
        dict(serial_count_by_department),
    )
    print(
        "Laptop Storage Store-to-Packing serial count by warehouse:",
        dict(serial_count_by_warehouse),
    )
    for row in serial_rows:
        print(
            "Laptop Storage Store-to-Packing diff serial:",
            "serial_no:", row.serial_no,
            "current_item_code:", row.item_code,
            "to_make:", row.to_make,
            "item_wizard:", row.item_wizard,
            "warehouse:", row.warehouse,
            "warehouse_location:", PP_MR_LAPTOP_STORAGE_BG_LOCATION,
            "current_department:", row.current_department,
            "current_department_sequence:", row.current_department_sequence,
        )

    return serial_rows


def get_laptop_storage_stock_store_to_packing():
    print(
        "Laptop Storage Store-to-Packing stock fetch started:",
        "departments:", PP_MR_LAPTOP_STORAGE_STORE_TO_PACKING_STOCK_DEPARTMENTS,
    )
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
        WHERE w.department IN %(stock_departments)s
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
        ORDER BY b.item_code, w.department, b.warehouse
    """, {
        "stock_departments": PP_MR_LAPTOP_STORAGE_STORE_TO_PACKING_STOCK_DEPARTMENTS,
        "item_group": PP_MR_LAPTOP_STORAGE_ITEM_GROUP,
        "grade": PP_MR_LAPTOP_STORAGE_GRADE,
    }, as_dict=True)

    stock_qty_by_department = defaultdict(float)
    stock_qty_by_item = defaultdict(float)
    for row in stock_rows:
        stock_qty_by_department[row.department] += flt(row.stock_qty)
        stock_qty_by_item[row.item_code] += flt(row.stock_qty)

    print("Laptop Storage Store-to-Packing stock row count:", len(stock_rows))
    print(
        "Laptop Storage Store-to-Packing stock qty by department:",
        dict(stock_qty_by_department),
    )
    print(
        "Laptop Storage Store-to-Packing stock qty by item:",
        dict(stock_qty_by_item),
    )
    for row in stock_rows:
        print(
            "Laptop Storage Store-to-Packing stock row:",
            "item_code:", row.item_code,
            "stock_qty:", flt(row.stock_qty),
            "warehouse:", row.warehouse,
            "department:", row.department,
        )

    return stock_rows


def laptop_storage_mr_store_to_packing(doc=None, method=None):
    print("laptop_storage_mr_store_to_packing=======")
    print(
        "Laptop Storage Store-to-Packing configuration:",
        "demand_department_range:", "Stores - NJ -> Packing & Dispatch - NJ",
        "demand_warehouse_location:", PP_MR_LAPTOP_STORAGE_BG_LOCATION,
        "stock_departments:", PP_MR_LAPTOP_STORAGE_STORE_TO_PACKING_STOCK_DEPARTMENTS,
        "material_request_type:", "Material Issue",
    )

    diff_item_serials = get_laptop_storage_diff_serials_store_to_packing()
    print("Laptop Storage Store-to-Packing diff item rows returned:", len(diff_item_serials))

    diff_storage_serials = get_only_storage_diff_item_codes(diff_item_serials)
    print("Laptop Storage Store-to-Packing filtered Storage diff rows returned:", len(diff_storage_serials))
    print(
        "Laptop Storage Store-to-Packing filtered Storage serials:",
        [
            {
                "serial_no": row.get("serial_no"),
                "item_code": row.get("item_code"),
                "to_make": row.get("to_make"),
                "required_storage_capacity": row.get("required_storage_capacity"),
                "department": row.get("current_department"),
                "warehouse": row.get("warehouse"),
            }
            for row in diff_storage_serials
        ],
    )

    storage_stock_rows = get_laptop_storage_stock_store_to_packing()
    print("Laptop Storage Store-to-Packing stock rows returned:", len(storage_stock_rows))

    storage_wizard_combinations = build_laptop_storage_wizard_combinations(
        diff_storage_serials,
        storage_stock_rows,
    )
    print("Laptop Storage Store-to-Packing wizard combinations returned:", len(storage_wizard_combinations))

    storage_shortage_items = build_laptop_storage_shortage_items(
        diff_storage_serials,
        storage_wizard_combinations,
    )
    print("Laptop Storage Store-to-Packing shortage items returned:", len(storage_shortage_items))
    print(
        "Laptop Storage Store-to-Packing final shortage items:",
        storage_shortage_items,
    )

    laptop_storage_mr = create_laptop_storage_material_issue_mr(
        "Store To Packing - BG",
        storage_shortage_items,
    )
    print("Laptop Storage Store-to-Packing MR created name:", laptop_storage_mr)
    print(
        "Laptop Storage Store-to-Packing completed:",
        "eligible_diff_serial_count:", len(diff_item_serials),
        "storage_diff_serial_count:", len(diff_storage_serials),
        "stock_row_count:", len(storage_stock_rows),
        "shortage_item_count:", len(storage_shortage_items),
        "material_request:", laptop_storage_mr or "Not Created",
    )

    return {
        "diff_storage_serials": diff_storage_serials,
        "storage_stock_rows": storage_stock_rows,
        "storage_wizard_combinations": storage_wizard_combinations,
        "storage_shortage_items": storage_shortage_items,
        "laptop_storage_mr": laptop_storage_mr,
    }
