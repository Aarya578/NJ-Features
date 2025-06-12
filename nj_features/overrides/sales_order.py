import frappe , requests
import requests
import json
import base64
import frappe
import time
import datetime
from datetime import datetime
from frappe.utils import getdate
import json
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
from nj_features.nj_features.api.shiprocket_api import get_auth_token,generate_awb,generate_label
logger = frappe.logger('SOLogger', allow_site=True, file_count=100)
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
        # self.total_item_group_sum()
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


    def total_item_group_sum(self):
    # Step 1: Get item groups from NJ Settings
        item_group_value = frappe.db.get_value(
            "NJ Settings", 
            {"parameter": "Item Group Validation"}, 
            "value"
        )
        print("item_group_value===================", item_group_value)
        
        if not item_group_value:
            return

        # Convert comma-separated value to list
        allowed_item_groups = [group.strip() for group in item_group_value.split(",")]
        print("allowed_item_groups==================", allowed_item_groups)

        # Step 2: Loop through items in Sales Order and calculate total qty
        total_qty = 0
        for item in self.items:
            item_group = frappe.db.get_value("Item", item.item_code, "item_group")
            if item_group in allowed_item_groups:
                total_qty += item.qty

        # Step 3: Update a custom field `item_group_qty` (you need to add this field in Sales Order)
        self.item_group_qty = total_qty
        print("self.item_group_qty=================", self.item_group_qty)
        self.save(ignore_permissions=True)    

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
    from datetime import datetime
    import json
    print('------------------- DEBUG START -------------------')

    if isinstance(self, str):
        self = json.loads(self)

    total_weight = 0
    height = length = breadth = None

    # Step 1: Get allowed item groups from NJ Settings
    item_group_value = frappe.db.get_value(
        "NJ Settings",
        {"parameter": "Item Group Validation"},
        "value"
    )

    allowed_item_groups = []
    if item_group_value:
        allowed_item_groups = [group.strip() for group in item_group_value.split(",")]

    print(f"Allowed item groups: {allowed_item_groups}")

    # Step 2: Count how many matching item group rows exist
    matching_rows = []
    for row in self.get("items", []):
        item_code = row.get("item_code")
        if not item_code:
            continue

        item_group = frappe.db.get_value("Item", item_code, "item_group")
        if item_group in allowed_item_groups:
            matching_rows.append(row)

    print(f"Matching rows count: {len(matching_rows)}")

    # Step 3: If more than one matching row, skip fetching weight/dimensions
    if len(matching_rows) != 1:
        print("Skipping weight and dimension fetch due to multiple matching item group rows.")
        return {
            'weight': 0,
            'height': None,
            'length': None,
            'breadth': None
        }

    # Step 4: Only one row matched — process it
    item = matching_rows[0]
    if item.get("qty") != 1:
        print("Skipping because qty is not 1.")
        return {
            'weight': 0,
            'height': None,
            'length': None,
            'breadth': None
        }

    item_code = item.get("item_code")
    item_group = frappe.db.get_value("Item", item_code, "item_group")
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
            print(f"No weight found in item group {group_doc.name}")

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

    return {
        'weight': total_weight,
        'height': height,
        'length': length,
        'breadth': breadth
    }

# @frappe.whitelist()
# def send_consignement_data(doc):
#     start_time = time.time()
#     print("Triggered send_consignement_data...")
#     try:
#         # Convert string to Frappe dict
#         doc = frappe._dict(json.loads(doc))
#         sales_order_doc = frappe.get_doc("Sales Order", doc.name)
#         # Validate shipping address and calculate cost of delivery
#         if not doc.shipping_address_name:
#             frappe.throw("Shipping address is not set.")
        
#         # Get the pincode from the Address doctype
#         pincode = frappe.db.get_value("Address", doc.shipping_address_name, "pincode")
#         print("pincode===========================", pincode)
#         if not pincode:
#             frappe.throw("Pincode not found in the shipping address.")
        
#         # Check if Pincode exists in Pincode doctype
#         pincode_doc = frappe.db.get_value("Pincode", {"pincode_no": pincode}, ["rate", "cod"], as_dict=True)
#         print("pincode_doc===========================", pincode_doc)
#         if not pincode_doc:
#             frappe.throw(f"Pincode {pincode} not found in Pincode master.")
        
#         if not doc.weight:
#             frappe.throw("Weight is not set in Sales Order.")
        
#         # Convert string to float for arithmetic
#         rate = float(pincode_doc.rate or 0)
#         print("rate===========================", rate)
#         cod_charge = float(pincode_doc.cod or 0)
#         print("cod_charge===========================", cod_charge)
#         weight = float(doc.weight or 0)
#         print("weight===========================", weight)

#         if doc.get('is_cod'):
#             cost_of_delivery = (rate * weight) + cod_charge
#             print("cost_of_delivery===========================", cost_of_delivery)
#         else:
#             cost_of_delivery = rate * weight
#             print("cost_of_delivery===========================", cost_of_delivery)

#         # Update the document with calculated cost
#         doc.cost_of_delivery = cost_of_delivery
        
#         # Fetch addresses
#         company_address = frappe.get_doc("Address", doc.company_address) if doc.company_address else None
#         shipping_address = frappe.get_doc("Address", doc.shipping_address_name) if doc.shipping_address_name else None
#         formatted_date = doc.delivery_date.strftime("%Y-%m-%d") if hasattr(doc.delivery_date, 'strftime') else str(doc.delivery_date)
        
#         if sales_order_doc.is_cod == 1:
#             PaymentType = "COD"
           
#             consignmentValue = float(sales_order_doc.total_outstanding) if sales_order_doc.total_outstanding else 0
           
#         else:
#             PaymentType = "Prepaid"
           
#             consignmentValue = float(sales_order_doc.grand_total) if sales_order_doc.grand_total else 0
           
