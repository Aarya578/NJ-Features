import frappe , requests
import requests
import json
import base64
import frappe

import json
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
from nj_features.nj_features.api.shiprocket_api import get_auth_token,generate_awb,generate_label
SHOPIFY_URL = "https://newjaisa.myshopify.com/admin/api/2025-01/orders.json?name=" 
TOKEN = "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"
FULLFILMENT_ORDER_ID = "https://newjaisa.myshopify.com/admin/api/2025-01/orders/{shopify_order_id}/fulfillment_orders.json"
MAKE_FULLFILMENT = "https://newjaisa.myshopify.com/admin/api/2025-01/fulfillments.json"
import uuid
class CustomSalesOrder(SalesOrder):
    def on_submit(self):
        if self.naming_series and self.naming_series.startswith("SO-Snapmint-"):
            return
        # self.update_item_details()
        # self.ship_consignement_data()
        # self.cod_calculation()
        # self.fetching_tracking_details()
        # self.getting_shiprocket_order_details()
        raw_order_id = None
        if self.order_type!="Maintenance":
            if self.shopify_order_id:
                stripped_id = self.shopify_order_id.lstrip('#')
                if len(stripped_id) < 7:
                    raw_order_id = self.shopify_order_id

            if not raw_order_id and self.shopify_order_number:
                raw_order_id = self.shopify_order_number

            order_id = raw_order_id.lstrip('#') if raw_order_id else None

            if order_id:
                trigger_fulfillment(order_id)
    
@frappe.whitelist(allow_guest=True)
def trigger_fulfillment(order_id):
    try:
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": TOKEN
        }
        print("order_id-----26---in so-", order_id)
        # Step 1: Fetch Order Details
        url = f"{SHOPIFY_URL}{order_id}"
        response = requests.get(url, headers=headers)  
        data = response.json()

        if "orders" in data and data["orders"]:
            order = data["orders"][0]  
            order_id_shopify = order.get("id")

            if not order_id_shopify:
                frappe.throw("Shopify Order ID not found.")

            full_filment_status = order.get("fulfillment_status")

            if full_filment_status == "fulfilled":
                return {"status": "already_fulfilled"}

            # Step 2: Fetch Fulfillment Order
            fulfillment_order_url = FULLFILMENT_ORDER_ID.format(shopify_order_id=order_id_shopify)
            fulfillment_order_response = requests.get(fulfillment_order_url, headers=headers)
            fulfillment_order_data = fulfillment_order_response.json()

            if "fulfillment_orders" in fulfillment_order_data and fulfillment_order_data["fulfillment_orders"]:
                fulfillment_order_id = fulfillment_order_data["fulfillment_orders"][0]["id"]

                # Dummy Tracking Info
                tracking_number = str(uuid.uuid4()).replace('-', '')[:12].upper()
                tracking_url = "https://criticalog.com/tracking/"
                tracking_company = "Criticalog"

                fulfillment_payload = {
                    "fulfillment": {
                        "line_items_by_fulfillment_order": [
                            {
                                "fulfillment_order_id": fulfillment_order_id
                            }
                        ],
                        "tracking_info": {
                            "number": tracking_number,
                            "company": tracking_company,
                            "url": tracking_url
                        },
                        "notify_customer": False
                    }
                }

                fulfillment_response = requests.post(MAKE_FULLFILMENT, headers=headers, json=fulfillment_payload)
                fulfillment_data = fulfillment_response.json()
                # print("fulfillment_data----75-", fulfillment_data)
                if "fulfillment" in fulfillment_data:
                    fulfillment_id = fulfillment_data["fulfillment"]["id"]
                    return {
                            "status": "success", "fulfillment_id": fulfillment_id
                        }
                else:
                    frappe.msgprint("Fulfillment creation failed.")
            else:
                frappe.msgprint("Fulfillment Order not found.")
        else:
            frappe.msgprint("Order not found.")
    except Exception as e:
        frappe.throw(str(e))

