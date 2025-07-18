# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import re
import json
import frappe
import time
import base64
import requests
import traceback
from frappe import _
from frappe.utils import now
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error
from datetime import datetime, timedelta
from frappe.utils import now_datetime, get_datetime
from nj_lib.utils.common_utils import get_latest_item_wizard
from frappe.utils import add_days, nowdate, getdate, add_years
from nj_features.nj_features.api.shiprocket_api import get_auth_token,generate_awb,generate_label
from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote
logger = frappe.logger('DNLogger', allow_site=True, file_count=1)
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
            # if against_sales_order and against_sales_order.startswith("SO-Snapmint-"):
            #     self.rto_charges_update()
            #     self.fetching_tracking_details()
            #     # self.set_cit_image_from_sales_order()
            #     self.update_details_to_delivery_charege_doc()
            #     qi_mandatory_checks_on_dn_submit(self, method=None)
            #     # self.qc_nj_of_days_checking()
            #     if self.is_return == 0:
            #         send_sales_invoice_email_on_delivery_note(self, method=None)
                
            #     if not self.is_return:
            #         self._process_customer_details()
            #     return
            
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
            
            # if order_id and self.is_return == 0:
            #     trigger_fulfillment(order_id, raw_order_id, shopify_order_no, self.name)
            if order_id and self.is_return == 0:
                # Get order_type and sale_type from related Sales Order
                order_details = frappe.db.sql("""
                    SELECT so.order_type, so.sale_type
                    FROM `tabSales Order` so  
                    JOIN `tabDelivery Note Item` dni ON dni.against_sales_order = so.name 
                    WHERE dni.parent = %s
                    LIMIT 1
                """, (self.name,), as_dict=True)
                
                if order_details:
                    order_type = order_details[0].get('order_type')
                    sale_type = order_details[0].get('sale_type')
                    
                    # Only trigger fulfillment if conditions are met
                    if order_type == 'Sales' and sale_type == 'NJ-Website-B2C':
                        trigger_fulfillment(order_id, raw_order_id, shopify_order_no, self.name)
                    else:
                        print(f"Skipping fulfillment trigger for DN {self.name} - Order Type: {order_type}, Sale Type: {sale_type}")
                else:
                    print(f"No Sales Order found for DN {self.name}")

            self.update_mail_from_address()
            self.rto_charges_update()
            # self.set_cit_image_from_sales_order()
            self.fetching_tracking_details()

            self.update_details_to_delivery_charege_doc()
            qi_mandatory_checks_on_dn_submit(self, method=None)
            # self.qc_nj_of_days_checking()
            # if self.is_return == 0:
            #     # send_sales_invoice_email_on_delivery_note(self, method=None)
            #     self._process_customer_details()
            # else:
            #     self._process_serial_numbers()
            
        except Exception as e:
            frappe.db.rollback()
            log_error(traceback.format_exc(), "Error in on_submit")
            frappe.throw("Error in on_submit", str(e))


    def _process_customer_details(self):
        try:
            sales_order_info_map = {}

            for item in self.get('items', []):
                if not item.against_sales_order:
                    frappe.throw(f"Missing Sales Order reference for item: {item.item_code}")

                if item.against_sales_order not in sales_order_info_map:
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
                        WHERE so.name = %s LIMIT 1
                    """, (item.against_sales_order,), as_dict=True)

                    if not sales_order_data:
                        frappe.throw(f"No Sales Order data found for {item.against_sales_order}")

                    sales_order_info_map[item.item_code] = {
                        "sales_order": item.against_sales_order,
                        "info": sales_order_data[0]
                    }

            def process_serials(item, child_table="Delivery Note Item"):
                serial_no = item.serial_no.strip() if item.serial_no else ""
                if not serial_no:
                    return

                serial_list = serial_no.split('\n')

                if child_table == "Packed Item":
                    order_entry = sales_order_info_map.get(item.parent_item)
                else:
                    order_entry = sales_order_info_map.get(item.item_code)

                if not order_entry:
                    frappe.throw(f"Cannot find Sales Order info for item: {item.item_code}")

                sales_order_info = order_entry["info"]

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
                    phone = sales_order_info.get("phone", "")
                    serial_no_doc.mobile_no = "" if phone.lower() == "na" else phone
                    serial_no_doc.email_id = sales_order_info.get("email_id", "")
                    serial_no_doc.address = sales_order_info.get("so_address", "")
                    serial_no_doc.warranty_start_date_ = self.get("posting_date")

                    posting_date_raw = self.get("posting_date")
                    if isinstance(posting_date_raw, str):
                        end_date = datetime.strptime(posting_date_raw, "%Y-%m-%d")
                    else:
                        end_date = posting_date_raw

                    serial_no_doc.end_date = end_date + timedelta(days=365)
                    # serial_no_doc.modified = now()

                    try:
                        serial_no_doc.save()
                    except Exception as e:
                        log_error(traceback.format_exc(), "Error in saving serial_no_doc")
                        frappe.throw("Error while updating Serial No", str(e))

            for item in self.get('items', []):
                process_serials(item)

            for item in self.get('packed_items', []):
                process_serials(item, "Packed Item")

        except Exception as e:
            log_error(traceback.format_exc(), "Error in _process_customer_details")
            frappe.throw(f"Error in _process_customer_details: {str(e)}")
    
    def _process_serial_numbers(self):

        for item in self.items:
            if not self._should_process_item(item):
                continue
            
            self._update_serial_number_components(item)
        
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
        
        serial_no_doc.awb_no = ''
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
            serial_no_doc.save()
        

    def update_mail_from_address(self):
        try:
            if not self.shipping_address_name:
                frappe.throw("Shipping address not set on Delivery Note.")
            
            address = frappe.get_doc("Address", self.shipping_address_name)
            # print("address=======================", address)
            
            email_id = address.get("email_id")  # Use .get() for safer access
            # print("email_id=======================", email_id)
            
            if not email_id:
                frappe.throw(f"No email_id found in address {self.shipping_address_name}")
            
            self.email = email_id
            # print("self.email=======================", self.email)
            
            self.save(ignore_permissions=True)
            return f"Email set to {email_id} for Delivery Note {self.name}"
            
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Error in update_mail_from_address")
            frappe.throw(f"Error updating email from address: {str(e)}")
        

            
    def fetching_tracking_details(self):
    # Skip if return or not CriticaLog
        if self.is_return or self.courier_service != "CriticaLog":
            return
        try:
            payload = {
                "Auth": " MTMzMzQzNzMwMzIz",  # Include leading space
                "DocketNo": self.name
            }
            url = "https://testing.ecritica.co/eFreightLive/api/tracking.php"
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, headers=headers, json=payload)

            if response.status_code == 200:
                data = response.json()

                # Check for invalid response
                if data.get("code") == 5 and "Invalid Con Number" in str(data.get("data", {}).get("docketDetails", "")):
                    frappe.msgprint(f"The sales order number '{self.name}' is not recognized as a valid tracking number.")
                    return

                # Extract and save remark
                remark = (
                    data.get("data", {})
                    .get("docketDetails", {})
                    .get("Booking_Status", {})
                    .get("Remark")
                )
                if remark:
                    self.remark_status = remark
                    self.db_update()
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
        if rto_cost and self.cost_of_delivery:
            try:
                updated_cost = float(self.cost_of_delivery) + float(rto_cost)
                self.cost_of_delivery = updated_cost
                self.db_update()
            except Exception as e:
                frappe.log_error(f"RTO Cost update failed: {e}", "RTO Charges Update")

    def update_details_to_delivery_charege_doc(self):
        if self.is_return:
            return
        # Check if a Delivery Charges document with the same AWB number exists
        existing_delivery_charge = frappe.get_all(
            "Delivery Charges",
            filters={"awb_number": self.tracking_id},
            limit=1
        )

        serial_nos = set()
        sales_orders = set()

        # Loop through items and collect serial numbers and sales orders
        for row in self.get("items"):
            if row.get("serial_no"):
                # Handle serial numbers separated by comma, newline, or both
                # First split by newlines, then by commas
                serial_text = row.get("serial_no")
                # Split by newlines first
                for line in serial_text.split("\n"):
                    # Then split each line by commas
                    for serial in line.split(","):
                        serial = serial.strip()  # Remove any whitespace
                        if serial:  # Only add non-empty serials
                            serial_nos.add(serial)
            if row.get("against_sales_order"):
                # Handle multiple sales orders if comma-separated
                for order in row.get("against_sales_order").split(","):
                    order = order.strip()
                    if order:
                        sales_orders.add(order)

        # Check packed_items as well (not just when items are empty)
        for row in self.get("packed_items"):
            if row.get("serial_no"):
                # Handle serial numbers separated by comma, newline, or both
                # First split by newlines, then by commas
                serial_text = row.get("serial_no")
                # Split by newlines first
                for line in serial_text.split("\n"):
                    # Then split each line by commas
                    for serial in line.split(","):
                        serial = serial.strip()  # Remove any whitespace
                        if serial:  # Only add non-empty serials
                            serial_nos.add(serial)

        # Convert sets to sorted, comma-separated strings
        serial_nos_str = ",".join(sorted(serial_nos))
        sales_orders_str = ",".join(sorted(sales_orders))

        if existing_delivery_charge:
            # If exists, get the document
            delivery_charge = frappe.get_doc("Delivery Charges", existing_delivery_charge[0].name)

            # Update serial_no
            existing_serials = set()
            if delivery_charge.serial_no:
                for serial in delivery_charge.serial_no.split(","):
                    serial = serial.strip()
                    if serial:
                        existing_serials.add(serial)
            
            all_serials = existing_serials.union(serial_nos)
            delivery_charge.serial_no = ",".join(sorted(all_serials))

            # Update sales_order
            existing_orders = set()
            if delivery_charge.sales_order:
                for order in delivery_charge.sales_order.split(","):
                    order = order.strip()
                    if order:
                        existing_orders.add(order)
            
            all_orders = existing_orders.union(sales_orders)
            delivery_charge.sales_order = ",".join(sorted(all_orders))
        else:
            # Create a new document
            delivery_charge = frappe.new_doc("Delivery Charges")
            delivery_charge.awb_number = self.tracking_id
            delivery_charge.serial_no = serial_nos_str
            delivery_charge.sales_order = sales_orders_str
            delivery_charge.delivery_note = self.name
            delivery_charge.shiprocket_order_id = self.shiprocket_order_id
            delivery_charge.shiprocket_shipment_id = self.shiprocket_shipment_id
            delivery_charge.courier_service = self.courier_service
            delivery_charge.remark_status = self.remark_status
            delivery_charge.cit_image = self.cit_image
            delivery_charge.shiprocket_manifests = self.shiprocket_manifests
            delivery_charge.shiprocket_image = self.shiprocket_image
            delivery_charge.shiprocket_invoice = self.shiprocket_invoice
            delivery_charge.pickup_scheduled_date = self.pickup_scheduled_date
            delivery_charge.weight = self.weight
            delivery_charge.height = self.height
            delivery_charge.length = self.length
            delivery_charge.breadth = self.breadth
            delivery_charge.item_group_qty = self.item_group_qty

        # Set common fields
        delivery_charge.rto_charges = self.cost_of_delivery
        delivery_charge.cit_image = self.cit_image

        if getattr(self, 'is_return', False):
            delivery_charge.cause_of_return = self.cause_of_return

        # Save or insert the document
        try:
            if delivery_charge.is_new():
                delivery_charge.insert(ignore_permissions=True)
            else:
                delivery_charge.save(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Error updating Delivery Charges doc: {e}", "Delivery Charges Sync Error")

    def qc_nj_of_days_checking(self):
    # 1. Check if DN QC is active
        is_active = frappe.db.get_value('NJ Settings', {'parameter': 'dn_qc_active_status'}, 'value')
        if is_active != "Active":
            return 
        
        # 2. Get allowed inspection types and number of days
        allowed_inspection_types = frappe.db.get_value('NJ Settings', {'parameter': 'inspection_type'}, 'value')
        inspection_days = frappe.db.get_value('NJ Settings', {'parameter': 'no_of_days'}, 'value')
        
        # Convert comma-separated inspection types into a list
        allowed_inspection_types_list = [t.strip() for t in allowed_inspection_types.split(",")]
        
        # 3. Get all serial numbers in the Delivery Note
        serial_nos_raw = frappe.get_all(
            'Delivery Note Item',
            filters={'parent': self.name},
            fields=['serial_no', 'name', 'item_code']  # Added more fields for debugging
        )
        
        # Extract unique serial numbers
        serial_nos = set()
        
        for row in serial_nos_raw:
            if row.serial_no:
                # Handle multiple serials in one field (e.g., "SN-001\nSN-002")
                for s in row.serial_no.split('\n'):
                    if s.strip():  # Only add non-empty serial numbers
                        serial_nos.add(s.strip())
        

        # 4. Process each unique serial number and collect error messages
        error_messages = []
        
        for serial_no in serial_nos: 
            
            # 5. Fetch all QI for this serial no (barcode)
            qi_records = frappe.db.sql("""
                SELECT name, creation, inspection_type
                FROM `tabNJ Quality Inspection`
                WHERE barcode = %s AND docstatus = 1
                ORDER BY creation DESC
            """, serial_no, as_dict=True)
            
            
            if not qi_records:
                continue # No QI records found, skip
            
            latest_qi = qi_records[0]
            qi_type = latest_qi.inspection_type.strip()
            
            # 6. Check if QI type is allowed
            if qi_type not in allowed_inspection_types_list:
                continue # Not an allowed inspection type, skip
            
            # 7. Check if QI creation is within the allowed number of days
            creation_date = get_datetime(latest_qi.creation)
            current_date = now_datetime()
            days_difference = (current_date - creation_date).days
            
            if int(days_difference) > int(inspection_days):
                error_msg = f"More than {inspection_days} days have passed for Serial No {serial_no}. Please perform re-QC."
                error_messages.append(error_msg)
        
        # 8. Throw all error messages at once
        if error_messages:
            # Remove duplicates and join messages
            unique_errors = list(set(error_messages))
            frappe.throw("<br>".join(unique_errors))

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

# @frappe.whitelist()
# def get_cod_amount(so_name):
#     try:
#         headers = {
#             "Content-Type": "application/json",
#             "X-Shopify-Access-Token": TOKEN
#         }

#         filters = {"name": so_name, "docstatus": 1,'order_type':"Sales"}

#         raw_order_id = frappe.get_value("Sales Order", filters, "shopify_order_id")

#         if raw_order_id and len(raw_order_id.lstrip('#')) < 7:
#             order_id = raw_order_id.lstrip('#')
#         else:
#             raw_order_id = frappe.get_value("Sales Order", filters, "order_id")
#             order_id = raw_order_id.lstrip('#') if raw_order_id else None

#             if not order_id:
#                 raw_order_id = frappe.get_value("Sales Order", filters, "shopify_order_number")
#                 order_id = raw_order_id.lstrip('#') if raw_order_id else None

#         if not order_id:
#             return {"order_id": None, "cod_amount": 0}

#         url = f"{SHOPIFY_URL}{order_id}"
#         response = requests.get(url, headers=headers)
#         data = response.json()

#         if "orders" in data and data["orders"]:
#             order = data["orders"][0]
#             cod_amount = order.get("total_outstanding", 0)
#             return {"order_id": order_id, "cod_amount": cod_amount}

#         return {"order_id": order_id, "cod_amount": 0}

#     except Exception as e:
#         frappe.log_error(f"Error in get_cod_amount: {str(e)}", "Shopify COD Fetch Error")
#         return {"order_id": None, "cod_amount": 0}

@frappe.whitelist(allow_guest=True)
def trigger_fulfillment(order_id,original_order_id=None,shopify_order_no=None,dn_name=None):
    doc = frappe.get_doc("Delivery Note", dn_name)
    if doc.is_return:
        return
    # 2. Skip if any return DN exists with items against the same Sales Order
    against_sales_order = frappe.get_value("Delivery Note Item", {"parent": dn_name}, "against_sales_order")

    # 3. Check if any return Delivery Note exists for the same against_sales_order
    if against_sales_order:
        return_dn_exists = frappe.db.sql("""
            SELECT 1 FROM `tabDelivery Note Item` dn_item
            JOIN `tabDelivery Note` dn ON dn.name = dn_item.parent
            WHERE dn.is_return = 1
            AND dn_item.against_sales_order = %s
            LIMIT 1
        """, (against_sales_order,), as_dict=1)

        if return_dn_exists:
            return # Skip fulfillment trigger

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
            
            # Get tracking data from Delivery Note
            tracking_data = frappe.db.get_value("Delivery Note", {"name": dn_name}, ["tracking_id", "courier_service"])

            if not tracking_data:
                frappe.throw("Tracking data not found in Delivery Note.")

            tracking_number, courier_service = tracking_data
             
            # Get tracking URL from Courier Service document
            tracking_link = None
            courier_company = courier_service  # Default company name
            
            if courier_service:
                try:
                    # Try to get tracking URL from Courier Service doctype
                    courier_doc = frappe.get_doc("Courier Service", courier_service)
                    if hasattr(courier_doc, 'tracking_url') and courier_doc.tracking_url:
                        base_url = courier_doc.tracking_url
                        # Append tracking number to the base URL
                        if tracking_number:
                            tracking_link = f"{base_url.rstrip('/')}/{tracking_number}"
                        else:
                            tracking_link = base_url
                    
                    # Get proper company name if available
                    if hasattr(courier_doc, 'courier_name') and courier_doc.courier_name:
                        courier_company = courier_doc.courier_name
                    elif hasattr(courier_doc, 'company_name') and courier_doc.company_name:
                        courier_company = courier_doc.company_name
                        
                except frappe.DoesNotExistError:
                    # Fallback: try to extract company name from service name
                    if "delhivery" in courier_service.lower():
                        courier_company = "Delhivery"
                        if tracking_number:
                            tracking_link = f"https://www.delhivery.com/track/package/{tracking_number}"
                        else:
                            tracking_link = "https://www.delhivery.com/track/package/"
                    elif "shiprocket" in courier_service.lower():
                        courier_company = "Shiprocket"
                        if tracking_number:
                            tracking_link = f"https://shiprocket.co/tracking/{tracking_number}"
                        else:
                            tracking_link = "https://shiprocket.co/tracking/"
                    elif "criticalog" in courier_service.lower():
                        courier_company = "CriticaLog"
                        if tracking_number:
                            tracking_link = f"https://criticalog.com/tracking/{tracking_number}"
                        else:
                            tracking_link = "https://criticalog.com/tracking/"
                    else:
                        courier_company = courier_service
                        tracking_link = None

            # Case 1: Already fulfilled -> update tracking info
            if fulfillment_status == "fulfilled":
                fulfillment_url = f"https://newjaisa.myshopify.com/admin/api/2025-01/orders/{order_id_shopify}/fulfillments.json"
                fulfillment_response = requests.get(fulfillment_url, headers=headers)
                fulfillment_json = fulfillment_response.json()

                if fulfillment_json.get("fulfillments"):
                    existing_fulfillment_id = fulfillment_json["fulfillments"][0]["id"]
                    
                    # Prepare tracking info
                    tracking_info = {
                        "number": tracking_number,
                        "company": courier_company
                    }
                    
                    # Only add URL if it exists
                    if tracking_link:
                        tracking_info["url"] = tracking_link
                    
                    update_payload = {
                        "fulfillment": {
                            "tracking_info": tracking_info,
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
                            "tracking_number": tracking_number,
                            "courier_company": courier_company,
                            "tracking_url": tracking_link
                        }
                    else:
                        frappe.throw(f"Failed to update existing fulfillment. Response: {update_data}")
                else:
                    frappe.throw("No fulfillment found to update.")

            # Case 2: Not fulfilled -> create fulfillment
            else:
                fulfillment_order_url = FULLFILMENT_ORDER_ID.format(shopify_order_id=order_id_shopify)
                fulfillment_order_response = requests.get(fulfillment_order_url, headers=headers)
                fulfillment_order_data = fulfillment_order_response.json()

                if "fulfillment_orders" in fulfillment_order_data and fulfillment_order_data["fulfillment_orders"]:
                    fulfillment_order_id = fulfillment_order_data["fulfillment_orders"][0]["id"]

                    # Prepare tracking info
                    tracking_info = {
                        "number": tracking_number,
                        "company": courier_company
                    }
                    
                    # Only add URL if it exists
                    if tracking_link:
                        tracking_info["url"] = tracking_link

                    fulfillment_payload = {
                        "fulfillment": {
                            "line_items_by_fulfillment_order": [
                                {
                                    "fulfillment_order_id": fulfillment_order_id
                                }
                            ],
                            "tracking_info": tracking_info
                        }
                    }

                    fulfillment_response = requests.post(MAKE_FULLFILMENT, headers=headers, json=fulfillment_payload)
                    fulfillment_data = fulfillment_response.json()
                    
                    if "fulfillment" in fulfillment_data and fulfillment_data["fulfillment"]:
                        fulfillment_id = fulfillment_data["fulfillment"]["id"]
                        return {
                            "status": "created", 
                            "fulfillment_id": fulfillment_id,
                            "tracking_number": tracking_number,
                            "courier_company": courier_company,
                            "tracking_url": tracking_link
                        }
                    else:
                        frappe.throw(f"Fulfillment creation failed. Response: {fulfillment_data}")
                else:
                    frappe.throw("Fulfillment Order not found.")
        else:
            frappe.throw("Order not found.")
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

@frappe.whitelist()
def update_item_details(self):
    if isinstance(self, str):
        self = json.loads(self)
    # If weight/dimensions are already filled, assume user has set them — do not override
    if self.get("weight") or self.get("height") or self.get("length") or self.get("breadth"):
        return None
    total_weight = 0
    height = length = breadth = None
    # Step 1: Get allowed item groups from NJ Settings
    item_group_value = frappe.db.get_value(
        "NJ Settings", {"parameter": "Item Group Validation"}, "value"
    )
    allowed_item_groups = []
    if item_group_value:
        allowed_item_groups = [group.strip() for group in item_group_value.split(",")]
    # Step 2: Filter matching items
    matching_rows = []
    for row in self.get("items", []):
        item_code = row.get("item_code")
        if not item_code:
            continue
        item_group = frappe.db.get_value("Item", item_code, "item_group")
        if item_group in allowed_item_groups:
            matching_rows.append(row)
    # Step 3: If not exactly 1 matching item, skip
    if len(matching_rows) != 1:
        print("Skipping: multiple matching items.")
        return None
    item = matching_rows[0]
    if item.get("qty") != 1:
        print("Skipping: qty is not 1.")
        return None
    # Step 4: Fetch from Item Group
    item_code = item.get("item_code")
    item_group = frappe.db.get_value("Item", item_code, "item_group")
    try:
        group_doc = frappe.get_doc("Item Group", item_group)

        if group_doc.get("weight"):
            try:
                total_weight += float(group_doc.weight)
            except ValueError:
                frappe.log_error(f"Invalid weight in Item Group: {group_doc.name}", "Weight Error")

        for dim in group_doc.get("dimensions", []):
            param = dim.parameter.strip().lower()
            value = dim.value
            if "height" in param and not height:
                height = value
            elif "length" in param and not length:
                length = value
            elif "breadth" in param and not breadth:
                breadth = value

    except Exception as e:
        print(f"Error reading item group {item_group}: {str(e)}")

    return {
        'weight': total_weight,
        'height': height,
        'length': length,
        'breadth': breadth
    }
           
@frappe.whitelist()
def fetch_cod_amount(doc_name):
    against_sales_order = frappe.get_value("Delivery Note Item", {"parent": doc_name}, "against_sales_order")
    cod_amt = frappe.get_value("Sales Order", {"name": against_sales_order}, "total_outstanding") 
    return { 'cod_amount': cod_amt }

@frappe.whitelist()
def send_consignement_data(doc):
    # start_time = time.time()
    try:
        # Convert string to Frappe dict
        doc = frappe._dict(json.loads(doc))
        # sales_order_doc = frappe.get_doc("Sales Order", doc.name)
        delivery_note = frappe.get_doc("Delivery Note", doc.name)
        against_sales_order = frappe.get_value(
            "Delivery Note Item", {"parent": delivery_note.name}, "against_sales_order"
        )

        total_qty = 0
        for item in delivery_note.items:
            is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")
            # print("is_stock_item==================",is_stock_item)
            
            # Only add qty if is_stock_item is 1 (i.e., checked/true)
            if is_stock_item == 1:
                total_qty += item.qty
                # print("total_qty==================",total_qty)
        frappe.db.set_value("Delivery Note", doc.name, "item_group_qty", total_qty)              
        # Validate shipping address and calculate cost of delivery
        if not doc.shipping_address_name:
            frappe.throw("Shipping address is not set.")
        total_item_charges = 0
        for item in doc.get("items", []):
            # Check if item_code exists
            if not item.get("item_code"):
                continue
            # Get item group
            item_group = frappe.db.get_value("Item", item.get("item_code"), "item_group") 
            # Get the item group document
            group_doc = frappe.get_doc("Item Group", item_group)
            # Get item_charges (float)
            item_charges = group_doc.get("item_charges")
            if item_charges and item.get("qty"):
                item_total_charge = float(item_charges) * float(item.get("qty"))
                total_item_charges += item_total_charge
            else:
                print("Missing item_charges or quantity for item:", item.get("item_code"))
        # Get the pincode from the Address doctype
        pincode = frappe.db.get_value("Address", doc.shipping_address_name, "pincode")
        if not pincode:
            frappe.throw("Pincode not found in the shipping address.")
        
        # Check if Pincode exists in Pincode doctype
        pincode_doc = frappe.db.get_value("Pincode", {"pincode_no": pincode}, ["rate", "cod"], as_dict=True)
        if not pincode_doc:
            frappe.throw(f"Pincode {pincode} not found in Pincode master.")
        
        if not doc.weight:
            frappe.throw("Weight is not set in Delivery Note.")
        # Calculate total item charges
        total_item_charges = 0
        for item in doc.get("items", []):
            # Check if item_code exists
            if not item.get("item_code"):
                continue
            # Get item group
            item_group = frappe.db.get_value("Item", item.get("item_code"), "item_group") 
            # Get the item group document
            group_doc = frappe.get_doc("Item Group", item_group)
            # Get item_charges (float)
            item_charges = group_doc.get("item_charges")
            # print("item_charges=======================",item_charges)
            if item_charges and item.get("qty"):
                item_total_charge = float(item_charges) * float(item.get("qty"))
                total_item_charges += item_total_charge
            else:
                print("Missing item_charges or quantity for item:", item.get("item_code"))
        # Convert string to float for arithmetic  
        rate = float(pincode_doc.rate or 0)
        # print("rate=======================", rate)
        cod_charge = float(pincode_doc.cod or 0)
        # print("cod_charge=======================", cod_charge)
        weight = float(doc.weight or 0)
        # print("weight=======================", weight)
        is_cod = False
        if against_sales_order:
            # Method 1: Fetch only is_cod field
            is_cod = frappe.db.get_value("Sales Order", against_sales_order, "is_cod") or 0

        # Calculate cost of delivery and run COD validation only for COD orders
        if is_cod == 1:  # is_cod is typically stored as 1 for True, 0 for False
            cost_of_delivery = (rate * weight) + cod_charge
            # print("cost_of_delivery=======================", cost_of_delivery)     
            # COD validation - only run for COD orders
            ship_rocket_settings = frappe.get_doc("Ship Rocket Settings")
            # print("ship_rocket_settings=======================", ship_rocket_settings)        
            cod_charges_table = ship_rocket_settings.get("cod_charges", [])
            # print("cod_charges_table=======================", cod_charges_table)         
            # Find the charges_value from COD Charges child table
            charges_value = None
            for cod_charge_row in cod_charges_table:
                charges_value = cod_charge_row.charges_value  # Access as field attribute
                # print("charges_value=======================", charges_value)
                if charges_value:
                    break      
            if charges_value:
                # Extract numeric value from percentage string (e.g., "8%" -> 8)
                numeric_charges_value = float(charges_value.replace('%', '').strip())
                # print("numeric_charges_value=======================", numeric_charges_value)       
                # Calculate percentage of grand_total
                grand_total = float(doc.get("grand_total", 0) or 0)
                # print("grand_total=======================", grand_total)
                cod_percentage_amount = round((numeric_charges_value / 100) * grand_total, 2)
                # print("cod_percentage_amount=======================", cod_percentage_amount)
                cod_and_item_charges_total = total_item_charges + cod_percentage_amount
                # print("cod_and_item_charges_total=======================", cod_and_item_charges_total)
                # COD specific validation - throw error if COD charges are too high
                if cod_and_item_charges_total < cost_of_delivery:
                    frappe.throw(f"COD validation failed: COD charges courier total cost ({cost_of_delivery:.2f}) is greater than ({numeric_charges_value:.2f}% of grand total = {cod_percentage_amount:.2f})")
            
        else:
            # For prepaid orders, no COD charges
            cost_of_delivery = rate * weight
            # print("cost_of_delivery=======================", cost_of_delivery)
            
            # Non-COD validation - check if cost exceeds item charges
            if cost_of_delivery > total_item_charges:
                frappe.throw(f"Cannot generate AWB number because courier total cost ({cost_of_delivery}) is more than item charges total ({total_item_charges})")
        # Fetch addresses
        company_address = frappe.get_doc("Address", doc.company_address) if doc.company_address else None
        shipping_address = frappe.get_doc("Address", doc.shipping_address_name) if doc.shipping_address_name else None
        # formatted_date = doc.delivery_date.strftime("%Y-%m-%d") if hasattr(doc.delivery_date, 'strftime') else str(doc.delivery_date)
        formatted_date = datetime.today().strftime("%Y-%m-%d")
        
        against_sales_order = frappe.get_value(
            "Delivery Note Item", {"parent": delivery_note.name}, "against_sales_order"
        )
        if against_sales_order:
            sales_order_doc = frappe.get_doc("Sales Order", against_sales_order)
            
            if sales_order_doc.is_cod == 1:
                PaymentType = "COD"
                consignmentValue = float(sales_order_doc.total_outstanding or 0)
            else:
                PaymentType = "Prepaid"
                # Check if grand_total exists and has value
                if sales_order_doc.grand_total:
                    consignmentValue = float(sales_order_doc.grand_total)
                else:
                    # If grand_total not found, fetch from item groups
                    total_default_charge = 0
                    found_charges = False
                    
                    # Loop through items in Sales Order
                    for item in sales_order_doc.items:
                        if item.item_code:
                            # Get item document to fetch item_group
                            item_doc = frappe.get_doc("Item", item.item_code)
                            if item_doc.item_group:
                                try:
                                    # Get item group document and fetch default_charge
                                    item_group_doc = frappe.get_doc("Item Group", item_doc.item_group)
                                    if hasattr(item_group_doc, 'default_charge') and item_group_doc.default_charge:
                                        total_default_charge += float(item_group_doc.default_charge)
                                        found_charges = True
                                except:
                                    continue
                    
                    # Set consignment value based on what was found
                    if found_charges and total_default_charge > 0:
                        consignmentValue = total_default_charge
                    else:
                        # Fallback to Rs 1000 if no default charges found
                        consignmentValue = 300.0
        else:
            frappe.throw("Sales Order not linked to this Delivery Note.")      
        # Fetch item groups
        item_group_value = frappe.db.get_value(
            "NJ Settings", {"parameter": "Item Group Validation"}, "value"
        )
        allowed_item_groups = []
        if item_group_value:
            allowed_item_groups = [group.strip() for group in item_group_value.split(",")]
        
        # Calculate total quantity for allowed items only
        total_quantity = 0
        items = []
        for row in doc.get('items', []):
            # Get item group for current item
            item_group = frappe.db.get_value("Item", row.get("item_code"), "item_group")
            
            # Only include items whose item group is in the allowed list
            if not allowed_item_groups or item_group in allowed_item_groups:
                qty = float(row.get('qty', 1))
                total_quantity += qty  # Sum up quantities for allowed items only
                items.append({
                    "Length": f"{float(doc.length):.2f}",
                    "Breadth": f"{float(doc.breadth):.2f}",
                    "Height": f"{float(doc.height):.2f}",
                    "ProductCode": "AUTO",
                    "ProductDescription": row.get("item_name"),
                    "SplitPcs": f"{qty:.4f}",  # Individual item quantity
                    "IsPackaging": "0"
                })
            else:
                print(f"Skipping item {row.get('item_name')} - item group {item_group} not in allowed list")
        
        # Check if any items are left after filtering
        if not items:
            frappe.throw("No items found with allowed item groups for shipping.")
        transport = doc.mode_of_transfer
        # print("transport===================================", transport)
        if against_sales_order:
            sales_order_doc = frappe.get_doc("Sales Order", against_sales_order)
            # print("sales_order_doc===================================", sales_order_doc)
        # Function to determine ClientCode based on the fetched transport mode
        def get_client_code(transport_mode):
            if transport_mode == "Air":
                # print("air===================================", frappe.db.get_single_value("Logistics Settings", "air"))    
                return frappe.db.get_single_value("Logistics Settings", "air")
            elif transport_mode == "Surface":
                # print("surface===================================", frappe.db.get_single_value("Logistics Settings", "surface"))
                return frappe.db.get_single_value("Logistics Settings", "surface")
            elif transport_mode == "COD Air":
                # print("cod_air===================================", frappe.db.get_single_value("Logistics Settings", "cod_air"))
                return frappe.db.get_single_value("Logistics Settings", "cod_air")
            elif transport_mode == "COD Surface":
                # print("cod_surface===================================", frappe.db.get_single_value("Logistics Settings", "cod_surface"))
                return frappe.db.get_single_value("Logistics Settings", "cod_surface")
        # Get the appropriate ClientCode based on the fetched transport mode
        client_code = get_client_code(transport)
        # print("client_code===================================", client_code)
        # Prepare header with correct total quantity
        header = {
            "ClientCode": client_code,
            "OrderNo/InvoiceNo": doc.name,
            "Order/InvoiceDate": formatted_date,
            "SenderName": doc.company,
            "SenderAdd1": company_address.address_line1 or " ",
            "SenderAdd2": company_address.address_line2 or "",
            "SenderCity": company_address.city or "",
            "SenderState": company_address.state or "",
            "SenderCountry": company_address.country or "India",
            "SenderPin": company_address.pincode or "",
            "SenderMobile": sanitize_phone(shipping_address.phone),
            "SenderEmail": company_address.email_id or "",
            "ReceiverName": doc.customer_name or "",
            "ReceiverAdd1": shipping_address.address_line1 or "",
            "ReceiverAdd2": shipping_address.address_line2 or " ",
            "ReceiverCity": shipping_address.city or "",
            "ReceiverState": shipping_address.state or "",
            "ReceiverCountry": shipping_address.country or "India",
            "ReceiverPin": shipping_address.pincode or "",
            "ReceiverMobile": sanitize_phone(shipping_address.phone),
            "ConsignmentValue": str(doc.grand_total),
            "NoQuantity": int(total_quantity),  # Fixed: Use total quantity of all items
            "consignmentValue": str(doc.grand_total),
            "Weight": f"{weight:.2f}",  # Fixed: Use doc.weight instead of doc.length
            "TransitMode": doc.mode_of_transfer,
            "ProductMode": "Normal",
            "PaymentType": PaymentType,
            "Amount": consignmentValue,
            "Need_CitImage": "1"
        }
        # print(f"Header:===================================== {header}")
        # Add validation to ensure quantities match
        calculated_total = sum(float(item["SplitPcs"]) for item in items)
        if abs(calculated_total - total_quantity) > 0.001:  # Allow for small floating point differences
            frappe.throw(f"Quantity mismatch: Total quantity ({total_quantity}) doesn't match sum of split quantities ({calculated_total})")
        
        data = {
            "ResponseHeader": "yes",
            "Header": [header],
            "ItemsDetails": items
        }
        # print("Data:===============================================", data)
        url = frappe.db.get_single_value("Logistics Settings", "url")
        # url = "https://testing.ecritica.co/eFreightLive/api/con_generation.php"
        # url = "https://www.ecritica.co/eFreightLive/api/con_generation.php"
        headers = {"Content-Type": "application/json"}
        # print("headers=======================",headers)
        response = requests.post(url, headers=headers, json=data)
        # print("response=======================",response)
        resp_json = response.json()
        # print("resp_json=======================",resp_json)    
        if resp_json.get('code') == 1 and resp_json.get('status') == 200:
            tracking_id = resp_json.get('data', {}).get('AWB Number') or resp_json.get('data', {}).get('AWBNumber')
            cit_data = resp_json.get('data', {}).get('CitImage') or resp_json.get('CitImage')          
            # Update the Sales Order document with AWB number, CIT image, cost of delivery, and courier service
            delivery_note = frappe.get_doc("Delivery Note", doc.name)
            delivery_note.tracking_id = tracking_id
            delivery_note.cit_image = cit_data
            delivery_note.cost_of_delivery = cost_of_delivery
            delivery_note.courier_service = "CriticaLog"  # Set courier service
            delivery_note.item_group_qty = total_quantity
            delivery_note.save()           
            # Use db_set to update without triggering validations or changing docstatus
            # delivery_note.db_set('tracking_id', tracking_id)
            # delivery_note.db_set('cit_image', cit_data)
            # delivery_note.db_set('cost_of_delivery', cost_of_delivery)
            # delivery_note.db_set('courier_service', 'CriticaLog')
            # delivery_note.db_set('item_group_qty', total_quantity)            
            frappe.msgprint(f"AWB Number generated successfully: {tracking_id}") 
            return {"awb_number": tracking_id, "cit_image": cit_data, "cost_of_delivery": cost_of_delivery}           
        else:
            frappe.throw(f"API returned error: {response.text}")
         
    except Exception as e:
        frappe.throw(f"Failed to send data to Criticalog API. Error: {str(e)}")   

@frappe.whitelist()
def shiprocket_awb_number(doc):

    # start_time = time.time()
    """Create a ShipRocket consignment, assign an AWB, and generate a manifest and invoice."""
    doc = frappe._dict(json.loads(doc))
    auth_token = get_auth_token().get("token")

    if not auth_token:
        frappe.throw("Authentication token could not be retrieved from Shiprocket.")   
    try:
        # Get the Delivery Note document
        delivery_note_doc = frappe.get_doc("Delivery Note", doc.name)

        total_qty = 0
        for item in delivery_note_doc.items:
            is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")
            # print("is_stock_item==================",is_stock_item)
            
            # Only add qty if is_stock_item is 1 (i.e., checked/true)
            if is_stock_item == 1:
                total_qty += item.qty
                # print("total_qty==================",total_qty)

        # Update the item_group_qty field in the parent Delivery Note
        frappe.db.set_value("Delivery Note", doc.name, "item_group_qty", total_qty)
        against_sales_order = frappe.get_value(
            "Delivery Note Item", {"parent": delivery_note_doc.name}, "against_sales_order"
        )       
        # Fetch addresses
        shipping_address = frappe.get_doc("Address", delivery_note_doc.shipping_address_name) if delivery_note_doc.shipping_address_name else None    
        if not shipping_address:
            frappe.throw("Shipping address is required")
        formatted_date = datetime.today().strftime("%Y-%m-%d")

        # Prepare order_items from child table - ShipRocket format
        order_items = []
        for row in delivery_note_doc.items:
            order_items.append({
                "name": (row.item_code[:50] if row.item_code else "")[:50], 
                "sku": (row.item_code[:50] if row.item_code else "")[:50],   
                "units": int(row.qty),                      
                "selling_price": str(row.rate * 1.18),    
                "discount": "",
                "tax": 18.0,
                "hsn": ""
            })

        if against_sales_order:
            sales_order_doc = frappe.get_doc("Sales Order", against_sales_order)

            if sales_order_doc.is_cod == 1:
                payment_method = "COD"
                sub_total = float(sales_order_doc.total_outstanding or 0)
            else:
                payment_method = "Prepaid"
                # sub_total = float(sales_order_doc.grand_total or 0)
                if sales_order_doc.grand_total:
                    sub_total = float(sales_order_doc.grand_total)
                    # print("sub_total==================",sub_total)
                else:
                    # If grand_total not found, fetch from item groups
                    total_default_charge = 0
                    found_charges = False                
                    # Loop through items in Sales Order
                    for item in sales_order_doc.items:
                        if item.item_code:
                            # Get item document to fetch item_group
                            item_doc = frappe.get_doc("Item", item.item_code)
                            # print("item_doc==================",item_doc)
                            if item_doc.item_group:
                                try:
                                    # Get item group document and fetch default_charge
                                    item_group_doc = frappe.get_doc("Item Group", item_doc.item_group)
                                    # print("item_group_doc==================",item_group_doc)
                                    if hasattr(item_group_doc, 'default_charge') and item_group_doc.default_charge:
                                        total_default_charge += float(item_group_doc.default_charge)
                                        # print("total_default_charge==================",total_default_charge)
                                        found_charges = True
                                except:
                                    # Continue if item group not found or error occurs
                                    continue
                    
                    # Set consignment value based on what was found
                    if found_charges and total_default_charge > 0:
                        sub_total = total_default_charge
                        print("sub_total==================",sub_total)
                    else:
                        # Fallback to Rs 1000 if no default charges found
                        sub_total = 300.0
        else:
            frappe.throw("Sales Order not linked to this Delivery Note.")

        # ShipRocket API payload structure
        data = {
            "order_id": delivery_note_doc.name,
            "order_date": formatted_date,
            "pickup_location": "Office",
            "comment": f"Order from {delivery_note_doc.customer_name}",
            "billing_customer_name": delivery_note_doc.customer_name or "",
            "billing_last_name": "",
            "billing_address": shipping_address.address_line1 if shipping_address.address_line1 else "",
            "billing_address_2": shipping_address.address_line2 if shipping_address.address_line2 else "",
            "billing_city": shipping_address.city if shipping_address.city else "",
            "billing_pincode": shipping_address.pincode if shipping_address.pincode else "",
            "billing_state": shipping_address.state if shipping_address.state else "",
            "billing_country": shipping_address.country if shipping_address.country else "India",
            "billing_email": shipping_address.email_id if shipping_address.email_id else "",
            "billing_phone":sanitize_phone(shipping_address.phone),
            "shipping_is_billing": True,
            "shipping_customer_name": "",
            "shipping_last_name": "", 
            "order_items": order_items,
            "payment_method": payment_method,
            "sub_total": sub_total,
            "length": str(delivery_note_doc.length),
            "breadth": str(delivery_note_doc.breadth), 
            "height": str(delivery_note_doc.height),
            "weight": str(delivery_note_doc.weight)
        }
        # print("Data: ===========", data)

        # url = "https://apiv2.shiprocket.in/v1/external/orders/create/adhoc"
        url = frappe.db.get_single_value("Logistics Settings", "adhoc_url")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token.strip()}"
        }
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            try:
                resp_json = response.json()
                if resp_json.get('order_id'):
                    # Update document with ShipRocket IDs
                    frappe.db.set_value("Delivery Note", doc.name, "shiprocket_order_id", resp_json.get('order_id'))
                    frappe.db.set_value("Delivery Note", doc.name, "shiprocket_shipment_id", resp_json.get('shipment_id'))
                    
                    # Update local doc object for further processing
                    doc.shiprocket_order_id = resp_json.get('order_id')
                    doc.shiprocket_shipment_id = resp_json.get('shipment_id')
                    
                    frappe.db.commit()
                else:
                    frappe.throw(f"Order creation failed: {response.text}")
            except ValueError as json_err:
                frappe.throw(f"Could not parse API response: {response.text}")
        else:
            # Handle different error codes
            if response.status_code == 401:
                frappe.throw("Authentication failed. Please check your ShipRocket credentials.")
            elif response.status_code == 422:
                frappe.throw(f"Validation error: {response.text}")
            else:
                frappe.throw(f"API request failed with status {response.status_code}: {response.text}")
                
    except Exception as e:
        frappe.log_error(f"Consignment API Failed for {doc.name}: {str(e)}", frappe.get_traceback())
        frappe.throw(f"Failed to send data to ShipRocket API. Error: {str(e)}")

    if not doc.shiprocket_shipment_id:
        frappe.throw("Shipment ID not found on the document after consignment creation.")
    
    shipment_id = doc.shiprocket_shipment_id
    invoice_order_id = doc.shiprocket_order_id
    shipment_list = [int(shipment_id)]

    # 1. Service Availability
    service_url = frappe.db.get_single_value("Logistics Settings", "service_url")
    service_response = requests.get(service_url, headers=headers, json={"order_id": invoice_order_id})
    service_json = service_response.json()
    courier_data = service_json.get("data", {}).get("available_courier_companies", [])
    if not courier_data:
        frappe.throw("No courier companies found in serviceability response.")

    # Get skipping courier names from Logistics Settings child table
    logistics_settings = frappe.get_doc("Logistics Settings")
    skipping_courier_names = []
    logistics_settings = frappe.get_doc("Logistics Settings")
    allowed_courier_names = []
    if logistics_settings and logistics_settings.shiprocketcourier_name_block_list:
        allowed_courier_names = [row.courier_name.strip() for row in logistics_settings.shiprocketcourier_name_block_list if row.courier_name]

    # Calculate total charges for each courier
    best_courier = None
    lowest_total = float('inf')

    for courier in courier_data:
        try:
            courier_name = courier.get("courier_name", "")
            
            # Only consider couriers that are in the allowed list
            if courier_name and allowed_courier_names:
                if courier_name not in allowed_courier_names:
                    continue  # Skip couriers NOT in the allowed list
            else:
                # If no allowed list is configured, skip this courier
                continue        
            # Check rating - skip if 4 or below
            log_rating = frappe.db.get_single_value("Logistics Settings", "rating")
            # print("log_rating==================================", log_rating)
            rating = float(courier.get("rating", 0) or 0)
            if rating < log_rating:
                continue           
            # Calculate total cost
            freight_charge = float(courier.get("freight_charge", 0) or 0)
            cod_charges = float(courier.get("cod_charges", 0) or 0)
            total = freight_charge + cod_charges
            
            # Select courier with lowest total cost
            if total < lowest_total:
                lowest_total = total
                best_courier = {
                    "courier_name": courier.get("courier_name"),
                    "courier_company_id": courier.get("courier_company_id"),
                    "total_cost": total,
                    "rating": rating,
                    "freight_charge": freight_charge,
                    "cod_charges": cod_charges
                }
        except (ValueError, TypeError) as e:
            continue

    if not best_courier:
        frappe.throw(f"No suitable courier found from the allowed courier list with rating above {log_rating}.")
    if best_courier:
        courier_service_name = best_courier.get("courier_name")     
        # Check if courier service exists, if not create it
        if courier_service_name:
            if not frappe.db.exists("Courier Service", courier_service_name):
                # Create new Courier Service with tracking URL
                courier_service_doc = frappe.get_doc({
                    "doctype": "Courier Service",
                    "courier_name": courier_service_name,
                    "tracking_url": "https://shiprocket.co/tracking/"
                })
                courier_service_doc.insert(ignore_permissions=True)
            else:
                print(f"Courier Service '{courier_service_name}' already exists")
            
            # Set values on Delivery Note
            # dn_doc.db_set("awb_number", awb_number)  # Uncomment when awb_number is available
            delivery_note_doc.db_set("courier_service", courier_service_name)
            # dn_doc.db_set("shiprocket_courier_name", courier_service_name)
            
        else:
            frappe.throw("Courier name not found in best courier selection")    
    # Calculate total item charges
    total_item_charges = 0
    for item in doc.get("items", []):
        # Check if item_code exists
        if not item.get("item_code"):
            continue
        # Get item group
        item_group = frappe.db.get_value("Item", item.get("item_code"), "item_group") 
        # Get the item group document
        group_doc = frappe.get_doc("Item Group", item_group)
        # Get item_charges (float)
        item_charges = group_doc.get("item_charges")
        # print("item_charges=======================",item_charges)
        if item_charges and item.get("qty"):
            item_total_charge = float(item_charges) * float(item.get("qty"))
            total_item_charges += item_total_charge
        else:
            print("Missing item_charges or quantity for item:", item.get("item_code"))

    # Calculate total COD charges
    is_cod = False
    # cod_and_item_charges_total = 0
    if against_sales_order:
        is_cod = frappe.db.get_value("Sales Order", against_sales_order, "is_cod") or 0
    # COD Validation - Check if is_cod is enabled
    if is_cod == 1:  # Check if COD is enabled
        
        if best_courier:
            # Calculate total cost with weight
            freight_charge = best_courier.get('freight_charge', 0)
            # print("freight_charge===============",freight_charge)
            cod_charges = best_courier.get('cod_charges', 0)
            # print("cod_charges==============",cod_charges)
            doc_weight = doc.get('weight', 0) or 0
            # print("doc_weight===============",doc_weight)
            
            total_cost = (freight_charge ) + cod_charges
            # print("total_cost================",total_cost)
            # Fetch COD charges from Ship Rocket Settings
            ship_rocket_settings = frappe.get_doc("Ship Rocket Settings")
            # print("ship_rocket_settings==================",ship_rocket_settings)
            cod_charges_table = ship_rocket_settings.get("cod_charges", [])
            # print("cod_charges_table==================",cod_charges_table)          
            # Find the charges_value from COD Charges child table
            charges_value = None
            for cod_charge_row in cod_charges_table:
                charges_value = cod_charge_row.charges_value  # Access as field attribute
                # print("charges_value==================",charges_value)
                if charges_value:
                    break         
            if charges_value:              
                # Extract numeric value from percentage string (e.g., "8%" -> 8)
                numeric_charges_value = float(charges_value.replace('%', '').strip())
                # print("numeric_charges_value==================",numeric_charges_value)
                
                # Calculate percentage of grand_total
              
                grand_total = float(doc.get("grand_total", 0) or 0)
                # print("grand_total==================",grand_total)
                cod_percentage_amount = round((numeric_charges_value / 100) * grand_total, 2)
                # print("cod_percentage_amount==================",cod_percentage_amount)
                cod_and_item_charges_total = cod_percentage_amount+total_item_charges
                # print("cod_and_item_charges_total==================",cod_and_item_charges_total)

                # Compare COD percentage amount with total_cost
                if cod_and_item_charges_total< total_cost:
                    frappe.throw(f"COD validation failed: COD charges courier total cost ({total_cost:.2f}) is greater than ({numeric_charges_value:.2f}% of grand total = {cod_and_item_charges_total:.2f})")             
            else:
                frappe.throw("No COD charges value found in Ship Rocket Settings")
    else:
        print("COD is not enabled, skipping COD validation...")
        # Check if courier total cost exceeds item charges total for non-COD orders
        if best_courier and best_courier.get('total_cost', 0) > total_item_charges:
            frappe.throw(f"Cannot generate AWB number because courier '{best_courier.get('courier_name')}' total cost ({best_courier.get('total_cost')}) is more than item charges total ({total_item_charges})")

    frappe.db.set_value("Delivery Note", doc.name, "shiprocket_courier_name", best_courier.get("courier_name"))

    # 2. AWB Assignment
    awb_url = "https://apiv2.shiprocket.in/v1/external/courier/assign/awb"
    awb_response = requests.post(awb_url, headers=headers, json={
        "shipment_id": shipment_id,
        "courier_id": best_courier.get("courier_company_id")
    })
    awb_json = awb_response.json()

    # ✅ If there's an error message, show and stop
    if "message" in awb_json:
        frappe.throw(f"ShipRocket AWB Assignment Failed: {awb_json.get('message')}")

    response_data = awb_json.get("response", {})
    data = response_data.get("data", {})

    awb_code = None
    pickup_scheduled_date = None

    if isinstance(data, dict):
        awb_code = data.get("awb_code")
        # print("awb_code===============",awb_code)
        invoice_no = data.get("invoice_no")
        # print("invoice_no===============",invoice_no)

        transporter_id = data.get("transporter_id")
        # print("transporter_id===============",transporter_id)
        transporter_name = data.get("transporter_name")
        # print("transporter_name===============",transporter_name)
        pickup_scheduled_date = data.get("pickup_scheduled_date")  # Try to get from AWB response
        # print("pickup_scheduled_date===============",pickup_scheduled_date)
    else:

        frappe.throw(f"ShipRocket AWB Assignment Failed: Invalid response format - {data}")

    # ✅ Save AWB Code and other details to Delivery Note
    frappe.db.set_value("Delivery Note", doc.name, "tracking_id", awb_code)
    frappe.db.set_value("Delivery Note", doc.name, "lr_no", invoice_no)
    frappe.db.set_value("Delivery Note", doc.name, "gst_transporter_id", transporter_id)
    frappe.db.set_value("Delivery Note", doc.name, "transporter_name", transporter_name)

    # ✅ Handle pickup scheduling
    if pickup_scheduled_date:
        # Pickup date was returned in AWB response
        frappe.db.set_value("Delivery Note", doc.name, "pickup_scheduled_date", pickup_scheduled_date)
        frappe.msgprint(f"AWB: {awb_code} assigned successfully. Pickup scheduled for: {pickup_scheduled_date}")
    else:
        # 3. Pickup Generation (when pickup date was not in AWB response)
        try:
            pickup_url = "https://apiv2.shiprocket.in/v1/external/courier/generate/pickup"
            # print("pickup_url===============",pickup_url)
            pickup_response = requests.post(pickup_url, headers=headers, json={"shipment_id": shipment_list})
            # print("pickup_response===============",pickup_response)
            pickup_json = pickup_response.json()

            if "message" in pickup_json and pickup_json.get("message") != "Pickup scheduled successfully":
                frappe.msgprint(f"Pickup scheduling message: {pickup_json.get('message')}")
            
            # Try different possible locations for pickup date
            pickup_date = None
            response_data = pickup_json.get("response", {})
            # print("response_data===============",response_data)
            
            if isinstance(response_data, dict):
                pickup_date = response_data.get("pickup_scheduled_date")
                # print("pickup_date===============",pickup_date)
                if not pickup_date:
                    pickup_date = response_data.get("pickup_date")
                    # print("pickup_date===============",pickup_date)
            
            # If still no date, check if pickup was scheduled successfully
            if pickup_date:
                frappe.db.set_value("Delivery Note", doc.name, "pickup_scheduled_date", pickup_date)
                frappe.msgprint(f"AWB: {awb_code} assigned successfully. Pickup scheduled for: {pickup_date}")
            else:
                # Even if date is not returned, AWB assignment was successful
                frappe.msgprint(f"AWB: {awb_code} assigned successfully. Pickup may have been scheduled - please check ShipRocket dashboard.")
                
        except Exception as e:
            # Don't fail the entire process if pickup scheduling fails
            frappe.msgprint(f"AWB: {awb_code} assigned successfully, but pickup scheduling encountered an issue: {str(e)}")

    # 5. Invoice Generation
    invoice_order_id = doc.shiprocket_order_id
    # invoice_url = "https://apiv2.shiprocket.in/v1/external/orders/print/invoice"
    invoice_url = frappe.db.get_single_value("Logistics Settings", "invoice_url")
    invoice_response = requests.post(invoice_url, headers=headers, json={"ids": [invoice_order_id]})
    invoice_json = invoice_response.json()
    invoice_pdf_url = invoice_json.get("invoice_url")
    if not invoice_pdf_url:
        frappe.throw("Invoice URL not found in response.")
    invoice_file_response = requests.get(invoice_pdf_url)
    if invoice_file_response.status_code != 200:
        frappe.throw(f"Could not fetch invoice PDF: {invoice_file_response.status_code}")
    invoice_pdf_b64 = base64.b64encode(invoice_file_response.content).decode()
    frappe.db.set_value("Delivery Note", doc.name, "shiprocket_invoice", invoice_pdf_b64)


    # 6. Label Generation
    # label_url = "https://apiv2.shiprocket.in/v1/external/courier/generate/label"
    label_url = frappe.db.get_single_value("Logistics Settings", "label_url")
    label_response = requests.post(label_url, headers=headers, json={"shipment_id": shipment_list})
    label_json = label_response.json()
    label_link = label_json.get("label_url")
    if not label_link:
        frappe.throw("Label URL not found in response.")
    label_file_response = requests.get(label_link)
    if label_file_response.status_code != 200:
        frappe.throw(f"Could not fetch label PDF: {label_file_response.status_code}")
    label_pdf_b64 = base64.b64encode(label_file_response.content).decode()
    frappe.db.set_value("Delivery Note", doc.name, "shiprocket_image", label_pdf_b64) 

    
    # 4. Manifest Generation
    manifest_url = "https://apiv2.shiprocket.in/v1/external/manifests/generate"
    manifest_response = requests.post(manifest_url, headers=headers, json={"shipment_id": shipment_list})
    manifest_json = manifest_response.json()

    # Check if there's an error message in the response
    if "message" in manifest_json:
        frappe.throw(f"Manifest Generation Error: {manifest_json.get('message')}")

    # Get manifest URL
    manifest_pdf_url = manifest_json.get("manifest_url")
    if not manifest_pdf_url:
        frappe.throw(f"Manifest URL not found. Full response: {manifest_json}")

    # Fetch and save manifest PDF
    manifest_file_response = requests.get(manifest_pdf_url)
    if manifest_file_response.status_code != 200:
        frappe.throw(f"Could not fetch manifest PDF: {manifest_file_response.status_code}")

    manifest_pdf_b64 = base64.b64encode(manifest_file_response.content).decode()
    frappe.db.set_value("Delivery Note", doc.name, "shiprocket_manifests", manifest_pdf_b64)
    frappe.db.commit()

    return {
        "awb_code": awb_code,
        "pickup_scheduled_date": pickup_scheduled_date,
        "label_url": label_link,
        "manifest_url": manifest_pdf_url,
        "invoice_url": invoice_pdf_url,
        "shiprocket_courier_name": best_courier,
        "tranporter_name": transporter_name,
        "lr_no" : invoice_no,
        "gst_transporter_id" : transporter_id
    }

# def adapter_repacked_serial_no(nj_serial_no):
#     try:
#         query="""
#             SELECT tot_sed.serial_no as adapter_serial_no
#             FROM `tabStock Entry Detail` AS sed
#             INNER JOIN `tabStock Entry Detail` AS tot_sed ON tot_sed.parent = sed.parent
#             INNER JOIN `tabStock Entry` AS stock_entry ON stock_entry.name = sed.parent
#             WHERE
#                 (sed.serial_no = %(serial_no)s OR 
#                     sed.serial_no LIKE CONCAT(%(serial_no)s, '\\n%%') OR 
#                     sed.serial_no LIKE CONCAT('%%\\n', %(serial_no)s) OR 
#                     sed.serial_no LIKE CONCAT('%%\\n', %(serial_no)s, '\\n%%')) AND
#                 stock_entry.purpose = 'Repack' AND 
#                 stock_entry.docstatus = 1 AND
#                 tot_sed.s_warehouse IS NOT NULL AND 
#                 tot_sed.item_group = 'Laptop Adaptors'
#             ORDER BY stock_entry.creation DESC
#             LIMIT 1
#         """
#         partlist_query="""
#           Select component_serial_no as adapter_serial_no from `tabSerial No Component` where parent=%s and item_group="Laptop Adaptors" order by idx desc limit 1;
#         """
#         if nj_serial_no is not None and nj_serial_no:

def adapter_repacked_serial_no(nj_serial_no):
    try:
        query="""
            SELECT tot_sed.serial_no as adapter_serial_no
            FROM `tabStock Entry Detail` AS sed
            INNER JOIN `tabStock Entry Detail` AS tot_sed ON tot_sed.parent = sed.parent
            INNER JOIN `tabStock Entry` AS stock_entry ON stock_entry.name = sed.parent
            WHERE
                (sed.serial_no = %(serial_no)s OR 
                    sed.serial_no LIKE CONCAT(%(serial_no)s, '\\n%%') OR 
                    sed.serial_no LIKE CONCAT('%%\\n', %(serial_no)s) OR 
                    sed.serial_no LIKE CONCAT('%%\\n', %(serial_no)s, '\\n%%')) AND
                stock_entry.purpose = 'Repack' AND 
                stock_entry.docstatus = 1 AND
                tot_sed.s_warehouse IS NOT NULL AND 
                tot_sed.item_group = 'Laptop Adaptors'
            ORDER BY stock_entry.creation DESC
            LIMIT 1
        """
        partlist_query="""
          Select component_serial_no as adapter_serial_no from `tabSerial No Component` where parent=%s and item_group="Laptop Adaptors" and component_serial_no <> "" order by item_group_idx desc limit 1;
        """
        if nj_serial_no is not None and nj_serial_no:

            data=frappe.db.sql(partlist_query, nj_serial_no, as_dict=1)
        
            if data is not None and data:  
                return data[0].get("adapter_serial_no","")
            else:
                data=frappe.db.sql(query, {"serial_no": nj_serial_no}, as_dict=1)
                if data is not None and data:
                    return data[0].get("adapter_serial_no","")
                else:
                   return "Empty"
                
    except Exception as e:
        log_error(traceback.format_exc(),"Error while getting adapter repacked serial no in for serial no "+nj_serial_no)
        return str(e)
    