#         # Prepare header
#         header = {
#             "ClientCode": "207433",
#             "OrderNo/InvoiceNo": doc.name,
#             "Order/InvoiceDate": formatted_date,
#             "SenderName": doc.company,
#             "SenderAdd1": company_address.address_line1 or " ",
#             "SenderAdd2": company_address.address_line2 or "",
#             "SenderCity": company_address.city or "",
#             "SenderState": company_address.state or "",
#             "SenderCountry": company_address.country or "India",
#             "SenderPin": company_address.pincode or "",
#             "SenderMobile": company_address.phone or "",
#             "SenderEmail": company_address.email_id or "",
#             "ReceiverName": doc.customer_name or "",
#             "ReceiverAdd1": shipping_address.address_line1 or "",
#             "ReceiverAdd2": shipping_address.address_line2 or " ",
#             "ReceiverCity": shipping_address.city or "",
#             "ReceiverState": shipping_address.state or "",
#             "ReceiverCountry": shipping_address.country or "India",
#             "ReceiverPin": shipping_address.pincode or "",
#             "ReceiverMobile": shipping_address.phone or "",
#             "ConsignmentValue": consignmentValue,
#             "NoQuantity": 1,
#             "consignmentValue": consignmentValue,
#             "Weight": f"{float(doc.length):.2f}",
#             "TransitMode": doc.mode_of_transfer,
#             "ProductMode": "Normal",
#             "PaymentType": PaymentType,
#             "Amount": str(doc.grand_total),
#             "Need_CitImage": "1"
#         }
        
#         # Prepare items
#         items = []
#         for row in doc.get('items', []):
#             items.append({
#                 "Length": f"{float(doc.length):.2f}",
#                 "Breadth": f"{float(doc.breadth):.2f}",
#                 "Height": f"{float(doc.height):.2f}",
#                 "ProductCode": "AUTO",
#                 "ProductDescription": row.get("item_name"),
#                 "SplitPcs": f"{float(row.get('qty', 1)):.4f}",
#                 "IsPackaging": "0"
#             })
        
#         data = {
#             "ResponseHeader": "yes",
#             "Header": [header],
#             "ItemsDetails": items
#         }
        
#         url = "https://testing.ecritica.co/eFreightLive/api/con_generation.php"
#         # url = "https://www.ecritica.co/eFreightLive/api/con_generation.php"
#         headers = {"Content-Type": "application/json"}
        
#         print("Sending data:", json.dumps(data, indent=2))
        
#         response = requests.post(url, headers=headers, json=data)
       
#         resp_json = response.json()
        
#         if resp_json.get('code') == 1 and resp_json.get('status') == 200:
#             awb_number = resp_json.get('data', {}).get('AWB Number') or resp_json.get('data', {}).get('AWBNumber')
#             cit_data = resp_json.get('data', {}).get('CitImage') or resp_json.get('CitImage')
            
#             # Update the Sales Order document with AWB number, CIT image, cost of delivery, and courier service
#             sales_order = frappe.get_doc("Sales Order", doc.name)
#             sales_order.awb_number = awb_number
#             sales_order.cit_image = cit_data
#             sales_order.cost_of_delivery = cost_of_delivery
#             sales_order.courier_service = "CriticaLog"  # Set courier service
            
#             # Use db_set to update without triggering validations or changing docstatus
#             sales_order.db_set('awb_number', awb_number)
#             sales_order.db_set('cit_image', cit_data)
#             sales_order.db_set('cost_of_delivery', cost_of_delivery)
#             sales_order.db_set('courier_service', 'CriticaLog')
            
#             frappe.msgprint(f"AWB Number generated successfully: {awb_number}")
            
#             return {"awb_number": awb_number, "cit_image": cit_data, "cost_of_delivery": cost_of_delivery}
            
#         else:
#             frappe.throw(f"API returned error: {response.text}")
#         end_time = time.time()  # End timer
#         execution_time = round(end_time - start_time, 4)
#         print(f"Execution Time=========================: {execution_time} seconds")        
#     except Exception as e:
#         frappe.throw(f"Failed to send data to Criticalog API. Error: {str(e)}")
#     finally:
#         end_time = time.time()
#         execution_time = round(end_time - start_time, 4)
#         print(f"Execution Time =========================: {execution_time} seconds")
#         logger.info(f"Execution Time: =================={execution_time} seconds")    




