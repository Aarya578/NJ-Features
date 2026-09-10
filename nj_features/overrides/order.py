# nj_features/overrides/order.py
import json
import frappe
from frappe import _
from ecommerce_integrations.shopify import utils as shopify_utils
from frappe.utils import add_days, cint, cstr, flt, get_datetime, getdate, nowdate
# from ecommerce_integrations.shopify.product import create_items_if_not_exist

# from ecommerce_integrations.shopify.product import create_items_if_not_exist
from nj_features.overrides.product import create_items_if_not_exist,get_item_code
# from ecommerce_integrations.shopify.product import create_items_if_not_exist
from ecommerce_integrations.shopify.constants import (
    CUSTOMER_ID_FIELD,
    EVENT_MAPPER,
    ORDER_ID_FIELD,
    ORDER_ITEM_DISCOUNT_FIELD,
    ORDER_NUMBER_FIELD,
    ORDER_STATUS_FIELD,
    SETTING_DOCTYPE,
)
from ecommerce_integrations.utils.price_list import get_dummy_price_list
from nj_features.overrides.customer import ShopifyCustomer

logger = frappe.logger('SHopifyNJOrder', allow_site=True, file_count=1)
def sync_sales_order(payload, request_id=None):
    order = payload
    frappe.set_user("Administrator")
    frappe.flags.request_id = request_id

    if frappe.db.get_value("Sales Order", filters={ORDER_ID_FIELD: cstr(order["id"])}):
        shopify_utils.create_shopify_log(status="Invalid", message="Sales order already exists, not synced")
        return
    try:
        shopify_customer = order.get("customer", {})
        shopify_customer["billing_address"] = order.get("billing_address")
        shopify_customer["shipping_address"] = order.get("shipping_address")
        customer_id = shopify_customer.get("id")
        if customer_id:
            customer = ShopifyCustomer(customer_id=customer_id)
            if not customer.is_synced():
                customer.sync_customer(customer=shopify_customer)
            else:
                customer.update_existing_addresses(shopify_customer)

        create_items_if_not_exist(order)

        setting = frappe.get_doc(SETTING_DOCTYPE)
        create_order(order, setting)
    except Exception as e:
        shopify_utils.create_shopify_log(status="Error", exception=e, rollback=True)
    else:
        shopify_utils.create_shopify_log(status="Success")

def create_order(order, setting, company=None):
    from ecommerce_integrations.shopify.fulfillment import create_delivery_note
    from ecommerce_integrations.shopify.invoice import create_sales_invoice

    si_partial_submission_rqd = frappe.db.get_value("NJ Settings", {"parameter": "si_partially_paid_submission"}, "value")

    so = create_sales_order(order, setting, company)
    if so:
        if order.get("financial_status") == "paid":
            create_sales_invoice(order, setting, so)

        elif order.get("financial_status") == "partially_paid":
            if int(si_partial_submission_rqd or 0) == 1: 
                create_sales_invoice(order, setting, so)

        if order.get("fulfillments"):
            create_delivery_note(order, setting, so)


def get_latest_customer_addresses(customer_name):
    """Get the most recently created billing and shipping addresses for a customer"""
    
    # Get latest billing address
    billing_address = frappe.db.sql("""
        SELECT name 
        FROM `tabAddress` 
        WHERE address_type = 'Billing' 
        AND is_primary_address = 0
        AND EXISTS (
            SELECT 1 FROM `tabDynamic Link` dl 
            WHERE dl.parent = `tabAddress`.name 
            AND dl.link_doctype = 'Customer' 
            AND dl.link_name = %s
        )
        ORDER BY creation DESC 
        LIMIT 1
    """, [customer_name], as_dict=True)
    # logger.info(f"billing address ========316======{billing_address}")
    # Get latest shipping address
    shipping_address = frappe.db.sql("""
        SELECT name 
        FROM `tabAddress` 
        WHERE address_type = 'Shipping'
        AND is_shipping_address = 0
        AND EXISTS (
            SELECT 1 FROM `tabDynamic Link` dl 
            WHERE dl.parent = `tabAddress`.name 
            AND dl.link_doctype = 'Customer' 
            AND dl.link_name = %s
        )
        ORDER BY creation DESC 
        LIMIT 1
    """, [customer_name], as_dict=True)
    # logger.info(f"shipping address ========316======{shipping_address}")
    return {
        'billing_address': billing_address[0].name if billing_address else None,
        'shipping_address': shipping_address[0].name if shipping_address else None
    }
