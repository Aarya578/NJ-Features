import math

import frappe
from frappe.model.document import Document
from erpnext.selling.doctype.quotation.quotation import Quotation
from frappe.model.mapper import get_mapped_doc
from frappe.utils import nowdate, getdate
from datetime import date

# Quotation ETA uses the SAME matching rules as the NJ Inventory Sync ETD
# (updting_sla_department in so_quantity_check.py), so a quote and the
# Shopify listing tell the customer the same thing:
#   1. Exact item code               -> department SLA
#   2. Same Shopify variant           -> department SLA + reconfig days
#   3. Same model + processor         -> department SLA + reconfig days
#   4. Same base model (variant_of)   -> department SLA + reconfig days
# The fastest match wins. Before 2026-10-14 the quote matched the exact
# item code only, so a variant with no finished stock (e.g. 16 GB / 1 TB
# while 16 GB / 512 GB sat in Packing) fell straight to 45 days.
#
# One difference from the sync: the sync ETD is the single most advanced
# unit, but a quote can be for 10+ units. Here a match only counts if it
# holds the FULL quoted qty, and the ETA is the slowest unit needed to
# reach that qty. Lines on the same quote never count the same serial
# twice.
#
# Nothing here reserves serials - a Quotation must never lock inventory.
#
# add_working_days() is imported from Sales Order: skips Sundays AND
# company holidays (Holiday List).
from nj_features.overrides.sales_order import add_working_days, RECONFIG_SLA_DAYS

# Worst-case fallback (days) when no match holds the full quoted qty
# (zero stock, or a partial shortfall) - realistic procurement lead time.
NO_STOCK_FALLBACK_DAYS = 45

# Extra days for a non-exact match (RAM/SSD swap). One shared constant
# with Sales Order and the Shopify ETD (6 days since 2026-10-14).
RECONFIG_EXTRA_DAYS = RECONFIG_SLA_DAYS

MIN_PIPELINE_SEQ = 1


def _get_pipeline_departments():
    """Pipeline departments with the sync's SLA overrides applied."""
    depts = frappe.db.sql("""
        SELECT name, department_sequence, department_sla, sla_item_groups
        FROM `tabDepartment`
        WHERE department_sequence >= %s
        ORDER BY department_sequence ASC
    """, (MIN_PIPELINE_SEQ,), as_dict=True)

    # Same overrides as the sync: Packing & Dispatch = 1, Sales = 1,
    # Inward = 1, everything else clamped to 0-15.
    for d in depts:
        d_name = (d.get("name") or "").lower()
        if "packing & dispatch" in d_name or "sales" in d_name or "inward" in d_name:
            d["department_sla"] = 1
        else:
            d["department_sla"] = min(max(int(d.get("department_sla") or 0), 0), 15)
    return depts


def _is_sla_dept_applicable(dept_row, item_grp):
    """Copy of the sync's is_dept_applicable()."""
    dept_name = str(dept_row.get("name") or "").lower()
    if "packing & dispatch" in dept_name or "sales" in dept_name:
        return True
    if not item_grp:
        return False
    groups_str = str(dept_row.get("sla_item_groups") or "").strip()
    if not groups_str or groups_str.lower() in ("none", "null"):
        return False
    allowed = [g.strip().lower() for g in groups_str.split(",") if g.strip()]
    return item_grp.strip().lower() in allowed


def _total_sla_from(dept_name, dept_seq, depts, item_grp):
    """Copy of the sync's calculate_total_sla(): days for a unit sitting in
    dept_name to reach dispatch (its own SLA + every later department,
    +10%, capped at 45)."""
    d_name_lower = (dept_name or "").lower()
    if "packing & dispatch" in d_name_lower or "sales" in d_name_lower:
        return 1

    cand_sla = 0
    for d in depts:
        if d.get("name") == dept_name:
            cand_sla = d.get("department_sla", 0)
            break

    seq_max_sla = {}
    for d in depts:
        if not _is_sla_dept_applicable(d, item_grp):
            continue
        if "inward" in (d.get("name") or "").lower():
            continue
        seq = d.get("department_sequence")
        sla = d.get("department_sla") or 0
        if seq not in seq_max_sla or sla > seq_max_sla[seq]:
            seq_max_sla[seq] = sla

    max_seq = max(seq_max_sla.keys()) if seq_max_sla else MIN_PIPELINE_SEQ

    total = cand_sla
    for s in range(dept_seq + 1, max_seq + 1):
        if s in seq_max_sla:
            total += seq_max_sla[s]
    return min(math.ceil(total * 1.10), 45)


