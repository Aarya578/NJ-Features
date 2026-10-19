"""Shared return state for allocation, planning and the Sales Order screen.

The latest submitted delivery event wins (creation, then name). A subsequent
dispatch clears the return state; an NJ Refund record remains an independent
block. Historical Repair returns must never turn a new Replace into a repair.

One exception, Python paths only (see _return_owed_delivery): an order that was
fully dispatched before its first return and still owes units owes them only
because of returns. One re-shipment must not turn the rest back into fresh
demand - SAL-ORD-2025-07398 had 10 Repair/Replace returns, 8 re-shipments, and
got fresh stock as plain NJ-Direct-B2B once the latest DN was a dispatch.
"""

import frappe
from frappe.utils import add_days, getdate, nowdate


REFUND_BLOCKING_STATUSES = ('Paid', 'Refunded', 'Initiated', 'Debit Failed', 'Returned')
RTO_BLOCKING_CAUSES = ('RTO Customer', 'RTO Delivery Partner')
HARDWARE_GROUPS = ('Laptops', 'Chromebooks', 'MacBooks', 'Desktops', 'AIO',
                   'Full Set Desktops', 'Chromeboxes')

# cause_of_return is authoritative; return_reason supports older records only
# when cause_of_return is empty. Do not let a stale legacy Repair override Replace.
RETURN_CAUSE_SQL = "COALESCE(NULLIF(TRIM(dn.cause_of_return), ''), TRIM(dn.return_reason), '')"
LATEST_DELIVERY_SQL = """
    NOT EXISTS (
        SELECT 1
        FROM `tabDelivery Note Item` newer_item
        INNER JOIN `tabDelivery Note` newer ON newer.name = newer_item.parent
        WHERE newer_item.against_sales_order = dni.against_sales_order
          AND newer.docstatus = 1
          AND (newer.creation > dn.creation
               OR (newer.creation = dn.creation AND newer.name > dn.name))
    )
"""


def _return_exclusion(causes):
    # Internal constants only, never caller-provided SQL values.
    values = ', '.join("'{}'".format(cause) for cause in causes)
    return f"""
        AND so.name NOT IN (
            SELECT DISTINCT dni.against_sales_order
            FROM `tabDelivery Note Item` dni
            INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            WHERE dn.docstatus = 1 AND dn.is_return = 1
              AND {RETURN_CAUSE_SQL} IN ({values})
              AND dni.against_sales_order IS NOT NULL
              AND dni.against_sales_order != ''
              AND {LATEST_DELIVERY_SQL}
        )
    """


REFUND_EXCLUSION_SQL = """
    AND so.name NOT IN (
        SELECT DISTINCT sales_order FROM `tabNJ Refund`
        WHERE docstatus = 1
          AND refund_status IN ('Paid', 'Refunded', 'Initiated', 'Debit Failed', 'Returned')
          AND sales_order IS NOT NULL AND sales_order != ''
    )
""" + _return_exclusion(('Refund',))
RTO_EXCLUSION_SQL = _return_exclusion(RTO_BLOCKING_CAUSES)
REPAIR_EXCLUSION_SQL = _return_exclusion(('Repair', 'In-House Repair'))
FRESH_ALLOCATION_EXCLUSION_SQL = REFUND_EXCLUSION_SQL + RTO_EXCLUSION_SQL + REPAIR_EXCLUSION_SQL


def get_latest_delivery(so_name, use_bold_desk=True):
    rows = frappe.db.sql(f"""
        SELECT dn.name, dn.is_return, dn.creation, {RETURN_CAUSE_SQL} AS cause_of_return
        FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dni.against_sales_order = %s AND dn.docstatus = 1
        GROUP BY dn.name, dn.is_return, dn.creation, cause_of_return
        ORDER BY dn.creation DESC, dn.name DESC
    """, (so_name,), as_dict=True)
    if not rows:
        return {}
    if rows[0].is_return:
        if use_bold_desk and return_cause(rows[0]) == 'Refund':
            return _bold_desk_corrected_return(so_name, rows[0])
        return rows[0]
    return _return_owed_delivery(so_name, rows) or rows[0]


