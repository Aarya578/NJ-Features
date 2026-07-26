from tokenize import Ignore
from frappe import _
import json
import requests
import frappe
import six
import frappe, json, six
from frappe.utils import (
    flt, getdate, cint,add_days, nowdate, getdate
)
from erpnext.regional.india.e_invoice.utils import (
    read_json,
    get_transaction_details,
    get_doc_details,
    get_invoice_value_details,
    get_party_details,
    get_overseas_address_details,
    get_place_of_supply,
    sanitize_for_json,
    get_payment_details,
    get_return_doc_reference,
    get_eway_bill_details,
    update_item_taxes,
    safe_json_load,
    santize_einvoice_fields,
    validate_totals,
    show_link_to_error_log,
    log_error,
)
from frappe.utils.print_format import download_pdf
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from erpnext.regional.india.e_invoice.utils import raise_document_name_too_long_error
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list

class CustomSalesInvoice(SalesInvoice):
    def on_submit(self):
        super(CustomSalesInvoice, self).on_submit()
        self.close_sales_order_if_fully_refunded()
        self.validate_si_tax_presence()
    

    def close_sales_order_if_fully_refunded(self):
        """Close linked Sales Orders if full qty refunded via Credit Notes"""

        if not self.is_return:
            return

        if not self.return_against:
            return

        original_sinv = frappe.get_doc("Sales Invoice", self.return_against)

        # collect SOs from line items
        sales_orders = {d.sales_order for d in original_sinv.items if d.sales_order}
        if not sales_orders:
            return

        # Total qty of original SINV
        total_original_qty = sum([d.qty for d in original_sinv.items])

        # Total returned qty across all credit notes
        returned_qty = 0
        credit_notes = frappe.get_all(
            "Sales Invoice",
            filters={"is_return": 1, "return_against": original_sinv.name, "docstatus": 1},
            fields=["name"]
        )
        for cn in credit_notes:
            cn_doc = frappe.get_doc("Sales Invoice", cn.name)
            returned_qty += sum([abs(d.qty) for d in cn_doc.items])

        # If fully refunded, close each linked SO
        if flt(returned_qty, 2) >= flt(total_original_qty, 2):
            for so_name in sales_orders:
                so = frappe.get_doc("Sales Order", so_name)
                so.update_status("Closed")
                frappe.msgprint(f"Sales Order {so.name} is closed as full qty refunded.")

    def validate(self):
        self.set_linked_sales_order_advances()
        super(CustomSalesInvoice, self).validate()
        # if self.is_return==1 and frappe.db.get_value("Sales Invoice",self.return_against,"status")!="Paid":
        #     frappe.throw(f"Sales Invoice:{self.return_against} is not paid")

        einvoice_settings = frappe.get_cached_doc("E Invoice Settings")
        if einvoice_settings.enable:
            self.validate_einvoice_fields()
        else:
            return  # Skip validation if e-invoicing is not enabled

    def set_linked_sales_order_advances(self):
        """Fetch submitted advances linked to the Sales Orders in this invoice."""
        if self.is_return or self.is_pos:
            return

        sales_orders = {item.sales_order for item in self.items if item.sales_order}
        if not sales_orders:
            return

        advance_entries = self.get_advance_entries(include_unallocated=False)
        if not advance_entries:
            return

        existing_rows = {
            (row.reference_type, row.reference_name, row.reference_row)
            for row in self.advances
        }
        allocated_amount = sum(flt(row.allocated_amount) for row in self.advances)
        if self.party_account_currency == self.company_currency:
            invoice_amount = flt(self.base_rounded_total or self.base_grand_total)
        else:
            invoice_amount = flt(self.rounded_total or self.grand_total)

        for entry in advance_entries:
            entry_key = (entry.reference_type, entry.reference_name, entry.reference_row)
            if entry.against_order not in sales_orders or entry_key in existing_rows:
                continue

            remaining_amount = max(invoice_amount - allocated_amount, 0)
            if not remaining_amount:
                break

            amount = flt(entry.amount)
            amount_to_allocate = min(amount, remaining_amount)
            self.append("advances", {
                "reference_type": entry.reference_type,
                "reference_name": entry.reference_name,
                "reference_row": entry.reference_row,
                "remarks": entry.remarks,
                "advance_amount": amount,
                "allocated_amount": amount_to_allocate,
                "ref_exchange_rate": flt(entry.exchange_rate),
            })
            existing_rows.add(entry_key)
            allocated_amount += amount_to_allocate

    def before_submit(self):
        """ Prevent stock update on submission, but retain packed items """
        self.update_stock = False
        self.approve_validation()
        self.email_field_filling()

    def update_packing_list(self):
        """ Override the default method to prevent clearing packed_items """
        if self.update_stock:
            make_packing_list(self)
        # Removed the `else` block to prevent clearing packed_items

    def validate_einvoice_fields(self):
        
        invoice_eligible = _validate_eligibility(self)
        if not invoice_eligible:
            return
        sales_order_name = None
        for item in self.items:
            if item.sales_order:
                sales_order_name = item.sales_order
                break

        if not sales_order_name:
            frappe.throw("No sales order found for this sales invoice.")

        query = """
            SELECT 
                si.name AS sales_invoice, 
                so.approve 
            FROM `tabSales Invoice` si 
            INNER JOIN `tabSales Invoice Item` sii     
                ON si.name = sii.parent 
            INNER JOIN `tabSales Order` so
                ON sii.sales_order = so.name 
            WHERE so.name = %s 
        """  
        results = frappe.db.sql(query, (sales_order_name,), as_dict=True) 
        # print("results=======================",results)       
        for row in results:        
            if not row.approve or int(row.approve) != 1:
                # self.approved = 1
                frappe.throw(f"Sales Order {sales_order_name} is not approved. Please approve it first.")
            else:
                self.approved = 1
        if self.docstatus == 0 and self._action == "save":
            if self.irn:
                frappe.throw(_("You cannot edit the invoice after generating IRN"), title=_("Edit Not Allowed"))
            if len(self.name) > 16:
                raise_document_name_too_long_error()
            self.einvoice_status = "Pending"

        elif self.docstatus == 1 and self._action == "submit" and not self.irn:
            frappe.throw(_("You must generate IRN before submitting the document."), title=_("Missing IRN"))

        elif self.irn and self.docstatus == 2 and self._action == "cancel" and not self.irn_cancelled:
            frappe.throw(_("You must cancel IRN before cancelling the document."), title=_("Cancel Not Allowed"))

    def approve_validation(self):
        if self.is_return == 1:
            return
        # get first sales_order from child table
        sales_order_name = None
        for item in self.items:
            if item.sales_order:
                sales_order_name = item.sales_order
                break

        if not sales_order_name:
            frappe.throw("No sales order found for this sales invoice.")

        query = """
            SELECT 
                si.name AS sales_invoice, 
                so.approve 
            FROM `tabSales Invoice` si 
            INNER JOIN `tabSales Invoice Item` sii     
                ON si.name = sii.parent 
            INNER JOIN `tabSales Order` so
                ON sii.sales_order = so.name 
            WHERE so.name = %s 
        """  
        results = frappe.db.sql(query, (sales_order_name,), as_dict=True)  
        for row in results:        
            if not row.approve or int(row.approve) != 1:
                # self.approved = 1
                frappe.throw(f"Sales Order {sales_order_name} is not approved. Please approve it first.")
            else:
                self.approved = 1

    def email_field_filling(self):
        if not self.customer_address:
            frappe.throw(_("Please select Customer Address"))

        # Fetch email_id from Address doctype
        email_id = frappe.db.get_value("Address", self.customer_address, "email_id")

        if email_id:
            self.email = email_id
        else:
            frappe.throw(_("Please enter Email ID in Customer Address"))      
    def validate_si_tax_presence(self):
        # print("inside tax validation=================")

        if not self.name:
            return

        # 🔹 Fetch values from Sales Invoice
        data = frappe.db.get_value(
            "Sales Invoice",
            self.name,
            ["total", "total_taxes_and_charges"],
            as_dict=True
        )

        if not data:
            return

        total = data.get("total") or 0
        taxes = data.get("total_taxes_and_charges") or 0

        # print("total=================", total)
        # print("taxes=================", taxes)

        # ✅ Condition
        if total > 0 and taxes == 0:
            frappe.throw(_(
                f"""Invalid Sales Invoice!

    Total is {total} but Taxes & Charges is 0.

    Please ensure taxes are applied before proceeding."""
            ))

