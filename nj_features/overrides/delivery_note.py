# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import re
import json
import frappe
import requests
import traceback
from frappe import _
from frappe.utils import now
from datetime import datetime, timedelta
from nj_lib.utils.common_utils import get_latest_item_wizard
from frappe.utils import add_days, nowdate, getdate, add_years
from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote

# from nj_features.nj_features.api.shiprocket_api import generate_awb,check_courie_service , generate_label
SHOPIFY_URL = "https://newjaisa.myshopify.com/admin/api/2025-01/orders.json?name=" 
TOKEN = "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"
FULLFILMENT_ORDER_ID = "https://newjaisa.myshopify.com/admin/api/2025-01/orders/{shopify_order_id}/fulfillment_orders.json"
MAKE_FULLFILMENT = "https://newjaisa.myshopify.com/admin/api/2025-01/fulfillments.json"

class CustomDeliveryNote(DeliveryNote):
    
    def on_submit(self):
        try:
            super().on_submit()
            against_sales_order = frappe.get_value("Delivery Note Item", {"parent": self.name}, "against_sales_order")
            
            # Early return for Snapmint orders (skipping trigger_fulfillment)
            if against_sales_order and against_sales_order.startswith("SO-Snapmint-"):
                # self.rto_charges_update()
                # self.fetching_tracking_details()
                # self.set_cit_image_from_sales_order()
                # self.update_details_to_delivery_charege_doc()
                qi_mandatory_checks_on_dn_submit(self, method=None)
                if self.is_return == 0:
                    send_sales_invoice_email_on_delivery_note(self, method=None)
                
                if not self.is_return:
                    self._process_customer_details()
                return
            
            # For non-Snapmint orders, proceed with normal flow
            raw_order_id = frappe.get_value("Sales Order", {"name": against_sales_order}, "shopify_order_id")
            shopify_order_no = frappe.get_value("Sales Order", {"name": against_sales_order}, "shopify_order_number")
            
            if raw_order_id and len(raw_order_id.lstrip('#')) < 7:
                order_id = raw_order_id.lstrip('#')
            else:
                raw_order_id = frappe.get_value("Sales Order", {"name": against_sales_order}, "order_id")
                order_id = raw_order_id.lstrip('#') if raw_order_id else None
                
                if not order_id:
                    raw_order_id = frappe.get_value("Sales Order", {"name": against_sales_order}, "shopify_order_number")
                    order_id = raw_order_id.lstrip('#') if raw_order_id else None
            
            if order_id and self.is_return == 0:
                trigger_fulfillment(order_id, raw_order_id, shopify_order_no, self.name)

            # self.rto_charges_update()
            # self.set_cit_image_from_sales_order()
            # self.fetching_tracking_details()

            # self.update_details_to_delivery_charege_doc()
            qi_mandatory_checks_on_dn_submit(self, method=None)
            if self.is_return == 0:
                send_sales_invoice_email_on_delivery_note(self, method=None)
            
            if not self.is_return:
                self._process_customer_details()
                return
            
            self._process_serial_numbers()
            
        except Exception as e:
            frappe.db.rollback()
            frappe.throw(str(e))
#     def on_submit(self):
#         try:
#             super().on_submit()
            
#             against_sales_order = frappe.get_value("Delivery Note Item", {"parent": self.name}, "against_sales_order")
#             if against_sales_order and against_sales_order.startswith("SO-Snapmint-"):
#             # Skip the trigger_fulfillment for Snapmint series
#                 qi_mandatory_checks_on_dn_submit(self, method=None)
#                 if self.is_return == 0:
#                     send_sales_invoice_email_on_delivery_note(self, method=None)
#                 return
            
#             raw_order_id = frappe.get_value("Sales Order", {"name": against_sales_order}, "shopify_order_id")
#             shopify_order_no = frappe.get_value("Sales Order", {"name": against_sales_order}, "shopify_order_number")
#             if raw_order_id and len(raw_order_id.lstrip('#')) < 7:
#                 order_id = raw_order_id.lstrip('#')
#             else:
#                 raw_order_id = frappe.get_value("Sales Order", {"name": against_sales_order}, "order_id")
#                 order_id = raw_order_id.lstrip('#') if raw_order_id else None

