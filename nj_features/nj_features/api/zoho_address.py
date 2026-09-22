"""
Zoho Quote's native Billing Address -> a real ERPNext Address, for the
Zoho-ERPNext Quote Bridge's Quotes-module flow. A real, structured
Address (with a GST state matching ERPNext's Address.gst_state options
exactly) is what lets ERPNext compute real GST tax (CGST+SGST vs IGST)
on the resulting Quotation, rather than leaving tax at zero.

Reads Zoho's own native Billing Address block (Billing_Street,
Billing_City, Billing_State, Billing_Code) rather than a separate set
of custom fields -- confirmed the State picklist there uses the exact
same plain state names as ERPNext's gst_state options (e.g.
"Karnataka", not an abbreviation), so no translation layer is needed.
Customer_Email and GSTIN stay custom fields since Zoho has no native
equivalent on Quotes.
"""

import frappe

REQUIRED_QUOTE_FIELDS = ["Billing_Street", "Billing_City", "Billing_State", "Billing_Code", "Customer_Email"]


def resolve_address(quote_row, customer_name, quote_id):
    """Find-or-update-or-create the Billing Address for a Zoho Quote and
    return its name, or None if any required field is missing
    (address_line2/state/email_id/country/pincode are all mandatory on
    this site's Address doctype -- confirmed by reading the live meta,
    not assumed from stock ERPNext).

    Keyed on quote_id (via address_title = f"Zoho Quote {quote_id}") and
    updated in place on repeat calls, rather than creating a new Address
    every time -- this gets called on every price/tax preview while a
    rep is still editing the Quote, not just once at final submission,
    so a naive "always insert" would pile up duplicate Address records.
    """
    if not all(quote_row.get(f) for f in REQUIRED_QUOTE_FIELDS):
        return None

    address_line1 = quote_row["Billing_Street"]
    city = quote_row["Billing_City"]
    state = quote_row["Billing_State"]
    pincode = quote_row["Billing_Code"]
    address_title = f"Zoho Quote {quote_id}"

    existing_name = frappe.db.get_value("Address", {"address_title": address_title, "address_type": "Billing"})
    address = frappe.get_doc("Address", existing_name) if existing_name else frappe.new_doc("Address")

    address.address_title = address_title
    address.address_type = "Billing"
    address.address_line1 = address_line1
    address.address_line2 = f"{pincode}, {city}"
    address.city = city
    address.state = state
    address.gst_state = state
    address.country = "India"
    address.pincode = pincode
    address.email_id = quote_row["Customer_Email"]
    # ERPNext's India Compliance validation rejects the whole Address save
    # (and so the whole Quote) if GSTIN is present but not exactly 15
    # characters -- since it's meant to be optional (unregistered
    # customers won't have one), a mistyped/partial value should just be
    # dropped rather than blocking everything else.
    gstin = (quote_row.get("GSTIN") or "").strip()
    address.gstin = gstin if len(gstin) == 15 else None

    if not existing_name:
        address.append("links", {"link_doctype": "Customer", "link_name": customer_name})

    address.save(ignore_permissions=True)
    frappe.db.commit()

    return address.name