@frappe.whitelist()
def send_consignement_data(doc):
    start_time = time.time()
    print("Triggered send_consignement_data...")
    try:
        # Convert string to Frappe dict
        doc = frappe._dict(json.loads(doc))
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
        
        # Convert string to float for arithmetic
        rate = float(pincode_doc.rate or 0)
        cod_charge = float(pincode_doc.cod or 0)
        weight = float(doc.weight or 0)

        if doc.get('is_cod'):
            cost_of_delivery = (rate * weight) + cod_charge
        else:
            cost_of_delivery = rate * weight

        ship_rocket_settings = frappe.get_doc("Ship Rocket Settings")
        cod_charges_table = ship_rocket_settings.get("cod_charges", [])
            
            # Find the charges_value from COD Charges child table
        charges_value = None
        for cod_charge_row in cod_charges_table:
            charges_value = cod_charge_row.charges_value  # Access as field attribute
            if charges_value:
                break
        
        if charges_value:
            
            # Extract numeric value from percentage string (e.g., "8%" -> 8)
            numeric_charges_value = float(charges_value.replace('%', '').strip())
            
            # Calculate percentage of grand_total
            grand_total = float(doc.get("grand_total", 0) or 0)
            cod_percentage_amount = round((numeric_charges_value / 100) * grand_total, 2)
            
            # Compare COD percentage amount with total_cost
            if cod_percentage_amount < cost_of_delivery:
                frappe.throw(f"COD validation failed: COD charges courier total cost ({cost_of_delivery:.2f}) is greater than ({numeric_charges_value:.2f}% of grand total = {cod_percentage_amount:.2f})")    

        # Update the document with calculated cost
        doc.cost_of_delivery = cost_of_delivery
        
        # Fetch addresses
        company_address = frappe.get_doc("Address", doc.company_address) if doc.company_address else None
        shipping_address = frappe.get_doc("Address", doc.shipping_address_name) if doc.shipping_address_name else None
        # formatted_date = doc.delivery_date.strftime("%Y-%m-%d") if hasattr(doc.delivery_date, 'strftime') else str(doc.delivery_date)
        formatted_date = datetime.today().strftime("%Y-%m-%d")
        print("formatted_date======================", formatted_date)
        
        if sales_order_doc.is_cod == 1:
            PaymentType = "COD"
            consignmentValue = float(sales_order_doc.total_outstanding) if sales_order_doc.total_outstanding else 0
        else:
            PaymentType = "Prepaid"
            consignmentValue = float(sales_order_doc.grand_total) if sales_order_doc.grand_total else 0
        
        # Get allowed item groups from NJ Settings
        item_group_value = frappe.db.get_value(
            "NJ Settings",
            {"parameter": "Item Group Validation"},
            "value"
        )
        allowed_item_groups = []
        if item_group_value:
            allowed_item_groups = [group.strip() for group in item_group_value.split(",")]
        
        print(f"Allowed item groups: {allowed_item_groups}")
        
        # Calculate total quantity for allowed items only
        total_quantity = 0
        items = []
        for row in doc.get('items', []):
            # Get item group for current item
            item_group = frappe.db.get_value("Item", row.get("item_code"), "item_group")
            print(f"Item: {row.get('item_name')}, Item Group: {item_group}")
            
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
        
      
        # Prepare header with correct total quantity
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
            "SenderMobile": company_address.phone or "",
            "SenderEmail": company_address.email_id or "",
            "ReceiverName": doc.customer_name or "",
            "ReceiverAdd1": shipping_address.address_line1 or "",
            "ReceiverAdd2": shipping_address.address_line2 or " ",
            "ReceiverCity": shipping_address.city or "",
            "ReceiverState": shipping_address.state or "",
            "ReceiverCountry": shipping_address.country or "India",
            "ReceiverPin": shipping_address.pincode or "",
            "ReceiverMobile": shipping_address.phone or "",
            "ConsignmentValue": consignmentValue,
            "NoQuantity": int(total_quantity),  # Fixed: Use total quantity of all items
            "consignmentValue": consignmentValue,
            "Weight": f"{weight:.2f}",  # Fixed: Use doc.weight instead of doc.length
            "TransitMode": doc.mode_of_transfer,
            "ProductMode": "Normal",
            "PaymentType": PaymentType,
            "Amount": str(doc.grand_total),
            "Need_CitImage": "1"
        }
        
        # Add validation to ensure quantities match
        calculated_total = sum(float(item["SplitPcs"]) for item in items)
        if abs(calculated_total - total_quantity) > 0.001:  # Allow for small floating point differences
            frappe.throw(f"Quantity mismatch: Total quantity ({total_quantity}) doesn't match sum of split quantities ({calculated_total})")
        
        data = {
            "ResponseHeader": "yes",
            "Header": [header],
            "ItemsDetails": items
        }
        
        url = "https://testing.ecritica.co/eFreightLive/api/con_generation.php"
        # url = "https://www.ecritica.co/eFreightLive/api/con_generation.php"
        headers = {"Content-Type": "application/json"}
        
        print("Sending data:", json.dumps(data, indent=2))
        print(f"Total quantity: {total_quantity}, Sum of split quantities: {calculated_total}")
        
        response = requests.post(url, headers=headers, json=data)
       
        resp_json = response.json()
        
        if resp_json.get('code') == 1 and resp_json.get('status') == 200:
            awb_number = resp_json.get('data', {}).get('AWB Number') or resp_json.get('data', {}).get('AWBNumber')
            cit_data = resp_json.get('data', {}).get('CitImage') or resp_json.get('CitImage')
            
            # Update the Sales Order document with AWB number, CIT image, cost of delivery, and courier service
            sales_order = frappe.get_doc("Sales Order", doc.name)
            sales_order.awb_number = awb_number
            sales_order.cit_image = cit_data
            sales_order.cost_of_delivery = cost_of_delivery
            sales_order.courier_service = "CriticaLog"  # Set courier service
            
            # Use db_set to update without triggering validations or changing docstatus
            sales_order.db_set('awb_number', awb_number)
            sales_order.db_set('cit_image', cit_data)
            sales_order.db_set('cost_of_delivery', cost_of_delivery)
            sales_order.db_set('courier_service', 'CriticaLog')
            
            frappe.msgprint(f"AWB Number generated successfully: {awb_number}")
            
            return {"awb_number": awb_number, "cit_image": cit_data, "cost_of_delivery": cost_of_delivery}
            
        else:
            frappe.throw(f"API returned error: {response.text}")
         
    except Exception as e:
        frappe.throw(f"Failed to send data to Criticalog API. Error: {str(e)}")
 





# @frappe.whitelist()
# def shiprocket_awb_number(doc):

#     # start_time = time.time()
#     """Create a ShipRocket consignment, assign an AWB, and generate a manifest and invoice."""
#     # print("======================== Inside shiprocket_awb_number")
#     doc = frappe._dict(json.loads(doc))
#     auth_token = get_auth_token().get("token")

#     if not auth_token:
#         frappe.throw("Authentication token could not be retrieved from Shiprocket.")

    
#     try:
#         # Get the actual Sales Order document to access child table properly
#         sales_order = frappe.get_doc("Sales Order", doc.name)
#         sales_order_doc = frappe.get_doc("Sales Order", doc.name)
        
#         # Fetch addresses
#         shipping_address = frappe.get_doc("Address", sales_order_doc.shipping_address_name) if sales_order_doc.shipping_address_name else None
        
#         if not shipping_address:
#             frappe.throw("Shipping address is required")

#         formatted_date = sales_order_doc.transaction_date.strftime("%Y-%m-%d") if hasattr(sales_order_doc.transaction_date, 'strftime') else str(sales_order_doc.transaction_date)
#         # Fetch addresses

#         # Prepare order_items from child table - ShipRocket format
#         order_items = []
#         for row in sales_order_doc.items:
#             order_items.append({
#                 "name": (row.item_code[:50] if row.item_code else "")[:50], 
#                 "sku": (row.item_code[:50] if row.item_code else "")[:50],   
#                 "units": int(row.qty),                      
#                 "selling_price": str(row.rate * 1.18),    
#                 "discount": "",
#                 "tax": 18.0,
#                 "hsn": ""
#             })

#         # Determine payment method and subtotal based on is_cod condition
#         if sales_order_doc.is_cod == 1:
#             payment_method = "COD"
#             sub_total = float(sales_order_doc.total_outstanding) if sales_order_doc.total_outstanding else 0
#         else:
#             payment_method = "Prepaid"
#             sub_total = float(sales_order_doc.grand_total) if sales_order_doc.grand_total else 0

