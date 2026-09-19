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
