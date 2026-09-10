"""
Data remediation script for Repair Return Sales Orders and stale reservations.
Fixes:
1. SAL-ORD-2025-12830-1: Re-links NJ-LP-161196 and releases NJ-LP-408896.
2. SO-03723: Re-links NJ-LP-939122 and releases NJ-LP-580930.
3. SO-2025-06-00098-1: Releases phantom serial NJ-LP-399957 and completes the Sales Order.
"""

import frappe
from frappe.utils import now_datetime


def remediate():
    now_str = now_datetime().strftime("%Y-%m-%d %H:%M:%S")
    results = {}

    # --------------------------------------------------------------------------
    # 1. SAL-ORD-2025-12830-1
    # --------------------------------------------------------------------------
    # Release wrongly swapped serial NJ-LP-408896
    frappe.db.sql("""
        UPDATE `tabSerial No`
        SET reserved_sales_order = NULL,
            order_source = NULL,
            remarks = %s,
            modified = %s
        WHERE name = 'NJ-LP-408896' AND reserved_sales_order = 'SAL-ORD-2025-12830-1'
    """, (f"Released from SAL-ORD-2025-12830-1 on {now_str}: Restoring customer repair unit NJ-LP-161196", now_str))

    # Re-link customer's actual unit NJ-LP-161196
    frappe.db.sql("""
        UPDATE `tabSerial No`
        SET reserved_sales_order = 'SAL-ORD-2025-12830-1',
            to_make = 'S-Lenovo L490-CORE I5 - 8TH GEN-8 GB-512 GB SSD',
            order_source = 'NJ-Website-B2C - Repair',
            return_reason = 'Repair',
            status = 'Active',
            remarks = %s,
            modified = %s
        WHERE name = 'NJ-LP-161196'
    """, (f"Allocated to SO SAL-ORD-2025-12830-1 (Original Customer Repair Unit) on {now_str}", now_str))

    results["SAL-ORD-2025-12830-1"] = "Re-linked NJ-LP-161196, released NJ-LP-408896"

    # --------------------------------------------------------------------------
    # 2. SO-03723
    # --------------------------------------------------------------------------
    # Release wrongly allocated Inward unit NJ-LP-580930
    frappe.db.sql("""
        UPDATE `tabSerial No`
        SET reserved_sales_order = NULL,
            order_source = NULL,
            remarks = %s,
            modified = %s
        WHERE name = 'NJ-LP-580930' AND reserved_sales_order = 'SO-03723'
    """, (f"Released from SO-03723 on {now_str}: Restoring customer repair unit NJ-LP-939122", now_str))

    # Re-link customer's actual unit NJ-LP-939122
    ret_wh = frappe.db.get_value("Stock Ledger Entry", {"voucher_no": "DN-285247", "is_cancelled": 0}, "warehouse") or "BG - INW-R32-S3 - NJ"
    frappe.db.sql("""
        UPDATE `tabSerial No`
        SET reserved_sales_order = 'SO-03723',
            to_make = 'S-Lenovo L470-CORE I5 - 7TH GEN-8 GB-256 GB SSD',
            order_source = 'NJ-Direct-B2C - Repair',
            return_reason = 'Repair',
            status = 'Active',
            warehouse = COALESCE(NULLIF(warehouse, ''), %s),
            remarks = %s,
            modified = %s
        WHERE name = 'NJ-LP-939122'
    """, (ret_wh, f"Allocated to SO SO-03723 (Original Customer Repair Unit) on {now_str}", now_str))

    results["SO-03723"] = "Re-linked NJ-LP-939122, released NJ-LP-580930"

    # --------------------------------------------------------------------------
    # 3. SO-2025-06-00098-1
    # --------------------------------------------------------------------------
    # Release phantom serial NJ-LP-399957
    frappe.db.sql("""
        UPDATE `tabSerial No`
        SET reserved_sales_order = NULL,
            order_source = NULL,
            remarks = %s,
            modified = %s
        WHERE name = 'NJ-LP-399957' AND reserved_sales_order = 'SO-2025-06-00098-1'
    """, (f"Released from SO-2025-06-00098-1 on {now_str}: Completed B2B order", now_str))

    # Sync delivered qty and mark SO Completed
    frappe.db.sql("""
        UPDATE `tabSales Order Item`
        SET delivered_qty = 10
        WHERE parent = 'SO-2025-06-00098-1'
          AND item_code = 'S-Dell 5300-CORE I5 - 8TH GEN-16 GB-256 GB SSD'
    """)

    frappe.db.sql("""
        UPDATE `tabSales Order`
        SET per_delivered = 100.0,
            status = 'Completed',
            modified = %s
        WHERE name = 'SO-2025-06-00098-1'
    """, (now_str,))

    results["SO-2025-06-00098-1"] = "Released NJ-LP-399957, marked SO Completed (100% delivered)"

    # Audit comments on Sales Orders
    for so_name, detail in results.items():
        c = frappe.new_doc("Comment")
        c.comment_type = "Comment"
        c.reference_doctype = "Sales Order"
        c.reference_name = so_name
        c.content = f"Repair / Stale Reservation Remediation: {detail}"
        c.insert(ignore_permissions=True)

    frappe.db.commit()
    return results

