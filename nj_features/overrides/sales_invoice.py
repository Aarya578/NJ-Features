import frappe
from frappe import _
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list

class CustomSalesInvoice(SalesInvoice):

    def before_submit(self):
        """ Prevent stock update on submission, but retain packed items """
        self.update_stock = False

    def update_packing_list(self):
        """ Override the default method to prevent clearing packed_items """
        if self.update_stock:
            make_packing_list(self)
        # Removed the `else` block to prevent clearing packed_items

# Hook this class to override default Sales Invoice behavior
def override_sales_invoice():
    from erpnext.accounts.doctype.sales_invoice import sales_invoice
    sales_invoice.SalesInvoice = CustomSalesInvoice

from frappe.utils import nowdate, add_days, getdate

@frappe.whitelist()
def mail_trigger_for_payment_terms_from_quotation():
    try:
        quotation_data = frappe.db.sql("""
            SELECT q.name
            FROM `tabQuotation` q
            WHERE q.docstatus = 1
              AND q.creation >= DATE_SUB(CURDATE(), INTERVAL 2 MONTH)
              AND (
                  SELECT COUNT(*) 
                  FROM `tabPayment Schedule` ps 
                  WHERE ps.parent = q.name
              ) > 1
        """, as_dict=1)

        if not quotation_data:
            frappe.msgprint("No matching quotations found.")
            return

        for quotation in quotation_data:
            quotation_name = quotation["name"]

            sales_orders = frappe.db.sql("""
                SELECT DISTINCT parent
                FROM `tabSales Order Item`
                WHERE prevdoc_docname = %s AND docstatus = 1
            """, quotation_name, as_dict=1)

            for so in sales_orders:
                sales_order_name = so["parent"]

                sales_invoices = frappe.db.sql("""
                    SELECT si.name, si.customer
                    FROM `tabSales Invoice` si
                    JOIN `tabSales Invoice Item` sii ON si.name = sii.parent
                    WHERE si.docstatus = 1 AND si.is_return = 0 AND sii.sales_order = %s
                """, sales_order_name, as_dict=1)

                for sinv in sales_invoices:
                    sinv_name = sinv["name"]
                    customer = sinv["customer"]

                    payment_terms = frappe.db.sql("""
                        SELECT due_date, invoice_portion, payment_amount
                        FROM `tabPayment Schedule`
                        WHERE parent = %s
                    """, sinv_name, as_dict=1)

                    print("payment_terms", payment_terms)
                    for term in payment_terms:
                        due_date = getdate(term["due_date"])
                        tomorrow = getdate(add_days(nowdate(), 1))

                        if due_date == tomorrow:
                            # Try Address table first
                            customer_email = frappe.db.get_value("Address", {"address_title": customer}, "email_id")

                            # Fallback to Customer table if not found
                            if not customer_email:
                                customer_email = frappe.db.get_value("Customer", customer, "email_id")

                            if customer_email:
                                cc_mail = ["accounts@newjaisa.com"]
                                subject = f"Upcoming Payment Due for Invoice {sinv_name}"
                                message = f"""
                                    Dear Customer,<br><br>
                                    This is a reminder that a payment of ₹{term['payment_amount']} 
                                    (portion: {term['invoice_portion']}%) is due tomorrow 
                                    ({due_date}) for Sales Invoice <strong>{sinv_name}</strong>.<br><br>
                                    If you have already made the payment, please disregard this message.<br>
                                    This is an auto-generated reminder.<br><br>
                                    Kindly make the payment on time.<br><br>
                                    Regards,<br>
                                    NewJaisa Technologies Ltd
                                """
                                send_email_to_user_for_payment_terms(customer_email, subject, message, cc_mail)
                            else:
                                msg = f"No email found for customer {customer}"
                                print(msg)
                                frappe.log_error(msg, "Email Not Sent")
    except Exception as e:
        frappe.log_error(message=str(e), title="Error while triggering payment terms email")
        frappe.throw(f"Error while triggering payment terms email: {str(e)}")


def send_email_to_user_for_payment_terms(recipient_email, subject, message, cc_emails=None):
    try:
        email_args = {
            'recipients': recipient_email,
            'cc': cc_emails,
            'subject': subject,
            'message': message,
            'reference_doctype': None,
            'reference_name': None,
            'attachments': None,
        }

        frappe.sendmail(**email_args)
        frappe.msgprint(f"Email sent successfully to {recipient_email}")
    except Exception as e:
        frappe.log_error(message=str(e), title="Email Sending Failed")
        frappe.throw(f"Failed to send email: {str(e)}")

@frappe.whitelist()
def custom_bulk_update_approved(names, approved_value):
    try:
        if isinstance(names, str):
            names = frappe.parse_json(names)

        if "Accounts Manager" not in frappe.get_roles():
            frappe.throw(_("You are not authorized to perform this action."))

        updated = 0

        for name in names:
            doc = frappe.get_doc("Sales Invoice", name)

            if not frappe.has_permission(doctype="Sales Invoice", ptype="write", doc=doc):
                frappe.msgprint(_("No write access for {0}").format(name))
                continue

            doc.approved = int(approved_value)
            doc.save(ignore_permissions=True)
            updated += 1

        return {
            "updated": updated,
            "status": "success"
        }

    except Exception as e:
        frappe.log_error(message=str(e), title="Bulk Update Failed")
        frappe.throw(f"Failed to bulk update: {str(e)}")