# Hook this class to override default Sales Invoice behavior
def override_sales_invoice():
    from erpnext.accounts.doctype.sales_invoice import sales_invoice
    sales_invoice.SalesInvoice = CustomSalesInvoice


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

                    for term in payment_terms:
                        due_date = getdate(term["due_date"])
                        tomorrow = getdate(add_days(nowdate(), 1))

                        if due_date == tomorrow:
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
    if isinstance(names, str):
        names = frappe.parse_json(names)
    
    if "Accounts Manager" not in frappe.get_roles(frappe.session.user):
        frappe.throw(_("You don't have the permission to perform this action."))

    has_permission = frappe.db.exists(
        "Custom DocPerm",
        {
            "parent": "Sales Invoice",
            "permlevel": 1,
            "write": 1,
            "role": "Accounts Manager"
        }
    )

    if not has_permission:
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

def get_shipping_address_gstin(doc):
    if not doc.get("shipping_address_name"):
        return ""

    return frappe.db.get_value("Address", doc.get("shipping_address_name"), "gstin") or ""


def get_customer_address_gstin(doc):
    if not doc.get("customer_address"):
        return ""

    return frappe.db.get_value("Address", doc.get("customer_address"), "gstin") or ""


def get_ship_to_gstin(doc):
    return (doc.get("customer_gstin") or get_shipping_address_gstin(doc) or "URP").strip()