@frappe.whitelist()
def sanitize_phone(phone):
    # Remove all non-digit characters
    digits = ''.join(filter(str.isdigit, phone or ""))
    # If phone has more than 10 digits, take the last 10
    if len(digits) > 10:
        digits = digits[-10:]
    # Return only if it's exactly 10 digits
    return digits if len(digits) == 10 else ""

@frappe.whitelist()
def allow_to_save(doc):
    try:
        if isinstance(doc,str):
            doc=json.loads(doc)
        is_return=frappe.db.get_value("Delivery Note",{"name":doc.get("name","")},"is_return")
        if is_return is not None and is_return==1:
            return "pass"
        execute=frappe.db.get_value("NJ Settings", {"parameter": "Adaptor_restriction_in_DN"}, "value")
        if execute is not None and execute=="0":
            return "pass"
        child_data=doc["packed_items"]
        dn_name=doc.get("name","")
        

        if not child_data:
            child_data=doc["items"]
        log_error(str(child_data),"child_data for dn name "+dn_name)
        for data in child_data:
            child_nj_serial_data=data.get("serial_no","")
            child_adapter_serial_no=data.get("adapter_serial_no","")
            nj_serial_nos=[]
            adapter_serial_nos=[]

            if  child_nj_serial_data:
                if '\n' in child_nj_serial_data:
                    nj_serial_nos=child_nj_serial_data.split('\n')
                else:
                    nj_serial_nos.append(child_nj_serial_data)
            else:
                continue

            if child_adapter_serial_no:
                if '\n' in child_adapter_serial_no:
                    adapter_serial_nos=child_adapter_serial_no.split('\n')
                else:
                    adapter_serial_nos.append(child_adapter_serial_no)

            serial_no_order=0
            log_error(str(adapter_serial_nos),"adapter_serial_nos for dn name "+dn_name)
            log_error(str(nj_serial_nos),"nj_serial_nos for dn name "+dn_name)
            
            for nj_serial_no in nj_serial_nos:
                item_group=frappe.db.get_value("Serial No",nj_serial_no,"item_group")
                if item_group and item_group=="Laptops" or item_group=="Chromebooks":
                    serial_no_order+=1
                    if not adapter_serial_nos:
                        return "Please enter Adapter Serial No"
                    else:
                        repacked_serial_no=adapter_repacked_serial_no(nj_serial_no)
                        try:
                          if repacked_serial_no!=str(adapter_serial_nos[serial_no_order-1]):
                            return "Repacked Adapter Serial No for Serial No: " +nj_serial_no+ " does not match with the scanned Serial No:"+ str(adapter_serial_nos[serial_no_order-1])
                        except IndexError:
                          return "NO Adapter Serial No Found for Serial No:" + nj_serial_no
                else:
                    continue
        return "pass"
    
    except Exception as e:
        log_error(traceback.format_exc(),"Error while saving delivery note "+dn_name)
        return str(e)


@frappe.whitelist()
def setting_dispatch_address(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)

    bg_address = frappe.db.get_value("NJ Settings", {"parameter": "bg_dispatch_address"}, "value")
    nj_address = frappe.db.get_value("NJ Settings", {"parameter": "jn_dispatch_address"}, "value")

    dispatch_location = None

    for item in doc.get("items", []):
        warehouse = item.get("warehouse")
        if not warehouse:
            continue

        location = frappe.db.get_value("Warehouse", warehouse, "location")
        if location == "BG":
            dispatch_location = bg_address
            break
        elif location == "JN":
            dispatch_location = nj_address
            break

    return dispatch_location
