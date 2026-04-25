import frappe
from frappe import _
from frappe.utils import flt, cint
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
# from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import (
#     reconcile_dr_cr_note,
# )
from nj_lib.nj_lib.doctype.nj_refund.nj_refund import supplier_payment_reconcile
# class CustomPurchaseInvoice(PurchaseInvoice):
#     pass
# def on_submit_purchase_invoice(doc, method):
#     print("on_submit_purchase_invoice============================================================")
#     if cint(doc.is_return) != 1:
#         return
#     frappe.logger().info(f"Calling reconcile for supplier: {doc.supplier}")
#     supplier_payment_reconcile(doc.supplier)
class CustomPurchaseInvoice(PurchaseInvoice):
    pass


def _reconcile_supplier_with_elevated_access(supplier):
    current_user = frappe.session.user
    previous_ignore_permissions = getattr(frappe.flags, "ignore_permissions", False)

    try:
        frappe.set_user("Administrator")
        frappe.flags.ignore_permissions = True
        supplier_payment_reconcile(supplier)
    finally:
        frappe.flags.ignore_permissions = previous_ignore_permissions
        frappe.set_user(current_user)


def on_submit_purchase_invoice(doc, method):
    if cint(doc.is_return) != 1:
        return

    frappe.logger().info(f"Calling reconcile for supplier: {doc.supplier}")
    _reconcile_supplier_with_elevated_access(doc.supplier)


def send_invoice_email(doc, method=None):
    """
    Email logic for Purchase Invoice:
    - Purchase Invoice  → always send
    - Purchase Credit Note → always send
    - Deduplication: only send once per unique bill_no
      (skip if another submitted PI with same bill_no already exists before this one)
    """
    try:
        # ── Deduplication by bill_no ──
        if doc.bill_no:
            duplicate = frappe.db.sql("""
                SELECT name FROM `tabPurchase Invoice`
                WHERE bill_no = %s
                  AND docstatus = 1
                  AND name != %s
                  AND creation < (
                      SELECT creation FROM `tabPurchase Invoice` WHERE name = %s
                  )
                LIMIT 1
            """, (doc.bill_no, doc.name, doc.name))

            if duplicate:
                frappe.logger().info(
                    f"Skipping email for {doc.name} — bill_no {doc.bill_no} "
                    f"already emailed via {duplicate[0][0]}"
                )
                return

        recipient = (
            doc.contact_email
            or frappe.db.get_value("Supplier", doc.supplier, "email_id")
        )

        if not recipient:
            frappe.log_error(
                f"No email found for {doc.name} (supplier: {doc.supplier})",
                "NJ Purchase Invoice Email"
            )
            return

        doc_label = "Credit Note" if cint(doc.is_return) else "Purchase Invoice"

        pdf = frappe.get_print(
            "Purchase Invoice",
            doc.name,
            print_format="NJ Purchase Invoice",
            as_pdf=True
        )

        frappe.sendmail(
            recipients=[recipient],
            subject=f"{doc_label} {doc.name} - NEWJAISA Technologies Limited",
            message=f"""<p>Dear {doc.supplier_name},</p>
<p>Please find attached {doc_label} <b>{doc.name}</b> dated {doc.posting_date}
for <b>&#8377; {doc.rounded_total or doc.grand_total}</b>.</p>
<p>For any queries, contact us at support@newjaisa.com</p>
<p>Thanks,<br>NEWJAISA Technologies Limited</p>""",
            attachments=[{"fname": f"{doc.name}.pdf", "fcontent": pdf}]
        )

        frappe.logger().info(
            f"Purchase invoice email sent for {doc.name} to {recipient}"
        )

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"NJ Purchase Invoice Email Failed: {doc.name}"
        )