def _get_match_tiers(item_code):
    """[(label, extra_days, [item_codes])] in the sync's priority order."""
    tiers = [("exact item", 0, [item_code])]

    variant_ids = frappe.db.sql_list("""
        SELECT DISTINCT pb.shopify_variant_id
        FROM `tabProduct Bundle Item` pbi
        INNER JOIN `tabProduct Bundle` pb ON pb.name = pbi.parent
        WHERE pbi.item_code = %s
          AND pb.shopify_variant_id IS NOT NULL AND pb.shopify_variant_id != ''
          AND COALESCE(pb.disable, 0) = 0
    """, (item_code,))
    if variant_ids:
        placeholders = ", ".join(["%s"] * len(variant_ids))
        codes = frappe.db.sql_list(f"""
            SELECT DISTINCT pbi.item_code
            FROM `tabProduct Bundle Item` pbi
            INNER JOIN `tabProduct Bundle` pb ON pb.name = pbi.parent
            WHERE pb.shopify_variant_id IN ({placeholders})
              AND COALESCE(pb.disable, 0) = 0
        """, variant_ids)
        tiers.append(("same Shopify variant", RECONFIG_EXTRA_DAYS, codes))

    variant_of = frappe.db.get_value("Item", item_code, "variant_of")
    if variant_of:
        processor = frappe.db.get_value(
            "Item Variant Attribute",
            {"parent": item_code, "attribute": "Processor Type1"},
            "attribute_value",
        ) or ""
        proc_codes = frappe.db.sql_list("""
            SELECT i.name
            FROM `tabItem` i
            LEFT JOIN `tabItem Variant Attribute` proc
                ON proc.parent = i.name AND proc.attribute = 'Processor Type1'
            WHERE i.variant_of = %s
              AND COALESCE(proc.attribute_value, '') = %s
        """, (variant_of, processor))
        tiers.append(("same model + processor", RECONFIG_EXTRA_DAYS, proc_codes))

        model_codes = frappe.db.sql_list(
            "SELECT name FROM `tabItem` WHERE variant_of = %s", (variant_of,)
        )
        tiers.append(("same model", RECONFIG_EXTRA_DAYS, model_codes))

    return [t for t in tiers if t[2]]


def _get_free_serials(item_codes):
    """Unreserved serials in pipeline departments - same filters as the sync."""
    placeholders = ", ".join(["%s"] * len(item_codes))
    return frappe.db.sql(f"""
        SELECT s.name, d.name AS dept_name, d.department_sequence AS dept_seq
        FROM `tabSerial No` s
        INNER JOIN `tabWarehouse` w ON w.name = s.warehouse
        INNER JOIN `tabDepartment` d ON d.name = w.department
        WHERE s.item_code IN ({placeholders})
          AND (s.reserved_sales_order IS NULL OR s.reserved_sales_order = '')
          AND s.is_replace = 0
          AND (s.return_reason IS NULL OR s.return_reason = ''
               OR s.return_reason NOT IN ('Repair', 'Replace'))
          AND d.department_sequence >= %s
    """, list(item_codes) + [MIN_PIPELINE_SEQ], as_dict=True)


