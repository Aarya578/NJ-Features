
import json
import requests
import frappe
import six
from frappe import _
from frappe.utils import (
    flt, getdate, cint
)
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from erpnext.regional.india.e_invoice.utils import raise_document_name_too_long_error
from frappe import _
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list

class CustomSalesInvoice(SalesInvoice):
    def validate(self):
        self.validate_einvoice_fields()
    # custom_validate_mandatory_fields(self)

    def validate_einvoice_fields(self):
        print("✅ CUSTOM validate_einvoice_fields() from nj_features called")

        invoice_eligible = _validate_eligibility(self)
        # print("========================",invoice_eligible)
        # print("invoice_eligible==========================",not invoice_eligible)
        # logger.debug("invoice_eligible==========================",not invoice_eligible)
        # print("invoice_eligible==========================",invoice_eligible)
        if not invoice_eligible:
            return

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

    def before_submit(self):
        """ Prevent stock update on submission, but retain packed items """
        self.update_stock = False

    def update_packing_list(self):
        """ Override the default method to prevent clearing packed_items """
        if self.update_stock:
            make_packing_list(self)
        # Removed the `else` block to prevent clearing packed_items




# ✅ Used inside validate()
def custom_validate_mandatory_fields(doc):
    print("✅ custom_validate_mandatory_fields() from nj_features")

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

    company_gstin = frappe.db.get_value("Address", doc.company_address, "gstin")
    if not company_gstin:
        frappe.throw(
            _("GSTIN is mandatory to fetch company GSTIN details. Please enter GSTIN in selected company address."),
            title=_("Missing Fields"),
        )

    # ✅ Use shipping address GSTIN instead of customer address
    shipping_gstin = (
        frappe.db.get_value("Address", doc.shipping_address_name, "gstin")
        if doc.shipping_address_name else None
    )
    # print("customer gst=====================",doc.get("customer_gstin"), "doc.get('grand_total')", flt(doc.get("grand_total")),"cond:",(doc.get("customer_gstin") is None or doc.get("customer_gstin") == "undefined") and flt(doc.get("grand_total")) >= 50000)
    if (doc.get("customer_gstin") is None or doc.get("customer_gstin") == "undefined") and flt(doc.get("grand_total")) <= 50000:  
        # print("doc.get('customer_gstin')================", doc.get("customer_gstin"))      

        return

        # ✅ Only validate shipping GSTIN on SUBMIT
    # if doc.docstatus == "save":
    #     if flt(doc.get("grand_total")) >= 50000 and doc.gst_category != "Overseas" and not shipping_gstin:
    #         frappe.throw(
    #             _("GSTIN is not found in selected *Shipping Address*. Please Create 'E-Way Bill' Directly."),
    #             title=_("Missing GSTIN in Shipping Address"),
    #         )
    # if frappe.flags.in_submit:
    if doc.gst_category != "Overseas" and not shipping_gstin:
        frappe.throw(
            _(
            "GSTIN is not found in selected *Shipping Address* Please Create 'E-Way Bill' Directly."),
            title=_("Missing GSTIN in Shipping Address"),
        )
# Hook this class to override default Sales Invoice behavior
def override_sales_invoice():
    from erpnext.accounts.doctype.sales_invoice import sales_invoice
    sales_invoice.SalesInvoice = CustomSalesInvoice

from frappe.utils import nowdate, add_days, getdate



# ✅ JS call-compatible
@frappe.whitelist()
def validate_eligibility(doc):
    if isinstance(doc, six.string_types):
        doc = json.loads(doc)
    return _validate_eligibility(doc)


