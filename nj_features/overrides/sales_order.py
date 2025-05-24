import frappe , requests
import requests
import json
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
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
        # self.send_consignement_data()
        self.cod_calculation()
        # self.fetching_tracking_details()
        raw_order_id = None
        if self.order_type!="Maintenance":
            if self.shopify_order_id:
                stripped_id = self.shopify_order_id.lstrip('#')
                if len(stripped_id) < 7:
                    raw_order_id = self.shopify_order_id

            # if not raw_order_id and self.order_id:
            #     raw_order_id = self.order_id

            if not raw_order_id and self.shopify_order_number:
                raw_order_id = self.shopify_order_number

            order_id = raw_order_id.lstrip('#') if raw_order_id else None

            if order_id:
                trigger_fulfillment(order_id)


    # def send_consignement_data(self):
    #     print("Triggered send_consignement_data...")
    #     try:
    #         # Fetch addresses
    #         company_address = frappe.get_doc("Address", self.company_address) if self.company_address else None
    #         shipping_address = frappe.get_doc("Address", self.shipping_address_name) if self.shipping_address_name else None

    #         formatted_date = self.transaction_date.strftime("%Y-%m-%d") if hasattr(self.transaction_date, 'strftime') else str(self.transaction_date)

    #         # Prepare header with consistent structure matching Postman example
    #         header = {
    #             "ClientCode": "207433",
    #             "OrderNo/InvoiceNo": self.name,
    #             # "Order/InvoiceDate": "2025-05-16",
    #             "Order/InvoiceDate": self.transaction_date,
    #             # Sender
    #             "SenderName": self.company,
    #             "SenderAdd1": company_address.address_line1 if company_address.address_line1 else " ",
    #             "SenderAdd2": company_address.address_line2 if company_address.address_line2 else "",
    #             "SenderCity": company_address.city if company_address.city else "",
    #             "SenderState": company_address.state if company_address.state else "",
    #             "SenderCountry": company_address.country if company_address.country else "India",
    #             # "SenderPin": company_address.pincode if company_address else "",
    #             "SenderPin": "560100",
    #             "SenderMobile": company_address.phone or "",
    #             "SenderEmail": company_address.email_id or "",

    #             # Receiver
    #             "ReceiverName": self.customer_name or "",
    #             "ReceiverAdd1": shipping_address.address_line1 if shipping_address.address_line1 else "",
    #             "ReceiverAdd2": shipping_address.address_line2 if shipping_address.address_line2 else " ",
    #             "ReceiverCity": shipping_address.city if shipping_address.city else "",
    #             "ReceiverState": shipping_address.state if shipping_address.state else "",
    #             "ReceiverCountry": shipping_address.country if shipping_address.country else "India",
    #             # "ReceiverPin": shipping_address.pincode if shipping_address else "",
    #             "ReceiverPin": "110002",
    #             "ReceiverMobile": shipping_address.phone or "",

    #             "ConsignmentValue": str(self.grand_total),
    #             "NoQuantity": 1,
    #             "consignmentValue": str(self.grand_total),  # Added this field to match Postman
    #             "Weight": str(self.weight),
    #             "TransitMode": self.mode_of_transfer,
    #             "ProductMode": "Normal",
    #             "PaymentType": "COD",
    #             "Amount": str(self.grand_total),
    #             "Need_CitImage": "1"
    #         }

    #         # Prepare items with consistent formatting
    #         items = []
    #         for row in self.items:
    #             items.append({
    #                 "Length": f"{float(self.length):.2f}",
    #                 "Breadth": f"{float(self.breadth):.2f}",
    #                 "Height": f"{float(self.height):.2f}",
    #                 "ProductCode": "AUTO",
    #                 "ProductDescription": row.item_name,
    #                 "SplitPcs": f"{float(row.qty):.4f}",
    #                 "IsPackaging": "0"
    #             })

    #         data = {
    #             "ResponseHeader": "yes",
    #             "Header": [header],
    #             "ItemsDetails": items
    #         }

    #         url = "https://testing.ecritica.co/eFreightLive/api/con_generation.php"
    #         headers = {"Content-Type": "application/json"}

    #         print("Sending data:", json.dumps(data, indent=2))  # Print the actual payload
    #         response = requests.post(url, headers=headers, json=data)
    #         print(f"Response status: {response.status_code}")
    #         print(f"Response content: {response.text}")

    #         try:
    #             resp_json = response.json()
    #             if resp_json.get('code') == 1 and resp_json.get('status') == 200:
    #                 awb_number = resp_json.get('data', {}).get('AWB Number') or resp_json.get('data', {}).get('AWBNumber')
    #                 print(f"AWB Number generated: {awb_number}")
    #                 # Look for cit_data in different possible locations in the response
    #                 cit_data = resp_json.get('data', {}).get('CitImage') or resp_json.get('CitImage')
    #                 frappe.msgprint(f"AWB Number generated: {awb_number}")
    #                 # Store the AWB number in your document if needed
    #                 self.awb_number = awb_number
    #                 self.cit_image = cit_data
    #                 self.db_update()
    #             else:
    #                 frappe.throw(f"API returned error: {response.text}")
    #         except Exception as json_err:
    #             frappe.throw(f"Could not parse API response: {response.text}")
    #     except Exception as e:
    #         # Show the actual error for debugging
    #         # frappe.log_error(f"Consignment API Failed for {self.name}", frappe.get_traceback())
    #         frappe.throw(f"Failed to send data to Criticalog API. Error: {str(e)}")



    def cod_calculation(self):
        if not self.shipping_address_name:
            frappe.throw("Shipping address is not set.")

        # Get the pincode from the Address doctype
        pincode = frappe.db.get_value("Address", self.shipping_address_name, "pincode")
        if not pincode:
            frappe.throw("Pincode not found in the shipping address.")

        # Check if Pincode exists in Pincode doctype
        pincode_doc = frappe.db.get_value("Pincode", {"pincode_no": pincode}, ["rate", "cod"], as_dict=True)
        if not pincode_doc:
            frappe.throw(f"Pincode {pincode} not found in Pincode master.")

        if not self.weight:
            frappe.throw("Weight is not set in Sales Order.")

        rate = pincode_doc.rate or 0
        cod_charge = pincode_doc.cod or 0
        weight = self.weight

        if self.is_cod:
            cost_of_delivery = (rate * weight) + cod_charge
        else:
            cost_of_delivery = rate * weight

        self.cost_of_delivery = cost_of_delivery
        self.db_update()


    
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