# def create_sales_order(shopify_order, setting, company=None):   
#     logger.info(f"shopify_order ====from njfeatures====316======{shopify_order}")      
#     customer = setting.default_customer
#     if customer_id := shopify_order.get("customer", {}).get("id"):
#         customer = frappe.db.get_value("Customer", {CUSTOMER_ID_FIELD: customer_id}, "name")
    
#     so = frappe.db.get_value("Sales Order", {ORDER_ID_FIELD: shopify_order.get("id")}, "name")
#     if not so:
#         # Determine naming series based on tags
#         naming_series = setting.sales_order_series or "SO-Shopify-"
        
#         # Check for specific tags in the order
#         tags = shopify_order.get("tags", "")
#         is_snapmint = False
#         snapmint_id = None
        
#         if tags:
#             tags_list = [tag.strip().lower() for tag in tags.split(",")]
#             # Check for any of the specified tags
#             special_tags = ["snapmint_emi_str"]
#             if all(tag in tags_list for tag in special_tags):
#                 naming_series = "SO-Snapmint-"
#                 is_snapmint = True
                
#                 # Extract Snapmint ID from tags (format: snapmint_XXXXXXXX)
#                 for tag in tags_list:
#                     if tag.startswith("snapmint_") and tag != "snapmint_emi_str":
#                         snapmint_id = tag.replace("snapmint_", "")
#                         break
        
#         # FIXED: Pass shipping_lines to get_order_items
#         # items = get_order_items(
#         #     shopify_order.get("line_items"),
#         #     setting,
#         #     getdate(shopify_order.get("created_at")),
#         #     taxes_inclusive=shopify_order.get("taxes_included"),
#         # )
#         items = get_order_items(
#             shopify_order.get("line_items"),
#             setting,
#             getdate(shopify_order.get("created_at")),
#             taxes_inclusive=shopify_order.get("taxes_included"),
#             shopify_response=shopify_order  # Pass the full order so we can check coupons
#         )

#         if not items:
#             message = (
#                 "Following items exist in the Shopify order but relevant records were "
#                 "not found in the Shopify Product Master"
#             )
#             product_not_exists = [] # TODO: Fix missing items
#             message += "\n" + ", ".join(product_not_exists)
#             create_shopify_log(status="Error", exception=message, rollback=True)
#             return ""
            
#         # taxes = get_order_taxes(shopify_order, setting, items)
#         taxes = get_order_taxes(shopify_order, setting, items)

#         # Determine if the order should be marked as COD
#         is_cod = 1 if shopify_order.get("financial_status") == "partially_paid" else 0     
#         payment_id = shopify_order.get("source_identifier")
#         if is_snapmint and snapmint_id:
#             payment_id = snapmint_id
        
#         # Get the latest addresses for the customer
#         latest_addresses = get_latest_customer_addresses(customer)
#         logger.info(f"latest_addresses ========316======{latest_addresses}")
        
#         so_data = {
#             "doctype": "Sales Order",
#             "naming_series": naming_series,
#             ORDER_ID_FIELD: str(shopify_order.get("id")),
#             ORDER_NUMBER_FIELD: shopify_order.get("name"),
#             "customer": customer,
#             "transaction_date": getdate(shopify_order.get("created_at")) or nowdate(),
#             "delivery_date": getdate(shopify_order.get("created_at")) or nowdate(),
#             "company": setting.company,
#             "selling_price_list": get_dummy_price_list(),
#             "ignore_pricing_rule": 1,
#             "items": items,
#             "taxes": taxes,
#             "payment_id": payment_id,
#             "sale_type": shopify_order.get("sale_type") or "NJ-Website-B2C",
#             "shopify_order_id": str(shopify_order.get("order_number", "")),
#             "total_outstanding": str(shopify_order.get("total_outstanding", "")),
#             "shopify_order_number": str(shopify_order.get("id", "")),
#             "sales_channel":"Shopify",
#             "is_cod": is_cod,
#             # "taxes_and_charges": setting.default_taxes_and_charges
            
#         }

    
#         # Set the latest addresses if available
#         if latest_addresses['billing_address']:
#             so_data["customer_address"] = latest_addresses['billing_address']
        
#         if latest_addresses['shipping_address']:
#             so_data["shipping_address_name"] = latest_addresses['shipping_address']
        
