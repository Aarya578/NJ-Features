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
from frappe.utils import now_datetime, flt

from nj_features.nj_features.api.zoho_api import zoho_put, zoho_post, zoho_get, ZohoAPIError


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


def _create_zoho_quote_from_quotation(doc):
    """Creates a corresponding record in Zoho CRM's native Quotes module and links it to Deal and Account."""
    # 1. Resolve Account ID
    account_id = None
    if doc.party_name:
        account_id = frappe.db.get_value("Customer", doc.party_name, "zoho_account_id")

    if not account_id and doc.zoho_deal_id:
        try:
            dres = zoho_get(f"Deals/{doc.zoho_deal_id}", params={"fields": "Account_Name"})
            ddata = (dres.get("data") or [{}])[0]
            account_id = (ddata.get("Account_Name") or {}).get("id")
        except Exception:
            pass

    if not account_id:
        frappe.log_error(
            f"Cannot create Zoho Quote for Quotation {doc.name}: no Zoho Account ID found",
            "Zoho quote create skipped",
        )
        return None

def _resolve_or_create_zoho_product(row):
    """Resolves an ERPNext line item to a Zoho CRM Product ID, auto-creating it in Zoho CRM if not found."""
    fallback_product_id = "1250991000002566041"

    # 1. Check if row or Item doctype already has zoho_product_id
    if hasattr(row, "zoho_product_id") and row.zoho_product_id:
        return row.zoho_product_id
    if frappe.db.has_column("Item", "zoho_product_id"):
        cached = frappe.db.get_value("Item", row.item_code, "zoho_product_id")
        if cached:
            return cached

    item_code = row.item_code
    item_name = getattr(row, "item_name", None) or item_code
    rate = flt(getattr(row, "rate", 0.0))
    desc = getattr(row, "description", None) or item_name

    # 2. Search Zoho CRM by ERP_Item_Code
    try:
        pres = zoho_get("Products/search", params={"criteria": f'(ERP_Item_Code:equals:"{item_code}")'})
        prows = pres.get("data") or []
        if prows:
            return prows[0]["id"]
    except Exception:
        pass

    # 3. Search Zoho CRM by Product_Name
    try:
        pres = zoho_get("Products/search", params={"criteria": f'(Product_Name:equals:"{item_name}")'})
        prows = pres.get("data") or []
        if prows:
            return prows[0]["id"]
    except Exception:
        pass

    # 4. Search Zoho CRM by word search
    try:
        pres = zoho_get("Products/search", params={"word": item_code})
        prows = pres.get("data") or []
        for p in prows:
            if p.get("ERP_Item_Code") == item_code or p.get("Product_Name") == item_name:
                return p["id"]
    except Exception:
        pass

    # 5. Auto-create the Product in Zoho CRM so it always matches accurately
    try:
        prod_payload = {
            "data": [
                {
                    "Product_Name": item_name,
                    "Product_Code": item_code,
                    "ERP_Item_Code": item_code,
                    "Unit_Price": rate,
                    "Description": desc,
                }
            ]
        }
        res = zoho_post("Products", prod_payload)
        data = res.get("data") or []
        if data and data[0].get("status") == "success":
            created_prod_id = data[0].get("details", {}).get("id")
            if created_prod_id:
                if frappe.db.has_column("Item", "zoho_product_id"):
                    frappe.db.set_value("Item", item_code, "zoho_product_id", str(created_prod_id))
                return created_prod_id
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Zoho Product auto-create error for {item_code}")

    return fallback_product_id