#                 if not order_id:
#                     raw_order_id = frappe.get_value("Sales Order", {"name": against_sales_order}, "shopify_order_number")
#                     order_id = raw_order_id.lstrip('#') if raw_order_id else None
            
#             if order_id and self.is_return==0:
#                 trigger_fulfillment(order_id,raw_order_id,shopify_order_no,self.name)

#             qi_mandatory_checks_on_dn_submit(self, method=None)

#             if self.is_return==0:
#                 send_sales_invoice_email_on_delivery_note(self, method=None)

            
#             # send_delivery_note_email(self, method=None)
#             # against_sales_order = frappe.get_value("Delivery Note Item", {"parent": self.name}, "against_sales_order")
#             # order_id = None
#             # order_values = frappe.db.get_value(
#             # "Sales Order", 
#             # {"name": against_sales_order}, 
#             # ["order_id", "amazon_order_id", "shopify_order_id"]
#             # )
#             # Get the first non-empty value
#             # if order_values:
#             #     order_id = next((value for value in order_values if value), None)

#                 # if order_id:
#                 #     awb_data = check_courie_service(order_id)

#                 #     # Initialize variables
#                 #     awb_code = None
#                 #     courier_name = None
#                 #     label_url = None

#                 #     if awb_data and awb_data.get("message"):
#                 #         awb_info = awb_data["message"].get("awb", {})
#                 #         label_info = awb_data["message"].get("label", {})

#                 #         # Extract AWB code only if successfully generated
#                 #         if isinstance(awb_info, dict) and awb_info.get("status_code") == 400:
#                 #             print("AWB generation failed:", awb_info.get("message"))
#                 #             awb_code = awb_info.get("message").split("Current AWB")[-1].strip()
#                 #         elif isinstance(awb_info, dict):
#                 #             awb_code = awb_info.get("awb_code")  # Adjust based on actual API response

#                 #         # Extract courier name if available
#                 #         if awb_code:
#                 #             courier_name = "Extract Courier Name Logic Here"  # Adjust this if the courier name is provided in the response

#                 #         # Extract label URL
#                 #         if isinstance(label_info, dict) and label_info.get("label_created") == 1:
#                 #             label_url = label_info.get("label_url")

#                 #     # Assign extracted values
#                 #     self.tracking_id = awb_code
#                 #     self.courier_partner = courier_name
#                 #     self.shipping_label = label_url

#             if not self.is_return:
#                 self._process_customer_details()
#                 return
            