@frappe.whitelist()
def update_item_details(self):
    print('------------------- DEBUG START -------------------')
    if isinstance(self, str):
        self = json.loads(self)    
    total_weight = 0
    height = length = breadth = None
    
    for item in self.get("items", []):
        
        # Debug: Check if item_code exists
        if not item.get("item_code"):
            continue
        item_group = frappe.db.get_value("Item", item.get("item_code"), "item_group")
        if not item_group:
            continue
        
        try:    
            group_doc = frappe.get_doc("Item Group", item_group)

            if group_doc.get("weight"):
               
                try:
                    weight_value = float(group_doc.weight)
                    total_weight += weight_value
                    
                except ValueError:
                   
                    frappe.log_error(
                        f"Invalid weight '{group_doc.weight}' in Item Group: {group_doc.name}",
                        "Weight Parsing Error"
                    )
            else:
                print(f"No weight field found in item group {group_doc.name}")          
            # Get dimensions from child table
            dimension_count = len(group_doc.get("dimensions", []))
           
            
            for dim in group_doc.get("dimensions", []):
                param = dim.parameter.strip().lower()
                value = dim.value
                print(f"Dimension: {param} = {value}")
                
                if "height" in param and not height:
                    height = value
                   
                elif "length" in param and not length:
                    length = value
                    
                elif "breadth" in param and not breadth:
                    breadth = value
                    
        except Exception as e:
            print(f"Error processing item group {item_group}: {str(e)}")
    
    # Return values to update in JavaScript
    result = {
        'weight': total_weight,
        'height': height,
        'length': length,
        'breadth': breadth
    }

    return result

