import frappe
import time
from frappe import _
from frappe.utils import flt, cint
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
# from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import (
#     reconcile_dr_cr_note,
# )
from nj_lib.nj_lib.doctype.nj_refund.nj_refund import supplier_payment_reconcile

logger = frappe.logger("pitimelog", allow_site=True, file_count=1)


def log_pi_time(label, docname, start):
    logger.debug(f"[PI: {docname}] {label} took {time.perf_counter() - start:.4f} seconds")


# class CustomPurchaseInvoice(PurchaseInvoice):
#     pass
# def on_submit_purchase_invoice(doc, method):
#     print("on_submit_purchase_invoice============================================================")
#     if cint(doc.is_return) != 1:
#         return
#     frappe.logger().info(f"Calling reconcile for supplier: {doc.supplier}")
#     supplier_payment_reconcile(doc.supplier)
class CustomPurchaseInvoice(PurchaseInvoice):
    def before_submit(self):
        start = time.perf_counter()
        try:
            self.email_field_filling()
        finally:
            log_pi_time("before_submit", self.name, start)

    def email_field_filling(self):
        start = time.perf_counter()
        try:
            print("inside email_field_filling=================")
            if not self.shipping_address:
                frappe.throw(_("Please select Customer Address"))

            # Fetch email_id from Address doctype
            email_id = frappe.db.get_value("Address", self.shipping_address, "email_id")
            print("email_id===================", email_id)

            if email_id:
                self.email = email_id
                print("self.email===================", self.email)
            else:
                frappe.throw(_("Please enter Email ID in Customer Address"))
        finally:
            log_pi_time("email_field_filling", self.name, start)


def _reconcile_supplier_with_elevated_access(supplier):
    start = time.perf_counter()
    previous_ignore_permissions = getattr(frappe.flags, "ignore_permissions", False)
    previous_ignore_account_permission = getattr(
        frappe.flags, "ignore_account_permission", False
    )

    try:
        frappe.flags.ignore_permissions = True
        frappe.flags.ignore_account_permission = True
        supplier_payment_reconcile(supplier)
    finally:
        frappe.flags.ignore_permissions = previous_ignore_permissions
        frappe.flags.ignore_account_permission = previous_ignore_account_permission
        log_pi_time("_reconcile_supplier_with_elevated_access", supplier, start)


def on_submit_purchase_invoice(doc, method):
    start = time.perf_counter()
    try:
        if cint(doc.is_return) != 1:
            return

        # Supplier reconciliation scans all unreconciled invoices/payments for
        # the supplier and can take minutes. The submitted Debit Note is
        # already part of the surrounding transaction, so run this independent
        # maintenance step only after that transaction commits.
        frappe.enqueue(
            "nj_features.overrides.purchase_invoice."
            "_reconcile_supplier_with_elevated_access",
            queue="long",
            timeout=1800,
            enqueue_after_commit=True,
            job_name=f"supplier_payment_reconcile_{doc.name}",
            supplier=doc.supplier,
        )
        frappe.logger().info(
            "Queued supplier reconciliation for %s after submitting %s",
            doc.supplier,
            doc.name,
        )
    finally:
        log_pi_time("on_submit_purchase_invoice", doc.name, start)


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