def _create_zoho_quote_from_quotation(doc):
    """Creates a corresponding record in Zoho CRM's native Quotes module and links it to Deal and Account."""
    # 1. Resolve Account ID
    account_id = None
    if doc.party_name:
        account_id = frappe.db.get_value("Customer", doc.party_name, "zoho_account_id")

    if not account_id and doc.zoho_deal_id:
        try:
            dres = zoho_get(f"Deals/{doc.zoho_deal_id}", params={"fields": "Account_Name"})
            ddata = (dres.get("data") or [{}])[0]
            account_id = (ddata.get("Account_Name") or {}).get("id")
        except Exception:
            pass

    if not account_id:
        frappe.log_error(
            f"Cannot create Zoho Quote for Quotation {doc.name}: no Zoho Account ID found",
            "Zoho quote create skipped",
        )
        return None

    # 2. Build Quoted_Items subform for Zoho Quotes
    quoted_items = []
    fallback_product_id = "1250991000002566041"

    for row in doc.items:
        prod_id = _resolve_or_create_zoho_product(row)
        quoted_items.append(
            {
                "Product_Name": {"id": prod_id},
                "Quantity": row.qty or 1,
                "List_Price": flt(row.rate),
                "Description": row.description or row.item_name or row.item_code,
            }
        )

    if not quoted_items:
        quoted_items.append(
            {
                "Product_Name": {"id": fallback_product_id},
                "Quantity": 1,
                "List_Price": flt(doc.grand_total),
            }
        )

    tax_amount = flt(getattr(doc, "total_taxes_and_charges", 0.0)) or flt(getattr(doc, "total_tax", 0.0))

    description_parts = []
    if doc.owner:
        description_parts.append(f"Created by: {doc.owner}")
    if getattr(doc, "valid_till", None):
        description_parts.append(f"Valid Till: {doc.valid_till}")
    if doc.get("remarks"):
        description_parts.append(f"Remarks: {doc.remarks}")
    quote_description = " | ".join(description_parts)

    quote_payload = {
        "data": [
            {
                "Subject": doc.name,
                "Deal_Name": {"id": str(doc.zoho_deal_id)},
                "Account_Name": {"id": str(account_id)},
                "Quote_Stage": "Confirmed",
                "ERP_Quotation_ID": doc.name,
                "ERP_Quotation_Status": doc.status or "Confirmed",
                "ERP_Grand_Total": flt(doc.grand_total),
                "ERP_Tax_Amount": tax_amount,
                "Grand_Total": flt(doc.grand_total),
                "Due_Date": str(doc.valid_till) if doc.valid_till else None,
                "Description": quote_description,
                "Quoted_Items": quoted_items,
            }
        ]
    }

    try:
        res = zoho_post("Quotes", quote_payload)
        data = res.get("data") or []
        if data and data[0].get("status") == "success":
            created_quote_id = data[0].get("details", {}).get("id")
            if created_quote_id:
                doc.db_set("zoho_quote_id", str(created_quote_id))
                return created_quote_id
        else:
            frappe.log_error(str(res), f"Zoho Quote creation failed for {doc.name}")
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Zoho Quote creation error for {doc.name}")

    return None


def on_quotation_submit(doc, method=None):
    """Closes the visibility gap between "ERPNext created a draft
    Quotation" and "ERPNext created a Sales Order from it" -- without
    this, Zoho keeps showing ERP_Quotation_Status: Draft the whole time
    Ops has the Quotation open for review, even after they've actually
    submitted it, right up until someone separately makes and submits
    the Sales Order.
    """
    if not _enabled():
        return

    # 1. Update the originating Deal
    if doc.zoho_deal_id:
        _push(
            "Deals",
            doc.zoho_deal_id,
            {"ERP_Quotation_Status": "Confirmed", "Currency_1": doc.grand_total},
            "Quotation submit",
        )

    # 2. If already linked to a Zoho Quote, update it; otherwise create a new Zoho Quote record
    if doc.zoho_quote_id:
        quote_updates = {"ERP_Quotation_Status": "Confirmed", "ERP_Grand_Total": doc.grand_total}
        if doc.valid_till:
            quote_updates["Due_Date"] = str(doc.valid_till)
        _push(
            "Quotes",
            doc.zoho_quote_id,
            quote_updates,
            "Quotation submit",
        )
    elif doc.zoho_deal_id:
        # Automatically creates a Quote in Zoho's Quotes module and writes back zoho_quote_id
        _create_zoho_quote_from_quotation(doc)


def on_quotation_cancel(doc, method=None):
    if not _enabled():
        return

    if doc.zoho_deal_id:
        _push("Deals", doc.zoho_deal_id, {"ERP_Quotation_Status": "Cancelled"}, "Quotation cancel")

    if doc.zoho_quote_id:
        _push("Quotes", doc.zoho_quote_id, {"ERP_Quotation_Status": "Cancelled"}, "Quotation cancel")


