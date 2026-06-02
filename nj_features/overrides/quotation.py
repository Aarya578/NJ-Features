import frappe
from frappe.model.document import Document
from erpnext.selling.doctype.quotation.quotation import Quotation
from frappe.model.mapper import get_mapped_doc
from datetime import date


class CustomQuotation(Quotation):
    pass


@frappe.whitelist()
def fetch_email_from_shipping_address(doc_name):
    """
    Return email_id from the Quotation's customer_address.
    Returns None silently if anything is missing / fails.
    """
    try:
        doc = frappe.get_doc("Quotation", doc_name)

        if not doc.customer_address:
            return None

        address = frappe.get_doc("Address", doc.customer_address)
        return address.get("email_id")

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Fetch Email Error")
        return None


@frappe.whitelist()
def bypass_so_permission(quotation_name):
    """
    Create Sales Order from Quotation, bypassing permissions,
    but only if customer_replay == 'Agree'.

    Also:
    - Keeps proper link fields (prevdoc_docname, quotation_item)
    - Auto-sets delivery_date if missing
    - Fills custom Order ID on Sales Order
    """
    # Check customer response first
    response = frappe.get_value("Quotation", quotation_name, "customer_replay")
    frappe.logger().debug(f"bypass_so_permission: response for {quotation_name} = {response}")

    if response != "Agree":
        frappe.throw("Customer has Not responded to the quotation")

    def set_missing_values(source, target):
        # Make sure customer is set from party_name
        target.customer = source.party_name

        # 🔹 Fill Order ID on Sales Order
        # 1) If Quotation has a custom field `order_id`, use that
        # 2) Otherwise fall back to the Quotation name
        if not target.get("order_id"):
            target.order_id = source.get("order_id") or source.name

    # Map Quotation -> Sales Order with proper link fields
    so = get_mapped_doc(
        "Quotation",
        quotation_name,
        {
            "Quotation": {
                "doctype": "Sales Order",
                "field_map": {
                    "party_name": "customer",
                    # If Quotation ALSO has `order_id` field and you want direct mapping, this helps too:
                    "order_id": "order_id"
                }
            },
            "Quotation Item": {
                "doctype": "Sales Order Item",
                "field_map": {
                    # Restore the link fields:
                    "parent": "prevdoc_docname",   # Quotation name -> SO Item.prevdoc_docname
                    "name": "quotation_item",      # Quotation Item row -> SO Item.quotation_item
                },
            }
        },
        ignore_permissions=True,
        postprocess=set_missing_values
    )

    frappe.logger().debug(f"bypass_so_permission: mapped SO = {so.as_dict()}")

    # Auto-assign Delivery Date for all items if empty
    for item in so.get("items", []):
        if not item.delivery_date:
            item.delivery_date = date.today()

    # Bypass permissions on insert/save
    so.flags.ignore_permissions = True
    so.insert(ignore_permissions=True)
    so.save()

    frappe.db.commit()
    return so.name