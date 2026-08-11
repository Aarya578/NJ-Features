# Copyright (c) 2026, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import hashlib
import secrets

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, get_datetime, get_url, getdate, now_datetime, nowdate


class RFQCustomerQuotationAccess(Document):
    def validate(self):
        if not frappe.db.exists(
            "Request for Quotation Supplier",
            {"parent": self.rfq, "supplier": self.supplier},
        ):
            frappe.throw(
                _("Supplier {0} is not present in RFQ {1}.").format(
                    frappe.bold(self.supplier),
                    frappe.bold(self.rfq),
                )
            )


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_customer_quotation_access(rfq, supplier, valid_days, one_time_use):
    raw_token = secrets.token_urlsafe(32)
    access = frappe.get_doc(
        {
            "doctype": "RFQ Customer Quotation Access",
            "supplier": supplier,
            "rfq": rfq,
            "token_hash": _hash_token(raw_token),
            "expires_on": add_days(now_datetime(), valid_days),
            "enabled": 1,
            "one_time_use": cint(one_time_use),
        }
    )
    access.insert(ignore_permissions=True)

    return {
        "access_name": access.name,
        "quotation_url": "{0}/customer_quotation?token={1}".format(
            get_url(),
            raw_token,
        ),
        "expires_on": access.expires_on,
    }


def _get_reusable_access(rfq, supplier_row):
    if not supplier_row.customer_quotation_access or not supplier_row.customer_quotation_link:
        return None

    access = frappe.db.get_value(
        "RFQ Customer Quotation Access",
        supplier_row.customer_quotation_access,
        [
            "name",
            "supplier",
            "rfq",
            "token_hash",
            "expires_on",
            "enabled",
            "one_time_use",
            "used_on",
        ],
        as_dict=True,
    )
    if (
        not access
        or access.rfq != rfq
        or access.supplier != supplier_row.supplier
        or not access.enabled
        or get_datetime(access.expires_on) <= now_datetime()
        or (access.one_time_use and access.used_on)
    ):
        return None

    token = supplier_row.customer_quotation_link.partition("token=")[2].partition("&")[0]
    if not token or _hash_token(token) != access.token_hash:
        return None

    return access


def ensure_customer_quotation_links(source_doc, valid_days=7, one_time_use=None):
    """Ensure every supplier selected for email has its own usable access link."""
    valid_days = cint(valid_days)
    default_lead_date = add_days(nowdate(), 3)
    if valid_days < 1:
        frappe.throw(_("Valid For Days must be at least 1."))

    results = []
    for supplier_row in source_doc.suppliers:
        if not supplier_row.send_email:
            continue
        if not supplier_row.supplier:
            frappe.throw(_("Row {0}: Supplier is required.").format(supplier_row.idx))
        if not supplier_row.email_id:
            frappe.throw(
                _("Row {0}: Email Address is required for Supplier {1}.").format(
                    supplier_row.idx,
                    frappe.bold(supplier_row.supplier),
                )
            )

        access = _get_reusable_access(source_doc.name, supplier_row)
        if access:
            result = {
                "access_name": access.name,
                "quotation_url": supplier_row.customer_quotation_link,
                "expires_on": access.expires_on,
            }
        else:
            previous_one_time_use = 0
            if supplier_row.customer_quotation_access:
                previous_one_time_use = cint(
                    frappe.db.get_value(
                        "RFQ Customer Quotation Access",
                        supplier_row.customer_quotation_access,
                        "one_time_use",
                    )
                )
                frappe.db.set_value(
                    "RFQ Customer Quotation Access",
                    supplier_row.customer_quotation_access,
                    "enabled",
                    0,
                    update_modified=False,
                )

            requested_one_time_use = (
                cint(one_time_use) if one_time_use is not None else previous_one_time_use
            )
            result = _create_customer_quotation_access(
                source_doc.name,
                supplier_row.supplier,
                valid_days,
                requested_one_time_use,
            )
            frappe.db.set_value(
                "Request for Quotation Supplier",
                supplier_row.name,
                {
                    "customer_quotation_link": result["quotation_url"],
                    "customer_quotation_access": result["access_name"],
                    "link_expires_on": result["expires_on"],
                },
                update_modified=False,
            )
            supplier_row.customer_quotation_link = result["quotation_url"]
            supplier_row.customer_quotation_access = result["access_name"]
            supplier_row.link_expires_on = result["expires_on"]

        results.append(
            {
                "row_name": supplier_row.name,
                "supplier": supplier_row.supplier,
                **result,
            }
        )

    if not results:
        frappe.throw(_("Select Send Email for at least one supplier."))

    if not source_doc.lead_date:
        frappe.db.set_value(
            "Request for Quotation",
            source_doc.name,
            "lead_date",
            default_lead_date,
            update_modified=False,
        )
        source_doc.lead_date = default_lead_date

    return results


