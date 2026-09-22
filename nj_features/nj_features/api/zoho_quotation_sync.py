"""
Zoho Deal -> ERPNext Quotation, for the Zoho-ERPNext Quote Bridge.

Runs on a schedule (see hooks.py). Polls Zoho Deals flagged
"Ready to Send to ERP" and creates a draft Quotation for each, then
writes the result back onto the Deal.

Zoho Deals here are single-line (quantity + total amount). The rep can
either pick a specific mirrored product via the ERP_Product lookup, or
just a Products category -- in the latter case the Quotation gets a
generic placeholder line item standing in for the category (see
zoho_sync.py's ITEM_GROUPS_TO_MIRROR docstring). Either way Ops should
double check the line before submitting -- the Quotation is never auto
submitted, matching the "Zoho can create but not submit" rule.
"""

import frappe
from frappe.utils import now_datetime, flt

from nj_features.nj_features.api.zoho_api import zoho_get, zoho_put, ZohoAPIError
from nj_features.nj_features.api.zoho_common import resolve_customer, skip as _skip

COMPANY = "NewJaisa"
SELLING_PRICE_LIST = "Standard Selling"
CURRENCY = "INR"
SALE_TYPE = "NJ-Direct-B2B"  # closest fit for Zoho's B2B deal pipeline among the mandatory Sale Type options

# Zoho Deal "Products" category -> the ERPNext placeholder item standing
# in for it on the draft Quotation. Keep in sync with zoho_sync.py's
# ITEM_GROUPS_TO_MIRROR and the four GENERIC-* items created alongside it.
CATEGORY_TO_PLACEHOLDER_ITEM = {
    "Laptops": "GENERIC-LAPTOPS",
    "Desktops": "GENERIC-DESKTOPS",
    "Laptops(Bundle)": "GENERIC-LAPTOPS-BUNDLE",
    "Desktops(Bundle)": "GENERIC-DESKTOPS-BUNDLE",
}


def _zoho_now():
    return now_datetime().astimezone().isoformat(timespec="seconds")


def _uncheck_ready_flag(deal_id, extra_fields=None):
    fields = {"Ready_to_Send_to_ER": False}
    if extra_fields:
        fields.update(extra_fields)
    zoho_put(f"Deals/{deal_id}", {"data": [{"id": deal_id, **fields}]})


def _resolve_line_item(row):
    """Pick the Quotation line item for a Deal: a rep-selected real product if
    the ERP_Product lookup is set, else the generic category placeholder.

    Returns (item_code, description) or (None, None) if it had to _skip.
    """
    deal_id = row["id"]

    product = row.get("ERP_Product")
    if product and product.get("id"):
        product_detail = zoho_get(f"Products/{product['id']}", params={"fields": "Product_Name,ERP_Item_Code"})
        product_data = (product_detail.get("data") or [{}])[0]
        erp_item_code = product_data.get("ERP_Item_Code")
        if not erp_item_code or not frappe.db.exists("Item", erp_item_code):
            _skip(deal_id, f"ERP_Product {product['id']} has no valid ERP_Item_Code.")
            return None, None
        return erp_item_code, f"Zoho Deal {row.get('Deal_Name')} ({deal_id})"

    category = row.get("Products")
    placeholder_item = CATEGORY_TO_PLACEHOLDER_ITEM.get(category)
    if not placeholder_item:
        _skip(deal_id, f"Products value {category!r} has no mapped placeholder item.")
        return None, None
    return placeholder_item, (
        f"Placeholder for Zoho Deal {row.get('Deal_Name')} ({deal_id}) -- replace with actual item before submitting."
    )


def poll_zoho_deals_and_create_quotations():
    settings = frappe.get_single("Zoho Settings")
    if not settings.enabled:
        return

    result = zoho_get(
        "Deals/search",
        params={
            "criteria": "(Ready_to_Send_to_ER:equals:true)",
            "fields": "Deal_Name,Account_Name,Products,ERP_Product,Quantity,Amount,ERP_Quotation_ID",
            "per_page": 200,
        },
    )
    rows = result.get("data", [])

    for row in rows:
        deal_id = row["id"]
        try:
            _process_deal(row)
        except Exception:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), f"Zoho quotation sync failed for Deal {deal_id}")


def _process_deal(row):
    deal_id = row["id"]

    if row.get("ERP_Quotation_ID"):
        _skip(deal_id, "Ready_to_Send_to_ER was checked again on a Deal that already has an ERP_Quotation_ID.")
        return

    account = row.get("Account_Name")
    if not account or not account.get("id"):
        _skip(deal_id, "No Account selected on the Deal.")
        return

    quantity = flt(row.get("Quantity"))
    if quantity <= 0:
        _skip(deal_id, f"Quantity is {row.get('Quantity')!r}, must be greater than zero.")
        return

    item_code, item_description = _resolve_line_item(row)
    if not item_code:
        return  # _resolve_line_item already called _skip with the reason

    erp_customer_id = resolve_customer(account["id"], deal_id, zoho_get, zoho_put)
    if not erp_customer_id:
        return  # resolve_customer already called skip() with the reason

    amount = flt(row.get("Amount"))
    rate = amount / quantity if amount else 0

    quotation = frappe.new_doc("Quotation")
    quotation.quotation_to = "Customer"
    quotation.party_name = erp_customer_id
    quotation.company = COMPANY
    quotation.currency = CURRENCY
    quotation.conversion_rate = 1
    quotation.selling_price_list = SELLING_PRICE_LIST
    quotation.sale_type = SALE_TYPE
    quotation.zoho_deal_id = deal_id
    quotation.append(
        "items",
        {
            "item_code": item_code,
            "qty": quantity,
            "rate": rate,
            "description": item_description,
        },
    )
    quotation.insert(ignore_permissions=True)
    frappe.db.commit()

    zoho_put(
        f"Deals/{deal_id}",
        {
            "data": [
                {
                    "id": deal_id,
                    "ERP_Quotation_ID": quotation.name,
                    "ERP_Quotation_Status": "Draft",
                    "Currency_1": quotation.grand_total,
                    "ERP_Last_Sync": _zoho_now(),
                    "Ready_to_Send_to_ER": False,
                }
            ]
        },
    )