#         # ShipRocket API payload structure
#         data = {
#             "order_id": sales_order_doc.name,
#             "order_date": formatted_date,
#             "pickup_location": "Office",
#             "comment": f"Order from {sales_order_doc.customer_name}",
#             "billing_customer_name": sales_order_doc.customer_name or "",
#             "billing_last_name": "",
#             "billing_address": shipping_address.address_line1 if shipping_address.address_line1 else "",
#             "billing_address_2": shipping_address.address_line2 if shipping_address.address_line2 else "",
#             "billing_city": shipping_address.city if shipping_address.city else "",
#             "billing_pincode": shipping_address.pincode if shipping_address.pincode else "",
#             "billing_state": shipping_address.state if shipping_address.state else "",
#             "billing_country": shipping_address.country if shipping_address.country else "India",
#             "billing_email": shipping_address.email_id if shipping_address.email_id else "",
#             "billing_phone": shipping_address.phone if shipping_address.phone else "",
#             "shipping_is_billing": True,
#             "shipping_customer_name": "",
#             "shipping_last_name": "", 
#             "order_items": order_items,
#             "payment_method": payment_method,
#             "sub_total": sub_total,
#             "length": str(sales_order_doc.length),
#             "breadth": str(sales_order_doc.breadth), 
#             "height": str(sales_order_doc.height),
#             "weight": str(sales_order_doc.weight)
#         }

#         url = "https://apiv2.shiprocket.in/v1/external/orders/create/adhoc"
#         headers = {
#             "Content-Type": "application/json",
#             "Authorization": f"Bearer {auth_token.strip()}"
#         }
#         response = requests.post(url, headers=headers, json=data)
        
#         if response.status_code == 200:
#             try:
#                 resp_json = response.json()
#                 if resp_json.get('order_id'):
#                     # Update document with ShipRocket IDs
#                     frappe.db.set_value("Sales Order", doc.name, "shiprocket_order_id", resp_json.get('order_id'))
#                     frappe.db.set_value("Sales Order", doc.name, "shiprocket_shipment_id", resp_json.get('shipment_id'))
                    
#                     # Update local doc object for further processing
#                     doc.shiprocket_order_id = resp_json.get('order_id')
#                     doc.shiprocket_shipment_id = resp_json.get('shipment_id')
                    
#                     frappe.db.commit()
#                 else:
#                     frappe.throw(f"Order creation failed: {response.text}")
#             except ValueError as json_err:
#                 frappe.throw(f"Could not parse API response: {response.text}")

#         else:
#             # Handle different error codes
#             if response.status_code == 401:
#                 frappe.throw("Authentication failed. Please check your ShipRocket credentials.")
#             elif response.status_code == 422:
#                 frappe.throw(f"Validation error: {response.text}")
#             else:
#                 frappe.throw(f"API request failed with status {response.status_code}: {response.text}")
                
#     except Exception as e:
#         frappe.log_error(f"Consignment API Failed for {doc.name}: {str(e)}", frappe.get_traceback())
#         frappe.throw(f"Failed to send data to ShipRocket API. Error: {str(e)}")

#     if not doc.shiprocket_shipment_id:
#         frappe.throw("Shipment ID not found on the document after consignment creation.")
    
#     shipment_id = doc.shiprocket_shipment_id
#     invoice_order_id = doc.shiprocket_order_id
#     shipment_list = [int(shipment_id)]

#     # 1. Service Availability
#     service_url = "https://apiv2.shiprocket.in/v1/external/courier/serviceability"
#     service_response = requests.get(service_url, headers=headers, json={"order_id": invoice_order_id})
#     service_json = service_response.json()
#     # print("service_json===========================", service_json)

#     courier_data = service_json.get("data", {}).get("available_courier_companies", [])

#     if not courier_data:
#         frappe.throw("No courier companies found in serviceability response.")

#     # Calculate total charges for each courier
#     best_courier = None
#     lowest_total = float('inf')

#     for courier in courier_data:
#         try:
#             rating = float(courier.get("rating", 0) or 0)
            
#             if rating <= 4:
#                 continue  # skip couriers with rating 4 or below
                
#             freight_charge = float(courier.get("freight_charge", 0) or 0)
#             cod_charges = float(courier.get("cod_charges", 0) or 0)
#             total = freight_charge + cod_charges
            
#             if total < lowest_total:
#                 lowest_total = total
#                 best_courier = {
#                     "courier_name": courier.get("courier_name"),
#                     "courier_company_id": courier.get("courier_company_id"),
#                     "total_cost": total,
#                     "rating": rating
#                 }
#                 print("best_courier=============================", best_courier)
                
#         except (ValueError, TypeError) as e:
#             print(f"Skipping courier due to invalid data: {e}")
#             continue

#     # if best_courier:
#     #     print("Best Courier (Rating > 4):", best_courier)
#     # else:
#     #     print("No suitable courier found with rating above 4.")

#    # Calculate total item charges
#     total_item_charges = 0
#     for item in doc.get("items", []):
#         # Check if item_code exists
#         if not item.get("item_code"):
#             continue

#         # Get item group
#         item_group = frappe.db.get_value("Item", item.get("item_code"), "item_group")       
#         # Get the item group document
#         group_doc = frappe.get_doc("Item Group", item_group)
#         # Get item_charges (float)
#         item_charges = group_doc.get("item_charges")

#         if item_charges and item.get("qty"):
#             item_total_charge = float(item_charges) * float(item.get("qty"))
#             total_item_charges += item_total_charge
#             print(f"item_charges: {item_charges}, qty: {item.get('qty')}, item total: {item_total_charge}")
#         else:
#             print("Missing item_charges or quantity for item:", item.get("item_code"))

#     print(f"Total item charges: {total_item_charges}")
#     print(f"Best courier total cost: {best_courier.get('total_cost') if best_courier else 'N/A'}")

#     # Check if courier total cost exceeds item charges total
#     if best_courier and best_courier.get('total_cost', 0) > total_item_charges:
#         frappe.throw(f"Cannot generate AWB number because courier '{best_courier.get('courier_name')}' total cost ({best_courier.get('total_cost')}) is more than item charges total ({total_item_charges})")