def should_send_shipping_and_dispatch_details(doc):
    customer_gstin = (get_customer_address_gstin(doc) or "").strip()
    ship_to_gstin = get_ship_to_gstin(doc)
    return customer_gstin != ship_to_gstin


# ✅ Used inside validate()
def custom_validate_mandatory_fields(doc):
    if not doc.company_address:
        frappe.throw(
            _("Company Address is mandatory to fetch company GSTIN details. Please set Company Address and try again."),
            title=_("Missing Fields"),
        )

    if not doc.customer_address:
        frappe.throw(
            _("Customer Address is mandatory to fetch customer GSTIN details. Please set Customer Address and try again."),
            title=_("Missing Fields"),
        )

    if not (doc.get("shipping_address_name") or "").strip():
        frappe.throw(
            _("Kindly Select Shipping Address Name"),
            title=_("Missing Fields"),
        )

    company_gstin = frappe.db.get_value("Address", doc.company_address, "gstin")
    if not company_gstin:
        frappe.throw(
            _("GSTIN is mandatory to fetch company GSTIN details. Please enter GSTIN in selected company address."),
            title=_("Missing Fields"),
        )

    # Only skip GSTIN check if total is <= 50000
    if flt(doc.get("grand_total")) <= 50000:
        return

    # shipping_gstin = (
    #     frappe.db.get_value("Address", doc.customer_address, "gstin")
    #     if doc.customer_address else None
    # )
    # if (doc.get("billing_address_gstin") is None or doc.get("billing_address_gstin") == "undefined") and flt(doc.get("grand_total")) <= 50000:  
    #     return

    # if doc.gst_category != "Overseas" and not shipping_gstin:
    #     frappe.throw(
    #         _(
    #         "GSTIN is not found in selected *Shipping Address* Please Create 'E-Way Bill' Directly."),
    #         title=_("Missing GSTIN in Shipping Address"),
    #     )

def custom_make_einvoice(invoice):
    custom_validate_mandatory_fields(invoice)
    schema = read_json("einv_template")

    transaction_details = get_transaction_details(invoice)
    item_list = get_item_list(invoice)
    doc_details = get_doc_details(invoice)
    invoice_value_details = get_invoice_value_details(invoice)
    seller_details = get_party_details(invoice.company_address)
    # dipatch_address = get_party_details(invoice.dispatch_address_name)
    # shipping_address = get_party_details(invoice.shipping_address_name)

    if invoice.gst_category == "Overseas":
        buyer_details = get_overseas_address_details(invoice.customer_address)
    else:
        buyer_details = get_party_details(invoice.customer_address)
        place_of_supply = get_place_of_supply(invoice, invoice.doctype)
        if place_of_supply:
            place_of_supply = place_of_supply.split("-")[0]
        else:
            place_of_supply = sanitize_for_json(invoice.billing_address_gstin)[:2]
        buyer_details.update(dict(place_of_supply=place_of_supply))

    seller_details.update(dict(legal_name=invoice.company))
    buyer_details.update(dict(legal_name=invoice.customer_name or invoice.customer))

    shipping_details = payment_details = prev_doc_details = eway_bill_details = frappe._dict({})
    send_shipping_and_dispatch_details = should_send_shipping_and_dispatch_details(invoice)
    if invoice.shipping_address_name and send_shipping_and_dispatch_details:
        if invoice.gst_category == "Overseas":
            shipping_details = get_overseas_address_details(invoice.shipping_address_name)
        else:
            shipping_details = get_party_details(invoice.shipping_address_name, skip_gstin_validation=True)
            shipping_details.gstin = get_ship_to_gstin(invoice)

    dispatch_details = frappe._dict({})
    if send_shipping_and_dispatch_details and invoice.dispatch_address_name:
        dispatch_details = get_party_details(invoice.dispatch_address_name, skip_gstin_validation=True)

    if invoice.is_pos and invoice.base_paid_amount:
        payment_details = get_payment_details(invoice)

    if invoice.is_return and invoice.return_against:
        prev_doc_details = get_return_doc_reference(invoice)

    if invoice.transporter and not invoice.is_return:
        eway_bill_details = get_eway_bill_details(invoice)

    period_details = export_details = frappe._dict({})

    einvoice = schema.format(
        transaction_details=transaction_details,
        doc_details=doc_details,
        dispatch_details=dispatch_details,
        seller_details=seller_details,
        buyer_details=buyer_details,
        shipping_details=shipping_details,
        item_list=item_list,
        invoice_value_details=invoice_value_details,
        payment_details=payment_details,
        period_details=period_details,
        prev_doc_details=prev_doc_details,
        export_details=export_details,
        eway_bill_details=eway_bill_details,
    )

    try:
        einvoice = safe_json_load(einvoice)
        einvoice = santize_einvoice_fields(einvoice)
    except json.JSONDecodeError:
        raise
    except Exception:
        show_link_to_error_log(invoice, einvoice)

    try:
        validate_totals(einvoice)
    except Exception:
        log_error(einvoice)
        raise

    return einvoice


