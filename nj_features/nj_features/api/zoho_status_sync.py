"""
ERPNext -> Zoho Deal status push-back, for the Zoho-ERPNext Quote Bridge.

Fired via doc_events (see hooks.py) when a Sales Order or Delivery Note
tied to a Zoho Deal (zoho_deal_id) is submitted/cancelled, keeping the
Deal's ERP_* fields in sync so reps can see order progress in Zoho
without needing ERPNext access. zoho_deal_id carries over automatically
from Quotation -> Sales Order via Frappe's standard mapped-doc field
copy (same fieldname on both doctypes), so no explicit propagation
logic is needed there.
"""

import frappe
from frappe.utils import now_datetime

from nj_features.nj_features.api.zoho_api import zoho_put, ZohoAPIError


def _zoho_now():
    return now_datetime().astimezone().isoformat(timespec="seconds")


def _enabled():
    return frappe.get_single("Zoho Settings").enabled


def _push(deal_id, fields, context):
    try:
        zoho_put(
            f"Deals/{deal_id}",
            {"data": [{"id": deal_id, **fields, "ERP_Last_Sync": _zoho_now()}]},
        )
    except ZohoAPIError:
        frappe.log_error(frappe.get_traceback(), f"Zoho status push-back failed for Deal {deal_id} ({context})")


def on_sales_order_submit(doc, method=None):
    if not doc.zoho_deal_id or not _enabled():
        return
    _push(
        doc.zoho_deal_id,
        {
            "ERP_Sales_Order_ID": doc.name,
            "ERP_Order_Value": doc.grand_total,
            "ERP_Quotation_Status": "Order Confirmed",
        },
        "Sales Order submit",
    )


def on_sales_order_cancel(doc, method=None):
    if not doc.zoho_deal_id or not _enabled():
        return
    _push(doc.zoho_deal_id, {"ERP_Quotation_Status": "Order Cancelled"}, "Sales Order cancel")


def on_delivery_note_submit(doc, method=None):
    if not _enabled():
        return

    sales_orders = {row.against_sales_order for row in doc.items if row.against_sales_order}
    for so_name in sales_orders:
        deal_id, per_delivered, per_billed = frappe.db.get_value(
            "Sales Order", so_name, ["zoho_deal_id", "per_delivered", "per_billed"]
        )
        if not deal_id:
            continue

        dn_rows = frappe.get_all(
            "Delivery Note Item",
            filters={"against_sales_order": so_name, "docstatus": 1},
            fields=["parent"],
            distinct=True,
        )
        dn_names = ", ".join(sorted({row.parent for row in dn_rows}))

        _push(
            deal_id,
            {
                "ERP_Delivered": per_delivered,
                "ERP_Billed": per_billed,
                "ERP_Delivery_Notes": dn_names,
            },
            "Delivery Note submit",
        )
