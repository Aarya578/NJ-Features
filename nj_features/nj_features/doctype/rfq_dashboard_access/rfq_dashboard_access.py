
# Copyright (c) 2026, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import hashlib
import secrets

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, get_datetime, get_url, now_datetime


class RFQDashboardAccess(Document):
    def validate(self):
        self.validate_supplier_rfq()

    def validate_supplier_rfq(self):
        if not self.rfq:
            return

        supplier_exists = frappe.db.exists(
            "Request for Quotation Supplier",
            {
                "parent": self.rfq,
                "supplier": self.supplier,
            },
        )

        if not supplier_exists:
            frappe.throw(
                _("RFQ {0} does not belong to supplier {1}.").format(
                    frappe.bold(self.rfq),
                    frappe.bold(self.supplier),
                )
            )


@frappe.whitelist()
def generate_access_link(supplier, rfq=None, valid_days=7, one_time_use=0):
    if not frappe.has_permission("RFQ Dashboard Access", "create"):
        frappe.throw(_("Not permitted to generate dashboard links."), frappe.PermissionError)

    return create_access_link(supplier, rfq, valid_days, one_time_use)


def create_access_link(supplier, rfq=None, valid_days=7, one_time_use=0):
    if not frappe.db.exists("Supplier", supplier):
        frappe.throw(_("Supplier does not exist."))

    valid_days = cint(valid_days)
    if valid_days < 1:
        frappe.throw(_("Valid For Days must be at least 1."))

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    access = frappe.get_doc({
        "doctype": "RFQ Dashboard Access",
        "supplier": supplier,
        "rfq": rfq,
        "token_hash": token_hash,
        "expires_on": add_days(now_datetime(), valid_days),
        "enabled": 1,
        "one_time_use": cint(one_time_use),
    })
    access.insert(ignore_permissions=True)

    dashboard_url = "{0}/rfq_dashboard?token={1}".format(
        get_url(),
        raw_token,
    )

    return {
        "access_name": access.name,
        "dashboard_url": dashboard_url,
        "expires_on": access.expires_on,
    }


def get_dashboard_access(token):
    if not token:
        frappe.throw(_("Invalid or expired dashboard link."), frappe.PermissionError)

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    access = frappe.db.get_value(
        "RFQ Dashboard Access",
        {"token_hash": token_hash},
        [
            "name",
            "supplier",
            "rfq",
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
        frappe.throw(_("Invalid or expired dashboard link."), frappe.PermissionError)

    return access


def get_access_rfqs(access):
    if access.rfq:
        return frappe.db.get_all(
            "Request for Quotation",
            filters={
                "name": access.rfq,
                "docstatus": ("<", 2),
            },
            fields=["name", "status"],
        )

    return frappe.db.sql(
        """
        SELECT DISTINCT
            rfq.name,
            rfq.status
        FROM `tabRequest for Quotation` rfq
        INNER JOIN `tabRequest for Quotation Supplier` supplier
            ON supplier.parent = rfq.name
            AND supplier.supplier = %(supplier)s
        WHERE rfq.docstatus < 2
        ORDER BY rfq.modified DESC
        """,
        {"supplier": access.supplier},
        as_dict=True,
    )


@frappe.whitelist(allow_guest=True)
def get_public_dashboard_options(token):
    access = get_dashboard_access(token)

    return {
        "supplier": access.supplier,
        "rfqs": get_access_rfqs(access),
        "expires_on": access.expires_on,
    }


@frappe.whitelist(allow_guest=True)
def get_public_dashboard(token, rfq):
    access = get_dashboard_access(token)

    if not rfq:
        frappe.throw(_("Please select an RFQ."))

    allowed_rfqs = {row.name for row in get_access_rfqs(access)}
    if rfq not in allowed_rfqs:
        frappe.throw(_("RFQ is not permitted for this dashboard link."), frappe.PermissionError)

    from nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_ import (
        get_supplier_rfq_dashboard,
    )

    dashboard = get_supplier_rfq_dashboard(access.supplier, rfq)

    if access.one_time_use:
        frappe.db.set_value(
            "RFQ Dashboard Access",
            access.name,
            {
                "used_on": now_datetime(),
                "enabled": 0,
            },
            update_modified=False,
        )
        frappe.db.commit()

    return dashboard
