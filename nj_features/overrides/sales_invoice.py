import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice as CoreSalesInvoice

class SalesInvoice(CoreSalesInvoice):
    def validate(self):
        super(SalesInvoice, self).validate()

        if self.items:
            # Ensure that the sales order exists for the first item in the list
            sales_order = self.items[0].get("sales_order")
            if not sales_order:
                frappe.throw("Sales Order is missing for the first item.")

            total_invoiced_result = frappe.db.sql("""
                SELECT SUM(si.grand_total) AS total_grand_total
                FROM `tabSales Invoice` AS si
                WHERE si.name IN (
                        SELECT DISTINCT sii.parent
                        FROM `tabSales Invoice Item` AS sii
                        WHERE sii.sales_order = %(sales_order)s
                    ) AND si.docstatus = 1
            """, {"sales_order": sales_order}, as_dict=True)

            # Check if any result was returned
            if total_invoiced_result:
                total_invoiced = total_invoiced_result[0].get('total_grand_total') or 0
            else:
                total_invoiced = 0

            sales_order_amount = frappe.db.get_value("Sales Order", sales_order, "grand_total")
            current_total = total_invoiced + self.grand_total

            if current_total > sales_order_amount:
                frappe.throw("Over-Invoicing is not allowed. Current total exceeds Sales Order amount.")
            if current_total < 0:
                frappe.throw("Over Credit Note is not allowed. Total amount cannot be negative.")

            # Handling the is_return case
            if self.is_return:  # Checking if the current invoice is a return
                if self.items[0].get('qty') == 0:  # Check if quantity is zero or less
                    frappe.throw("Credit Note is not allowed as the return quantity is already 0.")
