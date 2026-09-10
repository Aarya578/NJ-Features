import frappe
from frappe.model.document import Document
from erpnext.selling.doctype.quotation.quotation import Quotation
from frappe.model.mapper import get_mapped_doc
from frappe.utils import nowdate, getdate
from datetime import date

# Reuse the SAME department/eligibility helpers Sales Order uses, but do
# NOT reuse its calculate_item_eta() anymore — that function silently
# returns a "confident" ETA even when a partial shortfall is never fully
# covered (e.g. 120 required, only 110 found anywhere -> it still returns
# an ETA instead of falling back). This standalone version below fixes
# that specifically for Quotation, without touching Sales Order's file.
#
# We also do NOT import/use anything that reserves serial numbers
# (assign_serials / adjust_serial_allocations) — a Quotation must never
# lock real inventory, it is only an estimate at this stage.
#
# add_working_days() is also imported from Sales Order — it's a better
# working-day calculator than the old Sunday-only skip logic: it walks
# day by day and skips BOTH Sundays AND company holidays (from the
# Holiday List), not just Sundays. Reusing it keeps Quotation's delivery
# date logic consistent with Sales Order's.
#
# _get_dept_effective_sla() and get_dept_warehouses() are also imported —
# using the SAME SLA-resolution rules as Sales Order (Packing & Dispatch
# hardcoded to 1 day, Inward hardcoded to 45 days, everything else clamped
# to a 1-15 day range) instead of raw dept.min_aging_days, which could be
# 0 or unset and silently produce a same-day ETA that wasn't accurate.
from nj_features.overrides.sales_order import (
    get_departments,
    _is_dept_applicable,
    add_working_days,
    _get_dept_effective_sla,
    get_dept_warehouses,
)

# Worst-case fallback (days) when NO item on the quotation has any stock
# anywhere in any department, OR when the full required quantity is never
# fully covered across all departments (partial shortfall). Matches the
# "Inward" department SLA used elsewhere in the codebase as the realistic
# worst case.
NO_STOCK_FALLBACK_DAYS = 45


def calculate_item_eta_for_quotation(item_code, required_qty, departments):
    """
    Standalone ETA calculation for Quotation only — does NOT affect Sales
    Order (nj_features.overrides.sales_order.calculate_item_eta is left
    untouched).

    Walks department by department (in SLA order), counting unreserved
    serials available at each one, until the full required_qty is found.

    Fix vs. the Sales Order version: if the loop finishes checking every
    department and the full required_qty was NEVER fully covered (a
    partial shortfall, e.g. 120 required but only 110 found across every
    department combined), this returns None instead of silently returning
    the accumulated days as if the full quantity was available. The
    caller treats None as "no confident ETA" and applies the
    NO_STOCK_FALLBACK_DAYS fallback — the same fallback already used for
    the zero-stock case.

    Uses the SAME SLA-resolution rules as Sales Order via
    _get_dept_effective_sla() (Packing & Dispatch = 1 day, Inward = 45
    days, everything else clamped to 1-15 days) instead of raw
    dept.min_aging_days, which could be 0/unset and produce a misleading
    same-day ETA.
    """
    accumulated_days = 0
    remaining_qty = required_qty

    for dept in departments:
        accumulated_days += _get_dept_effective_sla(dept)
        dept_name = dept.get("name") if isinstance(dept, dict) else dept.name

        warehouses = get_dept_warehouses(dept_name)

        if not warehouses:
            continue

        placeholders = ', '.join(['%s'] * len(warehouses))

        query = f"""
            SELECT COUNT(*)
            FROM `tabSerial No`
            WHERE
                item_code = %s
                AND warehouse IN ({placeholders})
                AND (reserved_sales_order IS NULL OR reserved_sales_order = '')
                AND NOT EXISTS (
                    SELECT 1
                    FROM `tabDelivery Note Item`
                    WHERE serial_no = `tabSerial No`.name
                        AND docstatus = 1
                )
        """

        params = [item_code] + warehouses
        available_count = frappe.db.sql(query, params)[0][0] or 0

        if available_count >= remaining_qty:
            return accumulated_days
        else:
            remaining_qty -= available_count

    # Loop finished checking every department. Only trust this ETA if the
    # full required_qty was actually covered (remaining_qty hit zero).
    # Any leftover shortfall -> None -> caller applies the 45-day fallback.
    return accumulated_days if remaining_qty <= 0 else None


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

        # 🔹 Carry forward the Quotation's calculated Request Delivery Date
        # (fastest-item stock estimate, calculated by the "Calculate ETA"
        # button) into Sales Order's committed_delivery_date — the same
        # "freeze once, never overwrite" field Sales Order already uses,
        # before its own ETA engine recalculates "Delivery Date" on submit.
        requested = source.get("request_delivery_date")
        if requested and frappe.db.has_column("Sales Order", "committed_delivery_date"):
            if not target.get("committed_delivery_date"):
                target.committed_delivery_date = requested
            # Also seed the visible Delivery Date field so it isn't blank
            # until the ETA engine recalculates it on submit.
            if not target.get("delivery_date"):
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

    If NO item has any stock anywhere, OR if the full required quantity
    of any item is never fully covered across all departments (partial
    shortfall), falls back to NO_STOCK_FALLBACK_DAYS.
    """
    doc = frappe.get_doc("Quotation", quotation_name)

    if not doc.items:
        frappe.throw("Quotation has no items to calculate delivery dates for")

    departments = get_departments()
    eta_days_list = []

    for item in doc.items:
        item_group = frappe.db.get_value("Item", item.item_code, "item_group")
        item_depts = [d for d in departments if _is_dept_applicable(d, item_group)]

        eta_days = calculate_item_eta_for_quotation(item.item_code, item.qty or 1, item_depts)

        if eta_days is not None:
            eta_days_list.append(eta_days)

    if eta_days_list:
        min_eta_days = min(eta_days_list)   # fastest item — for Request Delivery Date
        max_eta_days = max(eta_days_list)   # slowest item — for Estimated Delivery Date
    else:
        # No item anywhere had full stock coverage — worst case for both
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