# BoldDesk is the service team's record of what the customer is getting. A
# return DN typed "Refund" while the ticket says Replacement/Repair blocked
# allocation (SAL-ORD-2026-02598, SAL-ORD-2025-07228 on 2026-10-06). The
# hourly BoldDesk sync corrects the DN itself; this covers the gap until it runs.
BOLD_DESK_PICKUP_CAUSES = {
    'In House Repair': 'Repair', 'Replacement': 'Replace', 'Refund': 'Refund', 'Buyback': 'Refund',
}
BOLD_DESK_STATUS_CAUSES = {
    'Replacement Pending': 'Replace', 'L2 Repair': 'Repair', 'Refund Approval Pending': 'Refund',
}
# The sync only refreshes tickets still open in BoldDesk; a closed ticket keeps
# its last status here for good, so only recently synced rows are trusted.
BOLD_DESK_FRESH_DAYS = 2


def bold_desk_cause(status, pickup_category):
    """Repair / Replace / Refund from a ticket, or None when unclear or contradictory."""
    by_pickup = BOLD_DESK_PICKUP_CAUSES.get((pickup_category or '').strip())
    by_status = BOLD_DESK_STATUS_CAUSES.get((status or '').strip())
    if by_pickup and by_status and by_pickup != by_status:
        return None
    return by_pickup or by_status


def return_dn_serials(dn_name):
    """Serials on a DN, from item rows and packed items (website bundles)."""
    serials = set()
    for value in frappe.db.sql_list("""
        SELECT serial_no FROM `tabDelivery Note Item` WHERE parent = %s
        UNION ALL
        SELECT serial_no FROM `tabPacked Item` WHERE parent = %s
    """, (dn_name, dn_name)):
        serials.update(s.strip() for s in (value or '').replace(',', '\n').split('\n') if s.strip())
    return serials


def get_bold_desk_return_ticket(so_name, serial_nos):
    """Freshest open ticket for this SO and returned serial, as (cause, ticket).

    (None, None) when any NJ Refund record exists, no fresh ticket matches,
    or the matching tickets disagree with each other.
    """
    if not serial_nos or not frappe.db.table_exists('Bold Desk History'):
        return None, None
    if frappe.db.exists('NJ Refund', {'sales_order': so_name, 'docstatus': ['<', 2]}):
        return None, None
    tickets = frappe.db.sql("""
        SELECT name, status, cf_pickup_category, serial_no, replacement_serial
        FROM `tabBold Desk History`
        WHERE sales_order = %s AND serial_no IN %s
          AND IFNULL(status, '') != 'Closed'
          AND last_synced_on >= %s
        ORDER BY updated_on DESC, name DESC
    """, (so_name, tuple(serial_nos), add_days(frappe.utils.now_datetime(), -BOLD_DESK_FRESH_DAYS)), as_dict=True)
    causes = {bold_desk_cause(t.status, t.cf_pickup_category) for t in tickets} - {None}
    if len(causes) != 1:
        return None, None
    cause = causes.pop()
    return cause, next(t for t in tickets if bold_desk_cause(t.status, t.cf_pickup_category) == cause)


def _bold_desk_corrected_return(so_name, latest):
    cause, ticket = get_bold_desk_return_ticket(so_name, return_dn_serials(latest.name))
    if cause not in ('Repair', 'Replace'):
        return latest
    corrected = frappe._dict(latest)
    corrected.cause_of_return = cause
    corrected.bold_desk_ticket = ticket.name
    return corrected


def _return_owed_delivery(so_name, rows):
    """Latest Repair/Replace return DN when every unit still owed comes from returns.

    rows are the order's delivery events, newest first. Requires every SO line to
    have been dispatched in full before the first return, and some line still
    short now. Orders that never shipped their full quantity keep plain demand
    for the balance (SO-2025-08-00088, SO-2026-02-00152).
    """
    returns = [r for r in rows if r.is_return]
    if not returns or return_cause(returns[0]) not in ('Repair', 'Replace'):
        return None
    lines = frappe.db.sql("""
        SELECT name, qty, delivered_qty FROM `tabSales Order Item` WHERE parent = %s
    """, (so_name,), as_dict=True)
    if not lines or all(line.delivered_qty >= line.qty for line in lines):
        return None
    first_return = min(r.creation for r in returns)
    shipped_before = dict(frappe.db.sql("""
        SELECT dni.so_detail, SUM(dni.qty)
        FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dni.against_sales_order = %s AND dn.docstatus = 1
          AND dn.is_return = 0 AND dn.creation < %s
        GROUP BY dni.so_detail
    """, (so_name, first_return)))
    if any((shipped_before.get(line.name) or 0) < line.qty for line in lines):
        return None
    return returns[0]


# Same window as get_open_sales_orders() and the planner's LOOKBACK_DAYS_B2B.
ALLOCATION_WINDOW_DAYS = 200


