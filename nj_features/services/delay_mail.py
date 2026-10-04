"""
Customer delay mail - resent every RESEND_EVERY_DAYS while an order stays late.

Business rule 2026-09-28: a customer whose order is late is mailed, and mailed
again every 2 days until it ships - not on every estimate change (the stock
Value Change Notification did that, and could mail twice in one day or never
again for an order that stayed late at the same estimate).

"Late" is the same test the Notification used:
    estimated_delivery_date - committed_delivery_date >= MIN_DELAY_DAYS

The Notification "Customer Delay Delivery Notification - Sales Order" is kept
DISABLED and used only as the email template (subject, body, recipients).
Notification.send() does not check `enabled` or `condition`, so this job
decides who is due and the template decides what they get. Do not enable the
Notification itself - that would bring back the per-change mail alongside this.

Switched on/off by NJ Settings `delay_mail_enabled` (1 = on). Off by default.
"""

import frappe
from frappe.utils import add_to_date, now_datetime
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error

DELAY_NOTIFICATION = "Customer Delay Delivery Notification - Sales Order"
MIN_DELAY_DAYS = 2
RESEND_EVERY_DAYS = 2
SENT_LOG_METHOD = "delay_mail_sent"

# Scope (business decision 2026-09-28). Without it, the first run would have
# mailed 34,596 orders - mostly Amazon, Charges and years-old RO- orders that
# were never closed. The old per-change Notification never reached them only
# because their estimate stopped changing; a scheduled resend has no such brake.
CUSTOMER_SALE_TYPES = ("NJ-Website-B2C", "NJ-Direct-B2C", "NJ-Website-B2B", "NJ-Direct-B2B")
# Same window the stock sync treats as live demand (SO Quantity Check).
ORDER_AGE_DAYS = 100


def _is_enabled():
    value = frappe.db.get_value("NJ Settings", {"parameter": "delay_mail_enabled"}, "value")
    return str(value or "").strip() == "1"


def get_orders_due_delay_mail():
    """Open, late orders that have not been mailed in the last RESEND_EVERY_DAYS.

    Read only - also used to preview who would be mailed before switching on.
    """
    late = frappe.db.sql("""
        SELECT name, committed_delivery_date, DATE(estimated_delivery_date) AS estimated
        FROM `tabSales Order`
        WHERE docstatus = 1
          AND status NOT IN ('Closed', 'Completed', 'Cancelled', 'On Hold')
          AND IFNULL(per_delivered, 0) < 100
          AND sale_type IN %s
          AND creation > NOW() - INTERVAL %s DAY
          AND committed_delivery_date IS NOT NULL
          AND estimated_delivery_date IS NOT NULL AND estimated_delivery_date != ''
          AND DATEDIFF(DATE(estimated_delivery_date), committed_delivery_date) >= %s
          -- The mail quotes estimated_delivery_date as the new date. One already
          -- in the past is a stale estimate (27 of 115 on 2026-09-28); mailing it
          -- would tell the customer their new date was last week.
          AND DATE(estimated_delivery_date) >= CURDATE()
    """, (CUSTOMER_SALE_TYPES, ORDER_AGE_DAYS, MIN_DELAY_DAYS), as_dict=True)

    # The job runs once a day at a fixed time, so "sent 2 days ago" lands a few
    # seconds either side of exactly 48 hours. The 4-hour margin keeps it on a
    # 2-day rhythm instead of slipping to 3.
    # The cutoff comes from Frappe's clock, not MySQL NOW(): NJ Log.creation is
    # stored in IST but the DB server runs in UTC, and NOW() made the window
    # 5.5h too wide - every resend slipped to day 3.
    cutoff = add_to_date(now_datetime(), hours=-(RESEND_EVERY_DAYS * 24 - 4))
    recent = set(frappe.db.sql_list("""
        SELECT info FROM `tabNJ Log`
        WHERE method = %s AND creation > %s
    """, (SENT_LOG_METHOD, cutoff)))

    return [row for row in late if row.name not in recent]


def send_delay_mails():
    """Daily job: mail every order that is late and due a (re)send."""
    if not _is_enabled():
        return

    if not frappe.db.exists("Notification", DELAY_NOTIFICATION):
        log_error(f"Notification '{DELAY_NOTIFICATION}' not found", "send_delay_mails", "Error")
        return

    sent = 0
    for row in get_orders_due_delay_mail():
        try:
            # Fresh copy per order: Notification.send() renders the CC template
            # into the row in place, so a reused doc would CC the first order's
            # owner on every later customer's mail.
            notification = frappe.get_doc("Notification", DELAY_NOTIFICATION)
            notification.send(frappe.get_doc("Sales Order", row.name))
            # One row per mail: the resend clock reads it, and it is the record
            # of who was told what and when.
            log_error(row.name, SENT_LOG_METHOD, "Info")
            sent += 1
        except Exception:
            log_error(frappe.get_traceback(), "send_delay_mails", "Error")

    frappe.db.commit()
    log_error(f"Delay mails sent: {sent}", "send_delay_mails", "Info")