def calculate_item_eta_for_quotation(item_code, item_group, required_qty, depts, claimed):
    """
    Days until the full required_qty of item_code can dispatch, using the
    sync's four match tiers. Returns (days, label) or None when no tier
    holds the full qty (caller applies NO_STOCK_FALLBACK_DAYS).

    claimed: serials already counted for earlier lines of this quote;
    serials picked here are added to it.
    """
    required_qty = max(int(math.ceil(required_qty or 1)), 1)
    sla_cache = {}
    best = None

    for label, extra_days, codes in _get_match_tiers(item_code):
        serials = [s for s in _get_free_serials(codes) if s.name not in claimed]
        if len(serials) < required_qty:
            continue

        for s in serials:
            key = (s.dept_name, s.dept_seq)
            if key not in sla_cache:
                sla_cache[key] = _total_sla_from(s.dept_name, s.dept_seq, depts, item_group)
            s.days = sla_cache[key]

        # Fastest units first; the ETA is the slowest one needed.
        serials.sort(key=lambda s: s.days)
        picked = serials[:required_qty]
        days = picked[-1].days + extra_days

        if best is None or days < best[0]:
            best = (days, f"{label}, slowest unit in {picked[-1].dept_name}", picked)

    if not best:
        return None
    claimed.update(s.name for s in best[2])
    return best[0], best[1]


class CustomQuotation(Quotation):
    pass


@frappe.whitelist()
def fetch_email_from_shipping_address(doc_name):
    """
    Return email_id from the Quotation's customer_address.
    Returns None silently if anything is missing / fails.
    """
    try:
        doc = frappe.get_doc("Quotation", doc_name)

        if not doc.customer_address:
            return None

        address = frappe.get_doc("Address", doc.customer_address)
        return address.get("email_id")

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Fetch Email Error")
        return None


@frappe.whitelist()
def bypass_so_permission(quotation_name):
    """
    Create Sales Order from Quotation, bypassing permissions,
    but only if customer_replay == 'Agree'.

    Also:
    - Keeps proper link fields (prevdoc_docname, quotation_item)
    - Auto-sets delivery_date if missing
    - Fills custom Order ID on Sales Order
    """
    # Check customer response first
    response = frappe.get_value("Quotation", quotation_name, "customer_replay")
    frappe.logger().debug(f"bypass_so_permission: response for {quotation_name} = {response}")

    if response != "Agree":
        frappe.throw("Customer has Not responded to the quotation")

    def set_missing_values(source, target):
        # Make sure customer is set from party_name
        target.customer = source.party_name

        # 🔹 Fill Order ID on Sales Order
        # 1) If Quotation has a custom field `order_id`, use that
        # 2) Otherwise fall back to the Quotation name
        if not target.get("order_id"):
            target.order_id = source.get("order_id") or source.name

        # 🔹 Seed the visible Delivery Date from the Quotation's Request
        # Delivery Date so it isn't blank.
        #
        # committed_delivery_date is deliberately NOT copied (2026-10-13):
        # Sales Order works it out itself on first submit from where the
        # allocated machines actually are. A copied Quotation date skipped
        # that, and since allocation reads it to pick its starting
        # department, a far-out quote date sent the order upstream while
        # ready stock sat in Packing.
        requested = source.get("request_delivery_date")
        if requested and not target.get("delivery_date"):
            target.delivery_date = requested

    # Map Quotation -> Sales Order with proper link fields
    so = get_mapped_doc(
        "Quotation",
        quotation_name,
        {
            "Quotation": {
                "doctype": "Sales Order",
                "field_map": {
                    "party_name": "customer",
                    # If Quotation ALSO has `order_id` field and you want direct mapping, this helps too:
                    "order_id": "order_id"
                }
            },
            "Quotation Item": {
                "doctype": "Sales Order Item",
                "field_map": {
                    # Restore the link fields:
                    "parent": "prevdoc_docname",   # Quotation name -> SO Item.prevdoc_docname
                    "name": "quotation_item",      # Quotation Item row -> SO Item.quotation_item
                },
            }
        },
        ignore_permissions=True,
        postprocess=set_missing_values
    )

    frappe.logger().debug(f"bypass_so_permission: mapped SO = {so.as_dict()}")

    # Auto-assign Delivery Date for all items if empty
    for item in so.get("items", []):
        if not item.delivery_date:
            item.delivery_date = date.today()

    # Bypass permissions on insert/save
    so.flags.ignore_permissions = True
    so.insert(ignore_permissions=True)
    so.save()

    frappe.db.commit()
    return so.name