@frappe.whitelist()
def send_consignement_data(doc):
    
    print("Triggered send_consignement_data...")
    try:
        # Convert string to Frappe dict
        doc = frappe._dict(json.loads(doc))
        print("doc:----------------------------", doc)
        sales_order_doc = frappe.get_doc("Sales Order", doc.name)
        # Validate shipping address and calculate cost of delivery
        if not doc.shipping_address_name:
            frappe.throw("Shipping address is not set.")
        
        # Get the pincode from the Address doctype
        pincode = frappe.db.get_value("Address", doc.shipping_address_name, "pincode")
        if not pincode:
            frappe.throw("Pincode not found in the shipping address.")
        
        # Check if Pincode exists in Pincode doctype
        pincode_doc = frappe.db.get_value("Pincode", {"pincode_no": pincode}, ["rate", "cod"], as_dict=True)
        if not pincode_doc:
            frappe.throw(f"Pincode {pincode} not found in Pincode master.")
        
        if not doc.weight:
            frappe.throw("Weight is not set in Sales Order.")
        
        # rate = pincode_doc.rate or 0
        # cod_charge = pincode_doc.cod or 0
        # weight = doc.weight
        
        # if doc.get('is_cod'):
        #     cost_of_delivery = (rate * weight) + cod_charge
        # else:
        #     cost_of_delivery = rate * weight
        # Convert string to float for arithmetic
        rate = float(pincode_doc.rate or 0)
        cod_charge = float(pincode_doc.cod or 0)
        weight = float(doc.weight or 0)

        if doc.get('is_cod'):
            cost_of_delivery = (rate * weight) + cod_charge
        else:
            cost_of_delivery = rate * weight

        # Update the document with calculated cost
        doc.cost_of_delivery = cost_of_delivery
        
        # Fetch addresses
        company_address = frappe.get_doc("Address", doc.company_address) if doc.company_address else None
        shipping_address = frappe.get_doc("Address", doc.shipping_address_name) if doc.shipping_address_name else None
        formatted_date = doc.delivery_date.strftime("%Y-%m-%d") if hasattr(doc.delivery_date, 'strftime') else str(doc.delivery_date)
        
        if sales_order_doc.is_cod == 1:
            PaymentType = "COD"
            print("PaymentType=======================",PaymentType)
            consignmentValue = float(sales_order_doc.total_outstanding) if sales_order_doc.total_outstanding else 0
            print("consignmentValue=======================",consignmentValue)
        else:
            PaymentType = "Prepaid"
            print("PaymentType=======================",PaymentType)
            consignmentValue = float(sales_order_doc.grand_total) if sales_order_doc.grand_total else 0
            print("consignmentValue=======================",consignmentValue)
        # Prepare header
        header = {
            "ClientCode": "207433",
            "OrderNo/InvoiceNo": doc.name,
            "Order/InvoiceDate": formatted_date,
            "SenderName": doc.company,
            "SenderAdd1": company_address.address_line1 or " ",
            "SenderAdd2": company_address.address_line2 or "",
            "SenderCity": company_address.city or "",
            "SenderState": company_address.state or "",
            "SenderCountry": company_address.country or "India",
            "SenderPin": company_address.pincode or "",
            # "SenderPin": "560100",
            "SenderMobile": company_address.phone or "",
            "SenderEmail": company_address.email_id or "",
            "ReceiverName": doc.customer_name or "",
            "ReceiverAdd1": shipping_address.address_line1 or "",
            "ReceiverAdd2": shipping_address.address_line2 or " ",
            "ReceiverCity": shipping_address.city or "",
            "ReceiverState": shipping_address.state or "",
            "ReceiverCountry": shipping_address.country or "India",
            # "ReceiverPin": "110002",
            "ReceiverPin": shipping_address.pincode or "",
            "ReceiverMobile": shipping_address.phone or "",
            "ConsignmentValue": consignmentValue,
            "NoQuantity": 1,
            "consignmentValue": consignmentValue,
            "Weight": f"{float(doc.length):.2f}",
            "TransitMode": doc.mode_of_transfer,
            "ProductMode": "Normal",
            "PaymentType": PaymentType,
            "Amount": str(doc.grand_total),
            "Need_CitImage": "1"
        }
        
        # Prepare items - FIX: Access items as a list, not a method
        items = []
        for row in doc.get('items', []):  # Use doc.get('items', []) instead of doc.items
            items.append({
                "Length": f"{float(doc.length):.2f}",
                "Breadth": f"{float(doc.breadth):.2f}",
                "Height": f"{float(doc.height):.2f}",
                "ProductCode": "AUTO",
                "ProductDescription": row.get("item_name"),
                "SplitPcs": f"{float(row.get('qty', 1)):.4f}",
                "IsPackaging": "0"
            })
        
        data = {
            "ResponseHeader": "yes",
            "Header": [header],
            "ItemsDetails": items
        }
        
        url = "https://testing.ecritica.co/eFreightLive/api/con_generation.php"
        headers = {"Content-Type": "application/json"}
        
        print("Sending data:", json.dumps(data, indent=2))
        
        response = requests.post(url, headers=headers, json=data)
        print(f"Response status: {response.status_code}")
        print(f"Response content: {response.text}")
        
        resp_json = response.json()
        
        if resp_json.get('code') == 1 and resp_json.get('status') == 200:
            awb_number = resp_json.get('data', {}).get('AWB Number') or resp_json.get('data', {}).get('AWBNumber')
            cit_data = resp_json.get('data', {}).get('CitImage') or resp_json.get('CitImage')
            
            # Update the Sales Order document with AWB number, CIT image, and cost of delivery
            sales_order = frappe.get_doc("Sales Order", doc.name)
            sales_order.awb_number = awb_number
            sales_order.cit_image = cit_data
            sales_order.cost_of_delivery = cost_of_delivery
            sales_order.save(ignore_permissions=True)
            
            frappe.msgprint(f"AWB Number generated successfully: {awb_number}")
            print({"awb_number  /n": awb_number, "cit_image/n": cit_data, "cost_of_delivery/n": cost_of_delivery})
            return {"awb_number": awb_number, "cit_image": cit_data, "cost_of_delivery": cost_of_delivery}
        else:
            frappe.throw(f"API returned error: {response.text}")
            
    except Exception as e:
        frappe.throw(f"Failed to send data to Criticalog API. Error: {str(e)}")

