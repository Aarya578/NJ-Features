import frappe
from frappe import _
from frappe.utils.user import get_user_fullname

from erpnext.buying.doctype.request_for_quotation.request_for_quotation import (
    STANDARD_USERS,
    RequestforQuotation,
)

from nj_features.nj_features.doctype.rfq_customer_quotation_access.rfq_customer_quotation_access import (
    ensure_customer_quotation_links,
)
from nj_features.nj_features.doctype.rfq_dashboard_access.rfq_dashboard_access import (
    create_access_link,
)


class CustomRequestForQuotation(RequestforQuotation):
    CUSTOMER_QUOTATION_OPTION = "Customer Quotation"

    def send_to_supplier(self):
        if self.get("user_selected_option") == self.CUSTOMER_QUOTATION_OPTION:
            ensure_customer_quotation_links(self)
        return super().send_to_supplier()

    def supplier_rfq_mail(self, data, update_password_link, rfq_link, preview=False):
        if self.get("user_selected_option") != self.CUSTOMER_QUOTATION_OPTION:
            return super().supplier_rfq_mail(data, update_password_link, rfq_link, preview)

        if not data.customer_quotation_link:
            frappe.throw(
                _("Customer Quotation Link is missing for Supplier {0}.").format(
                    frappe.bold(data.supplier)
                )
            )

        full_name = get_user_fullname(frappe.session.user)
        if full_name == "Guest":
            full_name = "Administrator"

        supplier_name = None
        if data.contact:
            contact_name = frappe.db.get_value(
                "Contact",
                data.contact,
                ["first_name", "middle_name", "last_name"],
            )
            supplier_name = " ".join(value for value in contact_name if value)

        doc_args = self.as_dict()
        doc_args.update({"supplier": data.supplier, "supplier_name": data.supplier_name})
        message = frappe.render_template(self.message_for_supplier, doc_args)
        email_args = {
            "update_password_link": update_password_link,
            "message": message,
            "customer_quotation_link": data.customer_quotation_link,
            "user_fullname": full_name,
            "supplier_name": supplier_name or data.supplier_name,
            "supplier_salutation": self.salutation or "Dear Mx.",
        }
        email_message = frappe.get_template(
            "nj_features/templates/emails/customer_request_for_quotation.html"
        ).render(email_args)

        if preview:
            return email_message

        subject = self.subject or _("Request for Quotation")
        sender = frappe.session.user if frappe.session.user not in STANDARD_USERS else None
        self.send_email(data, sender, subject, email_message, [])


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