def get_item_list(invoice):
    item_list = []

    hide_discount_in_einvoice = cint(
        frappe.db.get_single_value("E Invoice Settings", "dont_show_discounts_in_e_invoice")
    )

    for d in invoice.items:
        einvoice_item_schema = read_json("einv_item_template")
        item = frappe._dict({})
        item.update(d.as_dict())

        item.sr_no = d.idx
        item.description = sanitize_for_json(d.item_name)

        item.qty = abs(item.qty)
        item_qty = item.qty
        item.taxable_value = abs(item.taxable_value)

        if invoice.get("is_return") or invoice.get("is_debit_note"):
            item_qty = item_qty or 1

        if hide_discount_in_einvoice or invoice.is_internal_customer or item.discount_amount < 0:
            item.unit_rate = item.taxable_value / item_qty
            item.gross_amount = item.taxable_value
            item.discount_amount = 0
        else:
            if invoice.get("apply_discount_on") and (abs(invoice.get("base_discount_amount") or 0.0) > 0.0):
                item.discount_amount = (item.discount_amount * item_qty) + (
                    abs(item.base_amount) - abs(item.base_net_amount)
                )
            else:
                item.discount_amount = item.discount_amount * item_qty

            try:
                item.unit_rate = (item.taxable_value + item.discount_amount) / item_qty
            except ZeroDivisionError:
                frappe.throw(_("Quantity can't be zero unless it's Credit/Debit Note."), title=_("Error: Qty is Zero"))

        item.gross_amount = item.taxable_value + item.discount_amount
        item.is_service_item = "Y" if item.gst_hsn_code and item.gst_hsn_code[:2] == "99" else "N"
        item.serial_no = ""

        item = update_item_taxes(invoice, item)

        item.total_value = abs(
            item.taxable_value
            + item.igst_amount
            + item.sgst_amount
            + item.cgst_amount
            + item.cess_amount
            + item.cess_nadv_amount
            + item.other_charges
        )

        einv_item = einvoice_item_schema.format(item=item)
        item_list.append(einv_item)

    return ", ".join(item_list)
# ✅ JS call-compatible
@frappe.whitelist()
def validate_eligibility(doc):
    if isinstance(doc, six.string_types):
        doc = json.loads(doc)
    return _validate_eligibility(doc)

# ✅ Internal validation
def _validate_eligibility(doc):

    if doc.get("doctype") != "Sales Invoice":
        return False
    if (doc.get("billing_address_gstin") is None or doc.get("billing_address_gstin") == "undefined") and flt(doc.get("grand_total")) >= 50000:
        if doc.get("ewaybill"):
            return False
        return True

    if (doc.get("billing_address_gstin")): 
        return True
    
    if flt(doc.get("grand_total")) <= 50000:
        return False
    

    einvoicing_enabled = cint(frappe.db.get_single_value("E Invoice Settings", "enable"))
    if not einvoicing_enabled:
        return False

    einvoicing_eligible_from = (
        frappe.db.get_single_value("E Invoice Settings", "applicable_from") or "2021-04-01"
    )
    if getdate(doc.get("posting_date")) < getdate(einvoicing_eligible_from):
        return False

    invalid_company_gstin = not frappe.db.get_value("E Invoice User", {"gstin": doc.get("company_gstin")})

    no_taxes_applied = (
        not doc.get("taxes")
        and doc.get("gst_category") not in ["Overseas", "SEZ"]
    )
    has_non_gst_item = any(d for d in doc.get("items", []) if d.get("is_non_gst"))

    if (
        invalid_company_gstin
        or no_taxes_applied
        or has_non_gst_item
    ):
        return False

    return True        