#             self._process_serial_numbers()

        # except Exception as e:
        #     error_message = f"An error occurred during on_submit:\n{traceback.format_exc()}"
        #     frappe.db.rollback()
        #     frappe.throw(error_message)
    


    def set_cit_image_from_sales_order(self):
        if  self.is_return:
            return
        # Use SQL to get the sales order and cit_image in one query
        result = frappe.db.sql("""
            SELECT so.cit_image
            FROM `tabSales Order` so
            JOIN `tabDelivery Note Item` dni ON dni.against_sales_order = so.name
            WHERE dni.parent = %s
            LIMIT 1
        """, (self.name,), as_dict=True)
        if result and result[0].cit_image:
            # Set the cit_image field in the Delivery Note
            self.db_set("cit_image", result[0].cit_image)

    def _process_customer_details(self):
        try:
            for item in self.get('items'):
                serial_no = item.serial_no.strip() if item.serial_no else ""

                if not serial_no:
                    continue

                serial_list = serial_no.split('\n')

                if not item.against_sales_order:
                    frappe.throw(f"Missing Sales Order reference for item: {item.item_code}")

                sales_order_data = frappe.db.sql("""
                    SELECT 
                        so.customer_name, so.name, 
                        COALESCE(so.amazon_order_id, so.order_id, so.shopify_order_id) AS order_id, 
                        so.transaction_date, so.delivery_date, si.sales_channel, 
                        COALESCE(addr_ship.email_id, addr_cust.email_id, '') AS email_id,
                        COALESCE(addr_ship.phone, addr_cust.phone, '') AS phone,
                        IFNULL(so.shipping_address, so.address_display) AS so_address
                    FROM `tabSales Order` so
                    INNER JOIN `tabSales Invoice Item` sii ON sii.sales_order = so.name
                    INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
                    LEFT JOIN `tabAddress` addr_ship ON addr_ship.name = so.shipping_address_name
                    LEFT JOIN `tabAddress` addr_cust ON addr_cust.name = so.customer_address
                    WHERE so.name = %s
                    LIMIT 1
                """, (item.against_sales_order,), as_dict=True)  # Fixed `item["against_sales_order"]`

                if not sales_order_data:
                    frappe.throw(f"No Sales Order data found for {item.against_sales_order}")

                sales_order_info = sales_order_data[0]

                for serial in serial_list:
                    serial = serial.strip()
                    if not serial:
                        continue

                    try:
                        serial_no_doc = frappe.get_doc('Serial No', serial, for_update=True)
                    
                    except frappe.DoesNotExistError:
                        frappe.throw(f"Serial No {serial} not found in the system")

                    serial_no_doc.first_name = sales_order_info.get("customer_name", "")
                    serial_no_doc.sales_order_id = sales_order_info.get("name", "")
                    serial_no_doc.order_id = sales_order_info.get("order_id", "")
                    serial_no_doc.order_date = sales_order_info.get("transaction_date")
                    serial_no_doc.shipped_date = self.get("posting_date")
                    serial_no_doc.tracking_id = self.get("tracking_id")
                    serial_no_doc.courier_name = self.get("courier_service")
                    serial_no_doc.deliver_date = sales_order_info.get("delivery_date")
                    serial_no_doc.sales_channel = sales_order_info.get("sales_channel", "")
                    serial_no_doc.mobile_no = sales_order_info.get("phone", "")
                    serial_no_doc.email_id = sales_order_info.get("email_id", "")
                    serial_no_doc.address = sales_order_info.get("so_address", "")
                    serial_no_doc.warranty_start_date_ = self.get("posting_date")

                    posting_date_raw = self.get("posting_date")
                    if isinstance(posting_date_raw, str):
                        end_date = datetime.strptime(posting_date_raw, "%Y-%m-%d")
                    else:
                        end_date = posting_date_raw

                    serial_no_doc.end_date = end_date + timedelta(days=365)
                    serial_no_doc.modified = now()
                    serial_no_doc.save(ignore_permissions=True)

        except Exception as e:
            frappe.throw(f"Error in _process_customer_details: {str(e)}")
    
    def _process_serial_numbers(self):

        for item in self.items:
            if not self._should_process_item(item):
                continue
            
            self._update_serial_number_components(item)
        
        frappe.db.commit()
    
    def _should_process_item(self, item):
       
        has_serial_no = frappe.db.get_value('Item', item.item_code, 'has_serial_no')
        
        return has_serial_no and item.serial_no
    
    def _update_serial_number_components(self, item):
       
        serial_list = item.serial_no.split('\n')
        
        for serial_no in serial_list:
            try:
                serial_no_doc = frappe.get_doc('Serial No', serial_no)
                
                item_template = frappe.db.get_value(
                    "Item", 
                    {'name': item.item_code}, 
                    'variant_of'
                )
                latest_item_wizard = self._get_latest_item_wizard(item_template, item.item_code)
                item_wizard_doc = frappe.get_doc('Item Wizards', latest_item_wizard)
                
                self._update_components(
                    serial_no_doc, 
                    item_wizard_doc, 
                    self.doctype, 
                    self.name
                )
                
            except Exception as e:
                frappe.log_error(
                    f"Error processing serial number {serial_no}: {str(e)}",
                    "CustomDeliveryNote Serial Number Update"
                )
    
    def _get_latest_item_wizard(self, item_template, item_code):

        return get_latest_item_wizard(item_template, item_code)
    
    def _update_components(self, serial_no_doc, item_wizard_doc, reference_doctype, reference_name):
      
        updated = False
        
        for item_component in item_wizard_doc.component:
            for serial_no_component in serial_no_doc.serial_no_component:
                    if serial_no_component.item_group == item_component.get("component_type"):
                        serial_no_component.quantity = '1'
                        serial_no_component.grade = 'UNKNOWN'
                        serial_no_component.reference_doctype = reference_doctype
                        serial_no_component.reference_doctype_no = reference_name
                        updated = True
        
        serial_no_doc.address = ''
        serial_no_doc.end_date = ''
        serial_no_doc.email_id = ''
        serial_no_doc.order_id = ''
        serial_no_doc.mobile_no = ''
        serial_no_doc.last_name = ''
        serial_no_doc.first_name = ''
        serial_no_doc.order_date = ''
        serial_no_doc.tracking_id = ''
        serial_no_doc.shipped_date = ''
        serial_no_doc.deliver_date = ''
        serial_no_doc.courier_name = ''
        serial_no_doc.sales_channel = ''
        serial_no_doc.sales_order_id = ''
        serial_no_doc.warranty_start_date_ = ''
        serial_no_doc.modified = now()
        if updated:
            serial_no_doc.save(ignore_permissions=True) 
        

    def fetching_tracking_details(self):
        if self.is_return:
            return
        against_sales_order = frappe.get_value("Delivery Note Item", {"parent": self.name}, "against_sales_order")
        # Check if we have a value to send
        if not against_sales_order:
            frappe.msgprint("No sales order found for this delivery note.")
            return
        # if against_sales_order:
        #     cost_of_delivery = frappe.db.get_value("Sales Order", against_sales_order, "cost_of_delivery")     
        if against_sales_order:
            cost_of_delivery, awb_number = frappe.db.get_value("Sales Order", against_sales_order, ["cost_of_delivery", "awb_number"])
        try:
            payload = {
                "Auth": " MTMzMzQzNzMwMzIz",  # Added the space at the beginning to match your example
                "DocketNo": against_sales_order
            }
            url = "https://testing.ecritica.co/eFreightLive/api/tracking.php"
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, headers=headers, json=payload)
            print(f"Response status: ========{response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if there's an error message
                if data.get("code") == 5 and "Invalid Con Number" in str(data.get("data", {}).get("docketDetails", "")):
                    frappe.msgprint(f"The sales order number '{against_sales_order}' is not recognized as a valid tracking number.")
                    return
                    
                # If successful, extract the remark
                remark = (
                    data.get("data", {})
                    .get("docketDetails", {})
                    .get("Booking_Status", {})
                    .get("Remark")
                )
                if remark:
                    self.remark_status = remark
                    self.cost_amount = cost_of_delivery
                    self.awb_number = awb_number
                    self.db_update()
                    print(f"Updated remark_status to: {remark}")
                else:
                    print("No remark found in the response")
            else:
                frappe.msgprint(f"API returned status code: {response.status_code}")
                
        except Exception as e:
            frappe.msgprint(f"Failed to send data to Criticalog API. Error: {str(e)}")


    def rto_charges_update(self):
        if not self.is_return:
            return

        valid_causes = ["RTO Customer", "RTO Delivery Partner"]
        if not self.cause_of_return or self.cause_of_return not in valid_causes:
            return

        # Fetch RTO Charges from NJ Settings
        rto_cost = frappe.db.get_value("NJ Settings", {"parameter": "RTO Charges"}, "value")
        # If value exists, sum with cost_amount
        if rto_cost and self.cost_amount:
            try:
                updated_cost = float(self.cost_amount) + float(rto_cost)
                self.cost_amount = updated_cost
                self.db_update()
            except Exception as e:
                frappe.log_error(f"RTO Cost update failed: {e}", "RTO Charges Update")


    def update_details_to_delivery_charege_doc(self):
    # First, check if a Delivery Charges document with the same AWB number exists
        existing_delivery_charge = frappe.get_all(
            "Delivery Charges", 
            filters={"awb_number": self.awb_number},
            limit=1
        )      
        if existing_delivery_charge:
            # If exists, get the document and update it
            delivery_charge = frappe.get_doc("Delivery Charges", existing_delivery_charge[0].name)
            print(f"Updating existing Delivery Charges document: {delivery_charge.name}")
        else:
            # If not exists, create a new one
            delivery_charge = frappe.new_doc("Delivery Charges")
            print("Creating new Delivery Charges document")
        delivery_charge.awb_number = self.awb_number
        delivery_charge.rto_charges = self.cost_amount
        delivery_charge.cit_image = self.cit_image
        if hasattr(self, 'is_return') and self.is_return:
            delivery_charge.cause_of_return = self.cause_of_return
        # Map from first item
        for row in self.get("items"):
            delivery_charge.serial_no = row.get("serial_no")
            delivery_charge.sales_order = row.get("against_sales_order")
            break  # Just get the first item's data
        
        try:
            if delivery_charge.is_new():
                delivery_charge.insert(ignore_permissions=True)
            else:
                delivery_charge.save(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Error updating Delivery Charges doc: {e}", "Delivery Charges Sync Error")
            print(f"Error: {e}")


@frappe.whitelist()
def set_tracking_id_for_delivery_note(doc):

    if isinstance(doc, str):
        doc = json.loads(doc)

    dn_item = doc.get('items')[0].get('against_sales_order')

    sales_order_type = frappe.db.get_value('Sales Order', dn_item, 'sale_type')

    if sales_order_type == 'Amazon':
        return True
    
    return False


@frappe.whitelist()
def get_link_1(name):
    nj_setting_value = frappe.db.get_value("NJ Settings", {"parameter": "NJpulse_url"}, "value")
    
    link = frappe.db.get_list("Doc Attachment", {"doctypename": name, "file_type": "Video", "docstatus": 1}, ["linked_data"])
    for item in link:
        item["linked_data"] = nj_setting_value + item["linked_data"]
    return link


@frappe.whitelist()
def validate_delivery_bios(doc):

    if isinstance(doc, str):
        doc = json.loads(doc)
    
    if doc.get("is_return"):
        return

    error_message = []

    bios_settings = frappe.db.get_value("NJ Settings", {"parameter": "bios_settings"}, "value")

    if not bios_settings:
        return {"error": "NJ Settings for Delivery Note, <b>bios_settings</b> is not defined"}
    
    if int(bios_settings):

            item_group_list = frappe.db.get_value('NJ Settings', {'parameter': 'bios_item_group'}, ['value'])

            if item_group_list:
                item_group_list = json.loads(item_group_list)

            for item in doc.get('items'):
                serial_no = item.get('serial_no', None)
                item_group = item.get("item_group")
                idx = item.get("idx", "N/A")

                if serial_no:
                    serial_no = serial_no.strip()
                    serial_list = serial_no.split('\n')

                    for serial in serial_list:
                        bios_serial_no = frappe.db.get_value('Serial No', serial, 'bios_serial_no')
                        if (bios_serial_no is None or bios_serial_no.strip() == '') and item_group in item_group_list:
                            error_message.append(
                                f"<b>Row {idx}</b>: Serial No <b>{serial}</b> for item group <b>{item_group}</b> has no Bios Serial No"
                            )

    return error_message if error_message else True


@frappe.whitelist()
def send_sales_invoice_email_on_delivery_note(doc, method=None):
    """Sends a single email with order readiness details and Sales Invoice PDF when a Delivery Note is submitted."""
    try:
        order_id = None

        sales_invoice = frappe.get_value("Delivery Note Item", {"parent": doc.name}, "against_sales_invoice")
        if not sales_invoice:
            frappe.msgprint(f"⚠️ No Sales Invoice found for Delivery Note {doc.name}. Email not sent.")
            return

        sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice)

        customer_email = frappe.db.get_value("Customer", sales_invoice_doc.customer, "email_id")
        if not customer_email:
            customer_email = frappe.db.get_value(
                "Dynamic Link",
                {"link_doctype": "Customer", "link_name": doc.customer, "parenttype": "Address"},
                "parent"
            )
            if customer_email:
                customer_email = frappe.db.get_value("Address", customer_email, "email_id")

        # if not customer_email:
        #     frappe.msgprint(f"⚠️ No email found for customer {sales_invoice_doc.customer}. Email not sent.")
        #     return

        pdf_data = frappe.attach_print("Sales Invoice", sales_invoice, print_format="Standard")

        tracking_id = doc.get("tracking_id")
        tracking_courier = doc.get("courier_service")
        billing_address = doc.get("address_display")
        against_sales_order = frappe.get_value("Delivery Note Item", {"parent": doc.name}, "against_sales_order")
        
        order_values = frappe.db.get_value(
            "Sales Order", 
            {"name": against_sales_order}, 
            ["order_id", "amazon_order_id", "shopify_order_id"]
        )

        if order_values:
            order_id = next((value for value in order_values if value), None)

        sender_email = frappe.db.get_value('NJ Settings', {'parameter': 'sender_mail'}, ['value'])

        courier_tracking_data = {
            'CriticaLog': 'https://criticalog.com/tracking/',
            'Tirupati Courier Tracking': 'http://www.shreetirupaticourier.net/',
            'Shiprocket Manifest': 'https://www.shiprocket.in/shipment-tracking/'
        }

        tracking_link = courier_tracking_data.get(tracking_courier, None)
        tracking_info = ""
        if tracking_link and tracking_id:
            tracking_info = f"<p><b>Courier Partner:</b> {tracking_courier}</p><p><b>Tracking Number:</b> {tracking_id}</p><p><b>Track your order here:</b> <a href='{tracking_link}'>{tracking_link}</a></p>"

        subject = f"Your Order {order_id} is Ready – with Tacking Id {tracking_id} "

        message = f"""
         <p>Dear {sales_invoice_doc.customer_name},</p>
        <p>We are pleased to inform you that your order <b>{order_id}</b> is now ready for pickup and will be delivered to:</p>
        <p><b>Shipping Address:</b><br>{billing_address}</p>
        {tracking_info}
        <br>
        <p>Thank you for choosing <b>NewJaisa Technologies</b>.</p>
        <p>Best regards,</p>
        <p><b>NewJaisa Technologies</b></p>
        """

        frappe.sendmail(
            recipients=[customer_email],
            subject=subject,
            message=message,
            reference_doctype=sales_invoice_doc.doctype,
            reference_name=sales_invoice_doc.name,
            # attachments=[pdf_data],
            sender=sender_email,
            now=True
        )

        frappe.msgprint(f"📧 Email sent successfully to {customer_email} with Sales Invoice {sales_invoice_doc.name}.")

    except Exception as e:
        frappe.log_error(message=str(e), title="Sales Invoice Email Failed")

@frappe.whitelist()
def get_cod_amount(so_name):
    try:
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": TOKEN
        }

        filters = {"name": so_name, "docstatus": 1,'order_type':"Sales"}

        raw_order_id = frappe.get_value("Sales Order", filters, "shopify_order_id")

        if raw_order_id and len(raw_order_id.lstrip('#')) < 7:
            order_id = raw_order_id.lstrip('#')
        else:
            raw_order_id = frappe.get_value("Sales Order", filters, "order_id")
            order_id = raw_order_id.lstrip('#') if raw_order_id else None

            if not order_id:
                raw_order_id = frappe.get_value("Sales Order", filters, "shopify_order_number")
                order_id = raw_order_id.lstrip('#') if raw_order_id else None

        if not order_id:
            return {"order_id": None, "cod_amount": 0}

        url = f"{SHOPIFY_URL}{order_id}"
        response = requests.get(url, headers=headers)
        data = response.json()

        if "orders" in data and data["orders"]:
            order = data["orders"][0]
            cod_amount = order.get("total_outstanding", 0)
            return {"order_id": order_id, "cod_amount": cod_amount}

        return {"order_id": order_id, "cod_amount": 0}

    except Exception as e:
        frappe.log_error(f"Error in get_cod_amount: {str(e)}", "Shopify COD Fetch Error")
        return {"order_id": None, "cod_amount": 0}