def _create_or_update_zoho_sales_order(doc):
    """Creates or updates a corresponding record in Zoho CRM's native Sales_Orders module."""
    if not _enabled():
        return None

    # 1. Resolve Account ID
    account_id = None
    customer_name = getattr(doc, "customer", None)
    if customer_name:
        account_id = frappe.db.get_value("Customer", customer_name, "zoho_account_id")

    if not account_id and getattr(doc, "zoho_deal_id", None):
        try:
            dres = zoho_get(f"Deals/{doc.zoho_deal_id}", params={"fields": "Account_Name"})
            ddata = (dres.get("data") or [{}])[0]
            account_id = (ddata.get("Account_Name") or {}).get("id")
        except Exception:
            pass

    if not account_id and getattr(doc, "zoho_quote_id", None):
        try:
            qres = zoho_get(f"Quotes/{doc.zoho_quote_id}", params={"fields": "Account_Name"})
            qdata = (qres.get("data") or [{}])[0]
            account_id = (qdata.get("Account_Name") or {}).get("id")
        except Exception:
            pass

    if not account_id and customer_name:
        try:
            ares = zoho_get("Accounts/search", params={"criteria": f'(Account_Name:equals:"{customer_name}")'})
            arows = ares.get("data") or []
            if arows:
                account_id = arows[0]["id"]
                frappe.db.set_value("Customer", customer_name, "zoho_account_id", str(account_id))
        except Exception:
            pass

    # Only create/update Zoho SO if linked to Zoho (has deal_id, quote_id, zoho_so_id, or valid zoho account)
    if not account_id and not getattr(doc, "zoho_deal_id", None) and not getattr(doc, "zoho_quote_id", None) and not getattr(doc, "zoho_so_id", None):
        return None

    # 2. Build Ordered_Items subform for Zoho Sales Orders
    ordered_items = []
    fallback_product_id = "1250991000002566041"

    for row in getattr(doc, "items", []):
        prod_id = _resolve_or_create_zoho_product(row)
        ordered_items.append(
            {
                "Product_Name": {"id": prod_id},
                "Quantity": row.qty or 1,
                "List_Price": flt(row.rate),
                "Description": row.description or row.item_name or row.item_code,
            }
        )

    if not ordered_items:
        ordered_items.append(
            {
                "Product_Name": {"id": fallback_product_id},
                "Quantity": 1,
                "List_Price": flt(doc.grand_total),
            }
        )

    tax_amount = flt(getattr(doc, "total_taxes_and_charges", 0.0)) or flt(getattr(doc, "total_tax", 0.0))

    so_payload_data = {
        "Subject": doc.name,
        "ERP_SO_Name": doc.name,
        "ERP_ID": doc.name,
        "ERP_Status": doc.status or "Confirmed",
        "SO_Status": "Confirmed",
        "ERP_Grand_Total": flt(doc.grand_total),
        "ERP_Tax_Total": tax_amount,
        "Grand_Total": flt(doc.grand_total),
        "Ordered_Items": ordered_items,
    }

    if account_id:
        so_payload_data["Account_Name"] = {"id": str(account_id)}

    if getattr(doc, "zoho_deal_id", None):
        so_payload_data["Deal_Name"] = {"id": str(doc.zoho_deal_id)}

    if getattr(doc, "zoho_quote_id", None):
        so_payload_data["Quote_Name"] = {"id": str(doc.zoho_quote_id)}

    # Field mappings:
    # Estimated Delivery Date = doc.maximum estimated delivery date (estimated_delivery_date)
    # Commited Delivery Date = doc.Commited Delivery Data (committed_delivery_date)
    # ERP SO Creation = doc.transaction_date
    if getattr(doc, "estimated_delivery_date", None):
        so_payload_data["Estimated_Delivery_Date"] = str(doc.estimated_delivery_date)

    if getattr(doc, "committed_delivery_date", None):
        so_payload_data["Commited_Delivery_Date"] = str(doc.committed_delivery_date)

    if getattr(doc, "transaction_date", None):
        so_payload_data["ERP_SO_Creation"] = str(doc.transaction_date)

    if getattr(doc, "delivery_status", None):
        so_payload_data["ERP_Delivery_Status"] = str(doc.delivery_status)

    zoho_so_id = getattr(doc, "zoho_so_id", None)
    if zoho_so_id:
        # Match existing subform row ids so Zoho updates the rows properly
        try:
            curr_so = zoho_get(f"Sales_Orders/{zoho_so_id}", params={"fields": "Ordered_Items"})
            curr_items = (curr_so.get("data") or [{}])[0].get("Ordered_Items") or []
            for idx, item in enumerate(ordered_items):
                if idx < len(curr_items) and "id" in curr_items[idx]:
                    item["id"] = curr_items[idx]["id"]
        except Exception:
            pass

        try:
            res = zoho_put(f"Sales_Orders/{zoho_so_id}", {"data": [{"id": str(zoho_so_id), **so_payload_data}]})
            data = res.get("data") or []
            if data and data[0].get("status") == "success":
                return zoho_so_id
            else:
                frappe.log_error(str(res), f"Zoho Sales Order update failed for {doc.name}")
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Zoho Sales Order update error for {doc.name}")
    else:
        try:
            res = zoho_post("Sales_Orders", {"data": [so_payload_data]})
            data = res.get("data") or []
            if data and data[0].get("status") == "success":
                created_so_id = data[0].get("details", {}).get("id")
                if created_so_id:
                    doc.db_set("zoho_so_id", str(created_so_id))
                    return created_so_id
            else:
                frappe.log_error(str(res), f"Zoho Sales Order creation failed for {doc.name}")
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Zoho Sales Order creation error for {doc.name}")

    return None