def is_past_allocation_window(so_name):
    """True when the SO was created before the 200-day allocation window.

    Such an order stays in scope through its reservations or a recent return,
    but its never-shipped balance must not take fresh stock (ops decision
    2026-10-06: Kaynes SO-2025-08-00088 got 15 machines for units unshipped
    since Aug 2025 after a May 2026 Repair return reopened it).
    """
    creation = frappe.db.get_value("Sales Order", so_name, "creation")
    return bool(creation) and getdate(creation) < add_days(getdate(nowdate()), -ALLOCATION_WINDOW_DAYS)


def get_return_owed_qty(so_name, item_code=None, causes=('Repair', 'In-House Repair', 'Replace')):
    """Units still owed because returns were not re-shipped, per SO line.

    Per line: returned qty minus dispatches after that line's first return.
    item_code narrows to lines for that item, or bundles containing it.
    Pass causes=('Replace',) for units that may take fresh stock - Repair is
    owed the customer's own unit, never a fresh one. Refund/RTO never count.
    """
    cause_list = ', '.join("'{}'".format(c) for c in causes if c in ('Repair', 'In-House Repair', 'Replace'))
    events = frappe.db.sql(f"""
        SELECT dni.so_detail, dn.is_return, dn.creation, SUM(dni.qty) AS qty
        FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dni.against_sales_order = %s AND dn.docstatus = 1
          -- Refund and RTO returns are never owed back to the customer.
          AND (dn.is_return = 0 OR {RETURN_CAUSE_SQL} IN ({cause_list}))
        GROUP BY dni.so_detail, dn.name, dn.is_return, dn.creation
    """, (so_name,), as_dict=True)
    by_line = {}
    for ev in events:
        by_line.setdefault(ev.so_detail, []).append(ev)

    lines = frappe.db.sql("""
        SELECT name, item_code FROM `tabSales Order Item` WHERE parent = %s
    """, (so_name,), as_dict=True)
    owed = 0
    for line in lines:
        if item_code and line.item_code != item_code and not frappe.db.sql("""
            SELECT 1 FROM `tabProduct Bundle` pb
            INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
            WHERE (pb.new_item_code = %s OR pb.name = %s) AND pbi.item_code = %s
            LIMIT 1
        """, (line.item_code, line.item_code, item_code)):
            continue
        line_events = by_line.get(line.name) or []
        returns = [ev for ev in line_events if ev.is_return]
        if not returns:
            continue
        first_return = min(ev.creation for ev in returns)
        returned = -sum(ev.qty for ev in returns)
        reshipped = sum(ev.qty for ev in line_events if not ev.is_return and ev.creation > first_return)
        owed += max(0, returned - reshipped)
    return int(owed)


def get_item_return_state(so_name, item_code):
    """What one item of an SO still owes because of returns, and what covers it.

    The order-level label hides mixed orders: SO-2025-11-00029 (Systech) owed
    mostly Repair units but held 7 fresh machines labelled plain "Distributor"
    (2026-10-07). Per item:
      repair_owed / replace_owed - units owed for un-reshipped returns
      own_units                  - customer's returned units reserved (Repair)
      replace_labelled           - reservations already labelled "- Replace"
      repair_gap                 - Repair units still waiting for their own unit;
                                   never filled with fresh stock
    """
    state = frappe._dict(repair_owed=0, replace_owed=0, own_units=0,
                         replace_labelled=0, repair_gap=0, reserved=0)
    if not frappe.db.sql(f"""
        SELECT 1 FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dni.against_sales_order = %s AND dn.docstatus = 1 AND dn.is_return = 1
          AND {RETURN_CAUSE_SQL} IN ('Repair', 'In-House Repair', 'Replace')
        LIMIT 1
    """, (so_name,)):
        return state
    state.repair_owed = get_return_owed_qty(so_name, item_code, ('Repair', 'In-House Repair'))
    state.replace_owed = get_return_owed_qty(so_name, item_code, ('Replace',))
    for return_reason, order_source in frappe.db.sql("""
        SELECT IFNULL(return_reason, ''), IFNULL(order_source, '')
        FROM `tabSerial No`
        WHERE reserved_sales_order = %s AND COALESCE(NULLIF(to_make, ''), item_code) = %s
    """, (so_name, item_code)):
        state.reserved += 1
        if return_reason == 'Repair':
            state.own_units += 1
        elif order_source == 'Replace' or order_source.endswith(' - Replace'):
            state.replace_labelled += 1
    state.repair_gap = max(0, state.repair_owed - state.own_units)
    # Undelivered qty on lines for this item (directly or as a bundle component).
    state.pending = int(frappe.db.sql("""
        SELECT COALESCE(SUM(soi.qty - soi.delivered_qty), 0)
        FROM `tabSales Order Item` soi
        WHERE soi.parent = %(so)s AND soi.qty > soi.delivered_qty
          AND (soi.item_code = %(item)s OR EXISTS (
              SELECT 1 FROM `tabProduct Bundle` pb
              INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
              WHERE (pb.new_item_code = soi.item_code OR pb.name = soi.item_code)
                AND pbi.item_code = %(item)s))
    """, {'so': so_name, 'item': item_code})[0][0] or 0)
    return state