@frappe.whitelist()
def shiprocket_awb_number(doc):
    # print("======================== Inside shiprocket_awb_number")
    doc = frappe._dict(json.loads(doc))
    auth_token = get_auth_token().get("token")

    if not auth_token:
        frappe.throw("Authentication token could not be retrieved from Shiprocket.")

    # Consignment Data Creation (from first code)
    print("auth_token:----55", auth_token)
    print("Triggered send_consignement_data...")
    
    try:
        # Get the actual Sales Order document to access child table properly
        sales_order_doc = frappe.get_doc("Sales Order", doc.name)
        
        # Fetch addresses
        shipping_address = frappe.get_doc("Address", sales_order_doc.shipping_address_name) if sales_order_doc.shipping_address_name else None
        
        if not shipping_address:
            frappe.throw("Shipping address is required")

        formatted_date = sales_order_doc.transaction_date.strftime("%Y-%m-%d") if hasattr(sales_order_doc.transaction_date, 'strftime') else str(sales_order_doc.transaction_date)

        # Prepare order_items from child table - ShipRocket format
        order_items = []
        for row in sales_order_doc.items:
            item_code = row.item_code
            item_doc = frappe.get_doc("Item", item_code) if item_code else None
            item_group = item_doc.item_group if item_doc else ""

            item_data = {
                "name": (item_code[:50] if item_code else "")[:50],
                "sku": (item_code[:50] if item_code else "")[:50],
                "selling_price": str(row.amount),
                "discount": "",
                "tax": "",
                "hsn": ""
            }

            # Only include 'units' if item group is 'Laptops'
            if item_group == "Laptops":
                item_data["units"] = int(row.qty)

            order_items.append(item_data)

        # Determine payment method and subtotal based on is_cod condition
        if sales_order_doc.is_cod == 1:
            payment_method = "COD"
            sub_total = float(sales_order_doc.total_outstanding) if sales_order_doc.total_outstanding else 0
        else:
            payment_method = "Prepaid"
            sub_total = float(sales_order_doc.grand_total) if sales_order_doc.grand_total else 0

        # ShipRocket API payload structure
        data = {
            "order_id": sales_order_doc.name,
            "order_date": formatted_date,
            "pickup_location": "Primary",
            "comment": f"Order from {sales_order_doc.customer_name}",
            "billing_customer_name": sales_order_doc.customer_name or "",
            "billing_last_name": "",
            "billing_address": shipping_address.address_line1 if shipping_address.address_line1 else "",
            "billing_address_2": shipping_address.address_line2 if shipping_address.address_line2 else "",
            "billing_city": shipping_address.city if shipping_address.city else "",
            "billing_pincode": shipping_address.pincode if shipping_address.pincode else "",
            "billing_state": shipping_address.state if shipping_address.state else "",
            "billing_country": shipping_address.country if shipping_address.country else "India",
            "billing_email": shipping_address.email_id if shipping_address.email_id else "",
            "billing_phone": shipping_address.phone if shipping_address.phone else "",
            "shipping_is_billing": True,
            "shipping_customer_name": "",
            "shipping_last_name": "", 
            "order_items": order_items,
            "payment_method": payment_method,
            "sub_total": sub_total,
            "length": str(sales_order_doc.length),
            "breadth": str(sales_order_doc.breadth), 
            "height": str(sales_order_doc.height),
            "weight": str(sales_order_doc.weight)
        }

        url = "https://apiv2.shiprocket.in/v1/external/orders/create/adhoc"
        
        # Debug: Print token details
        print(f"Token length: {len(auth_token) if auth_token else 'None'}")
        print(f"Token starts with: {auth_token[:20] if auth_token and len(auth_token) > 20 else auth_token}")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token.strip()}"
        }

        print("Sending data:", json.dumps(data, indent=2))
        response = requests.post(url, headers=headers, json=data)
        print(f"Response status: {response.status_code}")
        print(f"Response content: {response.text}")

        if response.status_code == 200:
            try:
                resp_json = response.json()
                if resp_json.get('order_id'):
                    print("==========================================Order created successfully")
                    print(f"ShipRocket Order ID: {resp_json.get('order_id')}")
                    print(f"Shipment ID: {resp_json.get('shipment_id')}")

                    # Update document with ShipRocket IDs
                    frappe.db.set_value("Sales Order", doc.name, "shiprocket_order_id", resp_json.get('order_id'))
                    frappe.db.set_value("Sales Order", doc.name, "shiprocket_shipment_id", resp_json.get('shipment_id'))
                    
                    # Update local doc object for further processing
                    doc.shiprocket_order_id = resp_json.get('order_id')
                    doc.shiprocket_shipment_id = resp_json.get('shipment_id')
                    
                    print("self.shipRocket_order_id==================", doc.shiprocket_order_id)
                    print("self.shipRocket_shipment_id==================", doc.shiprocket_shipment_id)
                    
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

    # Now check if we have the required IDs after consignment creation
    if not doc.shiprocket_shipment_id:
        frappe.throw("Shipment ID not found on the document after consignment creation.")
    
    shipment_id = doc.shiprocket_shipment_id
    invoice_order_id = doc.shiprocket_order_id
    shipment_list = [int(shipment_id)]

    # 1. Service Availability
    service_url = "https://apiv2.shiprocket.in/v1/external/courier/serviceability"
    service_response = requests.get(service_url, headers=headers, json={"order_id": invoice_order_id})
    service_json = service_response.json()
    # print("service_json===========================", service_json)

    courier_data = service_json.get("data", {}).get("available_courier_companies", [])

    if not courier_data:
        frappe.throw("No courier companies found in serviceability response.")

    # Calculate total charges for each courier
    best_courier = None
    lowest_total = float('inf')

    for courier in courier_data:
        freight_charge = courier.get("freight_charge", 0) or 0
        cod_charges = courier.get("cod_charges", 0) or 0
        total = freight_charge + cod_charges

        # print(f"{courier['courier_name']} | Freight: {freight_charge}, COD: {cod_charges}, Total: {total}")

        if total < lowest_total:
            lowest_total = total
            best_courier = {
                "courier_name": courier.get("courier_name"),
                "courier_company_id": courier.get("courier_company_id"),
                "total_cost": total
            }

    if best_courier:
        print("Best Courier:====================12345", best_courier)
    else:
        print("No suitable courier found.")

    # 2. AWB Assignment
    awb_url = "https://apiv2.shiprocket.in/v1/external/courier/assign/awb"
    awb_response = requests.post(awb_url, headers=headers, json={
        "shipment_id": shipment_id,
        "courier_id": best_courier.get("courier_company_id")
    })
    print("awb_response===========================", awb_response)  
    print(f"AWB Response: {awb_response.status_code} - {awb_response.text}")

    awb_json = awb_response.json()
    response_data = awb_json.get("response", {})
    data = response_data.get("data", {})

    awb_code = None
    if isinstance(data, dict):
        awb_code = data.get("awb_code")
    else:
        # Show and stop if there's an error message instead of AWB data
        frappe.msgprint(f"AWB Assignment Failed: {data}")
        frappe.throw(f"ShipRocket response: {data}")

    if not awb_code:
        frappe.throw("AWB code not found in response.")

    frappe.db.set_value("Sales Order", doc.name, "awb_number", awb_code)

    # 3. Pickup Generation
    pickup_url = "https://apiv2.shiprocket.in/v1/external/courier/generate/pickup"
    pickup_response = requests.post(pickup_url, headers=headers, json={"shipment_id": shipment_list})
    print(f"Pickup Response: {pickup_response.status_code} - {pickup_response.text}")
    pickup_json = pickup_response.json()
    pickup_scheduled_date = pickup_json.get("response", {}).get("pickup_scheduled_date")
    if pickup_scheduled_date:
        frappe.db.set_value("Sales Order", doc.name, "pickup_scheduled_date", pickup_scheduled_date)
    else:
        frappe.throw("Pickup scheduled date not found in response.")

    # 4. Manifest Generation
    manifest_url = "https://apiv2.shiprocket.in/v1/external/manifests/generate"
    manifest_response = requests.post(manifest_url, headers=headers, json={"shipment_id": shipment_list})
    print(f"Manifest Response: {manifest_response.status_code} - {manifest_response.text}")
    manifest_json = manifest_response.json()
    manifest_pdf_url = manifest_json.get("manifest_url")
    if not manifest_pdf_url:
        frappe.throw("Manifest URL not found in response.")
    manifest_file_response = requests.get(manifest_pdf_url)
    if manifest_file_response.status_code != 200:
        frappe.throw(f"Could not fetch manifest PDF: {manifest_file_response.status_code}")
    manifest_pdf_b64 = base64.b64encode(manifest_file_response.content).decode()
    frappe.db.set_value("Sales Order", doc.name, "shiprocket_manifests", manifest_pdf_b64)

    # 5. Invoice Generation
    invoice_order_id = doc.shiprocket_order_id
    print("invoice_order_id====================",invoice_order_id)
    invoice_url = "https://apiv2.shiprocket.in/v1/external/orders/print/invoice"
    print("invoice_url",invoice_url)
    invoice_response = requests.post(invoice_url, headers=headers, json={"ids": [invoice_order_id]})
    print("invoice_response",invoice_response)
    print(f"Invoice Response: {invoice_response.status_code} - {invoice_response.text}")
    invoice_json = invoice_response.json()
    invoice_pdf_url = invoice_json.get("invoice_url")
    if not invoice_pdf_url:
        frappe.throw("Invoice URL not found in response.")
    invoice_file_response = requests.get(invoice_pdf_url)
    if invoice_file_response.status_code != 200:
        frappe.throw(f"Could not fetch invoice PDF: {invoice_file_response.status_code}")
    invoice_pdf_b64 = base64.b64encode(invoice_file_response.content).decode()
    frappe.db.set_value("Sales Order", doc.name, "shiprocket_invoice", invoice_pdf_b64)

    # 6. Label Generation
    label_url = "https://apiv2.shiprocket.in/v1/external/courier/generate/label"
    label_response = requests.post(label_url, headers=headers, json={"shipment_id": shipment_list})
    print(f"Label Response: {label_response.status_code} - {label_response.text}")
    label_json = label_response.json()
    label_link = label_json.get("label_url")
    if not label_link:
        frappe.throw("Label URL not found in response.")
    label_file_response = requests.get(label_link)
    if label_file_response.status_code != 200:
        frappe.throw(f"Could not fetch label PDF: {label_file_response.status_code}")
    label_pdf_b64 = base64.b64encode(label_file_response.content).decode()
    frappe.db.set_value("Sales Order", doc.name, "shiprocket_image", label_pdf_b64)

    frappe.db.commit()
    return {
        "awb_code": awb_code,
        "pickup_scheduled_date": pickup_scheduled_date,
        "label_url": label_link,
        "manifest_url": manifest_pdf_url,
        "invoice_url": invoice_pdf_url
    }