@frappe.whitelist()
def sync_sales_order_to_zoho(sales_order_name):
    """Whitelisted endpoint to manually or programmically trigger Zoho SO creation/update."""
    doc = frappe.get_doc("Sales Order", sales_order_name)
    return _create_or_update_zoho_sales_order(doc)


def on_sales_order_submit(doc, method=None):
    if not _enabled():
        return

    # 1. Create or update the Sales Order in Zoho CRM native Sales_Orders module
    _create_or_update_zoho_sales_order(doc)

    # 2. Update originating Deal
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

    # 3. Update originating Quote
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

    if getattr(doc, "zoho_so_id", None):
        _push(
            "Sales_Orders",
            doc.zoho_so_id,
            {"ERP_Status": "Cancelled", "SO_Status": "Cancelled"},
            "Sales Order cancel",
        )

    if doc.zoho_deal_id:
        _push("Deals", doc.zoho_deal_id, {"ERP_Quotation_Status": "Order Cancelled"}, "Sales Order cancel")

    if doc.zoho_quote_id:
        _push("Quotes", doc.zoho_quote_id, {"ERP_Quotation_Status": "Order Cancelled"}, "Sales Order cancel")



def _create_or_update_zoho_delivery_note(doc):
    """Creates or updates a corresponding record in Zoho CRM's native Delivery_Notes module."""
    if not _enabled():
        return None

    # 1. Resolve Account ID and linked Deal ID / Sales Order ID / Sales Invoice ID
    account_id = None
    customer_name = getattr(doc, "customer", None)
    if customer_name:
        account_id = frappe.db.get_value("Customer", customer_name, "zoho_account_id")

    deal_id = getattr(doc, "zoho_deal_id", None)
    quote_id = getattr(doc, "zoho_quote_id", None)
    so_id = None
    inv_id = None

    # Child table resolution (Delivery Note Item)
    sales_orders = {row.against_sales_order for row in getattr(doc, "items", []) if getattr(row, "against_sales_order", None)}
    for so_name in sales_orders:
        s_deal_id, s_quote_id, s_so_id = frappe.db.get_value(
            "Sales Order", so_name, ["zoho_deal_id", "zoho_quote_id", "zoho_so_id"]
        ) or (None, None, None)
        if s_deal_id and not deal_id:
            deal_id = s_deal_id
        if s_quote_id and not quote_id:
            quote_id = s_quote_id
        if s_so_id and not so_id:
            so_id = s_so_id

    # Check against_sales_invoice from child table
    sales_invoices = {row.against_sales_invoice for row in getattr(doc, "items", []) if getattr(row, "against_sales_invoice", None)}
    if not sales_invoices:
        si_rows = frappe.get_all(
            "Sales Invoice Item",
            filters={"delivery_note": doc.name, "docstatus": 1},
            fields=["parent"],
            distinct=True,
        )
        sales_invoices = {r.parent for r in si_rows}

    for si_name in sales_invoices:
        s_inv_id = frappe.db.get_value("Sales Invoice", si_name, "zoho_invoice_id")
        if s_inv_id and not inv_id:
            inv_id = s_inv_id

    if not account_id and deal_id:
        try:
            dres = zoho_get(f"Deals/{deal_id}", params={"fields": "Account_Name"})
            ddata = (dres.get("data") or [{}])[0]
            account_id = (ddata.get("Account_Name") or {}).get("id")
        except Exception:
            pass

    if not account_id and customer_name:
        try:
            ares = zoho_get("Accounts/search", params={"criteria": f'(Account_Name:equals:"{customer_name}")'})
            arows = ares.get("data") or []
            if arows:
                account_id = arows[0]["id"]
                frappe.db.set_value("Customer", customer_name, "zoho_account_id", str(account_id))
        except Exception:
            pass

    # Only sync if linked to Zoho
    if not account_id and not deal_id and not quote_id and not so_id and not getattr(doc, "zoho_dn_id", None):
        return None

    # Calculate total quantity dispatched from child items
    total_qty = int(round(sum(flt(row.qty) for row in getattr(doc, "items", []))))
    tax_amount = flt(getattr(doc, "total_taxes_and_charges", 0.0)) or flt(getattr(doc, "total_tax", 0.0))

    # Calculate Order Qty, Cumulative Dispatched Qty, Pending Qty, and Revenues
    total_order_qty = 0
    total_dispatched_qty = 0
    dispatched_revenue = 0
    remaining_revenue = 0

    if sales_orders:
        so_names_list = list(sales_orders)
        so_totals = frappe.db.sql(
            """
            SELECT SUM(total_qty) as total_qty, SUM(net_total) as net_total
            FROM `tabSales Order`
            WHERE name IN %(so_names)s
            """,
            {"so_names": so_names_list},
            as_dict=True,
        )[0]
        total_order_qty = int(round(flt(so_totals.get("total_qty"))))
        total_order_revenue = flt(so_totals.get("net_total"))

        dn_totals = frappe.db.sql(
            """
            SELECT SUM(qty) as total_dispatched_qty, SUM(net_amount) as dispatched_revenue
            FROM `tabDelivery Note Item`
            WHERE against_sales_order IN %(so_names)s AND docstatus = 1
            """,
            {"so_names": so_names_list},
            as_dict=True,
        )[0]
        db_dispatched_qty = flt(dn_totals.get("total_dispatched_qty"))
        db_dispatched_revenue = flt(dn_totals.get("dispatched_revenue"))

        current_dn_in_db = frappe.db.sql(
            """
            SELECT 1 FROM `tabDelivery Note Item`
            WHERE parent = %(parent)s AND against_sales_order IN %(so_names)s AND docstatus = 1 LIMIT 1
            """,
            {"parent": doc.name, "so_names": so_names_list},
        )

        if not current_dn_in_db:
            current_so_items = [
                row for row in getattr(doc, "items", [])
                if getattr(row, "against_sales_order", None) in sales_orders
            ]
            current_qty = sum(flt(row.qty) for row in current_so_items)
            current_rev = sum(flt(getattr(row, "net_amount", getattr(row, "amount", 0.0))) for row in current_so_items)
            total_dispatched_qty = int(round(db_dispatched_qty + current_qty))
            dispatched_revenue = int(round(db_dispatched_revenue + current_rev))
        else:
            total_dispatched_qty = int(round(db_dispatched_qty))
            dispatched_revenue = int(round(db_dispatched_revenue))

        pending_qty = max(0, total_order_qty - total_dispatched_qty)
        remaining_revenue = max(0, int(round(total_order_revenue - dispatched_revenue)))
    else:
        total_order_qty = total_qty
        total_dispatched_qty = total_qty
        pending_qty = 0
        dispatched_revenue = int(round(flt(getattr(doc, "net_total", doc.total))))
        remaining_revenue = 0

    dn_payload_data = {
        "Name": doc.name,
        "DN_Number": doc.name,
        "ERP_ID": doc.name,
        "Qty_Dispatched": total_qty,
        "DN_Amount": flt(getattr(doc, "net_total", doc.total)),
        "DN_Grand_Total": flt(doc.grand_total),
        "DN_Total_Tax": tax_amount,
        "DN_Status": doc.status or "Submitted",
        "Total_Order_Qty": total_order_qty,
        "Total_Dispatched_Qty": total_dispatched_qty,
        "Pending_Qty": pending_qty,
        "Dispatched_Revenue": dispatched_revenue,
        "Remaining_Revenue": remaining_revenue,
    }

    if getattr(doc, "posting_date", None):
        dn_payload_data["DN_Date"] = str(doc.posting_date)

    if account_id:
        dn_payload_data["Account"] = {"id": str(account_id)}

    if deal_id:
        dn_payload_data["Deal"] = {"id": str(deal_id)}

    if so_id:
        dn_payload_data["Sales_Order"] = {"id": str(so_id)}

    if inv_id:
        dn_payload_data["Sales_Invoice"] = {"id": str(inv_id)}

    email = getattr(doc, "contact_email", None) or getattr(doc, "email_id", None)
    if email:
        dn_payload_data["Email"] = str(email)

    zoho_dn_id = getattr(doc, "zoho_dn_id", None)
    if zoho_dn_id:
        try:
            res = zoho_put(f"Delivery_Notes/{zoho_dn_id}", {"data": [{"id": str(zoho_dn_id), **dn_payload_data}]})
            data = res.get("data") or []
            if data and data[0].get("status") == "success":
                return zoho_dn_id
        except Exception:
            # If rejected (e.g. Sales_Invoice lookup constraint), retry cleanly without Sales_Invoice
            if "Sales_Invoice" in dn_payload_data:
                dn_payload_data.pop("Sales_Invoice", None)
                try:
                    res = zoho_put(f"Delivery_Notes/{zoho_dn_id}", {"data": [{"id": str(zoho_dn_id), **dn_payload_data}]})
                    data = res.get("data") or []
                    if data and data[0].get("status") == "success":
                        return zoho_dn_id
                except Exception:
                    pass
            frappe.log_error(frappe.get_traceback(), f"Zoho Delivery Note update error for {doc.name}")
    else:
        try:
            res = zoho_post("Delivery_Notes", {"data": [dn_payload_data]})
            data = res.get("data") or []
            if data and data[0].get("status") == "success":
                created_dn_id = data[0].get("details", {}).get("id")
                if created_dn_id:
                    doc.db_set("zoho_dn_id", str(created_dn_id))
                    return created_dn_id
        except Exception:
            # If rejected (e.g. Sales_Invoice lookup constraint), retry cleanly without Sales_Invoice
            if "Sales_Invoice" in dn_payload_data:
                dn_payload_data.pop("Sales_Invoice", None)
                try:
                    res = zoho_post("Delivery_Notes", {"data": [dn_payload_data]})
                    data = res.get("data") or []
                    if data and data[0].get("status") == "success":
                        created_dn_id = data[0].get("details", {}).get("id")
                        if created_dn_id:
                            doc.db_set("zoho_dn_id", str(created_dn_id))
                            return created_dn_id
                except Exception:
                    pass
            frappe.log_error(frappe.get_traceback(), f"Zoho Delivery Note creation error for {doc.name}")

    return None