def return_cause(delivery):
    if not delivery.get('is_return'):
        return ''
    cause = (delivery.get('cause_of_return') or '').strip()
    return 'Repair' if cause == 'In-House Repair' else cause


def get_allocation_block_reason(so_name):
    refund = frappe.db.get_value('NJ Refund', {
        'sales_order': so_name, 'docstatus': 1,
        'refund_status': ['in', REFUND_BLOCKING_STATUSES],
    }, 'name')
    if refund:
        return f'Allocation blocked by refund record {refund}.'
    latest = get_latest_delivery(so_name)
    cause = return_cause(latest)
    if cause == 'Refund':
        return f"Allocation blocked: latest delivery note {latest['name']} is a Refund return."
    if cause in RTO_BLOCKING_CAUSES:
        return f"Allocation blocked: latest delivery note {latest['name']} is {cause}. Review whether to re-ship or close the order."
    if cause == 'Repair':
        return f"Repair return {latest['name']}: fulfil using the customer's returned unit; fresh-stock allocation is excluded."
    return ''


def resolve_return_stock_item(item_code, returned_serial):
    """Resolve a website bundle to its physical hardware, without variant metadata.

Multi-machine bundles must identify the component using the returned serial;
never pick the first accessory or an arbitrary machine from a bundle.
"""
    item = frappe.db.get_value('Item', item_code,
                               ['is_stock_item', 'item_group'], as_dict=True) or {}
    if item.get('is_stock_item') and item.get('item_group') in HARDWARE_GROUPS:
        return item_code
    rows = frappe.db.sql("""
        SELECT DISTINCT pbi.item_code
        FROM `tabProduct Bundle` pb
        INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
        INNER JOIN `tabItem` i ON i.name = pbi.item_code
        WHERE (pb.name = %s OR pb.new_item_code = %s)
          AND i.is_stock_item = 1 AND i.item_group IN %s
          AND IFNULL(i.disabled, 0) = 0
    """, (item_code, item_code, HARDWARE_GROUPS), as_dict=True)
    codes = {row['item_code'] for row in rows}
    if len(codes) == 1:
        return next(iter(codes))
    physical = frappe.db.get_value('Serial No', returned_serial, 'item_code')
    return physical if physical in codes else None


