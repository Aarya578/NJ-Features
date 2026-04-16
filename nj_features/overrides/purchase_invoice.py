import frappe
from frappe import _
from frappe.utils import flt, cint
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
# from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import (
#     reconcile_dr_cr_note,
# )
from nj_lib.nj_lib.doctype.nj_refund.nj_refund import supplier_payment_reconcile


class CustomPurchaseInvoice(PurchaseInvoice):
    pass


def on_submit_purchase_invoice(doc, method):
    print("on_submit_purchase_invoice============================================================")

    if cint(doc.is_return) != 1:
        return

    frappe.logger().info(f"Calling reconcile for supplier: {doc.supplier}")
    supplier_payment_reconcile(doc.supplier)