#     #2. AWB Assignment
#     awb_url = "https://apiv2.shiprocket.in/v1/external/courier/assign/awb"
#     awb_response = requests.post(awb_url, headers=headers, json={
#         "shipment_id": shipment_id,
#         "courier_id": best_courier.get("courier_company_id")
#     })
#     awb_json = awb_response.json()
#     # logger.info(f"order awb_json ========313========================{awb_json}")

#     # ✅ If there's an error message, show and stop
#     if "message" in awb_json:
#         # frappe.msgprint(f"AWB Assignment Failed: {awb_json.get('message')}")
#         frappe.throw(f"ShipRocket response: {awb_json.get('message')}")

#     response_data = awb_json.get("response", {})
#     data = response_data.get("data", {})

#     awb_code = None
#     pickup_scheduled_date = None

#     if isinstance(data, dict):
#         awb_code = data.get("awb_code")
#         # logger.info(f"order awb_code ========313========================{awb_code}")
#         pickup_scheduled_date = data.get("pickup_scheduled_date")
#         # logger.info(f"order pickup_scheduled_date ========313========================{pickup_scheduled_date}")
#     else:
#         frappe.msgprint("AWB Assignment Failed: Invalid response format.")
#         frappe.throw(f"ShipRocket response: {data}")

#     # ✅ Validate AWB code
#     if not awb_code:
#         frappe.throw("AWB code not found in response.")

#     # ✅ Save AWB Code to Sales Order
#     frappe.db.set_value("Sales Order", doc.name, "awb_number", awb_code)

#     # ✅ Save pickup date if available
#     skip_pickup_generation = False
#     if pickup_scheduled_date:
#         frappe.db.set_value("Sales Order", doc.name, "pickup_scheduled_date", pickup_scheduled_date)
#         skip_pickup_generation = True

#     # 3. Pickup Generation (only if pickup date was not found in AWB response)
#     if not skip_pickup_generation:
#         pickup_url = "https://apiv2.shiprocket.in/v1/external/courier/generate/pickup"
#         pickup_response = requests.post(pickup_url, headers=headers, json={"shipment_id": shipment_list})
#         # print(f"Pickup Response: {pickup_response.status_code} - {pickup_response.text}")
#         pickup_json = pickup_response.json()
#         pickup_scheduled_date = pickup_json.get("response", {}).get("pickup_scheduled_date")
        
#         if pickup_scheduled_date:
#             frappe.db.set_value("Sales Order", doc.name, "pickup_scheduled_date", pickup_scheduled_date)
#         else:
#             frappe.throw("Pickup scheduled date not found in response.")

#     # 4. Manifest Generation
#     manifest_url = "https://apiv2.shiprocket.in/v1/external/manifests/generate"
#     manifest_response = requests.post(manifest_url, headers=headers, json={"shipment_id": shipment_list})
#     # print(f"Manifest Response: {manifest_response.status_code} - {manifest_response.text}")
#     manifest_json = manifest_response.json()
#     manifest_pdf_url = manifest_json.get("manifest_url")
#     if not manifest_pdf_url:
#         frappe.throw("Manifest URL not found in response.")
#     manifest_file_response = requests.get(manifest_pdf_url)
#     if manifest_file_response.status_code != 200:
#         frappe.throw(f"Could not fetch manifest PDF: {manifest_file_response.status_code}")
#     manifest_pdf_b64 = base64.b64encode(manifest_file_response.content).decode()
#     frappe.db.set_value("Sales Order", doc.name, "shiprocket_manifests", manifest_pdf_b64)

#     # 5. Invoice Generation
#     invoice_order_id = doc.shiprocket_order_id
#     invoice_url = "https://apiv2.shiprocket.in/v1/external/orders/print/invoice"
#     invoice_response = requests.post(invoice_url, headers=headers, json={"ids": [invoice_order_id]})
#     invoice_json = invoice_response.json()
#     invoice_pdf_url = invoice_json.get("invoice_url")
#     if not invoice_pdf_url:
#         frappe.throw("Invoice URL not found in response.")
#     invoice_file_response = requests.get(invoice_pdf_url)
#     if invoice_file_response.status_code != 200:
#         frappe.throw(f"Could not fetch invoice PDF: {invoice_file_response.status_code}")
#     invoice_pdf_b64 = base64.b64encode(invoice_file_response.content).decode()
#     frappe.db.set_value("Sales Order", doc.name, "shiprocket_invoice", invoice_pdf_b64)

#     # 6. Label Generation
#     label_url = "https://apiv2.shiprocket.in/v1/external/courier/generate/label"
#     label_response = requests.post(label_url, headers=headers, json={"shipment_id": shipment_list})
#     # print(f"Label Response: {label_response.status_code} - {label_response.text}")
#     label_json = label_response.json()
#     label_link = label_json.get("label_url")
#     if not label_link:
#         frappe.throw("Label URL not found in response.")
#     label_file_response = requests.get(label_link)
#     if label_file_response.status_code != 200:
#         frappe.throw(f"Could not fetch label PDF: {label_file_response.status_code}")
#     label_pdf_b64 = base64.b64encode(label_file_response.content).decode()
#     frappe.db.set_value("Sales Order", doc.name, "shiprocket_image", label_pdf_b64)

#     frappe.db.set_value("Sales Order", doc.name, "courier_service", "Shiprocket Manifest")
#    # Commit all Sales Order updates before handling Delivery Charges
#     frappe.db.commit()

#     #Get the updated Sales Order document to ensure we have all the latest data
#     updated_sales_order = frappe.get_doc("Sales Order", doc.name)

#     # ✅ Handle Delivery Charges DocType
#     delivery_charges = frappe.get_all(
#         "Delivery Charges", filters={"sales_order": doc.name}, limit=1
#     )
    
