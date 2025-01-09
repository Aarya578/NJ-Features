import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice as CoreSalesInvoice

class SalesInvoice(CoreSalesInvoice):
       def validate(self):
        super(SalesInvoice, self).validate()

        if self.items:
            total_invoiced = frappe.db.sql("""
                SELECT 
                    SUM(b.grand_total) AS total_grand_total
                FROM 
                    `tabSales Invoice Item` AS a
                INNER JOIN 
                    `tabSales Invoice` AS b 
                ON 
                    b.name = a.parent
                WHERE 
                    a.sales_order = %(sales_order)s
                    AND b.docstatus = 1
            """, {"sales_order": self.items[0].get("sales_order")}, as_dict=True)[0].get('total_grand_total') or 0
            print("=========total invoiced =amount===24=====", total_invoiced)

            sales_order_amount = frappe.db.get_value("Sales Order", self.items[0].get("sales_order"), "grand_total")
            print("==============sales - orders===amount ===30===", sales_order_amount)
            current_total = total_invoiced + self.grand_total
            print("====alculate current total after including this invoice====34=", sales_order_amount)

            if current_total > sales_order_amount:
                frappe.throw("Over-Invoicing is not allowed. Current total exceeds Sales Order amount.")
            if current_total < 0:
                frappe.throw("Over Credit Note is not allowed. Total amount cannot be negative.")

            # Handling the is_return case
            if self.is_return:  # Checking if the current invoice is a return
                if self.items[0].get('qty') == 0:  # Check if quantity is zero or less
                    frappe.throw("Credit Note is not allowed as the is return quantity already 0.")
                # is_return = self.is_return
                # if is_return == 0:
                #     frappe.throw("Credit Note is not allowed as the net outstanding already 0.")