#         so = frappe.get_doc(so_data)
#         # logger.info(f"so_data ========316======{so_data}")
           
#         if company:
#             so.update({"company": company, "status": "Draft"})
        
#         nj_setting_value = frappe.db.get_value(
#             "NJ Settings", 
#             {"parameter": "sale_type"}, 
#             "value"
#         )
#         # Skip if sale_type doesn't match NJ setting
#         if so.sale_type != nj_setting_value:
#             return
#         logger.info(f"so_data ========316======{so_data.payment_id}")
#         if so.payment_id:
#             existing_so = frappe.db.get_value(
#                 "Sales Order",
#                 {
#                     "payment_id": so.payment_id,
#                     "docstatus": 1,
#                     "name": ["!=", so.name]  # exclude self
#                 },
#                 "name"
#             )
#             logger.info(f"existing_so ========316======{existing_so}")

#             if existing_so:
#                 frappe.throw(
#                     f"Payment ID '{so.payment_id}' is already used in Sales Order: {existing_so}"
#                 )
#             else:
#                 so.approve = 1
        
#         so.flags.ignore_mandatory = True
#         so.flags.shopify_order_json = json.dumps(shopify_order)
        
#         # Fetch submission setting from NJ Settings
#         so_submission_rqd = frappe.db.get_value("NJ Settings", {"parameter": "so_shopify_submission"}, "value")
#         if int(so_submission_rqd or 0) == 1:
#             so.save(ignore_permissions=True)
#             so.submit()
        
#         if shopify_order.get("note"):
#             so.add_comment(text=f"Order Note: {shopify_order.get('note')}")
#     else:
#         so = frappe.get_doc("Sales Order", so)
    
#     return so
def create_sales_order(shopify_order, setting, company=None):

    logger.info(f"shopify_order ====from njfeatures====316======{shopify_order}")

    customer = setting.default_customer

    if customer_id := shopify_order.get("customer", {}).get("id"):
        customer = frappe.db.get_value("Customer", {CUSTOMER_ID_FIELD: customer_id}, "name")

    # Check if Shopify order already exists
    existing_so = frappe.db.get_value(
        "Sales Order",
        {ORDER_ID_FIELD: str(shopify_order.get("id"))},
        "name"
    )

    if existing_so:
        return frappe.get_doc("Sales Order", existing_so)

    naming_series = setting.sales_order_series or "SO-Shopify-"

    tags = shopify_order.get("tags", "")
    tags_list = [tag.strip().lower() for tag in tags.split(",")] if tags else []

    is_snapmint = False
    snapmint_id = None

    # Detect Snapmint order
    if "snapmint_emi_str" in tags_list:
        naming_series = "SO-Snapmint-"
        is_snapmint = True

        for tag in tags_list:
            if tag.startswith("snapmint_") and tag not in ["snapmint", "snapmint_emi_str"]:
                snapmint_id = tag.replace("snapmint_", "")
                break

    order_txn_date = getdate(shopify_order.get("created_at")) or nowdate()
    default_delivery_date = add_days(order_txn_date, 4)

    # Get order items
    items = get_order_items(
        shopify_order.get("line_items"),
        setting,
        default_delivery_date,
        taxes_inclusive=shopify_order.get("taxes_included"),
        shopify_response=shopify_order
    )

    if not items:
        message = (
            "Following items exist in the Shopify order but relevant records were "
            "not found in the Shopify Product Master"
        )
        shopify_utils.create_shopify_log(status="Error", exception=message, rollback=True)
        return ""

    taxes = get_order_taxes(shopify_order, setting, items)

    # COD detection
    is_cod = 1 if shopify_order.get("financial_status") == "partially_paid" else 0

    payment_id = shopify_order.get("source_identifier")

    # Shopify product properties normally belong to individual line items.
    # Set the Sales Order checkbox only when at least one property explicitly
    # identifies the purchase as an NM pre-order.
    property_groups = [shopify_order.get("properties") or []]
    property_groups.extend(
        line_item.get("properties") or []
        for line_item in (shopify_order.get("line_items") or [])
    )
    is_pre_order = int(any(
        str(prop.get("name") or "").strip() == "_purchase_type"
        and str(prop.get("value") or "").strip() == "NM-preorder"
        for properties in property_groups
        for prop in properties
        if isinstance(prop, dict)
    ))


    if is_snapmint and snapmint_id:
        payment_id = snapmint_id

    logger.info(f"Payment ID used for Sales Order: {payment_id}")

    # Check duplicate payment_id only for submitted documents
    if payment_id:

        existing_payment_so = frappe.db.exists(
            "Sales Order",
            {
                "payment_id": payment_id,
                "docstatus": 1
            }
        )

        if existing_payment_so:
            frappe.throw(
                f"Payment ID '{payment_id}' already used in Submitted Sales Order: {existing_payment_so}"
            )

    latest_addresses = get_latest_customer_addresses(customer)

    so_data = {
        "doctype": "Sales Order",
        "naming_series": naming_series,
        ORDER_ID_FIELD: str(shopify_order.get("id")),
        ORDER_NUMBER_FIELD: shopify_order.get("name"),
        "customer": customer,
        "transaction_date": order_txn_date,
        "delivery_date": default_delivery_date,
        "committed_delivery_date": default_delivery_date,
        "company": setting.company,
        "selling_price_list": get_dummy_price_list(),
        "ignore_pricing_rule": 1,
        "items": items,
        "taxes": taxes,
        "payment_id": payment_id,
        "sale_type": shopify_order.get("sale_type") or "NJ-Website-B2C",
        "total_outstanding": str(shopify_order.get("total_outstanding", "")),
        "sales_channel": "Shopify",
        "is_cod": is_cod,
        "pre_order": is_pre_order
    }

    if latest_addresses.get("billing_address"):
        so_data["customer_address"] = latest_addresses.get("billing_address")

    if latest_addresses.get("shipping_address"):
        so_data["shipping_address_name"] = latest_addresses.get("shipping_address")

    so = frappe.get_doc(so_data)

    if company:
        so.update({
            "company": company,
            "status": "Draft"
        })

    nj_setting_value = frappe.db.get_value(
        "NJ Settings",
        {"parameter": "sale_type"},
        "value"
    )

    if so.sale_type != nj_setting_value:
        return

    if so.payment_id:
        so.approve = 1

    so.flags.ignore_mandatory = True
    so.flags.shopify_order_json = json.dumps(shopify_order)

    so_submission_rqd = frappe.db.get_value(
        "NJ Settings",
        {"parameter": "so_shopify_submission"},
        "value"
    )

    if int(so_submission_rqd or 0) == 1:
        so.save(ignore_permissions=True)
        so.submit()
    else:
        so.save(ignore_permissions=True)

    if shopify_order.get("note"):
        so.add_comment(text=f"Order Note: {shopify_order.get('note')}")

    return so