#     if delivery_charges:
#         # Update existing Delivery Charges record
#         frappe.db.set_value(
#             "Delivery Charges",
#             delivery_charges[0]["name"],
#             {
#                 "sales_order": doc.name,
#                 "awb_number": awb_code,  # Use the variable directly
#                 "pickup_scheduled_date": pickup_scheduled_date,  # Use the variable directly
#                 "shiprocket_manifests": updated_sales_order.shiprocket_manifests,
#                 "shiprocket_invoice": updated_sales_order.shiprocket_invoice,
#                 "shiprocket_image": updated_sales_order.shiprocket_image
#             }
#         )
#     else:
#         # Create a new Delivery Charges record if not found
#         dc = frappe.new_doc("Delivery Charges")
#         dc.sales_order = doc.name
#         dc.awb_number = awb_code  # Use the variable directly instead of doc.awb_number
#         dc.pickup_scheduled_date = pickup_scheduled_date  # Use the variable directly
#         dc.shiprocket_manifests = updated_sales_order.shiprocket_manifests
#         dc.shiprocket_invoice = updated_sales_order.shiprocket_invoice  
#         dc.shiprocket_image = updated_sales_order.shiprocket_image
#         dc.insert(ignore_permissions=True)
#         # print("Created new delivery_charges================", dc.name)

#     # end_time = time.time()  # End timer
#     # execution_time = round(end_time - start_time, 4)
#     # print(f"Execution Time=========================: {execution_time} seconds")
#     # logger.info(f"Execution Time=========================: {execution_time} seconds")
#     # Final commit
#     frappe.db.commit()