def calculate_dispatch_eta_for_sales_order():
    """Main function to calculate dispatch ETA for all open sales orders"""
    try:
        # Get department-wise min aging days (in descending order of department_sequence)
        departments = get_departments()
        
        # Get all open sales orders with their items (including product bundles)
        open_orders = get_open_sales_orders()
        
        # Dictionary to track max ETA per sales order
        so_eta_map = {}
        
        # Process each sales order item
        for order in open_orders:
            so_name = order.sales_order
            item_code = order.item_code
            ordered_qty = order.ordered_qty
            
            # Get delivered quantity
            delivered_qty = get_delivered_quantity(so_name, item_code)
            
            # Calculate pending quantity
            net_pending = ordered_qty - delivered_qty
            if net_pending <= 0:
                continue
                
            # Adjust serial allocations
            adjust_serial_allocations(so_name, item_code, net_pending)
            
            # Calculate ETA for this item
            item_eta = calculate_item_eta(item_code, net_pending, departments)
            
            # Track max ETA per sales order
            if so_name not in so_eta_map or item_eta > so_eta_map[so_name]:
                so_eta_map[so_name] = item_eta
        
        # Update ETA for each sales order
        update_sales_order_etas(so_eta_map)
        
    except Exception as e:
        frappe.log_error(f"Error in calculate_dispatch_eta_for_sales_order: {str(e)}")
        frappe.db.rollback()

