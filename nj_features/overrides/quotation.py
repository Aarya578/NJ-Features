import frappe
from frappe.model.document import Document
from erpnext.selling.doctype.quotation.quotation import Quotation
from frappe.utils import nowdate
import frappe
from frappe.model.mapper import get_mapped_doc

import frappe
from datetime import date
class CustomQuotation(Quotation):
    pass

# @frappe.whitelist()
# def fetch_email_from_shipping_address(doc_name):
#     try:
#         doc = frappe.get_doc("Quotation", doc_name)
#         if not doc.customer_address:
#             frappe.throw("Customer Address not found in Quotation")
#         address = frappe.get_doc("Address", doc.customer_address)
#         email_id = address.get("email_id")
#         if not email_id:
#             frappe.throw("No Email found in the Customer Address")
#         return email_id
#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), "Fetch Email Error")
#         frappe.throw(str(e))


@frappe.whitelist()
def fetch_email_from_shipping_address(doc_name):
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
    response = frappe.get_value("Quotation", quotation_name, "customer_replay")
    print("response================",response)
    if response != "Agree":
        frappe.throw("Customer has Not responded to the quotation")
    def set_missing_values(source, target):
        target.customer = source.party_name

    so = get_mapped_doc(
        "Quotation",
        quotation_name,
        {
            "Quotation": {
                "doctype": "Sales Order",
                "field_map": { "party_name": "customer" }
            },
            "Quotation Item": {
                "doctype": "Sales Order Item"
            }
        },
        ignore_permissions=True,
        postprocess=set_missing_values
    )
    print("so================",so)

    # ✅ Auto-assign Delivery Date for all items
    for item in so.get("items", []):
        if not item.delivery_date:
            item.delivery_date = date.today()

    so.flags.ignore_permissions = True
    so.insert(ignore_permissions=True)
    so.save()

    frappe.db.commit()
    return so.name