@frappe.whitelist()
def generate_eway_bill(docname):
    try:
        # Step 1: Authenticate
        token = frappe.db.get_single_value("Logistics Settings", "api_token")
        secret = frappe.db.get_single_value("Logistics Settings", "api_secret")
        auth_headers = {
            "gspappid": token,
            "gspappsecret": secret,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        auth_res = requests.post(
            "https://gsp.adaequare.com/gsp/authenticate?action=GSP&grant_type=token",
            headers=auth_headers,
            data={"grant_type": "client_credentials"}
        )
        auth_json = auth_res.json()
        access_token = auth_json.get("access_token")
        if not access_token:
            frappe.throw(_("Failed to fetch access token."))

        # Step 2: Load Sales Invoice
        invoice = frappe.get_doc("Sales Invoice", docname)
        dispatch_address_name = frappe.get_doc("Address", invoice.dispatch_address_name) if invoice.dispatch_address_name else None
        company_address = frappe.get_doc("Address", invoice.company_address) if invoice.company_address else None

        if dispatch_address_name:
            final_address = dispatch_address_name
        else:
            final_address = company_address

        customer_address = frappe.get_doc("Address", invoice.customer_address) if invoice.customer_address else None
        shipping_address_name = frappe.get_doc("Address", invoice.shipping_address_name) if invoice.shipping_address_name else None

        # Step 3: Prepare Item List
        item_list = []
        for row in invoice.items:
            item = frappe.get_doc("Item", row.item_code)
            item_list.append({
                "productName": row.item_name,
                "productDesc": item.description or "",
                "hsnCode": item.gst_hsn_code or "",
                "quantity": float(row.qty),
                "qtyUnit": row.uom or "BOX",
                "cgstRate": 0.0,
                "sgstRate": 0.0,
                "igstRate": 18.0, 
                "cessRate": 0.0,
                "cessNonadvol": 0.0,
                "taxableAmount": float(row.amount)  
            })

        # Step 4: Prepare payload
        payload = {
            "supplyType": "O",
            "subSupplyType": "1",
            "subSupplyDesc": "",
            "docType": "INV",
            "docNo": invoice.name,
            "docDate": invoice.posting_date.strftime("%d/%m/%Y"),
            "fromGstin": company_address.gstin,
            "fromTrdName": invoice.company,
            "fromAddr1": final_address.address_line1,
            "fromAddr2": final_address.address_line2,
            "fromPlace": final_address.city,
            "fromPincode": final_address.pincode,
            "actFromStateCode": final_address.gst_state_number,
            "fromStateCode": final_address.gst_state_number,
            "toGstin": customer_address.gstin or "URP",
            "toTrdName": invoice.customer,
            "toAddr1": shipping_address_name.address_line1,
            "toAddr2": shipping_address_name.address_line2,
            "toPlace": shipping_address_name.city,
            "toPincode": shipping_address_name.pincode,
            "actToStateCode": shipping_address_name.gst_state_number,
            "toStateCode": customer_address.gst_state_number,
            "transactionType": 4,
            "otherValue": "0",
            "totalValue": invoice.total,
            "cgstValue": 0,
            "sgstValue": 0,
            "igstValue": invoice.total * 0.18,  # Approximate IGST if applicable
            "cessValue": 0,
            "cessNonAdvolValue": 0,
            "totInvValue": invoice.grand_total,
            "transporterId": "29AMBPG7773M000",
            "transporterName": "Test",
            "transDocNo": "",
            "transMode": "",
            "transDistance": "0",
            "transDocDate": "",
            "vehicleNo": "",
            "vehicleType": "",
            "itemList": item_list
        }
        # Step 5: Make API Call
        username = frappe.db.get_single_value("Logistics Settings", "username")
        password = frappe.db.get_single_value("Logistics Settings", "e_password")
        gstin = frappe.db.get_single_value("Logistics Settings", "gstin")
        api_headers = {
            "Content-Type": "application/json",
            "username": username,
            "password": password,
            "gstin": gstin,
            "authorization": f"Bearer {access_token}",
            "requestid": "REQ-" + frappe.generate_hash(length=10),
            "ctype": "irn"
        }
        # api_url = "https://gsp.adaequare.com/test/enriched/ewb/ewayapi?action=GENEWAYBILL"
        api_url = frappe.db.get_single_value("Logistics Settings", "eway_url")

        res = requests.post(api_url, headers=api_headers, data=json.dumps(payload))

        try:
            response_json = res.json()
        except Exception as e:
            frappe.log_error(f"[EWB] JSON parse error: {str(e)} | Raw: {res.text}")
            frappe.throw(_("Invalid response from EWB server."))

        # Get actual EWB number
        ewaybill_no = response_json.get("result", {}).get("ewayBillNo")

        # If ewaybill_no not present → show reason from API
        if not ewaybill_no:
            error_message = response_json.get("message") or "E-Way Bill Generation Failed. No reason provided."
            frappe.throw(_(f"E-Way Bill Generation Failed: {error_message}"))

        # Save EWB
        frappe.db.set_value("Sales Invoice", invoice.name, "ewaybill", ewaybill_no)
        frappe.db.commit()

        # Step 6: Return response
        try:
            return res.json()
        except Exception as e:
            frappe.log_error(f"[EWB] JSON parse error: {str(e)} | Raw: {res.text}")
            frappe.throw(_("Invalid response from EWB server."))

    except Exception as e:
        frappe.log_error(f"[EWB] Fatal Error: {frappe.get_traceback()}")
        frappe.throw(_("E-Way Bill Generation Failed. See error log."))


@frappe.whitelist()
def fetching_transporter_details(docname):
    invoice = frappe.get_doc("Sales Invoice", docname)

    for item in invoice.items:
        if item.delivery_note:
            dn = frappe.get_doc("Delivery Note", item.delivery_note)

            # Only set fields if they exist in DN
            invoice.invoice_no = dn.lr_no or ""
            invoice.transporter_id = dn.gst_transporter_id or ""
            invoice.transporter_names = dn.transporter_name or ""
            invoice.email = dn.email or ""

            break  # Stop after first DN

    invoice.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "success",
        "invoice_no": invoice.invoice_no,
        "transporter_id": invoice.transporter_id,
        "transporter_names": invoice.transporter_names,
        "email": invoice.email,
    }

