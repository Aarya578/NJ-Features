"""Clear Serial No.return_reason once the return it refers to is finished.

``return_reason`` records history - "this unit came back from a customer for
Repair/Replace" - but it is read as current state: the allocator refuses any
serial carrying it. Nothing ever clears it, so a machine that was repaired and
put back into stock stays permanently unallocatable.

That is not theoretical. On 2026-09-16 a Lenovo L13 sat finished in Packing &
Dispatch carrying a Repair flag from an order that completed on 2026-09-02. The
allocator skipped it and gave the customer a unit still in the Paint department,
while the website kept advertising the finished one.

The guard is deliberately narrow: a flag is only cleared when the Sales Order it
came from is verifiably Closed / Completed / 100% delivered. A serial with no
linked order, or whose order is still open, is left alone - it may still be a
customer's machine, and guessing wrong means selling it to someone else.

This module also releases reservations held by RTO'd orders - see
release_rto_dead_order_reservations(). Both jobs answer the same question ("is
this unit still owed to anyone?"), so they run together on the nightly cron.
"""

import time

import frappe
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error

RETURN_CAUSES = ("Repair", "Replace")
MAX_RETRIES = 3


FINISHED_SO_SQL = "(so.status IN ('Closed', 'Completed') OR so.per_delivered = 100)"


def _split_serials(value):
    return {s.strip() for s in (value or "").replace(",", "\n").split("\n") if s.strip()}


def _return_sales_order(serial_no):
    """The order on the latest submitted Repair/Replace return DN carrying this serial.

    Needed because sales_order_id cannot be relied on: a return DN wipes the
    customer details off the serial, sales_order_id included
    (delivery_note.py, the `not preserve_customer_details` block). On 2026-10-05
    58 of the 66 unreserved Repair/Replace-tagged units in sellable departments
    had it blank, so the original JOIN on sales_order_id never saw them - e.g.
    NJ-LP-500007 sat in Adaptor QC flagged Replace for an order (SAL-ORD-2026-08335)
    that was already Closed, and SAL-ORD-2026-09589 was given an L2 unit instead.
    The return DN always records the order, so it is the reliable link.
    """
    like = f"%{serial_no}%"
    rows = frappe.db.sql(
        """
        SELECT dni.against_sales_order AS sales_order, dni.serial_no
        FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dn.docstatus = 1 AND dn.is_return = 1
          AND dn.cause_of_return IN %s
          AND dni.serial_no LIKE %s
        ORDER BY dn.posting_date DESC, dn.creation DESC
        """,
        (RETURN_CAUSES, like),
        as_dict=True,
    )
    for row in rows:
        if row.sales_order and serial_no in _split_serials(row.serial_no):
            return row.sales_order

    # Bundled (SKU) lines can carry the serial on the packed item instead.
    rows = frappe.db.sql(
        """
        SELECT pi.serial_no,
               (SELECT dni.against_sales_order FROM `tabDelivery Note Item` dni
                WHERE dni.parent = dn.name AND IFNULL(dni.against_sales_order, '') != ''
                LIMIT 1) AS sales_order
        FROM `tabPacked Item` pi
        INNER JOIN `tabDelivery Note` dn ON dn.name = pi.parent AND pi.parenttype = 'Delivery Note'
        WHERE dn.docstatus = 1 AND dn.is_return = 1
          AND dn.cause_of_return IN %s
          AND pi.serial_no LIKE %s
        ORDER BY dn.posting_date DESC, dn.creation DESC
        """,
        (RETURN_CAUSES, like),
        as_dict=True,
    )
    for row in rows:
        if row.sales_order and serial_no in _split_serials(row.serial_no):
            return row.sales_order
    return None


def _origin_sales_orders(serial_no, sales_order_id):
    """Every order this flag could still belong to. All of them must be finished."""
    orders = {so for so in (sales_order_id, _return_sales_order(serial_no)) if so}
    return sorted(orders)


def _is_finished(sales_order):
    return bool(frappe.db.sql(
        f"SELECT 1 FROM `tabSales Order` so WHERE so.name = %s AND {FINISHED_SO_SQL}",
        (sales_order,),
    ))


