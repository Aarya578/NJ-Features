# Copyright (c) 2026, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import hashlib
import secrets

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, get_datetime, get_url, now_datetime, sanitize_html


CUSTOMER_RESPONSES = ("Agree", "Dis Agree")


class QuotationCustomerAccess(Document):
    def validate(self):
        quotation_customer = frappe.db.get_value("Quotation", self.quotation, "party_name")
        if not quotation_customer or quotation_customer != self.customer:
            frappe.throw(_("Customer does not match Quotation {0}.").format(self.quotation))


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_access(token):
    if not token:
        frappe.throw(_("Invalid or expired quotation link."), frappe.PermissionError)

    access = frappe.db.get_value(
        "Quotation Customer Access",
        {"token_hash": _hash_token(token)},
        [
            "name",
            "quotation",
            "customer",
            "expires_on",
            "enabled",
            "one_time_use",
            "used_on",
        ],
        as_dict=True,
    )
    if (
        not access
        or not access.enabled
        or get_datetime(access.expires_on) <= now_datetime()
        or (access.one_time_use and access.used_on)
    ):
        frappe.throw(_("Invalid or expired quotation link."), frappe.PermissionError)

    return access


def _validate_quotation(access):
    quotation = frappe.get_doc("Quotation", access.quotation)
    if quotation.docstatus != 1:
        frappe.throw(_("This Quotation is not available for customer response."))
    if quotation.quotation_to != "Customer" or quotation.party_name != access.customer:
        frappe.throw(_("Customer is no longer linked to this Quotation."), frappe.PermissionError)
    return quotation


@frappe.whitelist()
def generate_quotation_customer_link(source_quotation, valid_days=7, one_time_use=0):
    quotation = frappe.get_doc("Quotation", source_quotation)
    if quotation.docstatus != 0:
        frappe.throw(_("Customer quotation links can only be generated for a draft Quotation."))
    if quotation.quotation_to != "Customer" or not quotation.party_name:
        frappe.throw(_("The Quotation must be for a Customer."))
    if not frappe.has_permission("Quotation", "submit", doc=quotation):
        frappe.throw(_("Not permitted to submit this Quotation."), frappe.PermissionError)

    valid_days = cint(valid_days)
    if valid_days < 1:
        frappe.throw(_("Valid For Days must be at least 1."))

    raw_token = secrets.token_urlsafe(32)
    access = frappe.get_doc(
        {
            "doctype": "Quotation Customer Access",
            "quotation": quotation.name,
            "customer": quotation.party_name,
            "token_hash": _hash_token(raw_token),
            "expires_on": add_days(now_datetime(), valid_days),
            "enabled": 1,
            "one_time_use": cint(one_time_use),
        }
    )
    access.insert(ignore_permissions=True)

    quotation_url = "{0}/quotation_response?token={1}".format(get_url(), raw_token)
    frappe.db.set_value(
        "Quotation",
        quotation.name,
        "customer_quotation",
        quotation_url,
        update_modified=False,
    )

    return {
        "access_name": access.name,
        "quotation_url": quotation_url,
        "expires_on": access.expires_on,
    }


@frappe.whitelist(allow_guest=True)
def get_quotation_response(token):
    access = _get_access(token)
    quotation = _validate_quotation(access)

    return {
        "quotation": quotation.name,
        "customer": quotation.customer_name or quotation.party_name,
        "customer_replay": quotation.customer_replay or "",
        "currency": quotation.currency,
        "grand_total": quotation.grand_total,
        "tc_name": quotation.tc_name or "",
        "terms": sanitize_html(quotation.terms or ""),
        "expires_on": access.expires_on,
        "items": [
            {
                "item_code": row.item_code,
                "qty": row.qty,
                "rate": row.rate,
                "amount": row.amount,
                "hsn_sac": row.get("gst_hsn_code") or "",
            }
            for row in quotation.items
        ],
        "taxes": [
            {
                "type": row.charge_type,
                "account_head": row.account_head,
                "rate": row.rate,
                "amount": row.tax_amount,
                "total": row.total,
            }
            for row in quotation.taxes
        ],
        "payment_schedule": [
            {
                "payment_term": row.payment_term or "",
                "description": row.description or "",
                "due_date": row.due_date,
                "invoice_portion": row.invoice_portion,
                "payment_amount": row.payment_amount,
            }
            for row in quotation.payment_schedule
        ],
    }


@frappe.whitelist(allow_guest=True)
def submit_quotation_response(token, customer_replay):
    access = _get_access(token)
    quotation = _validate_quotation(access)
    if customer_replay not in CUSTOMER_RESPONSES:
        frappe.throw(_("Please select Agree or Dis Agree."))

    frappe.db.set_value(
        "Quotation",
        quotation.name,
        "customer_replay",
        customer_replay,
        update_modified=False,
    )

    access_values = {"submitted_on": now_datetime()}
    if access.one_time_use:
        access_values.update({"used_on": now_datetime(), "enabled": 0})
    frappe.db.set_value(
        "Quotation Customer Access",
        access.name,
        access_values,
        update_modified=False,
    )

    return {
        "message": _("Your response was submitted successfully."),
        "quotation": quotation.name,
        "customer_replay": customer_replay,
    }
