# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

# import frappe
import json
import frappe
import requests
import json
import requests
import traceback
from frappe import _
from frappe.utils import now
from datetime import datetime, timedelta
from frappe.utils import now_datetime, get_datetime
from frappe.model.document import Document
from nj_features.nj_features.api.shiprocket_api import get_auth_token

class DeliveryCharges(Document):
	pass


@frappe.whitelist()
def criticalog_awb_number_tracking_status():
    # Get only those Delivery Charges records which are not yet marked as Delivered
    docs = frappe.get_all(
        "Delivery Charges",
        filters={
            "awb_number": ["!=", ""],
            "remark_status": ["!=", "Delivered"]  # <-- skip already delivered
        },
        fields=["name", "awb_number", "delivery_note"]
    )
    # print(f"Processing {len(docs)} Delivery Charges records...",docs)

    url = "https://www.ecritica.co/eFreightLive/api/tracking.php"
    headers = {"Content-Type": "application/json"}

    for doc in docs:
        if not doc.delivery_note:
            print(f"[{doc.name}] Delivery Note not found, skipping...")
            continue

        try:
            payload = {
                "Auth": " MTMzMzQzNzMwMzIz",  # Preserve leading space
                "DocketNo": doc.delivery_note
            }

            response = requests.post(url, headers=headers, json=payload)

            if response.status_code == 200:
                data = response.json()
                print(f"[{doc.name}] Response: {data}")

                # Extract remark
                docket_details = data.get("data", {}).get("docketDetails", {})
                remark = docket_details.get("Booking_Status", {}).get("Remark")

                if remark:
                    frappe.db.set_value("Delivery Charges", doc.name, "remark_status", remark)
                    frappe.db.commit()
                    print(f"[{doc.name}] Updated remark_status to: {remark}")
                else:
                    print(f"[{doc.name}] No remark found in response.")
            else:
                print(f"[{doc.name}] API returned status code: {response.status_code}")

        except Exception as e:
            print(f"[{doc.name}] Error: {str(e)}")


@frappe.whitelist()
def awb_number_tracking_status():
    # Get all Delivery Charges records that have an AWB number and are not Delivered
    docs = frappe.get_all(
        "Delivery Charges",
        filters={
            "awb_number": ["!=", ""],
            "remark_status": ["!=", "Delivered"]  # <-- Skip Delivered entries
        },
        fields=["name", "awb_number"]
    )
    # print("docs=====================",docs)
    # Get authentication token from Shiprocket
    auth_token = get_auth_token().get("token")
    if not auth_token:
        frappe.throw("Authentication token could not be retrieved from Shiprocket.")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    }
    
    for doc in docs:
        awb = doc.awb_number
        url = f"https://apiv2.shiprocket.in/v1/external/courier/track/awb/{awb}"
        res = requests.get(url, headers=headers)

        if res.status_code != 200:
            print(f"[{doc.name}] Failed to get tracking for AWB {awb}")
            continue

        response = res.json()
        tracking_data = response.get("tracking_data", {})
        shipment_track = tracking_data.get("shipment_track", [])
        activities = tracking_data.get("shipment_track_activities", [])

        current_status = None
        activity = None
        location = None

        if shipment_track:
            current_status = shipment_track[0].get("current_status")
        if activities:
            activity = activities[0].get("activity")
            location = activities[0].get("location")

        print(f"[{doc.name}] current_status: {current_status}, activity: {activity}, location: {location}")

        if current_status or activity or location:
            delivery_doc = frappe.get_doc("Delivery Charges", doc.name)
            delivery_doc.remark_status = current_status
            delivery_doc.activity = activity
            delivery_doc.location = location
            delivery_doc.save(ignore_permissions=True)
            frappe.db.commit()




# def update_status_in_shopify():
#     token = "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"
#     base_url = "https://newjaisa.myshopify.com/admin/api/2023-10"

#     # Fetch all Delivery Charges
#     delivery_charges = frappe.get_all("Delivery Charges", fields=["name", "sales_order", "remark_status"])
#     # print("delivery_charges=================================",delivery_charges)

#     for dc in delivery_charges:
#         # Step 1: Get shopify_order_number from Sales Order
#         shopify_order_number = frappe.db.get_value("Sales Order", dc.sales_order, "shopify_order_number")
#         print("shopify_order_number=================================",shopify_order_number)

#         if not shopify_order_number:
#             frappe.logger().error(f"[{dc.name}] Shopify order number not found for Sales Order {dc.sales_order}")
#             continue

#         # Step 2: GET fulfillments
#         fulfillment_url = f"{base_url}/orders/{shopify_order_number}/fulfillments.json"
#         headers = {
#             "X-Shopify-Access-Token": token,
#             "Content-Type": "application/json"
#         }

#         try:
#             get_response = requests.get(fulfillment_url, headers=headers)
#             get_response.raise_for_status()

#             fulfillments = get_response.json().get("fulfillments", [])
#             print("fulfillments=================================",fulfillments)
#             if not fulfillments:
#                 frappe.logger().info(f"[{dc.name}] No fulfillments found for order {shopify_order_number}")
#                 continue

#             fulfillment_id = fulfillments[0].get("id")
#             print("fulfillment_id=================================",fulfillment_id)
#             if not fulfillment_id:
#                 frappe.logger().error(f"[{dc.name}] Fulfillment ID missing in response")
#                 continue