@frappe.whitelist(allow_guest=True)
def trigger_fulfillment(order_id,original_order_id=None,shopify_order_no=None,dn_name=None):
    try:
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": TOKEN
        }

        url = f"{SHOPIFY_URL}{order_id}"
        response = requests.get(url, headers=headers)  
        data = response.json()

        if "orders" in data and data["orders"]:
            order = data["orders"][0]  
            order_id_shopify = order.get("id")

            if not order_id_shopify:
                frappe.throw("Shopify Order ID not found.")

            fulfillment_status = order.get("fulfillment_status")
            # so_name = frappe.db.sql("""
            #     SELECT name FROM `tabDelivery Note Item`
            #     WHERE shopify_order_id = %s OR order_id = %s OR shopify_order_number = %s and docstatus = 1 
            #     LIMIT 1
            # """, (original_order_id, original_order_id,shopify_order_no), as_dict=True)
            # if so_name:
            #     so_name = so_name[0].name
            # else:
            #     frappe.throw("Sales Order not found.")

            # dn_name = frappe.db.get_value("Delivery Note Item", {"against_sales_order": so_name}, "parent")
            tracking_data = frappe.db.get_value("Delivery Note", {"name": dn_name}, ["tracking_id", "courier_service"])

            if not tracking_data:
                frappe.throw("Tracking data not found in Delivery Note.")

            tracking_number, courier_service = tracking_data
            courier_tracking_data = {
                'CriticaLog': 'https://criticalog.com/tracking/',
                'Tirupati Courier Tracking': 'http://www.shreetirupaticourier.net/',
                'Shiprocket Manifest': 'https://www.shiprocket.in/shipment-tracking/'
            }
            tracking_link = courier_tracking_data.get(courier_service)

            # Case 1: Already fulfilled -> update tracking info
            if fulfillment_status == "fulfilled":
                fulfillment_url = f"https://newjaisa.myshopify.com/admin/api/2025-01/orders/{order_id_shopify}/fulfillments.json"
                fulfillment_response = requests.get(fulfillment_url, headers=headers)
                fulfillment_json = fulfillment_response.json()

                if fulfillment_json.get("fulfillments"):
                    existing_fulfillment_id = fulfillment_json["fulfillments"][0]["id"]
                    update_payload = {
                    "fulfillment": {
                    "tracking_info": {
                                "number": tracking_number,
                                "company": courier_service,
                                "url": tracking_link
                            },
                            "notify_customer": True
                        }
                    }

                    update_url = f"https://newjaisa.myshopify.com/admin/api/2025-01/fulfillments/{existing_fulfillment_id}/update_tracking.json"
                    update_response = requests.post(update_url, headers=headers, json=update_payload)
                    update_data = update_response.json()

                    if "fulfillment" in update_data:
                        return {
                            "status": "updated",
                            "fulfillment_id": existing_fulfillment_id,
                            "tracking_number": tracking_number
                        }
                    else:
                        frappe.throw("Failed to update existing fulfillment.")
                else:
                    frappe.throw("No fulfillment found to update.")

            # Case 2: Not fulfilled -> create fulfillment
            else:
                fulfillment_order_url = FULLFILMENT_ORDER_ID.format(shopify_order_id=order_id_shopify)
                fulfillment_order_response = requests.get(fulfillment_order_url, headers=headers)
                fulfillment_order_data = fulfillment_order_response.json()

                if "fulfillment_orders" in fulfillment_order_data and fulfillment_order_data["fulfillment_orders"]:
                    fulfillment_order_id = fulfillment_order_data["fulfillment_orders"][0]["id"]

                    fulfillment_payload = {
                        "fulfillment": {
                            "line_items_by_fulfillment_order": [
                                {
                                    "fulfillment_order_id": fulfillment_order_id
                                }
                            ],
                            "tracking_info": {
                                "number": tracking_number, 
                                "company": courier_service,
                                "url": tracking_link
                            }
                        }
                    }

                    fulfillment_response = requests.post(MAKE_FULLFILMENT, headers=headers, json=fulfillment_payload)
                    fulfillment_data = fulfillment_response.json()

                    if "fulfillment" in fulfillment_data and fulfillment_data["fulfillment"]:
                        fulfillment_id = fulfillment_data["fulfillment"]["id"]
                        return {"status": "created", "fulfillment_id": fulfillment_id}
                    else:
                        frappe.throw("Fulfillment creation failed.")
                else:
                    frappe.throw("Fulfillment Order not found.")
        # else:
        #     frappe.throw("Order not found.")
    except Exception as e:
        frappe.throw(str(e))
        
