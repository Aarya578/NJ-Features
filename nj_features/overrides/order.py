# nj_features/overrides/order.py

import json
import frappe
from frappe.utils import getdate, nowdate, cstr

# Import original modules if you still need them
from ecommerce_integrations.shopify.utils import create_shopify_log
from ecommerce_integrations.shopify.utils import sync_sales_order
from ecommerce_integrations.shopify.product import create_items_if_not_exist

logger = frappe.logger('NewOrder', allow_site=True, file_count=1)
def sync_sales_order(payload, request_id=None):
    logger.info("hii inside sync submit from nj_fetures=============")
    order = payload
    frappe.set_user("Administrator")
    frappe.flags.request_id = request_id

    if frappe.db.get_value("Sales Order", filters={"shopify_order_id": cstr(order["id"])}):
        create_shopify_log(status="Invalid", message="Sales order already exists, not synced")
        return

    try:
        create_items_if_not_exist(order)

        setting = frappe.get_doc("Shopify Settings")
        create_order(order, setting)
    except Exception as e:
        create_shopify_log(status="Error", exception=e, rollback=True)
    else:
        create_shopify_log(status="Success")


def create_order(order, setting, company=None):
    from ecommerce_integrations.shopify.fulfillment import create_delivery_note
    from ecommerce_integrations.shopify.invoice import create_sales_invoice

    so = create_sales_order(order, setting, company)
    if so:
        if order.get("financial_status") == "paid":
            create_sales_invoice(order, setting, so)

        if order.get("fulfillments"):
            create_delivery_note(order, setting, so)


# def create_sales_order(shopify_order, setting, company=None):
#     # ✅ your modified implementation here
#     pass
