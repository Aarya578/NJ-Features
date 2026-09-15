"""
Zoho Quote -> ERPNext Quotation -> Sales Order, all auto-created AND
auto-submitted with no human review, for the Zoho-ERPNext Quote
Bridge's Quotes-module flow.

Runs on a schedule (see hooks.py), parallel to (not replacing)
zoho_quotation_sync.py's Deals-based flow. Polls Zoho Quotes flagged
"Ready to Send to ERP" and, for each one, builds a fully priced and
taxed multi-line Quotation (one line per row in the Quote's native
Quoted Items subform, each with a real price-list rate; real GST; real
Address), submits it, then immediately also creates, approves, and
submits the Sales Order from it -- explicitly requested (this reverses
the rest of the bridge's usual "Zoho can create but not submit" rule
for both of these steps, not just the Quotation). Delivery Note still
requires a human in ERPNext -- it fundamentally needs a warehouse
person assigning real physical Serial Numbers, which can't be
automated -- so that step stays exactly as zoho_status_sync.py already
handles it.

The Sales Order's status push-back to Zoho isn't duplicated here --
so.submit() triggers hooks.py's existing on_sales_order_submit doc
event (see zoho_status_sync.py), same as it would for a manually
submitted Sales Order.
"""

import frappe
from frappe.utils import add_days, nowdate

from nj_features.nj_features.api.zoho_api import zoho_get, zoho_put
from nj_features.nj_features.api.zoho_common import resolve_customer, skip, zoho_now
from nj_features.nj_features.api.zoho_address import resolve_address
from nj_features.nj_features.api.zoho_quote_pricing import (
    build_priced_quotation,
    resolve_line_items,
    native_quoted_items_update,
)

from erpnext.selling.doctype.quotation.quotation import make_sales_order

SKIP_CONTEXT = "Zoho quote auto-submit"
SALES_CHANNEL = "B2B"  # matches SALE_TYPE ("NJ-Direct-B2B") in zoho_quote_pricing.py


def poll_zoho_quotes_and_create_quotations():
    settings = frappe.get_single("Zoho Settings")
    if not settings.enabled:
        return

    # Quotes/search does not return subform (Quoted_Items) data -- a real
    # Zoho API limitation, confirmed by testing, not an oversight -- so
    # search is only used to find which records are ready; each match
    # gets a follow-up direct GET for the full row including line items.
    result = zoho_get(
        "Quotes/search",
        params={
            "criteria": "(Ready_to_Send_to_ERP:equals:true)",
            "fields": "ERP_Quotation_ID",
            "per_page": 200,
        },
    )
    candidate_ids = [row["id"] for row in result.get("data", [])]

    for quote_id in candidate_ids:
        try:
            detail = zoho_get(
                f"Quotes/{quote_id}",
                params={
                    "fields": "Account_Name,Quoted_Items,Billing_Street,Billing_City,Billing_State,"
                    "Billing_Code,Customer_Email,GSTIN,ERP_Quotation_ID"
                },
            )
            row = (detail.get("data") or [{}])[0]
            _process_quote(row)
        except Exception:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), f"{SKIP_CONTEXT} failed for Quote {quote_id}")


def _process_quote(row):
    quote_id = row["id"]

    if row.get("ERP_Quotation_ID"):
        skip(quote_id, "Ready_to_Send_to_ERP was checked again on a Quote that already has an ERP_Quotation_ID.", SKIP_CONTEXT)
        return

    account = row.get("Account_Name")
    if not account or not account.get("id"):
        skip(quote_id, "No Account selected on the Quote.", SKIP_CONTEXT)
        return

    line_items = resolve_line_items(row.get("Quoted_Items"))
    if not line_items:
        skip(quote_id, "Quoted Items has no rows with a valid product and quantity.", SKIP_CONTEXT)
        return

    customer = resolve_customer(account["id"], quote_id, zoho_get, zoho_put, skip_context=SKIP_CONTEXT)
    if not customer:
        return  # resolve_customer already called skip() with the reason

    address_name = resolve_address(row, customer, quote_id)
    if not address_name:
        skip(
            quote_id,
            "Billing Address fields (Street/City/State/Zip/Customer Email) are incomplete.",
            SKIP_CONTEXT,
        )
        return

    quotation = build_priced_quotation(customer, address_name, line_items)
    quotation.zoho_quote_id = quote_id
    quotation.insert(ignore_permissions=True)
    quotation.submit()
    frappe.db.commit()

    zoho_put(
        f"Quotes/{quote_id}",
        {
            "data": [
                {
                    "id": quote_id,
                    "ERP_Quotation_ID": quotation.name,
                    "ERP_Quotation_Status": "Confirmed",
                    "ERP_Tax_Amount": quotation.total_taxes_and_charges,
                    "ERP_Grand_Total": quotation.grand_total,
                    "ERP_Last_Sync": zoho_now(),
                    "Ready_to_Send_to_ERP": False,
                    "Quoted_Items": native_quoted_items_update(quotation, line_items),
                }
            ]
        },
    )

    _auto_create_sales_order(quotation, quote_id)


def _auto_create_sales_order(quotation, quote_id):
    """Auto-create, approve, and submit the Sales Order right after the
    Quotation -- no human review, per explicit instruction. If this
    fails, the Quotation above is already safely submitted and pushed
    to Zoho, so a failure here doesn't risk a duplicate Quotation on the
    next poll (the ERP_Quotation_ID guard in _process_quote already
    prevents reprocessing) -- it just leaves the Sales Order for Ops to
    create manually via the standard "Make Sales Order" button, logged
    here for visibility.
    """
    try:
        so = make_sales_order(quotation.name)
        so.delivery_date = add_days(nowdate(), 7)
        so.sales_channel = SALES_CHANNEL
        so.approve = 1
        so.insert(ignore_permissions=True)
        so.submit()
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(
            frappe.get_traceback(),
            f"{SKIP_CONTEXT}: Sales Order auto-creation failed for Quote {quote_id} "
            f"(Quotation {quotation.name} already submitted successfully)",
        )