# ✅ Internal validation
def _validate_eligibility(doc):
    print("✅ Inside _validate_eligibility")

    if doc.get("doctype") != "Sales Invoice":
        return False
    if (doc.get("customer_gstin") is None or doc.get("customer_gstin") == "undefined") and flt(doc.get("grand_total")) >= 50000:
        if doc.get("ewaybill"):
            # print("doc.get('ewaybill')================", doc.get("ewaybill"))
            return False
        # print("doc.get('company_gstin')================", doc.get("customer_gstin"))
        return True

    if (doc.get("customer_gstin")): 
        # print("doc.get('customer_gstin')================", doc.get("customer_gstin"))
        return True
    
    if flt(doc.get("grand_total")) <= 50000:
        # print("total================", doc.get("grand_total"))
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
        auth_headers = {
            "gspappid": "79536E39F216449883720CCD53643D8F",
            "gspappsecret": "EE5EFAACG8434G43E8GA90EG9660E98C3D71",
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
            print("Using Dispatch Address:=====================", final_address)
        else:
            final_address = company_address
            print("Using Company Address:=====================", final_address)

        # print("company_address=====================", company_address)
        customer_address = frappe.get_doc("Address", invoice.customer_address) if invoice.customer_address else None
        # print("customer_address=====================", customer_address)
        shipping_address_name = frappe.get_doc("Address", invoice.shipping_address_name) if invoice.shipping_address_name else None
        # print("shipping_address_name=====================", shipping_address_name)

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
                "igstRate": 18.0,  # Adjust if needed based on tax logic
                "cessRate": 0.0,
                "cessNonadvol": 0.0,
                "taxableAmount": float(row.amount)  # amount before tax
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
        print("payload=======================================",payload)
        # logger.debug("payload=======================================",payload)

        # Step 5: Make API Call
        api_headers = {
            "Content-Type": "application/json",
            "username": "adqgspchusr1",
            "password": "Gsp@1234",
            "gstin": "04AMBPG7773M002",
            "authorization": f"Bearer {access_token}",
            "requestid": "REQ-" + frappe.generate_hash(length=10),
            "ctype": "irn"
        }
        print("api_headers=======================================",api_headers)
        # logger.debug("api_headers=======================================",api_headers)
        api_url = "https://gsp.adaequare.com/test/enriched/ewb/ewayapi?action=GENEWAYBILL"
        # logger.debug("api_url=======================================", api_url)

        res = requests.post(api_url, headers=api_headers, data=json.dumps(payload))
        # logger.debug("res.status_code===============================", res.status_code)

        try:
            response_json = res.json()
        except Exception as e:
            frappe.log_error(f"[EWB] JSON parse error: {str(e)} | Raw: {res.text}")
            frappe.throw(_("Invalid response from EWB server."))

        # logger.debug("response_json=================================", response_json)

        # Get actual EWB number
        ewaybill_no = response_json.get("result", {}).get("ewayBillNo")
        # logger.debug("ewaybill_no===================================", ewaybill_no)

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
    try:
        invoice = frappe.get_doc("Sales Invoice", docname)
        for item in invoice.items:
            if item.delivery_note:
                dn = frappe.get_doc("Delivery Note", item.delivery_note)
                print("dn=======================", dn)

                # Set values in parent fields
                invoice.invoice_no = dn.lr_no
                print("invoice.invoice_no=======================", invoice.invoice_no)
                invoice.transporter_id = dn.gst_transporter_id
                print("invoice.transporter_id=======================", invoice.transporter_id)
                invoice.transporter_names = dn.transporter_name
                print("invoice.transporter_names=======================", invoice.transporter_names)

                break  # Assuming you want to take values from the first linked DN only

        invoice.save(ignore_permissions=True)
        frappe.db.commit()
        return {"status": "success"}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in fetching_transporter_details")
        frappe.throw(_("Failed to fetch transporter details. Check error log."))


# ✅ Register override class
def override_sales_invoice():
    from erpnext.accounts.doctype.sales_invoice import sales_invoice
    sales_invoice.SalesInvoice = CustomSalesInvoice


# ✅ Monkey patch core validate_mandatory_fields
import erpnext.regional.india.e_invoice.utils as einvoice_utils
einvoice_utils.validate_mandatory_fields = custom_validate_mandatory_fields

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
    if isinstance(names, str):
        names = frappe.parse_json(names)

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







# import json

# import requests
# import frappe
# import six
# from frappe import _
# from frappe.utils import (
#     flt, getdate, cint
# )
# from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
# from erpnext.regional.india.e_invoice.utils import raise_document_name_too_long_error
# # logger = frappe.logger('Sales Invoice Logger', allow_site=True, file_count=100)
# # logger.debug("executing logger file...===========================")
# class CustomSalesInvoice(SalesInvoice):
#     def validate(self):
#         self.validate_einvoice_fields()
#         # custom_validate_mandatory_fields(self)

#     def validate_einvoice_fields(self):
#         print("✅ CUSTOM validate_einvoice_fields() from nj_features called")

#         invoice_eligible = _validate_eligibility(self)
#         # print("========================",invoice_eligible)
#         # print("invoice_eligible==========================",not invoice_eligible)
#         # logger.debug("invoice_eligible==========================",not invoice_eligible)
#         # print("invoice_eligible==========================",invoice_eligible)
#         if not invoice_eligible:
#             return

#         if self.docstatus == 0 and self._action == "save":
#             if self.irn:
#                 frappe.throw(_("You cannot edit the invoice after generating IRN"), title=_("Edit Not Allowed"))
#             if len(self.name) > 16:
#                 raise_document_name_too_long_error()
#             self.einvoice_status = "Pending"

#         elif self.docstatus == 1 and self._action == "submit" and not self.irn:
#             frappe.throw(_("You must generate IRN before submitting the document."), title=_("Missing IRN"))

#         elif self.irn and self.docstatus == 2 and self._action == "cancel" and not self.irn_cancelled:
#             frappe.throw(_("You must cancel IRN before cancelling the document."), title=_("Cancel Not Allowed"))


# # ✅ Used inside validate()
# def custom_validate_mandatory_fields(doc):
#     print("✅ custom_validate_mandatory_fields() from nj_features")

#     if not doc.company_address:
#         frappe.throw(
#             _("Company Address is mandatory to fetch company GSTIN details. Please set Company Address and try again."),
#             title=_("Missing Fields"),
#         )

#     if not doc.customer_address:
#         frappe.throw(
#             _("Customer Address is mandatory to fetch customer GSTIN details. Please set Customer Address and try again."),
#             title=_("Missing Fields"),
#         )

#     company_gstin = frappe.db.get_value("Address", doc.company_address, "gstin")
#     if not company_gstin:
#         frappe.throw(
#             _("GSTIN is mandatory to fetch company GSTIN details. Please enter GSTIN in selected company address."),
#             title=_("Missing Fields"),
#         )

#     # ✅ Use shipping address GSTIN instead of customer address
#     shipping_gstin = (
#         frappe.db.get_value("Address", doc.shipping_address_name, "gstin")
#         if doc.shipping_address_name else None
#     )
#     # print("customer gst=====================",doc.get("customer_gstin"), "doc.get('grand_total')", flt(doc.get("grand_total")),"cond:",(doc.get("customer_gstin") is None or doc.get("customer_gstin") == "undefined") and flt(doc.get("grand_total")) >= 50000)
#     if (doc.get("customer_gstin") is None or doc.get("customer_gstin") == "undefined") and flt(doc.get("grand_total")) <= 50000:  
#         # print("doc.get('customer_gstin')================", doc.get("customer_gstin"))      

#         return

#         # ✅ Only validate shipping GSTIN on SUBMIT
#     # if doc.docstatus == "save":
#     #     if flt(doc.get("grand_total")) >= 50000 and doc.gst_category != "Overseas" and not shipping_gstin:
#     #         frappe.throw(
#     #             _("GSTIN is not found in selected *Shipping Address*. Please Create 'E-Way Bill' Directly."),
#     #             title=_("Missing GSTIN in Shipping Address"),
#     #         )
#     # if frappe.flags.in_submit:
#     if doc.gst_category != "Overseas" and not shipping_gstin:
#         frappe.throw(
#             _(
#             "GSTIN is not found in selected *Shipping Address* Please Create 'E-Way Bill' Directly."),
#             title=_("Missing GSTIN in Shipping Address"),
#         )


# # ✅ JS call-compatible
# @frappe.whitelist()
# def validate_eligibility(doc):
#     if isinstance(doc, six.string_types):
#         doc = json.loads(doc)
#     return _validate_eligibility(doc)


# # ✅ Internal validation
# def _validate_eligibility(doc):
#     print("✅ Inside _validate_eligibility")

#     if doc.get("doctype") != "Sales Invoice":
#         return False
#     if (doc.get("customer_gstin") is None or doc.get("customer_gstin") == "undefined") and flt(doc.get("grand_total")) >= 50000:
#         if doc.get("ewaybill"):
#             # print("doc.get('ewaybill')================", doc.get("ewaybill"))
#             return False
#         # print("doc.get('company_gstin')================", doc.get("customer_gstin"))
#         return True

#     if (doc.get("customer_gstin")): 
#         # print("doc.get('customer_gstin')================", doc.get("customer_gstin"))
#         return True
    
#     if flt(doc.get("grand_total")) <= 50000:
#         # print("total================", doc.get("grand_total"))
#         return False
    

#     einvoicing_enabled = cint(frappe.db.get_single_value("E Invoice Settings", "enable"))
#     if not einvoicing_enabled:
#         return False

#     einvoicing_eligible_from = (
#         frappe.db.get_single_value("E Invoice Settings", "applicable_from") or "2021-04-01"
#     )
#     if getdate(doc.get("posting_date")) < getdate(einvoicing_eligible_from):
#         return False

#     invalid_company_gstin = not frappe.db.get_value("E Invoice User", {"gstin": doc.get("company_gstin")})

#     no_taxes_applied = (
#         not doc.get("taxes")
#         and doc.get("gst_category") not in ["Overseas", "SEZ"]
#     )
#     has_non_gst_item = any(d for d in doc.get("items", []) if d.get("is_non_gst"))

#     if (
#         invalid_company_gstin
#         or no_taxes_applied
#         or has_non_gst_item
#     ):
#         return False

#     return True

# @frappe.whitelist()
# def generate_eway_bill(docname):
#     try:
#         # Step 1: Authenticate
#         auth_headers = {
#             "gspappid": "79536E39F216449883720CCD53643D8F",
#             "gspappsecret": "EE5EFAACG8434G43E8GA90EG9660E98C3D71",
#             "Content-Type": "application/x-www-form-urlencoded"
#         }
#         auth_res = requests.post(
#             "https://gsp.adaequare.com/gsp/authenticate?action=GSP&grant_type=token",
#             headers=auth_headers,
#             data={"grant_type": "client_credentials"}
#         )
#         auth_json = auth_res.json()
#         access_token = auth_json.get("access_token")
#         if not access_token:
#             frappe.throw(_("Failed to fetch access token."))

#         # Step 2: Load Sales Invoice
#         invoice = frappe.get_doc("Sales Invoice", docname)
#         company_address = frappe.get_doc("Address", invoice.company_address) if invoice.company_address else None
#         customer_address = frappe.get_doc("Address", invoice.customer_address) if invoice.customer_address else None

#         # Step 3: Prepare Item List
#         item_list = []
#         for row in invoice.items:
#             item = frappe.get_doc("Item", row.item_code)
#             item_list.append({
#                 "productName": row.item_name,
#                 "productDesc": item.description or "",
#                 "hsnCode": item.gst_hsn_code or "",
#                 "quantity": float(row.qty),
#                 "qtyUnit": row.uom or "BOX",
#                 "cgstRate": 0.0,
#                 "sgstRate": 0.0,
#                 "igstRate": 18.0,  # Adjust if needed based on tax logic
#                 "cessRate": 0.0,
#                 "cessNonadvol": 0.0,
#                 "taxableAmount": float(row.amount)  # amount before tax
#             })

#         # Step 4: Prepare payload
#         payload = {
#             "supplyType": "O",
#             "subSupplyType": "1",
#             "subSupplyDesc": "",
#             "docType": "INV",
#             "docNo": invoice.name,
#             "docDate": invoice.posting_date.strftime("%d/%m/%Y"),
#             "fromGstin": company_address.gstin,
#             "fromTrdName": invoice.company,
#             "fromAddr1": company_address.address_line1,
#             "fromAddr2": company_address.address_line2,
#             "fromPlace": company_address.city,
#             "fromPincode": company_address.pincode,
#             "actFromStateCode": company_address.gst_state_number,
#             "fromStateCode": company_address.gst_state_number,
#             "toGstin": customer_address.gstin or "URP",
#             "toTrdName": invoice.customer,
#             "toAddr1": customer_address.address_line1,
#             "toAddr2": customer_address.address_line2,
#             "toPlace": customer_address.city,
#             "toPincode": customer_address.pincode,
#             "actToStateCode": customer_address.gst_state_number,
#             "toStateCode": customer_address.gst_state_number,
#             "transactionType": 4,
#             "otherValue": "0",
#             "totalValue": invoice.total,
#             "cgstValue": 0,
#             "sgstValue": 0,
#             "igstValue": invoice.total * 0.18,  # Approximate IGST if applicable
#             "cessValue": 0,
#             "cessNonAdvolValue": 0,
#             "totInvValue": invoice.grand_total,
#             "transporterId": "29AMBPG7773M000",
#             "transporterName": "Test",
#             "transDocNo": "",
#             "transMode": "",
#             "transDistance": "0",
#             "transDocDate": "",
#             "vehicleNo": "",
#             "vehicleType": "",
#             "itemList": item_list
#         }
#         print("payload=======================================",payload)
#         # logger.debug("payload=======================================",payload)

#         # Step 5: Make API Call
#         api_headers = {
#             "Content-Type": "application/json",
#             "username": "adqgspchusr1",
#             "password": "Gsp@1234",
#             "gstin": "04AMBPG7773M002",
#             "authorization": f"Bearer {access_token}",
#             "requestid": "REQ-" + frappe.generate_hash(length=10),
#             "ctype": "irn"
#         }
#         print("api_headers=======================================",api_headers)
#         # logger.debug("api_headers=======================================",api_headers)
#         api_url = "https://gsp.adaequare.com/test/enriched/ewb/ewayapi?action=GENEWAYBILL"
#         # logger.debug("api_url=======================================", api_url)

#         res = requests.post(api_url, headers=api_headers, data=json.dumps(payload))
#         # logger.debug("res.status_code===============================", res.status_code)

#         try:
#             response_json = res.json()
#         except Exception as e:
#             frappe.log_error(f"[EWB] JSON parse error: {str(e)} | Raw: {res.text}")
#             frappe.throw(_("Invalid response from EWB server."))

#         # logger.debug("response_json=================================", response_json)

#         # Get actual EWB number
#         ewaybill_no = response_json.get("result", {}).get("ewayBillNo")
#         # logger.debug("ewaybill_no===================================", ewaybill_no)

#         # If ewaybill_no not present → show reason from API
#         if not ewaybill_no:
#             error_message = response_json.get("message") or "E-Way Bill Generation Failed. No reason provided."
#             frappe.throw(_(f"E-Way Bill Generation Failed: {error_message}"))

#         # Save EWB
#         frappe.db.set_value("Sales Invoice", invoice.name, "ewaybill", ewaybill_no)
#         frappe.db.commit()

#         # Step 6: Return response
#         try:
#             return res.json()
#         except Exception as e:
#             frappe.log_error(f"[EWB] JSON parse error: {str(e)} | Raw: {res.text}")
#             frappe.throw(_("Invalid response from EWB server."))

#     except Exception as e:
#         frappe.log_error(f"[EWB] Fatal Error: {frappe.get_traceback()}")
#         frappe.throw(_("E-Way Bill Generation Failed. See error log."))


# @frappe.whitelist()
# def fetching_transporter_details(docname):
#     try:
#         invoice = frappe.get_doc("Sales Invoice", docname)
#         for item in invoice.items:
#             if item.delivery_note:
#                 dn = frappe.get_doc("Delivery Note", item.delivery_note)
#                 print("dn=======================", dn)

#                 # Set values in parent fields
#                 invoice.invoice_no = dn.lr_no
#                 print("invoice.invoice_no=======================", invoice.invoice_no)
#                 invoice.transporter_id = dn.gst_transporter_id
#                 print("invoice.transporter_id=======================", invoice.transporter_id)
#                 invoice.transporter_names = dn.transporter_name
#                 print("invoice.transporter_names=======================", invoice.transporter_names)

#                 break  # Assuming you want to take values from the first linked DN only

#         invoice.save(ignore_permissions=True)
#         frappe.db.commit()
#         return {"status": "success"}

#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), "Error in fetching_transporter_details")
#         frappe.throw(_("Failed to fetch transporter details. Check error log."))




# # ✅ Register override class
# def override_sales_invoice():
#     from erpnext.accounts.doctype.sales_invoice import sales_invoice
#     sales_invoice.SalesInvoice = CustomSalesInvoice


# # ✅ Monkey patch core validate_mandatory_fields
# import erpnext.regional.india.e_invoice.utils as einvoice_utils
# einvoice_utils.validate_mandatory_fields = custom_validate_mandatory_fields
    }