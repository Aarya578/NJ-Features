import frappe
from frappe import _

from erpnext.buying.doctype.request_for_quotation.request_for_quotation import (
    RequestforQuotation,
)

from nj_features.nj_features.doctype.rfq_dashboard_access.rfq_dashboard_access import (
    create_access_link,
)


class CustomRequestForQuotation(RequestforQuotation):
    pass


@frappe.whitelist()
def generate_dashboard_link_before_submit(
    source_rfq,
    supplier,
    rfq=None,
    valid_days=7,
    one_time_use=0,
):
    source_doc = frappe.get_doc("Request for Quotation", source_rfq)

    if source_doc.docstatus != 0:
        frappe.throw(_("Dashboard links can only be generated before submitting a draft RFQ."))

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

    return create_access_link(
        supplier=supplier,
        rfq=rfq,
        valid_days=valid_days,
        one_time_use=one_time_use,
    )
