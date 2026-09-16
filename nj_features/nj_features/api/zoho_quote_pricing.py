"""
Real ERPNext pricing/tax computation for the Zoho Quotes-module flow.

build_priced_quotation() is the shared core used both by the live
preview webhook below (rep is still editing the Quote in Zoho) and by
zoho_quote_sync.py's final auto-create-and-submit step, so both always
agree on the same number -- computed by ERPNext's own SellingController
logic (set_missing_values + calculate_taxes_and_totals), not
reimplemented here.

Multi-line: a Quote's products come from Zoho's own native "Quoted
Items" subform (Product Name + Quantity per row), not the old single
ERP_Product/Quantity fields -- those are no longer read by this code
(left in place in Zoho, just unused, since removing fields someone
manually created wasn't asked for).

Negotiated price: a Quoted Items row may also carry a Negotiated_Price
(custom field, separate from List_Price -- List_Price is system-
computed output, mixing rep input into it would fight the idempotent
write-skip in _preview_price_and_tax below). When set, it overrides
that line's catalog rate before tax/total are computed, so a rep's
negotiated number flows straight through to ERPNext's Quotation and
Zoho's own List_Price/Grand_Total, without hand-computing tax.

The real price/tax is also pushed onto Zoho's own native per-line
List_Price/Tax fields, not just the custom ERP_Tax_Amount/
ERP_Grand_Total fields -- confirmed by testing that Zoho's native
Sub_Total formula already sums (List_Price*Qty + line Tax) per row, so
it comes out tax-inclusive on its own; Grand_Total = Sub_Total + header
Tax + Adjustment - Discount, so the header Tax field is deliberately
left untouched (0) here -- setting it too double-counts tax, since it's
already folded into Sub_Total via the line-level Tax values. Grand_Total
and Sub_Total are themselves read-only formulas (direct writes are
silently ignored).
"""

import frappe
from frappe.utils import flt
from frappe.utils.password import get_decrypted_password

from nj_features.nj_features.api.zoho_api import zoho_get, zoho_put
from nj_features.nj_features.api.zoho_common import resolve_customer, zoho_now
from nj_features.nj_features.api.zoho_address import resolve_address

COMPANY = "NewJaisa"
SELLING_PRICE_LIST = "Standard Selling"
CURRENCY = "INR"
SALE_TYPE = "NJ-Direct-B2B"  # closest fit among the mandatory Sale Type options, same as the Deals flow


def build_priced_quotation(customer, address_name, line_items):
    """Build an in-memory Quotation (not inserted) with real price-list
    rates and real computed tax across every line. Caller reads
    rate/taxes/grand_total off it for a preview, or inserts + submits it
    for the real thing.

    line_items: list of {"line_id", "item_code", "quantity",
    "negotiated_rate"} dicts, at least one. Appended to quotation.items
    in the same order, so quotation.items[i] always corresponds to
    line_items[i]. negotiated_rate is None for a line still at catalog
    price, or the rep-entered override for a negotiated one -- applied
    after the catalog price-list lookup so it wins, then taxes/totals
    are computed fresh off it like any other rate.
    """
    quotation = frappe.new_doc("Quotation")
    quotation.quotation_to = "Customer"
    quotation.party_name = customer
    quotation.company = COMPANY
    quotation.currency = CURRENCY
    quotation.conversion_rate = 1
    quotation.selling_price_list = SELLING_PRICE_LIST
    quotation.sale_type = SALE_TYPE
    quotation.customer_address = address_name
    quotation.shipping_address_name = address_name
    for li in line_items:
        quotation.append("items", {"item_code": li["item_code"], "qty": flt(li["quantity"])})

    quotation.set_missing_values()

    for li, item in zip(line_items, quotation.items):
        if li.get("negotiated_rate"):
            item.rate = li["negotiated_rate"]

    quotation.calculate_taxes_and_totals()

    return quotation


def native_quoted_items_update(quotation, line_items):
    """Build the Quoted_Items subform payload that writes the real
    ERPNext rate (List_Price) and each line's proportional share of the
    total tax back onto Zoho's own native fields -- List_Price is a
    plain writable Currency field; Zoho's line Total/Net_Total and the
    header Sub_Total/Grand_Total are formula fields that then compute
    themselves from it, so we never write those directly (confirmed
    writes to Grand_Total are silently discarded).
    """
    total_tax = flt(quotation.total_taxes_and_charges)
    net_total = flt(quotation.net_total)
    updates = []
    for li, item in zip(line_items, quotation.items):
        line_amount = flt(item.amount)
        line_tax = (total_tax * line_amount / net_total) if net_total else 0
        updates.append(
            {
                "id": li["line_id"],
                "List_Price": flt(item.rate),
                "Tax": flt(line_tax, 2),
            }
        )
    return updates


def resolve_item_code(product_field):
    """product_field is a Products lookup value (from either the old
    ERP_Product field or a Quoted_Items row's Product_Name):
    {"id": ..., "name": ...} or None/missing.
    """
    if not product_field or not product_field.get("id"):
        return None
    product_detail = zoho_get(f"Products/{product_field['id']}", params={"fields": "ERP_Item_Code"})
    product_data = (product_detail.get("data") or [{}])[0]
    erp_item_code = product_data.get("ERP_Item_Code")
    if not erp_item_code or not frappe.db.exists("Item", erp_item_code):
        return None
    return erp_item_code