#             # Step 3: Map remark_status -> shopify_delivery_status
#             # shopify_delivery_status = frappe.db.get_value(
#             #     "Shopify Status Update",
#             #     {
#             #         "parent": "Logistics Settings",
#             #         "shiprocket_status": dc.remark_status
#             #     },
#             #     "shopify_delivery_status"
#             # )
#             # print("shopify_delivery_status=================================",shopify_delivery_status)
#             # Get Logistics Settings doc and loop child table to find match
#             # Step 3: Map remark_status -> shopify_delivery_status (case-insensitive match)
#             logistics_settings = frappe.get_doc("Logistics Settings")

#             shopify_delivery_status = None
#             for row in logistics_settings.shopify_status_update:
#                 if row.shiprocket_status and row.shiprocket_status.strip().lower() == dc.remark_status.strip().lower():
#                     shopify_delivery_status = row.shopify_delivery_status
#                     break

#             # Log and move on with no POST if status is not found
#             if not shopify_delivery_status:
#                 frappe.logger().warning(f"[{dc.name}] No Shopify delivery status mapped for remark_status: '{dc.remark_status}'")
#                 continue  # this skips only the POST; the rest of the records will still process


#             # Step 4: POST fulfillment event
#             post_url = f"{base_url}/orders/{shopify_order_number}/fulfillments/{fulfillment_id}/events.json"
#             post_body = {
#                 "event": {
#                     "status": shopify_delivery_status
#                 }
#             }
#             print("post_body=================================",post_body)

#             post_response = requests.post(post_url, headers=headers, json=post_body)
#             post_response.raise_for_status()

#             # Log the result
#             post_result = post_response.json()
#             print("post second api data==========================================",post_result)


#             # Optional: Store response in a field
#             # frappe.db.set_value("Delivery Charges", dc.name, "shopify_response", json.dumps(post_result))

#         except requests.exceptions.RequestException as e:
#             frappe.logger().error(f"[{dc.name}] Shopify API error: {str(e)}")




def update_status_in_shopify():
    token = "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"
    base_url = "https://newjaisa.myshopify.com/admin/api/2023-10"

    # Fetch all Delivery Charges
    delivery_charges = frappe.get_all("Delivery Charges", fields=["name", "sales_order", "remark_status"])

    for dc in delivery_charges:
        shopify_order_number = frappe.db.get_value("Sales Order", dc.sales_order, "shopify_order_number")
        if not shopify_order_number:
            continue

        fulfillment_url = f"{base_url}/orders/{shopify_order_number}/fulfillments.json"
        headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json"
        }

        try:
            get_response = requests.get(fulfillment_url, headers=headers)

            # Check if the response is valid JSON
            if get_response.status_code != 200:
                frappe.logger().error(f"[{dc.name}] Shopify response status: {get_response.status_code}, body: {get_response.text}")
                continue

            if "application/json" not in get_response.headers.get("Content-Type", ""):
                frappe.logger().error(f"[{dc.name}] Invalid Content-Type. Response: {get_response.text}")
                continue

            try:
                fulfillments = get_response.json().get("fulfillments", [])
                print("fulfillments===================================",fulfillments)
            except json.JSONDecodeError:
                frappe.logger().error(f"[{dc.name}] Failed to parse JSON. Raw Response: {get_response.text}")
                continue

            if not fulfillments:
                continue

            fulfillment = fulfillments[0]
            fulfillment_id = fulfillment.get("id")
            if not fulfillment_id:
                continue

            shipment_status_raw = fulfillment.get("shipment_status")
            shipment_status = shipment_status_raw.lower() if shipment_status_raw else ""

            if shipment_status == "delivered":
                continue

            shopify_delivery_status = frappe.db.get_value(
                "Shopify Status Update",
                {
                    "parent": "Logistics Settings",
                    "shiprocket_status": dc.remark_status
                },
                "shopify_delivery_status"
            )
            print("shopify_delivery_status=================================",shopify_delivery_status)

            if not shopify_delivery_status:
                logistics_settings = frappe.get_doc("Logistics Settings")
                for row in logistics_settings.shopify_status_update:
                    if (
                        row.shiprocket_status and
                        dc.remark_status and
                        row.shiprocket_status.strip().lower() == dc.remark_status.strip().lower()
                    ):
                        shopify_delivery_status = row.shopify_delivery_status
                        break

            if not shopify_delivery_status:
                frappe.logger().warning(f"[{dc.name}] No Shopify delivery status mapped for remark_status: '{dc.remark_status}'")
                continue

            post_url = f"{base_url}/orders/{shopify_order_number}/fulfillments/{fulfillment_id}/events.json"
            post_body = {
                "event": {
                    "status": shopify_delivery_status
                }
            }

            post_response = requests.post(post_url, headers=headers, json=post_body)
            if post_response.status_code != 201:
                frappe.logger().error(f"[{dc.name}] Failed to post fulfillment event. Status: {post_response.status_code}, Response: {post_response.text}")
                continue

            post_result = post_response.json()
            print("post second api data==========================================", post_result)

        except requests.exceptions.RequestException as e:
            frappe.logger().error(f"[{dc.name}] Shopify API connection error: {str(e)}")
            continue