def get_order_items(order_items, setting, delivery_date, taxes_inclusive, shopify_response=None):
    items = []
    all_product_exists = True
    product_not_exists = []

    # -----------------------------
    # Normal Shopify Items
    # -----------------------------
    for shopify_item in order_items:
        if not shopify_item.get("product_exists"):
            all_product_exists = False
            product_not_exists.append({
                "title": shopify_item.get("title"),
                ORDER_ID_FIELD: shopify_item.get("id")
            })
            continue

        if all_product_exists:
            item_code = get_item_code(shopify_item)

            items.append({
                "item_code": item_code,
                "item_name": item_code,
                "qty": shopify_item.get("quantity"),
                "delivery_date": delivery_date,
                "stock_uom": shopify_item.get("uom") or "Nos",
                "warehouse": setting.warehouse,

                # normal pricing
                "rate": _get_item_price(shopify_item, taxes_inclusive),
                ORDER_ITEM_DISCOUNT_FIELD: (
                    _get_total_discount(shopify_item) / cint(shopify_item.get("quantity"))
                ),
            })
        else:
            items = []

    # -----------------------------
    # Coupon Logic
    # -----------------------------
    if shopify_response and all_product_exists:
        try:
            logistics_settings = frappe.get_single("Logistics Settings")

            if logistics_settings and logistics_settings.coupon_codes:

                # Build coupon map
                coupon_map = {}
                for c in logistics_settings.coupon_codes:
                    if c.code:
                        code = c.code.strip()
                        coupon_map.setdefault(code, []).append({
                            "item_code": c.item_code,
                            "apply_coupen_code": c.apply_coupen_code
                        })

                # Get discount code
                discount_code = ""
                if shopify_response.get("discount_codes"):
                    discount_code = (shopify_response["discount_codes"][0].get("code") or "").strip()

                elif shopify_response.get("discount_applications"):
                    discount_code = (shopify_response["discount_applications"][0].get("description") or "").strip()

                # Apply coupon items
                if discount_code and discount_code in coupon_map:

                    total_qty = sum(
                        li.get("fulfillable_quantity", 0)
                        for li in shopify_response.get("line_items", [])
                    )

                    for entry in coupon_map[discount_code]:
                        item_code = entry["item_code"]
                        apply_flag = entry.get("apply_coupen_code", 0)

                        qty = total_qty if apply_flag == 1 else 1

                        items.append({
                            "item_code": item_code,
                            "item_name": item_code,
                            "qty": qty,
                            "delivery_date": delivery_date,
                            "stock_uom": "Nos",
                            "warehouse": setting.warehouse,

                            # 🔥 FORCE ZERO PRICE (IMPORTANT)
                            "rate": 0,
                            "price_list_rate": 0,
                            "base_rate": 0,
                            "base_price_list_rate": 0,
                            "discount_percentage": 100,
                            "discount_amount": 0,

                            # 🔥 BLOCK ERP PRICING ENGINE
                            "is_free_item": 1,
                            "ignore_pricing_rule": 1,
                        })

        except Exception:
            frappe.log_error(f"Coupon code processing failed: {frappe.get_traceback()}")

    return items