def get_departments():
    """Get all departments with aging information"""
    return frappe.db.sql("""
        SELECT name, min_aging_days, department_sequence
        FROM `tabDepartment`
        WHERE department_sequence >= 1
        ORDER BY department_sequence DESC
    """, as_dict=True)

def get_open_sales_orders():
    """Get all open sales orders with pending items"""
    return frappe.db.sql("""
        -- 1. Direct stock items
            SELECT 
                so.name AS sales_order,
                soi.item_code,
                SUM(soi.qty) AS ordered_qty,
                so.transaction_date
            FROM 
                `tabSales Order` so
            INNER JOIN 
                `tabSales Order Item` soi ON soi.parent = so.name
            INNER JOIN 
                `tabItem` i ON soi.item_code = i.item_code
            WHERE
                so.docstatus = 1
                AND so.per_delivered < 100
                AND so.status NOT IN ('Completed', 'Closed', 'Cancelled')
                AND i.is_stock_item = 1
                AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
            GROUP BY 
                so.name, soi.item_code

            UNION ALL

            -- 2. Stock items from Product Bundles (component items)
            SELECT 
                so.name AS sales_order,
                pbi.item_code,
                SUM(pbi.qty * soi.qty) AS ordered_qty,
                so.transaction_date
            FROM 
                `tabSales Order` so
            INNER JOIN 
                `tabSales Order Item` soi ON soi.parent = so.name
            INNER JOIN 
                `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code
            INNER JOIN 
                `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
            INNER JOIN 
                `tabItem` i ON pbi.item_code = i.item_code
            WHERE
                so.docstatus = 1
                AND so.per_delivered < 100
                AND so.status NOT IN ('Completed', 'Closed', 'Cancelled')
                AND soi.item_code IN (
                    SELECT item_code FROM `tabItem` WHERE is_stock_item = 0
                )
                AND i.is_stock_item = 1
                AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
            GROUP BY 
                so.name, pbi.item_code;
    """, as_dict=True)