def _get_access(token):
    if not token:
        frappe.throw(_("Invalid or expired quotation link."), frappe.PermissionError)

    access = frappe.db.get_value(
        "RFQ Customer Quotation Access",
        {"token_hash": _hash_token(token)},
        [
            "name",
            "supplier",
            "rfq",
            "expires_on",
            "enabled",
            "one_time_use",
            "used_on",
            "submitted_on",
            "supplier_quotation",
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


@frappe.whitelist()
def generate_customer_quotation_link(
    source_rfq,
    supplier,
    rfq=None,
    valid_days=7,
    one_time_use=0,
):
    source_doc = frappe.get_doc("Request for Quotation", source_rfq)

    if source_doc.docstatus != 0:
        frappe.throw(_("Customer quotation links can only be generated for a draft RFQ."))

    if not frappe.has_permission(
        "Request for Quotation",
        "submit",
        doc=source_doc,
    ):
        frappe.throw(_("Not permitted to submit this Request for Quotation."), frappe.PermissionError)

    allowed_suppliers = {row.supplier for row in source_doc.suppliers if row.supplier}
    if supplier not in allowed_suppliers:
        frappe.throw(
            _("Supplier {0} is not present in this Request for Quotation.").format(
                frappe.bold(supplier)
            ),
            frappe.PermissionError,
        )

    rfq = rfq or source_rfq
    if rfq != source_rfq:
        frappe.throw(_("Customer quotation link must use the current Request for Quotation."))

    valid_days = cint(valid_days)
    if valid_days < 1:
        frappe.throw(_("Valid For Days must be at least 1."))

    return _create_customer_quotation_access(source_rfq, supplier, valid_days, one_time_use)


@frappe.whitelist()
def generate_customer_quotation_links(source_rfq, valid_days=7, one_time_use=0):
    source_doc = frappe.get_doc("Request for Quotation", source_rfq)
    if source_doc.docstatus != 0:
        frappe.throw(_("Customer quotation links can only be generated for a draft RFQ."))

    if not frappe.has_permission("Request for Quotation", "submit", doc=source_doc):
        frappe.throw(_("Not permitted to submit this Request for Quotation."), frappe.PermissionError)

    links = ensure_customer_quotation_links(
        source_doc,
        valid_days=valid_days,
        one_time_use=one_time_use,
    )
    frappe.db.set_value(
        "Request for Quotation",
        source_doc.name,
        "user_selected_option",
        "Customer Quotation",
        update_modified=False,
    )

    return {"links": links}


@frappe.whitelist(allow_guest=True)
def get_customer_quotation(token):
    access = _get_access(token)
    rfq = frappe.get_doc("Request for Quotation", access.rfq)

    if rfq.docstatus == 2:
        frappe.throw(_("This Request for Quotation has been cancelled."), frappe.PermissionError)

    if not any(row.supplier == access.supplier for row in rfq.suppliers):
        frappe.throw(_("Supplier is no longer linked to this RFQ."), frappe.PermissionError)

    return {
        "rfq": rfq.name,
        "supplier": access.supplier,
        "lead_date": rfq.get("lead_date") or "",
        "expires_on": access.expires_on,
        "items": [
            {
                "row_name": row.name,
                "item_code": row.item_code,
                "schedule_date": row.schedule_date,
                "qty": row.qty,
                "rate": row.get("rate") or 0,
                "availability": row.get("availability") or "",
                "available_qty": row.get("available_qty") or 0,
            }
            for row in rfq.items
        ],
    }


@frappe.whitelist(allow_guest=True)
def submit_customer_quotation(token, items, lead_date=None):
    access = _get_access(token)

    if access.supplier_quotation:
        return {
            "message": _("Supplier Quotation {0} was already created.").format(
                access.supplier_quotation
            ),
            "supplier_quotation": access.supplier_quotation,
        }

    submitted_items = frappe.parse_json(items)

    if not isinstance(submitted_items, list) or not submitted_items:
        frappe.throw(_("Please enter quotation rates."))

    rfq = frappe.get_doc("Request for Quotation", access.rfq)
    if rfq.docstatus != 1:
        frappe.throw(
            _("The Request for Quotation must be submitted before a quotation can be created.")
        )

    if not any(row.supplier == access.supplier for row in rfq.suppliers):
        frappe.throw(_("Supplier is no longer linked to this RFQ."), frappe.PermissionError)

    rfq_rows = {row.name: row for row in rfq.items}
    submitted_row_names = set()
    validated_items = {}

    if not lead_date:
        frappe.throw(_("Please enter the Lead Date."))

    try:
        lead_date = getdate(lead_date)
    except (TypeError, ValueError):
        frappe.throw(_("Please enter a valid Lead Date."))

    for submitted_row in submitted_items:
        row_name = submitted_row.get("row_name")
        item_code = submitted_row.get("item_code")
        rfq_row = rfq_rows.get(row_name)

        if not rfq_row or rfq_row.item_code != item_code:
            frappe.throw(_("Invalid RFQ item submitted."), frappe.PermissionError)

        if row_name in submitted_row_names:
            frappe.throw(_("Duplicate RFQ item submitted."))

        submitted_row_names.add(row_name)
        rate = flt(submitted_row.get("rate"))
        availability = submitted_row.get("availability")
        available_qty_value = flt(submitted_row.get("available_qty"))

        if rate < 0:
            frappe.throw(_("Rate cannot be negative for item {0}.").format(frappe.bold(item_code)))

        if availability not in ("Yes", "No"):
            frappe.throw(
                _("Please select Availability as Yes or No for item {0}.").format(
                    frappe.bold(item_code)
                )
            )

        if available_qty_value < 0 or available_qty_value != int(available_qty_value):
            frappe.throw(
                _("Available Qty must be a non-negative whole number for item {0}.").format(
                    frappe.bold(item_code)
                )
            )

        validated_items[row_name] = {
            "rate": rate,
            "availability": availability,
            "available_qty": int(available_qty_value),
        }

    if submitted_row_names != set(rfq_rows):
        frappe.throw(_("Rates must be submitted for all RFQ items."))

    from erpnext.buying.doctype.request_for_quotation.request_for_quotation import (
        make_supplier_quotation_from_rfq,
    )

    supplier_quotation = make_supplier_quotation_from_rfq(
        rfq.name,
        for_supplier=access.supplier,
    )
    supplier_quotation.lead_date = lead_date

    quotation_rows = {
        row.request_for_quotation_item: row for row in supplier_quotation.items
    }
    if set(quotation_rows) != set(rfq_rows):
        frappe.throw(_("Unable to map all RFQ items to the Supplier Quotation."))

    for row_name, values in validated_items.items():
        quotation_row = quotation_rows[row_name]
        quotation_row.rate = values["rate"]
        quotation_row.availability = values["availability"]
        quotation_row.available_qty = values["available_qty"]
        quotation_row.request_for_quotation = rfq.name

    supplier_quotation.insert(ignore_permissions=True)

    access_values = {
        "submitted_on": now_datetime(),
        "supplier_quotation": supplier_quotation.name,
    }
    if access.one_time_use:
        access_values.update(
            {
                "used_on": now_datetime(),
                "enabled": 0,
            }
        )

    frappe.db.set_value(
        "RFQ Customer Quotation Access",
        access.name,
        access_values,
        update_modified=False,
    )

    return {
        "message": _("Supplier Quotation {0} created successfully.").format(
            supplier_quotation.name
        ),
        "supplier_quotation": supplier_quotation.name,
    }
