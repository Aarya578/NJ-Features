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


def _clear_one(serial_no):
    """Clear one serial in its own transaction, retrying on lock contention.

    Per-row rather than one bulk UPDATE: the planner and the allocation jobs
    write to `tabSerial No` continuously, and a batched transaction deadlocks
    against them and rolls back the whole batch.
    """
    for attempt in range(MAX_RETRIES):
        try:
            frappe.db.sql(
                """
                UPDATE `tabSerial No` sn
                JOIN `tabSales Order` so ON so.name = sn.sales_order_id
                SET sn.return_reason = NULL, sn.modified = NOW()
                WHERE sn.name = %s
                  AND sn.return_reason IN %s
                  AND (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '')
                  AND sn.status = 'Active'
                  AND (so.status IN ('Closed', 'Completed') OR so.per_delivered = 100)
                """,
                (serial_no, RETURN_CAUSES),
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


def clear_completed_return_flags():
    """Scheduled: release serials whose return cycle has finished."""
    try:
        candidates = frappe.db.sql(
            """
            SELECT sn.name
            FROM `tabSerial No` sn
            JOIN `tabSales Order` so ON so.name = sn.sales_order_id
            WHERE sn.status = 'Active'
              AND sn.return_reason IN %s
              AND (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '')
              AND (so.status IN ('Closed', 'Completed') OR so.per_delivered = 100)
            """,
            (RETURN_CAUSES,),
            as_dict=True,
        )

        if not candidates:
            return

        cleared = failed = 0
        for row in candidates:
            try:
                if _clear_one(row.name):
                    cleared += 1
            except Exception:
                failed += 1
                log_error(
                    f"Could not clear return_reason on {row.name}: {frappe.get_traceback()}",
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