@frappe.whitelist()
def sync_delivery_note_to_zoho(delivery_note_name):
    """Whitelisted endpoint to manually or programmatically trigger Zoho Delivery Note creation/update."""
    doc = frappe.get_doc("Delivery Note", delivery_note_name)
    return _create_or_update_zoho_delivery_note(doc)


def on_delivery_note_submit(doc, method=None):
    if not _enabled():
        return

    # 1. Create or update record in Zoho CRM native Delivery_Notes module
    _create_or_update_zoho_delivery_note(doc)

    # 2. Update originating Sales Orders, Deals, Quotes
    sales_orders = {row.against_sales_order for row in doc.items if row.against_sales_order}
    for so_name in sales_orders:
        deal_id, quote_id, so_id, per_delivered, per_billed = frappe.db.get_value(
            "Sales Order", so_name, ["zoho_deal_id", "zoho_quote_id", "zoho_so_id", "per_delivered", "per_billed"]
        )
        if not deal_id and not quote_id and not so_id:
            continue

        dn_rows = frappe.get_all(
            "Delivery Note Item",
            filters={"against_sales_order": so_name, "docstatus": 1},
            fields=["parent"],
            distinct=True,
        )
        dn_names = ", ".join(sorted({row.parent for row in dn_rows}))

        # Collect LR / Waybill and Transporter details
        lr_no = getattr(doc, "lr_no", None) or getattr(doc, "lr_number", "") or ""
        transporter = getattr(doc, "transporter_name", "") or ""

        push_data = {
            "ERP_Delivered": per_delivered,
            "ERP_Billed": per_billed,
            "ERP_Delivery_Notes": dn_names,
        }
        if lr_no:
            push_data["ERP_LR_No"] = str(lr_no)
        if transporter:
            push_data["ERP_Transporter"] = str(transporter)

        if deal_id:
            _push("Deals", deal_id, push_data, "Delivery Note submit")

        if quote_id:
            _push("Quotes", quote_id, {"ERP_Delivery_Notes": dn_names}, "Delivery Note submit")

        if so_id:
            so_deliv_status = "Delivered" if flt(per_delivered) >= 100 else "Partially Delivered"
            _push("Sales_Orders", so_id, {"ERP_Delivery_Status": so_deliv_status}, "Delivery Note submit")