#     return {
#         "awb_code": awb_code,
#         "pickup_scheduled_date": pickup_scheduled_date,
#         "label_url": label_link,
#         "manifest_url": manifest_pdf_url,
#         "invoice_url": invoice_pdf_url
#     }

    
@frappe.whitelist()
def shiprocket_awb_number(doc):

    # start_time = time.time()
    """Create a ShipRocket consignment, assign an AWB, and generate a manifest and invoice."""
    # print("======================== Inside shiprocket_awb_number")
    doc = frappe._dict(json.loads(doc))
    auth_token = get_auth_token().get("token")

    if not auth_token:
        frappe.throw("Authentication token could not be retrieved from Shiprocket.")

    
    try:
        # Get the actual Sales Order document to access child table properly
        sales_order = frappe.get_doc("Sales Order", doc.name)
        sales_order_doc = frappe.get_doc("Sales Order", doc.name)
        
        # Fetch addresses
        shipping_address = frappe.get_doc("Address", sales_order_doc.shipping_address_name) if sales_order_doc.shipping_address_name else None
        
        if not shipping_address:
            frappe.throw("Shipping address is required")

        formatted_date = datetime.today().strftime("%Y-%m-%d")

        # formatted_date = sales_order_doc.transaction_date.strftime("%Y-%m-%d") if hasattr(sales_order_doc.transaction_date, 'strftime') else str(sales_order_doc.transaction_date)
        # Fetch addresses

        # Prepare order_items from child table - ShipRocket format
        order_items = []
        for row in sales_order_doc.items:
            order_items.append({
                "name": (row.item_code[:50] if row.item_code else "")[:50], 
                "sku": (row.item_code[:50] if row.item_code else "")[:50],   
                "units": int(row.qty),                      
                "selling_price": str(row.rate * 1.18),    
                "discount": "",
                "tax": 18.0,
                "hsn": ""
            })

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
            "pickup_location": "Office",
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
                    frappe.db.set_value("Sales Order", doc.name, "shiprocket_order_id", resp_json.get('order_id'))
                    frappe.db.set_value("Sales Order", doc.name, "shiprocket_shipment_id", resp_json.get('shipment_id'))
                    
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
        try:
            rating = float(courier.get("rating", 0) or 0)
            
            if rating <= 4:
                continue  # skip couriers with rating 4 or below
                
            freight_charge = float(courier.get("freight_charge", 0) or 0)
            cod_charges = float(courier.get("cod_charges", 0) or 0)
            total = freight_charge + cod_charges
            
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
                print("best_courier=============================", best_courier)
                
        except (ValueError, TypeError) as e:
            print(f"Skipping courier due to invalid data: {e}")
            continue

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
        if item_charges and item.get("qty"):
            item_total_charge = float(item_charges) * float(item.get("qty"))
            total_item_charges += item_total_charge
            print(f"item_charges: {item_charges}, qty: {item.get('qty')}, item total: {item_total_charge}")
        else:
            print("Missing item_charges or quantity for item:", item.get("item_code"))

    print(f"Total item charges: {total_item_charges}")
    print(f"Best courier total cost: {best_courier.get('total_cost') if best_courier else 'N/A'}")
    # frappe.db.set_value("Sales Order",doc.name,"courier_service", best_courier.get("courier_name"))
 
    # COD Validation - Check if is_cod is enabled
    if doc.get("is_cod") == 1:  # Check if COD is enabled
        print("COD is enabled, performing COD validation...")
        
        if best_courier:
            # Calculate total cost with weight
            freight_charge = best_courier.get('freight_charge', 0)
            cod_charges = best_courier.get('cod_charges', 0)
            doc_weight = doc.get('weight', 0) or 0
            
            total_cost = (freight_charge * float(doc_weight)) + cod_charges
            print(f"Calculated total cost with weight: {total_cost}")
            
            # Fetch COD charges from Ship Rocket Settings
            ship_rocket_settings = frappe.get_doc("Ship Rocket Settings")
            cod_charges_table = ship_rocket_settings.get("cod_charges", [])
            
            # Find the charges_value from COD Charges child table
            charges_value = None
            for cod_charge_row in cod_charges_table:
                charges_value = cod_charge_row.charges_value  # Access as field attribute
                if charges_value:
                    break
            
            if charges_value:
                print(f"COD charges value found: {charges_value}")
                
                # Extract numeric value from percentage string (e.g., "8%" -> 8)
                numeric_charges_value = float(charges_value.replace('%', '').strip())
                print(f"Numeric charges value: {numeric_charges_value}")
                
                # Calculate percentage of grand_total
                # grand_total = doc.get("grand_total", 0) or 0
                # cod_percentage_amount = (numeric_charges_value / 100) * float(grand_total)
                grand_total = float(doc.get("grand_total", 0) or 0)
                cod_percentage_amount = round((numeric_charges_value / 100) * grand_total, 2)

                print(f"Grand total: {grand_total}, COD percentage amount ({numeric_charges_value}%): {cod_percentage_amount}")
                
                # Compare COD percentage amount with total_cost
                if cod_percentage_amount < total_cost:
                    # frappe.throw(f"Grand total: {grand_total:.2f}, COD percentage amount ({numeric_charges_value}%): {cod_percentage_amount:.2f}")

                    frappe.throw(f"COD validation failed: COD charges courier total cost ({total_cost:.2f}) is greater than ({numeric_charges_value:.2f}% of grand total = {cod_percentage_amount:.2f})")
                
            else:
                frappe.throw("No COD charges value found in Ship Rocket Settings")
    else:
        print("COD is not enabled, skipping COD validation...")

    # Check if courier total cost exceeds item charges total
    if best_courier and best_courier.get('total_cost', 0) > total_item_charges:
        frappe.throw(f"Cannot generate AWB number because courier '{best_courier.get('courier_name')}' total cost ({best_courier.get('total_cost')}) is more than item charges total ({total_item_charges})")
    frappe.db.set_value("Sales Order", doc.name, "shiprocket_courier_name", best_courier.get("courier_name"))
    # frappe.db.commit()
    #2. AWB Assignment
    awb_url = "https://apiv2.shiprocket.in/v1/external/courier/assign/awb"
    awb_response = requests.post(awb_url, headers=headers, json={
        "shipment_id": shipment_id,
        "courier_id": best_courier.get("courier_company_id")
    })
    awb_json = awb_response.json()
    # logger.info(f"order awb_json ========313========================{awb_json}")

    # ✅ If there's an error message, show and stop
    if "message" in awb_json:
        # frappe.msgprint(f"AWB Assignment Failed: {awb_json.get('message')}")
        frappe.throw(f"ShipRocket response: {awb_json.get('message')}")

    response_data = awb_json.get("response", {})
    data = response_data.get("data", {})

    awb_code = None
    pickup_scheduled_date = None

    if isinstance(data, dict):
        awb_code = data.get("awb_code")
        # logger.info(f"order awb_code ========313========================{awb_code}")
        pickup_scheduled_date = data.get("pickup_scheduled_date")
        # logger.info(f"order pickup_scheduled_date ========313========================{pickup_scheduled_date}")
    else:
        frappe.msgprint("AWB Assignment Failed: Invalid response format.")
        frappe.throw(f"ShipRocket response: {data}")

    # ✅ Validate AWB code
    if not awb_code:
        frappe.throw("AWB code not found in response.")

    # ✅ Save AWB Code to Sales Order
    frappe.db.set_value("Sales Order", doc.name, "awb_number", awb_code)

    # ✅ Save pickup date if available
    skip_pickup_generation = False
    if pickup_scheduled_date:
        frappe.db.set_value("Sales Order", doc.name, "pickup_scheduled_date", pickup_scheduled_date)
        skip_pickup_generation = True

    # 3. Pickup Generation (only if pickup date was not found in AWB response)
    if not skip_pickup_generation:
        pickup_url = "https://apiv2.shiprocket.in/v1/external/courier/generate/pickup"
        pickup_response = requests.post(pickup_url, headers=headers, json={"shipment_id": shipment_list})
        # print(f"Pickup Response: {pickup_response.status_code} - {pickup_response.text}")
        pickup_json = pickup_response.json()
        pickup_scheduled_date = pickup_json.get("response", {}).get("pickup_scheduled_date")
        
        if pickup_scheduled_date:
            frappe.db.set_value("Sales Order", doc.name, "pickup_scheduled_date", pickup_scheduled_date)
        else:
            frappe.throw("Pickup scheduled date not found in response.")

    # 4. Manifest Generation
    manifest_url = "https://apiv2.shiprocket.in/v1/external/manifests/generate"
    manifest_response = requests.post(manifest_url, headers=headers, json={"shipment_id": shipment_list})
    # print(f"Manifest Response: {manifest_response.status_code} - {manifest_response.text}")
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
    invoice_url = "https://apiv2.shiprocket.in/v1/external/orders/print/invoice"
    invoice_response = requests.post(invoice_url, headers=headers, json={"ids": [invoice_order_id]})
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
    # print(f"Label Response: {label_response.status_code} - {label_response.text}")
    label_json = label_response.json()
    label_link = label_json.get("label_url")
    if not label_link:
        frappe.throw("Label URL not found in response.")
    label_file_response = requests.get(label_link)
    if label_file_response.status_code != 200:
        frappe.throw(f"Could not fetch label PDF: {label_file_response.status_code}")
    label_pdf_b64 = base64.b64encode(label_file_response.content).decode()
    frappe.db.set_value("Sales Order", doc.name, "shiprocket_image", label_pdf_b64)

    # frappe.db.set_value("Sales Order", doc.name, "courier_service", "Shiprocket Manifest")
   # Commit all Sales Order updates before handling Delivery Charges
    frappe.db.commit()

    #Get the updated Sales Order document to ensure we have all the latest data
    updated_sales_order = frappe.get_doc("Sales Order", doc.name)

    # ✅ Handle Delivery Charges DocType
    delivery_charges = frappe.get_all(
        "Delivery Charges", filters={"sales_order": doc.name}, limit=1
    )
    
    if delivery_charges:
        # Update existing Delivery Charges record
        frappe.db.set_value(
            "Delivery Charges",
            delivery_charges[0]["name"],
            {
                "sales_order": doc.name,
                "awb_number": awb_code,  # Use the variable directly
                "pickup_scheduled_date": pickup_scheduled_date,  # Use the variable directly
                "shiprocket_manifests": updated_sales_order.shiprocket_manifests,
                "shiprocket_invoice": updated_sales_order.shiprocket_invoice,
                "shiprocket_image": updated_sales_order.shiprocket_image
            }
        )
    else:
        # Create a new Delivery Charges record if not found
        dc = frappe.new_doc("Delivery Charges")
        dc.sales_order = doc.name
        dc.awb_number = awb_code  # Use the variable directly instead of doc.awb_number
        dc.pickup_scheduled_date = pickup_scheduled_date  # Use the variable directly
        dc.shiprocket_manifests = updated_sales_order.shiprocket_manifests
        dc.shiprocket_invoice = updated_sales_order.shiprocket_invoice  
        dc.shiprocket_image = updated_sales_order.shiprocket_image
        dc.insert(ignore_permissions=True)
        # print("Created new delivery_charges================", dc.name)

    # end_time = time.time()  # End timer
    # execution_time = round(end_time - start_time, 4)
    # print(f"Execution Time=========================: {execution_time} seconds")
    # logger.info(f"Execution Time=========================: {execution_time} seconds")
    # Final commit
    frappe.db.commit()

    return {
        "awb_code": awb_code,
        "pickup_scheduled_date": pickup_scheduled_date,
        "label_url": label_link,
        "manifest_url": manifest_pdf_url,
        "invoice_url": invoice_pdf_url,
        "shiprocket_courier_name": best_courier
    }