@frappe.whitelist()  
def qi_mandatory_checks_on_dn_submit(doc, method=None):
    """
    Checks mandatory NJ Quality Inspections for serial numbers in a Delivery Note.
    Throws an error if any mandatory check has a score greater than 0 or if any mandatory check is missing.
    Skips validation if:
    - No mandatory checks exist for the serial number
    - The Delivery Note is a return (is_return = 1)
    """
    # Skip validation if the delivery note is a return
    if doc.is_return:
        # frappe.msgprint("Skipping quality inspection checks as this is a return delivery note.")
        return
    for item in doc.items:
        if item.serial_no:
            serial_nos = [s.strip() for s in item.serial_no.split('\n') if s.strip()]
            for serial_no in serial_nos:

                # Get item_code and item_group from Serial No
                item_code = frappe.db.get_value("Serial No", serial_no, "item_code")
                item_group = frappe.db.get_value("Item", item_code, "item_group")

                # Skip validation if item group is not 'Laptops'
                if item_group != "Laptops":
                    continue

                # Fetch all mandatory checks for the serial number
                mandatory_checks = frappe.db.sql(
                    """
                    SELECT name FROM `tabNJ QC Check List` 
                    WHERE name IN (
                        SELECT quality_check 
                        FROM `tabNJ Quality Checks` njqc 
                        JOIN `tabNj QC Options` njqco ON njqco.parent = njqc.name
                        JOIN `tabInspection Type` it ON it.name = njqc.inspection_type
                        WHERE 
                            it.active = 1 AND
                            njqc.item_group IN (
                                SELECT component_type 
                                FROM `tabComponent` 
                                WHERE parent = (
                                    SELECT item_wizard 
                                    FROM `tabSerial No` 
                                    WHERE name = %s
                                )
                            )
                    )
                    AND mandatory = 1
                    """,
                    (serial_no,),
                    as_dict=True
                )

                # Skip validation if no mandatory checks found
                if not mandatory_checks:
                    continue

                # Fetch submitted NJ Quality Inspections
                qi_names = frappe.db.sql(
                    """
                    SELECT name FROM `tabNJ Quality Inspection`
                    WHERE barcode = %s AND docstatus = 1
                    ORDER BY creation DESC
                    """,
                    (serial_no,), as_list=True
                )

                if not qi_names:
                    frappe.throw(f"No submitted NJ Quality Inspection found for Serial No: {serial_no}")

                # Prepare sets
                mandatory_check_names = {check['name'] for check in mandatory_checks}
                passed_checks = set()
                failed_checks = {}
                missing_checks = mandatory_check_names.copy()

                for qi_name in qi_names:
                    # Fetch NJ Checks from QI
                    nj_checks = frappe.db.sql(
                        """
                        SELECT check_name, score FROM `tabNJ Checks` WHERE parent = %s
                        """,
                        (qi_name[0],), as_dict=True
                    )

                    nj_check_names = {check.check_name for check in nj_checks}
                    missing_checks -= nj_check_names

                    for check in nj_checks:
                        if check.check_name in mandatory_check_names:
                            if check.score == 0:
                                passed_checks.add(check.check_name)
                            elif check.check_name not in passed_checks:
                                failed_checks[check.check_name] = qi_name[0]

                    if passed_checks == mandatory_check_names:
                        frappe.msgprint(f"All mandatory checks passed for Serial No: {serial_no}")
                        break

                if failed_checks:
                    error_message = ", ".join([f"{check} (QI: {qi})" for check, qi in failed_checks.items()])
                    frappe.throw(f"Mandatory checks failed for Serial No: {serial_no}: {error_message}")

                if missing_checks:
                    frappe.throw(f"Mandatory checks missing for Serial No: {serial_no}: {', '.join(missing_checks)}")