def get_delivered_quantity(so_name, item_code):
    """Get delivered quantity for a sales order item"""
    result = frappe.db.sql("""
        SELECT SUM(dni.qty) 
        FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dni.parent = dn.name
        WHERE dni.against_sales_order = %s
            AND dni.item_code = %s
            AND dn.docstatus = 1
    """, (so_name, item_code))
    return result[0][0] if result and result[0][0] else 0

def adjust_serial_allocations(so_name, item_code, net_pending):
    """Adjust serial allocations based on pending quantity"""
    # Get already allocated count
    allocated_count = frappe.db.sql("""
        SELECT COUNT(*) 
        FROM `tabSerial No` 
        WHERE 
            reserved_sales_order = %s 
            AND item_code = %s
            AND NOT EXISTS (
                SELECT 1 
                FROM `tabDelivery Note Item` 
                WHERE serial_no = `tabSerial No`.name 
                    AND docstatus = 1
            )
    """, (so_name, item_code))[0][0] or 0

    # Calculate net to allocate
    to_allocate = net_pending - allocated_count

    # Unassign excess serial numbers
    if to_allocate < 0:
        unassign_serials(so_name, item_code, abs(to_allocate))
    
    # Allocate new serial numbers
    elif to_allocate > 0:
        assign_serials(so_name, item_code, to_allocate)