def _clear_one(serial_no, sales_orders):
    """Clear one serial in its own transaction, retrying on lock contention.

    Per-row rather than one bulk UPDATE: the planner and the allocation jobs
    write to `tabSerial No` continuously, and a batched transaction deadlocks
    against them and rolls back the whole batch.

    The finished-order check is repeated inside the UPDATE so an order reopened
    between the candidate scan and this write keeps its flag.
    """
    placeholders = ", ".join(["%s"] * len(sales_orders))
    for attempt in range(MAX_RETRIES):
        try:
            frappe.db.sql(
                f"""
                UPDATE `tabSerial No` sn
                SET sn.return_reason = NULL, sn.modified = NOW()
                WHERE sn.name = %s
                  AND sn.return_reason IN %s
                  AND (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '')
                  AND sn.status = 'Active'
                  AND NOT EXISTS (
                      SELECT 1 FROM `tabSales Order` so
                      WHERE so.name IN ({placeholders}) AND NOT {FINISHED_SO_SQL}
                  )
                """,
                (serial_no, RETURN_CAUSES, *sales_orders),
            )
            changed = (
                frappe.db._cursor.rowcount > 0
                if getattr(frappe.db, "_cursor", None) else False
            )
            frappe.db.commit()
            return changed
        except Exception as e:
            frappe.db.rollback()
            code = e.args[0] if getattr(e, "args", None) else None
            if code in (1213, 1205) and attempt < MAX_RETRIES - 1:
                time.sleep(0.4 * (attempt + 1))
                continue
            raise
    return False


def get_finished_return_flags():
    """Unreserved Active serials still flagged Repair/Replace whose order(s) are finished.

    Returns [{serial_no, sales_orders}]. A serial with no traceable order at all
    is left alone - it may still be a customer's machine.
    """
    flagged = frappe.db.sql(
        """
        SELECT sn.name, IFNULL(sn.sales_order_id, '') AS sales_order_id
        FROM `tabSerial No` sn
        WHERE sn.status = 'Active'
          AND sn.return_reason IN %s
          AND (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '')
        """,
        (RETURN_CAUSES,),
        as_dict=True,
    )
    finished = []
    for row in flagged:
        orders = _origin_sales_orders(row.name, row.sales_order_id)
        if orders and all(_is_finished(so) for so in orders):
            finished.append({"serial_no": row.name, "sales_orders": orders})
    return finished


def clear_completed_return_flags():
    """Scheduled: release serials whose return cycle has finished."""
    try:
        candidates = get_finished_return_flags()

        if not candidates:
            return

        cleared = failed = 0
        for row in candidates:
            try:
                if _clear_one(row["serial_no"], row["sales_orders"]):
                    cleared += 1
            except Exception:
                failed += 1
                log_error(
                    f"Could not clear return_reason on {row['serial_no']}: {frappe.get_traceback()}",
                    "clear_completed_return_flags",
                )

        log_error(
            f"Released {cleared} serial(s) whose return cycle is complete "
            f"({len(candidates)} candidate(s), {failed} failed). These were "
            f"finished machines the allocator was refusing.",
            "clear_completed_return_flags",
            "Info",
        )

    except Exception:
        log_error(frappe.get_traceback(), "clear_completed_return_flags")

    # Chained rather than registered as its own cron entry: hooks.py changes need
    # a bench migrate, this only needs a restart. Both jobs release units nobody
    # is owed, and neither depends on the other's result.
    release_rto_dead_order_reservations()


# ==============================================================================
# RTO'd orders: release the stock they are still holding
# ==============================================================================
# An RTO return reverses delivered_qty, so the order goes back to "To Deliver"
# with per_delivered = 0 while staying submitted and 100% billed - demand queries
# could not tell it apart from a fresh order and kept allocating it machines.
# RTO_EXCLUSION_SQL now stops new reservations, but it cannot undo the ones
# already made, and neither existing release path reaches them:
#
#   - trim_over_allocated_serials() / unassign_serials() only release a serial
#     with NO submitted Delivery Note. Every RTO'd unit has two (the original
#     dispatch and the return), so both skip all of them.
#   - both also only run for an order the demand query still returns, and an
#     RTO'd order is no longer returned at all.
#
# Without this pass the 32 units found held on 2026-09-22 (65 orders, oldest from
# 2026-03-15) would stay reserved to dead orders permanently.
#
# Repair/Replace units are left alone: those are owed to the customer who
# returned them.