# @frappe.whitelist()
# def get_warranty_data(doc):
#     if isinstance(doc, str):
#         try:
#             doc = json.loads(doc)
#         except json.JSONDecodeError:
#             frappe.throw("Invalid JSON string provided for warranty data.")

#     warranty_info = []

#     dn_items = frappe.db.sql("""
#         SELECT item_code 
#         FROM `tabDelivery Note Item` 
#         WHERE parent = %s
#     """, (doc.get('name'),), as_dict=True)

#     for item in dn_items:
#         item_code = item.get("item_code")
#         item_group = frappe.db.get_value('Item', item_code, 'item_group')

#         if item_group != "Warranty":
#             continue

#         item_name = frappe.db.get_value('Item', item_code, 'item_name')

#         match = re.search(r'(\d+)\s*YEAR', item_name.upper())
#         if not match:
#             continue

#         warranty_years = int(match.group(1))
#         dn_date = getdate(doc.get('creation')) if doc.get('creation') else getdate(nowdate())
#         warranty_start_date = add_days(dn_date, 5)
#         warranty_end_date = add_years(warranty_start_date, warranty_years)

#         warranty_info.append({
#             "item_code": item_code,
#             "warranty_start_date": warranty_start_date,
#             "warranty_end_date": warranty_end_date,
#             "warranty_years": warranty_years
#         })

#     return warranty_info