def calculate_dispatch_eta_for_sales_order():
    departments = frappe.db.sql("""
        SELECT 
            name, min_aging_days
        FROM
            `tabDepartment`
        WHERE
            department_sequence >= 1
        ORDER BY 
            department_sequence DESC
    """, as_dict=1)

    open_sales_orders = frappe.db.sql("""
        SELECT 
            so.name AS sales_order,
            soi.item_code
        FROM 
            `tabSales Order` so
        INNER JOIN 
            `tabSales Order Item` soi ON soi.parent = so.name
        INNER JOIN
            `tabItem` i ON soi.item_code = i.item_code
        WHERE
            (so.per_delivered < 100 OR so.per_billed < 100)
            AND so.docstatus = 1
            AND so.status NOT IN ('Completed', 'Closed', 'Cancelled')
            AND i.is_stock_item = 1
            AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')

        UNION ALL

        SELECT 
            so.name AS sales_order,
            pi.item_code
        FROM 
            `tabSales Order` so
        INNER JOIN 
            `tabSales Order Item` soi ON soi.parent = so.name
        INNER JOIN 
            `tabPacked Item` pi ON pi.parent = so.name AND pi.parent_detail_docname = soi.name
        INNER JOIN 
            `tabItem` i ON pi.item_code = i.item_code
        WHERE
            (so.per_delivered < 100 OR so.per_billed < 100)
            AND so.docstatus = 1
            AND so.status NOT IN ('Completed', 'Closed', 'Cancelled')
            AND soi.item_code IN (SELECT item_code FROM `tabItem` WHERE is_stock_item = 0)
            AND i.is_stock_item = 1
            AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')

        ORDER BY 
            sales_order DESC
    """, as_dict=1)

    for so in open_sales_orders:
        so_name = so["sales_order"]
        item_code = so["item_code"]

        accumulated_days = 0
        serial_found = False

        for dept in departments:
            dept_name = dept["name"]
            min_aging_days = dept.get("min_aging_days", 0)
            accumulated_days += min_aging_days

            warehouses = frappe.db.sql("""
                SELECT 
                    name
                FROM
                    `tabWarehouse`
                WHERE
                    department = %s
            """, (dept_name,), as_dict=1)

            for wh in warehouses:
                warehouse_name = wh["name"]

                serial_no = frappe.db.sql("""
                    SELECT 
                        name
                    FROM
                        `tabSerial No`
                    WHERE
                        item_code = %s AND warehouse = %s
                        AND (reserved_sales_order IS NULL OR reserved_sales_order = '')
                    LIMIT 1
                """, (item_code, warehouse_name), as_dict=1)

                if serial_no:
                    frappe.db.sql("""
                        UPDATE `tabSerial No` 
                        SET reserved_sales_order = %s
                        WHERE name = %s
                    """, (so_name, serial_no[0]["name"]))

                    frappe.db.sql("""
                        UPDATE `tabSales Order` 
                        SET eta_for_dispatch = %s
                        WHERE name = %s
                    """, (accumulated_days, so_name))

                    serial_found = True
                    break

            if serial_found:
                print("serial found for item_code", item_code)
                break
@frappe.whitelist()
def send_consignement_data(doc):
    print("Triggered send_consignement_data...")
    try:
        # Convert string to Frappe dict
        doc = frappe._dict(json.loads(doc))
        print("doc:----------------------------", doc)
        
        # Fetch addresses
        company_address = frappe.get_doc("Address", doc.company_address) if doc.company_address else None
        shipping_address = frappe.get_doc("Address", doc.shipping_address_name) if doc.shipping_address_name else None
        formatted_date = doc.transaction_date.strftime("%Y-%m-%d") if hasattr(doc.transaction_date, 'strftime') else str(doc.transaction_date)
        
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
            "ConsignmentValue": str(doc.grand_total),
            "NoQuantity": 1,
            "consignmentValue": str(doc.grand_total),
            "Weight": str(doc.weight),
            "TransitMode": doc.mode_of_transfer,
            "ProductMode": "Normal",
            "PaymentType": "COD",
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
            
            # Update the Sales Order document with AWB number and CIT image
            sales_order = frappe.get_doc("Sales Order", doc.name)
            sales_order.awb_number = awb_number
            sales_order.cit_image = cit_data
            sales_order.save(ignore_permissions=True)
            
            frappe.msgprint(f"AWB Number generated successfully: {awb_number}")
            return {"awb_number": awb_number, "cit_image": cit_data}
        else:
            frappe.throw(f"API returned error: {response.text}")
            
    except Exception as e:
        frappe.throw(f"Failed to send data to Criticalog API. Error: {str(e)}")