@frappe.whitelist()
def calculate_delivery_dates_for_quotation(quotation_name):
    """
    Both dates use the SAME formula: today + max_eta_days (slowest item's
    stock-availability check, read-only — no serial numbers get
    reserved/locked, this is only a quotation).

    Both fields now behave the SAME way on every click of "Calculate ETA":
        - 'estimated_delivery_date' ALWAYS recalculates fresh.
        - 'request_delivery_date' ALSO ALWAYS recalculates fresh now
          (previously frozen after the first click — that freeze has been
          removed so every click updates both fields together).

    Per-line days come from calculate_item_eta_for_quotation() (same
    match rules as the Inventory Sync ETD). A serialised line whose full
    qty isn't covered by any match counts as NO_STOCK_FALLBACK_DAYS -
    before 2026-10-14 such a line was silently dropped, so a quote with
    one short line still showed the other line's fast date. Non-serialised
    lines (warranty/services) are skipped.
    """
    doc = frappe.get_doc("Quotation", quotation_name)

    if not doc.items:
        frappe.throw("Quotation has no items to calculate delivery dates for")

    departments = _get_pipeline_departments()
    claimed = set()
    eta_days_list = []
    line_notes = []

    for item in doc.items:
        item_group, has_serial_no = frappe.db.get_value(
            "Item", item.item_code, ["item_group", "has_serial_no"]
        ) or (None, 0)

        # Warranty/service add-ons share Shopify bundles with laptops, so the
        # variant match would let them claim laptop serials. Skip them.
        if not has_serial_no:
            continue

        result = calculate_item_eta_for_quotation(
            item.item_code, item_group, item.qty or 1, departments, claimed
        )

        if result is not None:
            eta_days_list.append(result[0])
            line_notes.append(f"Row {item.idx}: {result[0]} working days ({result[1]})")
        elif has_serial_no:
            eta_days_list.append(NO_STOCK_FALLBACK_DAYS)
            line_notes.append(
                f"Row {item.idx}: {NO_STOCK_FALLBACK_DAYS} working days "
                f"(not enough free stock of this model for qty {item.qty:g})"
            )

    frappe.msgprint(
        msg="<br>".join(line_notes) or "No stock items on this quotation.",
        title="ETA Breakdown",
        indicator="blue",
    )

    if eta_days_list:
        min_eta_days = min(eta_days_list)   # fastest item — for Request Delivery Date
        max_eta_days = max(eta_days_list)   # slowest item — for Estimated Delivery Date
    else:
        # No stock lines at all (services only) — worst case for both
        min_eta_days = max_eta_days = NO_STOCK_FALLBACK_DAYS

    # Request Delivery Date = today + fastest item's SLA (MIN across all
    # items) — the earliest this order could possibly start shipping.
    # Estimated Delivery Date = today + slowest item's SLA (MAX across all
    # items) — when the WHOLE order (bottleneck item included) is ready.
    # This matches the real working Sales Order logic (compute_sales_order_
    # delivery_date): delivery_date takes MIN SLA, estimated_delivery_date
    # takes MAX SLA. Both recalculate fresh on every "Calculate ETA" click.
    request_date = add_working_days(nowdate(), min_eta_days)
    estimated_date = add_working_days(nowdate(), max_eta_days)

    # Popup notice: Request Delivery Date (fastest item) is earlier than
    # Estimated Delivery Date (slowest item) — this happens whenever items
    # in the quotation have different SLAs, so the customer sees when the
    # FIRST item could ship vs. when the WHOLE order is complete.
    if getdate(request_date) < getdate(estimated_date):
        frappe.msgprint(
            msg=(
                f"Request Delivery Date ({request_date}) is earlier than "
                f"Estimated Delivery Date ({estimated_date}) — items in this "
                f"quotation have different stock/SLA timelines. The full order "
                f"won't be complete until {estimated_date}."
            ),
            title="Request Earlier Than Estimated",
            indicator="orange",
        )

    update_values = {
        "estimated_delivery_date": estimated_date,
        "request_delivery_date": request_date,
    }

    frappe.db.set_value(
        "Quotation",
        quotation_name,
        update_values,
        update_modified=False,
    )
    frappe.db.commit()

    return {"request_delivery_date": str(request_date), "estimated_delivery_date": str(estimated_date)}