@frappe.whitelist()
def approve_validation(doc, method=None):
    print("inside approve validation================")

    if doc.is_return == 1:
        return

    # get sales order from items
    sales_order_name = None

    for item in doc.items:
        if item.sales_order:
            sales_order_name = item.sales_order
            break

    if not sales_order_name:
        frappe.throw("No Sales Order found for this Sales Invoice.")

    # directly check Sales Order approve field
    approve = frappe.db.get_value(
        "Sales Order",
        sales_order_name,
        "approve"
    )

    print("approve=====================", approve)

    if not approve or int(approve) != 1:
        frappe.throw(
            f"Sales Order {sales_order_name} is not approved. Please approve it first."
        )

    # if approved
    doc.approved = 1
# @frappe.whitelist()
# def approve_validation(doc,method=None):
#     print("inside approve validation================")
#     if doc.is_return == 1:
#         return
#     # get first sales_order from child table
#     sales_order_name = None

#     print("doc.items=======================",doc.items)
#     for item in doc.items:
#         if item.sales_order:
#             sales_order_name = item.sales_order
#             print("sales_order_name==============",sales_order_name)
#             break

#     if not sales_order_name:
#         frappe.throw("No sales order found for this sales invoice.")

#     query = """
#         SELECT 
#             si.name AS sales_invoice, 
#             so.approve 
#         FROM `tabSales Invoice` si 
#         INNER JOIN `tabSales Invoice Item` sii     
#             ON si.name = sii.parent 
#         INNER JOIN `tabSales Order` so
#             ON sii.sales_order = so.name 
#         WHERE so.name = %s 
#     """  
#     results = frappe.db.sql(query, (sales_order_name,), as_dict=True, debug=True)  
#     print("results=======================",results)
#     for row in results:        
#         if not row.approve or int(row.approve) != 1:
#             # self.approved = 1
#             frappe.throw(f"Sales Order {sales_order_name} is not approved. Please approve it first.")
#         else:
#             doc.approved = 1
# @frappe.whitelist()
# def due_date_validation(doc):
#     if isinstance(doc, str):
#         doc = json.loads(doc)

#     si = frappe.get_doc(doc)
#     current_date = getdate(nowdate())
#     new_due_date = add_days(current_date, 7)
#     si.due_date = new_due_date
#     si.save(ignore_permissions=True)
#     frappe.db.commit()

#     return {"due_date": new_due_date}

# ✅ Register override class
def override_sales_invoice():
    from erpnext.accounts.doctype.sales_invoice import sales_invoice
    sales_invoice.SalesInvoice = CustomSalesInvoice


# ✅ Monkey patch core validate_mandatory_fields
import erpnext.regional.india.e_invoice.utils as einvoice_utils
einvoice_utils.validate_mandatory_fields = custom_validate_mandatory_fields