def calculate_dispatch_eta_for_sales_order():
    """Main function to calculate dispatch ETA for all open sales orders"""
    try:
        # Get department-wise min aging days (in descending order of department_sequence)
        departments = get_departments()
        
        # Get all open sales orders with their items (including product bundles)
        open_orders = get_open_sales_orders()

        print("open Order", open_orders)
        print("len", len(open_orders))
        
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
                
            # Adjust serial allocations and get unallocated quantity
            unallocated_qty = adjust_serial_allocations(so_name, item_code, net_pending, departments)
            
            # Calculate ETA for this item (only if unallocated quantity exists)
            if unallocated_qty > 0:
                item_eta = calculate_item_eta(item_code, unallocated_qty, departments)
            else:
                item_eta = 0  # Fully allocated, no waiting time
            
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
    """Get all open sales orders with pending items (serialized items only)"""
    return frappe.db.sql("""
        -- 1. Direct stock items
            SELECT 
                so.name AS sales_order,
                soi.item_code,
                SUM(soi.qty) AS ordered_qty
            FROM 
                `tabSales Order` so
            INNER JOIN 
                `tabSales Order Item` soi ON soi.parent = so.name
            INNER JOIN 
                `tabItem` i ON soi.item_code = i.item_code
            WHERE
                so.docstatus = 1
                AND so.status NOT IN ('Completed', 'Closed', 'Cancelled', 'To Deliver')
                AND i.is_stock_item = 1
                AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
                AND so.creation >= DATE_SUB(CURDATE(), INTERVAL 20 DAY)
            GROUP BY 
                so.name, soi.item_code

            UNION ALL

            SELECT 
                so.name AS sales_order,
                pbi.item_code,
                pbi.qty * soi.qty AS ordered_qty
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
            INNER JOIN 
                `tabItem` soi_item ON soi.item_code = soi_item.item_code
            WHERE
                so.docstatus = 1
                AND so.status NOT IN ('Completed', 'Closed', 'Cancelled', 'To Deliver')
                AND soi_item.is_stock_item = 0
                AND i.is_stock_item = 1
                AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
                AND so.creation >= DATE_SUB(CURDATE(), INTERVAL 20 DAY)
            ORDER BY 
                sales_order DESC
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

def adjust_serial_allocations(so_name, item_code, net_pending, departments):
    """Adjust serial allocations and return unallocated quantity"""
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
    unallocated_qty = 0

    # Unassign excess serial numbers
    if to_allocate < 0:
        unassign_serials(so_name, item_code, abs(to_allocate))
    
    # Allocate new serial numbers and track unallocated quantity
    elif to_allocate > 0:
        allocated_in_this_call = assign_serials(so_name, item_code, to_allocate, departments)
        print("\n\n\nallocated_in_this_call", allocated_in_this_call)
        print("so_name ------------- 1293", so_name)
        print("item_code ------------- 1293", item_code)
        unallocated_qty = to_allocate - allocated_in_this_call
        print("unallocated_qty", unallocated_qty)

        if unallocated_qty > 0:
            print("unallocated_qty ------------- 1293", unallocated_qty)
            create_unallocated_log(so_name, item_code, unallocated_qty, "Insufficient available stock")
    
    return unallocated_qty

def assign_serials(so_name, item_code, to_allocate, departments):
    allocated_count = 0

    for dept in departments:
        print("\n\n======================== Inside assign_serials ==============================")
        print("dept ------------- 1293", dept)
        if allocated_count >= to_allocate:
            break

        # Get warehouses in this department
        warehouses = frappe.db.sql_list("""
            SELECT name FROM `tabWarehouse` WHERE department = %s
        """, dept.name)

        if not warehouses:
            continue

        remaining = int(to_allocate - allocated_count)

        # Build SQL-safe string: 'Warehouse A','Warehouse B',...
        warehouses_str = ', '.join(f"'{w}'" for w in warehouses)

        query = f"""
            SELECT name 
            FROM `tabSerial No` 
            WHERE 
                item_code = '{item_code}'
                AND warehouse IN ({warehouses_str})
                AND (reserved_sales_order IS NULL OR reserved_sales_order = '')
                AND NOT EXISTS (
                    SELECT 1 
                    FROM `tabDelivery Note Item` 
                    WHERE serial_no = `tabSerial No`.name 
                        AND docstatus = 1
                )
            ORDER BY creation ASC 
            LIMIT {remaining}
        """

        available_serials = frappe.db.sql(query, as_dict=1)
        print("available_serials:----55", available_serials)
        count_in_dept = len(available_serials)

        for serial in available_serials:
            print("serial:----55", serial)
            serial_name = serial.get("name")
            frappe.db.set_value("Serial No", serial_name, "reserved_sales_order", so_name)

            # Calculate aging days
            so_creation = frappe.get_value("Sales Order", so_name, "creation")
            aging_days = (getdate() - getdate(so_creation)).days if so_creation else 0

            # Append aging detail
            serial_doc = frappe.get_doc("Serial No", serial_name)
            serial_doc.append("sales_order_details", {
                "sales_order": so_name,
                "aging_days": aging_days
            })
            serial_doc.save()

        allocated_count += count_in_dept

    return allocated_count


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

def create_unallocated_log(sales_order, item_code, pending_qty, reason):
    print("======================== Inside create_unallocated_log ==============================")
    print("sales_order:----55", sales_order)
    print("item_code:----55", item_code)
    print("pending_qty:----55", pending_qty)
    print("reason:----55", reason)
    """Create a log entry in Unallocated Sales Order Item"""
    doc = frappe.new_doc("Unallocated Sales Order Item")
    doc.sales_order = sales_order
    doc.item_code = item_code
    doc.pending_qty = pending_qty
    doc.reason = reason
    doc.posting_date = frappe.utils.nowdate()
    doc.insert(ignore_permissions=True)
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