def on_delivery_note_cancel(doc, method=None):
    if not _enabled():
        return

    # 1. Cancel record in Zoho CRM native Delivery_Notes module
    if getattr(doc, "zoho_dn_id", None):
        _push("Delivery_Notes", doc.zoho_dn_id, {"DN_Status": "Cancelled"}, "Delivery Note cancel")

    # 2. Update linked Sales Orders
    sales_orders = {row.against_sales_order for row in doc.items if row.against_sales_order}
    for so_name in sales_orders:
        so_id, per_delivered = frappe.db.get_value("Sales Order", so_name, ["zoho_so_id", "per_delivered"])
        if so_id:
            so_deliv_status = "Delivered" if flt(per_delivered) >= 100 else ("Partially Delivered" if flt(per_delivered) > 0 else "Pending")
            _push("Sales_Orders", so_id, {"ERP_Delivery_Status": so_deliv_status}, "Delivery Note cancel")


def _create_or_update_zoho_sales_invoice(doc):
    """Creates or updates a corresponding record in Zoho CRM's native Invoices module."""
    if not _enabled():
        return None

    # 1. Resolve Account ID and linked Deal ID
    account_id = None
    customer_name = getattr(doc, "customer", None)
    if customer_name:
        account_id = frappe.db.get_value("Customer", customer_name, "zoho_account_id")

    deal_id = getattr(doc, "zoho_deal_id", None)
    quote_id = getattr(doc, "zoho_quote_id", None)
    so_id = None

    sales_orders = {row.sales_order for row in getattr(doc, "items", []) if getattr(row, "sales_order", None)}
    for so_name in sales_orders:
        s_deal_id, s_quote_id, s_so_id = frappe.db.get_value(
            "Sales Order", so_name, ["zoho_deal_id", "zoho_quote_id", "zoho_so_id"]
        ) or (None, None, None)
        if s_deal_id and not deal_id:
            deal_id = s_deal_id
        if s_quote_id and not quote_id:
            quote_id = s_quote_id
        if s_so_id and not so_id:
            so_id = s_so_id

    if not account_id and deal_id:
        try:
            dres = zoho_get(f"Deals/{deal_id}", params={"fields": "Account_Name"})
            ddata = (dres.get("data") or [{}])[0]
            account_id = (ddata.get("Account_Name") or {}).get("id")
        except Exception:
            pass

    if not account_id and customer_name:
        try:
            ares = zoho_get("Accounts/search", params={"criteria": f'(Account_Name:equals:"{customer_name}")'})
            arows = ares.get("data") or []
            if arows:
                account_id = arows[0]["id"]
                frappe.db.set_value("Customer", customer_name, "zoho_account_id", str(account_id))
        except Exception:
            pass

    # Only sync if linked to Zoho
    if not account_id and not deal_id and not quote_id and not getattr(doc, "zoho_invoice_id", None):
        return None

    # 2. Build Invoiced_Items subform
    invoiced_items = []
    fallback_product_id = "1250991000002566041"

    for row in getattr(doc, "items", []):
        prod_id = _resolve_or_create_zoho_product(row)
        invoiced_items.append(
            {
                "Product_Name": {"id": prod_id},
                "Quantity": row.qty or 1,
                "List_Price": flt(row.rate),
                "Description": row.description or row.item_name or row.item_code,
            }
        )

    if not invoiced_items:
        invoiced_items.append(
            {
                "Product_Name": {"id": fallback_product_id},
                "Quantity": 1,
                "List_Price": flt(doc.grand_total),
            }
        )

    tax_amount = flt(getattr(doc, "total_taxes_and_charges", 0.0)) or flt(getattr(doc, "total_tax", 0.0))

    inv_payload_data = {
        "Subject": doc.name,
        "ERP_ID": doc.name,
        "ERP_SI_Name": doc.name,
        "ERP_Status": doc.status or "Submitted",
        "ERP_SI_Status": doc.status or "Submitted",
        "ERP_Grand_Total": flt(doc.grand_total),
        "ERP_Outstanding": flt(getattr(doc, "outstanding_amount", doc.grand_total)),
        "ERP_Total_Tax": tax_amount,
        "Grand_Total": flt(doc.grand_total),
        "Invoiced_Items": invoiced_items,
    }

    if account_id:
        inv_payload_data["Account_Name"] = {"id": str(account_id)}

    if deal_id:
        inv_payload_data["Deal_Name__s"] = {"id": str(deal_id)}

    if getattr(doc, "posting_date", None):
        inv_payload_data["ERP_SI_Creation"] = str(doc.posting_date)

    if getattr(doc, "remarks", None):
        inv_payload_data["Description"] = str(doc.remarks)

    zoho_invoice_id = getattr(doc, "zoho_invoice_id", None)
    if zoho_invoice_id:
        # Match existing subform row ids so Zoho updates properly
        try:
            curr_inv = zoho_get(f"Invoices/{zoho_invoice_id}", params={"fields": "Invoiced_Items"})
            curr_items = (curr_inv.get("data") or [{}])[0].get("Invoiced_Items") or []
            for idx, item in enumerate(invoiced_items):
                if idx < len(curr_items) and "id" in curr_items[idx]:
                    item["id"] = curr_items[idx]["id"]
        except Exception:
            pass

        try:
            res = zoho_put(f"Invoices/{zoho_invoice_id}", {"data": [{"id": str(zoho_invoice_id), **inv_payload_data}]})
            data = res.get("data") or []
            if data and data[0].get("status") == "success":
                return zoho_invoice_id
            else:
                frappe.log_error(str(res), f"Zoho Invoice update failed for {doc.name}")
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Zoho Invoice update error for {doc.name}")
    else:
        try:
            res = zoho_post("Invoices", {"data": [inv_payload_data]})
            data = res.get("data") or []
            if data and data[0].get("status") == "success":
                created_inv_id = data[0].get("details", {}).get("id")
                if created_inv_id:
                    doc.db_set("zoho_invoice_id", str(created_inv_id))
                    return created_inv_id
            else:
                frappe.log_error(str(res), f"Zoho Invoice creation failed for {doc.name}")
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Zoho Invoice creation error for {doc.name}")

    return None