import erpnext.regional.india.e_invoice.utils as einvoice_utils
einvoice_utils.make_einvoice = custom_make_einvoice




@frappe.whitelist()
def get_item_group_cost_centers(items):
    """
    Fetch cost centers for given item_groups in bulk.
    items comes as JSON string, so parse it first.
    """
    try:
        items = json.loads(items)
    except Exception:
        items = []

    result = {}
    for item in items:
        if item.get("item_group"):
            cost_center = frappe.db.get_value("Item Group", item["item_group"], "cost_center")
            if cost_center:
                result[item["idx"]] = cost_center
    return result


@frappe.whitelist()
def deviding_tax_chargese(doc, method=None):
    if doc.is_return == 1:
        return

    # --------------------------------------------------
    # 1️⃣ Fetch Sales Orders from SI
    # --------------------------------------------------
    sales_orders = list({item.sales_order for item in doc.items if item.sales_order})
    print("sales_orders========================", sales_orders)

    if not sales_orders:
        return

    # --------------------------------------------------
    # 2️⃣ Pick FIRST Sales Order only
    # --------------------------------------------------
    first_so = sales_orders[0]
    sale_type = frappe.db.get_value("Sales Order", first_so, "sale_type")
    print("sale_type========================", sale_type)

    # --------------------------------------------------
    # 3️⃣ Run validation ONLY for Amazon
    # --------------------------------------------------
    if sale_type != "NJ-Website-B2C":
        return

    # --------------------------------------------------
    # 4️⃣ Fetch NJ Settings (Allowed tax accounts)
    # --------------------------------------------------
    nj_setting_value = frappe.db.get_value(
        "NJ Settings",
        {"parameter": "taxe_account_heads"},
        "value"
    )
    print("nj_setting_value=====================", nj_setting_value)
    if not nj_setting_value:
        return

    try:
        allowed_accounts = set(json.loads(nj_setting_value))
    except Exception:
        allowed_accounts = set(
            acc.strip() for acc in nj_setting_value.split(",") if acc.strip()
        )
    print("allowed_accounts=====================", allowed_accounts)

    # --------------------------------------------------
    # 5️⃣ Fetch SO TOTAL VALUE + CURRENT SI VALUE (per SO)
    # --------------------------------------------------
    so_total_value_rows = frappe.db.get_all(
        "Sales Order",
        filters={"name": ["in", sales_orders], "docstatus": 1},
        fields=["name", "total"]
    )
    so_total_value_map = {row.name: flt(row.total) for row in so_total_value_rows}
    print("so_total_value_map=====================", so_total_value_map)

    current_si_value_map = {}
    for item in doc.items:
        if not item.sales_order:
            continue
        current_si_value_map[item.sales_order] = (
            flt(current_si_value_map.get(item.sales_order)) + flt(item.amount)
        )
    print("current_si_value_map=====================", current_si_value_map)

    if not current_si_value_map:
        return

    # --------------------------------------------------
    # 6️⃣ Fetch UNMATCHED TAXES FROM SALES ORDER (per SO)
    # --------------------------------------------------
    so_unmatched_taxes = {}
    for so_name in sales_orders:
        so_taxes = frappe.get_all(
            "Sales Taxes and Charges",
            filters={"parent": so_name, "parenttype": "Sales Order"},
            fields=["account_head", "charge_type", "tax_amount"]
        )
        print("so_taxes=====================", so_taxes)

        so_unmatched_taxes[so_name] = {}
        for tax in so_taxes:
            if tax.account_head not in allowed_accounts:
                so_unmatched_taxes[so_name][tax.account_head] = flt(tax.tax_amount)

    print("so_unmatched_taxes=====================", so_unmatched_taxes)
    if not any(so_unmatched_taxes.values()):
        return

    # --------------------------------------------------
    # 7️⃣ Allocate unmatched SO taxes by VALUE ratio
    # formula: (SO tax / SO total value) * current SI value for that SO
    # --------------------------------------------------
    allocated_tax_by_account = {}

    for so_name in sales_orders:
        so_total_value = flt(so_total_value_map.get(so_name))
        current_si_value = flt(current_si_value_map.get(so_name))

        print("so_total_value=====================", so_total_value)
        print("current_si_value=====================", current_si_value)

        if not so_total_value or not current_si_value:
            continue

        for account_head, so_tax_amount in (so_unmatched_taxes.get(so_name) or {}).items():
            divided_amount = round((flt(so_tax_amount) / so_total_value) * current_si_value, 2)
            allocated_tax_by_account[account_head] = round(
                flt(allocated_tax_by_account.get(account_head)) + divided_amount, 2
            )
            print("divided_amount=====================", divided_amount)

    if not allocated_tax_by_account:
        return

    print("allocated_tax_by_account=====================", allocated_tax_by_account)

    # --------------------------------------------------
    # 8️⃣ Update SAME tax row in SI
    # --------------------------------------------------
    conversion_rate = flt(doc.conversion_rate) or 1
    for tax in doc.taxes:
        if tax.account_head in allocated_tax_by_account:
            tax_amount = flt(allocated_tax_by_account[tax.account_head])
            tax.tax_amount = tax_amount
            tax.base_tax_amount = round(tax_amount * conversion_rate, 2)