RTO_CAUSES = ("RTO Customer", "RTO Delivery Partner")


def _release_one(serial_no, sales_order):
    """Release one reservation in its own transaction, retrying on lock contention."""
    remarks = (
        "Released: Sales Order {0} was returned (RTO) and is no longer demand"
    ).format(sales_order)

    for attempt in range(MAX_RETRIES):
        try:
            frappe.db.sql(
                """
                UPDATE `tabSerial No`
                SET reserved_sales_order = NULL,
                    to_make = NULL,
                    order_source = NULL,
                    remarks = %s,
                    modified = NOW()
                WHERE name = %s
                  AND reserved_sales_order = %s
                  AND (return_reason IS NULL OR return_reason = ''
                       OR return_reason NOT IN ('Repair', 'Replace'))
                  AND (order_source IS NULL OR (
                      order_source NOT LIKE '%%- Repair%%'
                      AND order_source NOT LIKE '%%- Replace%%'
                  ))
                """,
                (remarks, serial_no, sales_order),
            )
            changed = (
                frappe.db._cursor.rowcount > 0
                if getattr(frappe.db, "_cursor", None) else False
            )
            frappe.db.commit()
            return changed
        except Exception as e:
            frappe.db.rollback()
            code = e.args[0] if getattr(e, "args", None) else None
            if code in (1213, 1205) and attempt < MAX_RETRIES - 1:
                time.sleep(0.4 * (attempt + 1))
                continue
            raise
    return False


def get_rto_held_serials():
    """Serials still reserved to an order whose latest submitted DN is an RTO return.

    Same "latest submitted Delivery Note wins" rule as RTO_EXCLUSION_SQL, so an
    order someone deliberately re-shipped is not treated as dead and its unit is
    left reserved.
    """
    return frappe.db.sql(
        """
        SELECT sn.name AS serial_no, sn.reserved_sales_order AS sales_order,
               sn.item_code, sn.department, sn.warehouse
        FROM `tabSerial No` sn
        INNER JOIN `tabSales Order` so ON so.name = sn.reserved_sales_order
        WHERE sn.reserved_sales_order IS NOT NULL AND sn.reserved_sales_order != ''
          AND so.docstatus = 1
          AND (sn.return_reason IS NULL OR sn.return_reason = ''
               OR sn.return_reason NOT IN ('Repair', 'Replace'))
          AND (sn.order_source IS NULL OR (
              sn.order_source NOT LIKE '%%- Repair%%'
              AND sn.order_source NOT LIKE '%%- Replace%%'
          ))
          AND EXISTS (
              SELECT 1
              FROM `tabDelivery Note Item` dni
              INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
              WHERE dni.against_sales_order = so.name
                AND dn.docstatus = 1
                AND dn.is_return = 1
                AND dn.cause_of_return IN %(causes)s
                AND NOT EXISTS (
                    SELECT 1
                    FROM `tabDelivery Note Item` dni2
                    INNER JOIN `tabDelivery Note` dn2 ON dn2.name = dni2.parent
                    WHERE dni2.against_sales_order = dni.against_sales_order
                      AND dn2.docstatus = 1
                      AND dn2.creation > dn.creation
                )
          )
        """,
        {"causes": RTO_CAUSES},
        as_dict=True,
    )


def release_rto_dead_order_reservations():
    """Scheduled: free machines still held by orders that came back as RTO."""
    try:
        candidates = get_rto_held_serials()
        if not candidates:
            return

        released = failed = 0
        for row in candidates:
            try:
                if _release_one(row.serial_no, row.sales_order):
                    released += 1
            except Exception:
                failed += 1
                log_error(
                    "Could not release {0} from RTO'd order {1}: {2}".format(
                        row.serial_no, row.sales_order, frappe.get_traceback()
                    ),
                    "release_rto_dead_order_reservations",
                )

        log_error(
            "Released {0} serial(s) held by RTO'd Sales Orders ({1} candidate(s), "
            "{2} failed). These were sellable machines reserved to orders whose "
            "parcel came back.".format(released, len(candidates), failed),
            "release_rto_dead_order_reservations",
            "Info",
        )

    except Exception:
        log_error(frappe.get_traceback(), "release_rto_dead_order_reservations")