# def get_order_items(order_items, setting, delivery_date, taxes_inclusive, shopify_response=None):
#     items = []
#     all_product_exists = True
#     product_not_exists = []
    
#     for shopify_item in order_items:
#         if not shopify_item.get("product_exists"):
#             all_product_exists = False
#             product_not_exists.append(
#                 {"title": shopify_item.get("title"), ORDER_ID_FIELD: shopify_item.get("id")}
#             )
#             continue
            
#         if all_product_exists:
#             item_code = get_item_code(shopify_item)
#             items.append(
#                 {
#                     "item_code": item_code,
#                     "item_name": item_code,
#                     "rate": _get_item_price(shopify_item, taxes_inclusive),  # Fixed: added underscore
#                     "delivery_date": delivery_date,
#                     "qty": shopify_item.get("quantity"),
#                     "stock_uom": shopify_item.get("uom") or "Nos",
#                     "warehouse": setting.warehouse,
#                     ORDER_ITEM_DISCOUNT_FIELD: (
#                         _get_total_discount(shopify_item) / cint(shopify_item.get("quantity"))  # Fixed: added underscore
#                     ),
#                 }
#             )
#         else:
#             items = []
#     if shopify_response and all_product_exists:
#         try:
#             logistics_settings = frappe.get_single("Logistics Settings")
#             if logistics_settings and logistics_settings.coupon_codes:

#                 coupon_map = {}
#                 for c in logistics_settings.coupon_codes:
#                     if c.code:
#                         code = c.code.strip()
#                         coupon_map.setdefault(code, []).append({
#                             "item_code": c.item_code,
#                             "apply_coupen_code": c.apply_coupen_code
#                         })

#                 # ✅ Get coupon code from discount_codes first
#                 discount_code = ""
#                 if shopify_response.get("discount_codes"):
#                     discount_code = (shopify_response["discount_codes"][0].get("code") or "").strip()

#                 # ✅ If discount_codes empty, fallback to discount_applications.description
#                 elif shopify_response.get("discount_applications"):
#                     discount_code = (shopify_response["discount_applications"][0].get("description") or "").strip()

#                 # ✅ Continue only if discount_code exists in our mapping
#                 if discount_code and discount_code in coupon_map:
#                     total_qty = sum(
#                         li.get("fulfillable_quantity", 0)
#                         for li in shopify_response.get("line_items", [])
#                     )

#                     for entry in coupon_map[discount_code]:
#                         item_code = entry["item_code"]
#                         apply_flag = entry.get("apply_coupen_code", 0)

#                         qty = total_qty if apply_flag == 1 else 1

#                         items.append({
#                             "item_code": item_code,
#                             "item_name": item_code,
#                             "rate": 0,
#                             "delivery_date": delivery_date,
#                             "qty": qty,
#                             "stock_uom": "Nos",
#                             "warehouse": setting.warehouse,
#                         })