def assign_serials(so_name, item_code, to_allocate):
    """Assign new serial numbers to sales order"""
    available_serials = frappe.db.sql_list("""
        SELECT name 
        FROM `tabSerial No` 
        WHERE 
            item_code = %s 
            AND (reserved_sales_order IS NULL OR reserved_sales_order = '')
            AND warehouse != 'WIP Warehouse'
            AND NOT EXISTS (
                SELECT 1 
                FROM `tabDelivery Note Item` 
                WHERE serial_no = `tabSerial No`.name 
                    AND docstatus = 1
            )
        ORDER BY creation ASC 
        LIMIT %s
    """, (item_code, int(to_allocate)))

    print("item code: ", item_code)
    print("available serials: ", available_serials)
    
    if available_serials:
        for serial in available_serials:
            frappe.db.set_value("Serial No", serial, "reserved_sales_order", so_name)
        frappe.db.commit()

def unassign_serials(so_name, item_code, excess_qty):
    """Unassign excess serial numbers"""
    excess_serials = frappe.db.sql_list("""
        SELECT name 
        FROM `tabSerial No` 
        WHERE 
            reserved_sales_order = %s 
            AND item_code = %s
            AND NOT EXISTS (
                SELECT 1 
                FROM `tabDelivery Note Item` 
                WHERE serial_no = `tabSerial No`.name 
                    AND docstatus = 1
            )
        ORDER BY creation ASC 
        LIMIT %s
    """, (so_name, item_code, int(excess_qty)))
    
    if excess_serials:
        frappe.db.sql("""
            UPDATE `tabSerial No`
            SET sales_order = NULL, reserved_sales_order = NULL
            WHERE name IN %(serials)s
        """, {"serials": excess_serials})
        frappe.db.commit()


def calculate_item_eta(item_code, required_qty, departments):
    """Calculate ETA for a specific item quantity"""
    accumulated_days = 0
    remaining_qty = required_qty
    
    for dept in departments:
        accumulated_days += dept.min_aging_days

        # Get warehouses in this department
        warehouses = frappe.db.sql_list("""
            SELECT name FROM `tabWarehouse` WHERE department = %s
        """, dept.name)

        if not warehouses:
            continue

        # Generate placeholders for warehouses
        placeholders = ', '.join(['%s'] * len(warehouses))
        
        # Compose the SQL query with dynamic placeholders
        query = f"""
            SELECT COUNT(*)
            FROM `tabSerial No`
            WHERE 
                item_code = %s
                AND warehouse IN ({placeholders})
                AND (reserved_sales_order IS NULL OR reserved_sales_order = '')
                AND NOT EXISTS (
                    SELECT 1 
                    FROM `tabDelivery Note Item` 
                    WHERE serial_no = `tabSerial No`.name 
                        AND docstatus = 1
                )
        """

        # Combine item_code and warehouses into a single params list
        params = [item_code] + warehouses

        # Execute the query
        available_count = frappe.db.sql(query, params)[0][0] or 0

        # Check if enough stock in this department
        if available_count >= remaining_qty:
            return accumulated_days
        else:
            remaining_qty -= available_count

    # Return total accumulated days if not enough stock
    return accumulated_days

def update_sales_order_etas(so_eta_map):
    """Update ETA for dispatch on sales orders using direct SQL UPDATE"""
    for so_name, eta in so_eta_map.items():
        frappe.db.sql("""
            UPDATE `tabSales Order`
            SET eta_for_dispatch = %s
            WHERE name = %s
        """, (eta, so_name))
    frappe.db.commit()