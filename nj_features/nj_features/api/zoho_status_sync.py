"""
ERPNext -> Zoho status push-back, for the Zoho-ERPNext Quote Bridge.

Fired via doc_events (see hooks.py) when a Sales Order or Delivery Note
is submitted/cancelled, keeping the originating Zoho record's ERP_*
fields in sync so reps can see order progress without needing ERPNext
access. A Quotation may be linked back to a Zoho Deal (zoho_deal_id,
the Deals-based flow), a Zoho Quote (zoho_quote_id, the Quotes-based
flow), both, or neither -- each gets pushed to independently when set,
since a Sales Order/Delivery Note doesn't know or care which flow its
Quotation came from.

zoho_deal_id/zoho_quote_id carry over automatically from Quotation ->
Sales Order via Frappe's standard mapped-doc field copy (same fieldname
on both doctypes), so no explicit propagation logic is needed there.
"""

import frappe
from frappe.utils import now_datetime

from nj_features.nj_features.api.zoho_api import zoho_put, ZohoAPIError


def _zoho_now():
    return now_datetime().astimezone().isoformat(timespec="seconds")


def _enabled():
    return frappe.get_single("Zoho Settings").enabled


def _push(module, record_id, fields, context):
    try:
        zoho_put(
            f"{module}/{record_id}",
            {"data": [{"id": record_id, **fields, "ERP_Last_Sync": _zoho_now()}]},
        )
    except ZohoAPIError:
        frappe.log_error(
            frappe.get_traceback(), f"Zoho status push-back failed for {module} {record_id} ({context})"
        )


def on_sales_order_submit(doc, method=None):
    if not _enabled():
        return

    if doc.zoho_deal_id:
        _push(
            "Deals",
            doc.zoho_deal_id,
            {
                "ERP_Sales_Order_ID": doc.name,
                "ERP_Order_Value": doc.grand_total,
                "ERP_Quotation_Status": "Order Confirmed",
            },
            "Sales Order submit",
        )

    if doc.zoho_quote_id:
        _push(
            "Quotes",
            doc.zoho_quote_id,
            {
                "ERP_Sales_Order_ID": doc.name,
                "ERP_Grand_Total": doc.grand_total,
                "ERP_Quotation_Status": "Order Confirmed",
            },
            "Sales Order submit",
        )


def on_sales_order_cancel(doc, method=None):
    if not _enabled():
        return

    if doc.zoho_deal_id:
        _push("Deals", doc.zoho_deal_id, {"ERP_Quotation_Status": "Order Cancelled"}, "Sales Order cancel")

    if doc.zoho_quote_id:
        _push("Quotes", doc.zoho_quote_id, {"ERP_Quotation_Status": "Order Cancelled"}, "Sales Order cancel")


def on_delivery_note_submit(doc, method=None):
    if not _enabled():
        return

    sales_orders = {row.against_sales_order for row in doc.items if row.against_sales_order}
    for so_name in sales_orders:
        deal_id, quote_id, per_delivered, per_billed = frappe.db.get_value(
            "Sales Order", so_name, ["zoho_deal_id", "zoho_quote_id", "per_delivered", "per_billed"]
        )
        if not deal_id and not quote_id:
            continue

        dn_rows = frappe.get_all(
            "Delivery Note Item",
            filters={"against_sales_order": so_name, "docstatus": 1},
            fields=["parent"],
            distinct=True,
        )
        dn_names = ", ".join(sorted({row.parent for row in dn_rows}))

        if deal_id:
            _push(
                "Deals",
                deal_id,
                {"ERP_Delivered": per_delivered, "ERP_Billed": per_billed, "ERP_Delivery_Notes": dn_names},
                "Delivery Note submit",
            )
        if quote_id:
            # Quotes module doesn't track ERP_Delivered/ERP_Billed (removed
            # by request -- not needed since Quotes only auto-submits the
            # Quotation, not Sales Order/Delivery Note), just which
            # Delivery Notes exist.
            _push("Quotes", quote_id, {"ERP_Delivery_Notes": dn_names}, "Delivery Note submit")