@frappe.whitelist()
def sync_sales_invoice_to_zoho(sales_invoice_name):
    """Whitelisted endpoint to manually or programmatically trigger Zoho Invoice creation/update."""
    doc = frappe.get_doc("Sales Invoice", sales_invoice_name)
    return _create_or_update_zoho_sales_invoice(doc)


def on_sales_invoice_submit(doc, method=None):
    if not _enabled():
        return

    # 1. Create or update record in Zoho CRM native Invoices module
    _create_or_update_zoho_sales_invoice(doc)

    # 2. Update originating Deals and Quotes
    sales_orders = {row.sales_order for row in doc.items if row.sales_order}
    for so_name in sales_orders:
        deal_id, quote_id = frappe.db.get_value("Sales Order", so_name, ["zoho_deal_id", "zoho_quote_id"])
        if not deal_id and not quote_id:
            continue

        inv_data = {
            "ERP_Invoice_ID": doc.name,
            "ERP_Outstanding": doc.outstanding_amount,
            "ERP_Invoice_Status": doc.status or "Submitted",
        }

        if deal_id:
            _push("Deals", deal_id, inv_data, "Sales Invoice submit")

        if quote_id:
            _push("Quotes", quote_id, inv_data, "Sales Invoice submit")

    # 3. Link this Sales Invoice to any referenced Delivery Notes in Zoho
    if getattr(doc, "zoho_invoice_id", None):
        dn_names = {row.delivery_note for row in getattr(doc, "items", []) if getattr(row, "delivery_note", None)}
        for dn_name in dn_names:
            z_dn_id = frappe.db.get_value("Delivery Note", dn_name, "zoho_dn_id")
            if z_dn_id:
                _push("Delivery_Notes", z_dn_id, {"Sales_Invoice": {"id": str(doc.zoho_invoice_id)}}, "Link Invoice to DN")