SALES_ORDER_TAX_ACCOUNTS_TO_RESTORE = (
    "Standard Shipping - NJ",
    "PG Surcharge - NJ",
)


def add_missing_sales_order_tax_accounts(doc, method=None):
    """Restore selected tax rows that are present in a linked SO but missing in the SI."""
    if cint(doc.is_return):
        return

    sales_orders = list(dict.fromkeys(
        item.sales_order for item in doc.items if item.sales_order
    ))
    if not sales_orders:
        return

    existing_accounts = {
        tax.account_head for tax in doc.taxes if tax.account_head
    }
    missing_accounts = set(SALES_ORDER_TAX_ACCOUNTS_TO_RESTORE) - existing_accounts
    if not missing_accounts:
        return

    rows_to_add = {}
    for sales_order in sales_orders:
        for tax in frappe.get_doc("Sales Order", sales_order).taxes:
            if tax.account_head in missing_accounts and tax.account_head not in rows_to_add:
                rows_to_add[tax.account_head] = tax

        if missing_accounts.issubset(rows_to_add):
            break

    if not rows_to_add:
        return

    child_table_fields = frappe.get_meta("Sales Invoice").get_field("taxes").options
    valid_fields = set(frappe.get_meta(child_table_fields).get_valid_columns())
    excluded_fields = {
        "name", "owner", "creation", "modified", "modified_by",
        "parent", "parentfield", "parenttype", "idx", "docstatus",
    }

    for account_head in SALES_ORDER_TAX_ACCOUNTS_TO_RESTORE:
        source_tax = rows_to_add.get(account_head)
        if not source_tax:
            continue

        tax_values = {
            fieldname: value
            for fieldname, value in source_tax.as_dict().items()
            if fieldname in valid_fields and fieldname not in excluded_fields
        }
        doc.append("taxes", tax_values)

    doc.calculate_taxes_and_totals()


def send_invoice_email(doc, method=None):
    """
    Email logic:
    - Sales Invoice  → always send, format: NJ Sales Invoice
    - Debit Note     → always send, format: NJ Sales Invoice
    - Credit Note    → only if IRN exists (signed_einvoice), format: NJ GST E INVOICE
    """
    try:
        # ── Credit Note: only send if IRN exists ──
        if cint(doc.is_return) and not doc.signed_einvoice:
            frappe.logger().info(
                f"Skipping email for credit note {doc.name} — no IRN"
            )
            return

        recipient = (
            doc.contact_email
            or frappe.db.get_value("Customer", doc.customer, "email_id")
        )

        if not recipient:
            frappe.log_error(
                f"No email found for {doc.name} (customer: {doc.customer})",
                "NJ Invoice Email"
            )
            return

        # ── Pick print format ──
        if doc.signed_einvoice:
            print_format = "NJ GST E INVOICE"
        else:
            print_format = "NJ Sales Invoice"

        # ── Doc label ──
        if cint(doc.is_return):
            doc_label = "Credit Note"
        elif cint(doc.is_debit_note):
            doc_label = "Debit Note"
        else:
            doc_label = "Sales Invoice"

        pdf = frappe.get_print(
            "Sales Invoice",
            doc.name,
            print_format=print_format,
            as_pdf=True
        )

        frappe.sendmail(
            recipients=[recipient],
            subject=f"{doc_label} {doc.name} - NEWJAISA Technologies Limited",
            message=f"""<p>Dear {doc.customer_name},</p>
<p>Please find attached your {doc_label} <b>{doc.name}</b> dated {doc.posting_date}
for <b>&#8377; {doc.rounded_total or doc.grand_total}</b>.</p>
<p>For any queries, contact us at support@newjaisa.com</p>
<p>Thanks,<br>NEWJAISA Technologies Limited</p>""",
            attachments=[{"fname": f"{doc.name}.pdf", "fcontent": pdf}]
        )

        frappe.logger().info(f"Invoice email sent for {doc.name} to {recipient}")

    except Exception:
        frappe.log_error(frappe.get_traceback(), f"NJ Invoice Email Failed: {doc.name}")