def allocate_return_replacement(so_name, website_or_stock_item, returned_serial, dn_name):
    """Reserve exact hardware or a mapped variant for one replacement return.

Resolve bundles before stock lookup and before writing to_make. Do not allocate
the rejected customer unit or fall back to model/CPU reconfiguration here.
"""
    from nj_features.overrides.sales_order import create_unallocated_log, is_serial_already_delivered
    from nj_features.services.reservation_service import get_effective_order_source
    from nj_features.services.model_compatibility import is_screen_type_compatible
    from nj_features.nj_features.doctype.nj_production_planning.nj_production_planning import (
        _get_shopify_variant_id, _get_variant_bundle_item_codes,
    )

    if get_allocation_block_reason(so_name):
        return None
    item_code = resolve_return_stock_item(website_or_stock_item, returned_serial)
    if not item_code:
        create_unallocated_log(so_name, website_or_stock_item, 1,
                               f"Return Replacement - Cannot resolve physical hardware item ({dn_name})")
        return None

    named = reserve_bold_desk_replacement(so_name, item_code, {returned_serial})
    if named:
        return named

    # Keep stock eligibility aligned with the hourly pool. RTO units can be
    # resold once eligible; Repair/Replace units are protected customer stock.
    eligible = """
        sn.status = 'Active'
        AND sn.name != %(returned_serial)s
        AND (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '')
        AND IFNULL(sn.is_replace, 0) = 0
        AND IFNULL(sn.return_reason, '') NOT IN ('Repair', 'Replace')
        AND IFNULL(dp.department_sequence, 0) > 0
        AND IFNULL(dp.sla_item_groups, '') != ''
        AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
        AND (IFNULL(sn.return_reason, '') = ''
             OR IFNULL(sn.sales_order_id, '') != ''
             OR dp.department_sequence >= 10)
    """
    joins = """
        INNER JOIN `tabWarehouse` w ON w.name = sn.warehouse
        INNER JOIN `tabDepartment` dp ON dp.name = w.department
    """
    variant_id = _get_shopify_variant_id(website_or_stock_item) or _get_shopify_variant_id(item_code)
    variant_codes = sorted(set(_get_variant_bundle_item_codes(variant_id)) - {item_code}) if variant_id else []
    for codes, reason in [([item_code], 'Return Replacement'),
                          (variant_codes, 'Return Replacement - Shopify Variant match')]:
        if not codes:
            continue
        params = {'codes': tuple(codes), 'returned_serial': returned_serial}
        candidates = frappe.db.sql(f"""
            SELECT sn.name, sn.item_code
            FROM `tabSerial No` sn {joins}
            WHERE {eligible}
              AND (sn.item_code IN %(codes)s OR sn.to_make IN %(codes)s)
            ORDER BY dp.department_sequence DESC,
                     CASE WHEN sn.item_code = %(target)s THEN 0 ELSE 1 END,
                     sn.creation, sn.name
        """, dict(params, target=item_code), as_dict=True)
        for candidate in candidates:
            if is_serial_already_delivered(candidate['name']):
                continue
            if not is_screen_type_compatible(candidate['item_code'], item_code):
                continue
            # Recheck eligibility at write time so a concurrent allocator cannot
            # have its reservation overwritten by the return handler.
            frappe.db.sql(f"""
                UPDATE `tabSerial No` sn {joins}
                SET sn.reserved_sales_order = %(so)s, sn.to_make = %(target)s,
                    sn.order_source = %(source)s, sn.remarks = %(remarks)s,
                    sn.return_reason = NULL, sn.is_replace = 0,
                    sn.modified = %(modified)s, sn.modified_by = %(modified_by)s
                WHERE sn.name = %(serial)s AND {eligible}
                  AND (sn.item_code IN %(codes)s OR sn.to_make IN %(codes)s)
            """, dict(params, so=so_name, target=item_code,
                       source=get_effective_order_source(so_name),
                       remarks=f"Allocated to SO {so_name} ({reason}) | to_make: {item_code}",
                       serial=candidate['name'], modified=frappe.utils.now_datetime(),
                       modified_by=frappe.session.user))
            if frappe.db._cursor.rowcount:
                from nj_features.services.reservation_service import stamp_allocated_department
                stamp_allocated_department(candidate['name'])
                return candidate['name']
    create_unallocated_log(so_name, item_code, 1,
                           f"Return Replacement - No available stock (returned serial {returned_serial} in DN {dn_name})")
    return None


def reserve_bold_desk_replacement(so_name, item_code, returned_serials):
    """Reserve the replacement unit service named on the BoldDesk ticket.

    Service flags that unit is_replace = 1, which every stock pool skips, so
    without this the order takes a second machine from stock (NJ-LP-797589
    for SAL-ORD-2026-02598). Same model only; otherwise normal allocation runs.
    """
    from nj_features.overrides.sales_order import is_serial_already_delivered
    from nj_features.services.reservation_service import get_effective_order_source

    cause, ticket = get_bold_desk_return_ticket(so_name, returned_serials)
    serial = ((ticket or {}).get('replacement_serial') or '').strip()
    if cause != 'Replace' or not serial or serial in returned_serials:
        return None
    if is_serial_already_delivered(serial):
        return None
    frappe.db.sql("""
        UPDATE `tabSerial No`
        SET reserved_sales_order = %(so)s, to_make = %(item)s, order_source = %(source)s,
            remarks = %(remarks)s, return_reason = NULL, is_replace = 0,
            modified = %(modified)s, modified_by = %(user)s
        WHERE name = %(serial)s AND status = 'Active'
          AND IFNULL(reserved_sales_order, '') = ''
          AND (item_code = %(item)s OR to_make = %(item)s)
          AND IFNULL(return_reason, '') NOT IN ('Repair', 'Replace')
    """, {
        'so': so_name, 'item': item_code, 'serial': serial,
        'source': get_effective_order_source(so_name),
        'remarks': f"BoldDesk ticket {ticket.name}: named replacement for SO {so_name} | to_make: {item_code}",
        'modified': frappe.utils.now_datetime(), 'user': frappe.session.user,
    })
    if not frappe.db._cursor.rowcount:
        return None
    from nj_features.services.reservation_service import stamp_allocated_department
    stamp_allocated_department(serial)
    return serial