def resolve_line_items(quoted_items):
    """quoted_items is the raw Quoted_Items subform list from a Zoho
    Quote row. Returns [{"line_id", "item_code", "quantity",
    "negotiated_rate"}, ...], silently skipping any row that doesn't
    resolve to a real ERPNext Item or has no quantity yet -- the rep
    may still be mid-edit on a row. line_id is that subform row's own
    Zoho id, needed to update it in place (rather than append a new
    row) when pushing List_Price/Tax back. negotiated_rate is None
    unless the rep has typed a value into that row's Negotiated_Price
    field.
    """
    line_items = []
    for row in quoted_items or []:
        item_code = resolve_item_code(row.get("Product_Name"))
        quantity = flt(row.get("Quantity"))
        if item_code and quantity > 0 and row.get("id"):
            line_items.append(
                {
                    "line_id": row["id"],
                    "item_code": item_code,
                    "quantity": quantity,
                    "negotiated_rate": flt(row.get("Negotiated_Price")) or None,
                }
            )
    return line_items


def _check_webhook_secret(webhook_secret):
    expected = get_decrypted_password("Zoho Settings", "Zoho Settings", "webhook_secret", raise_exception=False)
    if not expected or not webhook_secret or webhook_secret != expected:
        frappe.throw("Invalid webhook secret", frappe.PermissionError)


@frappe.whitelist(allow_guest=True)
def preview_price_and_tax(quote_id=None, webhook_secret=None):
    """Webhook target: Zoho fires this (via a Workflow Rule instant
    Webhook action) when a Quote is created/edited (product lines,
    address, etc). Looks up real price + tax across all lines and
    writes it straight back onto that same Quote -- both our own
    ERP_Tax_Amount/ERP_Grand_Total fields and Zoho's native per-line
    List_Price/Tax and header Tax. Best-effort -- the rep is often still
    mid-edit, so incomplete data is a quiet no-op, not an error.

    webhook_secret is sent as a Custom Parameter, not a header -- this
    Zoho account's webhook UI has no way to add custom headers, only
    Module/Custom Parameters and a Body, confirmed by checking the
    actual Create Webhook screen rather than assuming header support.
    """
    _check_webhook_secret(webhook_secret or frappe.form_dict.get("webhook_secret"))

    quote_id = quote_id or frappe.form_dict.get("quote_id")
    if not quote_id:
        return

    try:
        _preview_price_and_tax(quote_id)
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Zoho quote price preview failed for Quote {quote_id}")


def _preview_price_and_tax(quote_id):
    settings = frappe.get_single("Zoho Settings")
    if not settings.enabled:
        return

    result = zoho_get(
        f"Quotes/{quote_id}",
        params={
            "fields": "Account_Name,Quoted_Items,Billing_Street,Billing_City,Billing_State,Billing_Code,"
            "Customer_Email,GSTIN,ERP_Tax_Amount,ERP_Grand_Total,Grand_Total"
        },
    )
    row = (result.get("data") or [{}])[0]

    line_items = resolve_line_items(row.get("Quoted_Items"))
    account = row.get("Account_Name")

    if not line_items or not account or not account.get("id"):
        return  # rep still filling the Quote in -- nothing to preview yet

    customer = resolve_customer(account["id"], quote_id, zoho_get, zoho_put, skip_context="Zoho quote price preview")
    if not customer:
        return

    address_name = resolve_address(row, customer, quote_id)
    if not address_name:
        return  # address not fully filled in yet

    quotation = build_priced_quotation(customer, address_name, line_items)

    # This write-back is itself an edit to the Quote, which would
    # re-trigger the same "on edit" Workflow Rule that called this
    # webhook in the first place -- confirmed to actually happen live
    # (an infinite loop, ~1 request/second, until broken by deleting the
    # test record). Skipping the write entirely when nothing actually
    # changed breaks that loop after at most one extra hop, regardless
    # of how the Zoho Workflow Rule itself is configured (its trigger
    # type turned out to be locked/uneditable after creation).
    old_tax = flt(row.get("ERP_Tax_Amount"))
    old_total = flt(row.get("ERP_Grand_Total"))
    old_native_total = flt(row.get("Grand_Total"))
    new_total = flt(quotation.grand_total)
    if (
        abs(old_tax - flt(quotation.total_taxes_and_charges)) < 0.01
        and abs(old_total - new_total) < 0.01
        and abs(old_native_total - new_total) < 0.01
    ):
        return

    zoho_put(
        f"Quotes/{quote_id}",
        {
            "data": [
                {
                    "id": quote_id,
                    "ERP_Tax_Amount": quotation.total_taxes_and_charges,
                    "ERP_Grand_Total": quotation.grand_total,
                    "ERP_Last_Sync": zoho_now(),
                    "Quoted_Items": native_quoted_items_update(quotation, line_items),
                }
            ]
        },
    )
