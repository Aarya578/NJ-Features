import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list

class CustomSalesInvoice(SalesInvoice):

    def before_submit(self):
        """ Prevent stock update on submission, but retain packed items """
        self.update_stock = False
        super().before_submit()

    def update_packing_list(self):
        """ Override the default method to prevent clearing packed_items """
        if self.update_stock:
            make_packing_list(self)
        # Removed the `else` block to prevent clearing packed_items

# Hook this class to override default Sales Invoice behavior
def override_sales_invoice():
    from erpnext.accounts.doctype.sales_invoice import sales_invoice
    sales_invoice.SalesInvoice = CustomSalesInvoice