#         except Exception:
#             frappe.log_error(
#                 f"Coupon code processing failed: {frappe.get_traceback()}"
#             )

    # if shopify_response and shopify_response.get("discount_codes") and all_product_exists:
    #     try:
    #         logistics_settings = frappe.get_single("Logistics Settings")
    #         if logistics_settings and logistics_settings.coupon_codes:
    #             # Build mapping of coupon_code -> list of (item_code, apply_coupen_code)
    #             coupon_map = {}
    #             for c in logistics_settings.coupon_codes:
    #                 if c.code:
    #                     code = c.code.strip()
    #                     coupon_map.setdefault(code, []).append({
    #                         "item_code": c.item_code,
    #                         "apply_coupen_code": c.apply_coupen_code
    #                     })

    #             # Take first discount code from discount_codes
    #             discount_code = (shopify_response["discount_codes"][0].get("code") or "").strip()

    #             if discount_code in coupon_map:
    #                 # Calculate total fulfillable qty from line_items
    #                 total_qty = sum(
    #                     li.get("fulfillable_quantity", 0) 
    #                     for li in shopify_response.get("line_items", [])
    #                 )

    #                 for entry in coupon_map[discount_code]:
    #                     item_code = entry["item_code"]
    #                     apply_flag = entry.get("apply_coupen_code", 0)

    #                     # qty depends on apply_coupen_code
    #                     qty = total_qty if apply_flag == 1 else 1

    #                     items.append(
    #                         {
    #                             "item_code": item_code,
    #                             "item_name": item_code,
    #                             "rate": 0,
    #                             "delivery_date": delivery_date,
    #                             "qty": qty,
    #                             "stock_uom": "Nos",
    #                             "warehouse": setting.warehouse,
    #                         }
    #                     )
    #     except Exception as e:
    #         frappe.log_error(f"Coupon code processing failed: {frappe.get_traceback()}")

    return items
def get_order_taxes(shopify_order, setting, items):
    taxes = []
    line_items = shopify_order.get("line_items")

    # collect all item_codes from order items (including coupon/freebies)
    all_item_codes = [it["item_code"] for it in items]

    for line_item in line_items:
        item_code = get_item_code(line_item)
        for tax in line_item.get("tax_lines"):
            # Build full tax detail JSON with ALL items
            tax_detail = {}
            for ic in all_item_codes:
                if ic == item_code:
                    tax_detail[ic] = [
                        flt(tax.get("rate")) * 100,
                        flt(tax.get("price"))   
                    ]
                else:
                    # ensure item present but zero if not taxed
                    tax_detail[ic] = [0.0, 0.0]

            taxes.append(
                {
                    "charge_type": "Actual",
                    "account_head": get_tax_account_head(tax),
                    "description": (
                        get_tax_account_description(tax)
                        or f"{tax.get('title')} - {tax.get('rate') * 100.0:.2f}%"
                    ),
                    "tax_amount": tax.get("price"),
                    "included_in_print_rate": 0,
                    "cost_center": setting.cost_center,
                    "item_wise_tax_detail": json.dumps(tax_detail),
                    "dont_recompute_tax": 1,
                }
            )

    update_taxes_with_shipping_lines(
        taxes,
        shopify_order.get("shipping_lines"),
        setting,
        items,
        taxes_inclusive=shopify_order.get("taxes_included"),
    )

    if cint(setting.consolidate_taxes):
        taxes = consolidate_order_taxes(taxes)

    return taxes

# def get_order_taxes(shopify_order, setting, items):
#     taxes = []
#     line_items = shopify_order.get("line_items")

#     for line_item in line_items:
#         item_code = get_item_code(line_item)
#         for tax in line_item.get("tax_lines"):
#             taxes.append(
#                 {
#                     "charge_type": "Actual",
#                     "account_head": get_tax_account_head(tax),
#                     "description": (
#                         get_tax_account_description(tax) or f"{tax.get('title')} - {tax.get('rate') * 100.0:.2f}%"
#                     ),
#                     "tax_amount": tax.get("price"),
#                     "included_in_print_rate": 0,
#                     "cost_center": setting.cost_center,
#                     "item_wise_tax_detail": {item_code: [flt(tax.get("rate")) * 100, flt(tax.get("price"))]},
#                     "dont_recompute_tax": 1,
#                 }
#             )

#     update_taxes_with_shipping_lines(
#         taxes,
#         shopify_order.get("shipping_lines"),
#         setting,
#         items,
#         taxes_inclusive=shopify_order.get("taxes_included"),
#     )

#     if cint(setting.consolidate_taxes):
#         taxes = consolidate_order_taxes(taxes)

#     for row in taxes:
#         tax_detail = row.get("item_wise_tax_detail")
#         if isinstance(tax_detail, dict):
#             row["item_wise_tax_detail"] = json.dumps(tax_detail)

