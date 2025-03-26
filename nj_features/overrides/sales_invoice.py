import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

class CustomSalesInvoice(SalesInvoice):

    def before_submit(self):
        self.update_stock = False