def on_sales_invoice_update_after_submit(doc, method=None):
    """Fired when payments or status changes occur on the Sales Invoice."""
    if not _enabled():
        return

    # 1. Update native Zoho Invoice record with current balance and status
    if getattr(doc, "zoho_invoice_id", None):
        _push(
            "Invoices",
            doc.zoho_invoice_id,
            {
                "ERP_Outstanding": flt(doc.outstanding_amount),
                "ERP_Status": doc.status,
                "ERP_SI_Status": doc.status,
            },
            "Sales Invoice payment update",
        )

    # 2. Update originating Deals and Quotes
    sales_orders = {row.sales_order for row in doc.items if row.sales_order}
    for so_name in sales_orders:
        deal_id, quote_id = frappe.db.get_value("Sales Order", so_name, ["zoho_deal_id", "zoho_quote_id"])
        if not deal_id and not quote_id:
            continue

        update_data = {
            "ERP_Outstanding": doc.outstanding_amount,
            "ERP_Invoice_Status": doc.status,
        }

        if deal_id:
            _push("Deals", deal_id, update_data, "Sales Invoice payment update")

        if quote_id:
            _push("Quotes", quote_id, update_data, "Sales Invoice payment update")


def on_sales_invoice_cancel(doc, method=None):
    if not _enabled():
        return

    # 1. Cancel native Zoho Invoice record
    if getattr(doc, "zoho_invoice_id", None):
        _push(
            "Invoices",
            doc.zoho_invoice_id,
            {
                "ERP_Status": "Cancelled",
                "ERP_SI_Status": "Cancelled",
                "ERP_Outstanding": 0.0,
            },
            "Sales Invoice cancel",
        )

    # 2. Update originating Deals and Quotes
    sales_orders = {row.sales_order for row in doc.items if row.sales_order}
    for so_name in sales_orders:
        deal_id, quote_id = frappe.db.get_value("Sales Order", so_name, ["zoho_deal_id", "zoho_quote_id"])
        if not deal_id and not quote_id:
            continue

        cancel_data = {
            "ERP_Invoice_Status": "Cancelled",
            "ERP_Outstanding": 0.0,
        }

        if deal_id:
            _push("Deals", deal_id, cancel_data, "Sales Invoice cancel")

        if quote_id:
            _push("Quotes", quote_id, cancel_data, "Sales Invoice cancel")