#     return taxes

def get_tax_account_description(tax):
    tax_title = tax.get("title")

    tax_description = frappe.db.get_value(
        "Shopify Tax Account", {"parent": SETTING_DOCTYPE, "shopify_tax": tax_title}, "tax_description",
    )

    return tax_description

def _get_item_price(line_item, taxes_inclusive: bool) -> float:

    price = flt(line_item.get("price"))
    qty = cint(line_item.get("quantity"))

    # remove line item level discounts
    total_discount = _get_total_discount(line_item)

    if not taxes_inclusive:
        return price - (total_discount / qty)

    total_taxes = 0.0
    for tax in line_item.get("tax_lines"):
        total_taxes += flt(tax.get("price"))

    return price - (total_taxes + total_discount) / qty

def _get_total_discount(line_item) -> float:
    discount_allocations = line_item.get("discount_allocations") or []
    return sum(flt(discount.get("amount")) for discount in discount_allocations)

def get_tax_account_head(tax):
    tax_title = str(tax.get("title"))

    tax_account = frappe.db.get_value(
        "Shopify Tax Account", {"parent": SETTING_DOCTYPE, "shopify_tax": tax_title}, "tax_account",
    )

    if not tax_account:
        frappe.throw(_("Tax Account not specified for Shopify Tax {0}").format(tax.get("title")))

    return tax_account

def update_taxes_with_shipping_lines(taxes, shipping_lines, setting, items, taxes_inclusive=False):
    """Shipping lines represents the shipping details,
    each such shipping detail consists of a list of tax_lines"""
    shipping_as_item = cint(setting.add_shipping_as_item) and setting.shipping_item
    for shipping_charge in shipping_lines:
        if shipping_charge.get("price"):
            shipping_discounts = shipping_charge.get("discount_allocations") or []
            total_discount = sum(flt(discount.get("amount")) for discount in shipping_discounts)

            shipping_taxes = shipping_charge.get("tax_lines") or []
            total_tax = sum(flt(discount.get("price")) for discount in shipping_taxes)

            shipping_charge_amount = flt(shipping_charge["price"]) - flt(total_discount)
            if bool(taxes_inclusive):
                shipping_charge_amount -= total_tax

            if shipping_as_item:
                items.append(
                    {
                        "item_code": setting.shipping_item,
                        "rate": shipping_charge_amount,
                        "delivery_date": items[-1]["delivery_date"] if items else nowdate(),
                        "qty": 1,
                        "stock_uom": "Nos",
                        "warehouse": setting.warehouse,
                    }
                )
            else:
                taxes.append(
                    {
                        "charge_type": "Actual",
                        "account_head": get_tax_account_head(shipping_charge),
                        "description": get_tax_account_description(shipping_charge) or shipping_charge["title"],
                        "tax_amount": shipping_charge_amount,
                        "cost_center": setting.cost_center,
                    }
                )

        for tax in shipping_charge.get("tax_lines"):
            taxes.append(
                {
                    "charge_type": "Actual",
                    "account_head": get_tax_account_head(tax),
                    "description": (
                        get_tax_account_description(tax) or f"{tax.get('title')} - {tax.get('rate') * 100.0:.2f}%"
                    ),
                    "tax_amount": tax["price"],
                    "cost_center": setting.cost_center,
                    "item_wise_tax_detail": {
                        setting.shipping_item: [flt(tax.get("rate")) * 100, flt(tax.get("price"))]
                    }
                    if shipping_as_item
                    else {},
                    "dont_recompute_tax": 1,
                }
            )
def consolidate_order_taxes(taxes):
    tax_account_wise_data = {}
    for tax in taxes:
        account_head = tax["account_head"]
        tax_account_wise_data.setdefault(
            account_head,
            {
                "charge_type": "Actual",
                "account_head": account_head,
                "description": tax.get("description"),
                "cost_center": tax.get("cost_center"),
                "included_in_print_rate": 0,
                "dont_recompute_tax": 1,
                "tax_amount": 0,
                "item_wise_tax_detail": {},
            },
        )
        tax_account_wise_data[account_head]["tax_amount"] += flt(tax.get("tax_amount"))
        if tax.get("item_wise_tax_detail"):
            tax_account_wise_data[account_head]["item_wise_tax_detail"].update(tax["item_wise_tax_detail"])

    return tax_account_wise_data.values()
