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
from datetime import datetime, timedelta
from datetime import datetime
from nj_features.nj_features.api.shiprocket_api import get_auth_token
class DeliveryCharges(Document):
	pass


# @frappe.whitelist()
# def criticalog_awb_number_tracking_status():

#     docs = frappe.get_all(
#         "Delivery Charges",
#         filters={
#             "awb_number": ["!=", ""],
#             "remark_status": ["!=", "Delivered"]
#         },
#         fields=["name", "awb_number", "delivery_note"]
#     )

#     url = "https://www.ecritica.co/eFreightLive/api/tracking.php"
#     headers = {"Content-Type": "application/json"}

#     for doc in docs:
#         if not doc.delivery_note:
#             print(f"[{doc.name}] Delivery Note not found, skipping...")
#             continue

#         try:
#             dn = frappe.get_doc("Delivery Note", doc.delivery_note)
#             # print(f"[{doc.name}] Delivery Note=======================: {dn}")
#             mode = (dn.mode_of_transfer or "").lower()
#             # print("mode=======================", mode)

#             if "air" in mode:
#                 auth = frappe.db.get_single_value("Logistics Settings", "air_auth")
#             elif "surface" in mode or "road" in mode:
#                 auth = frappe.db.get_single_value("Logistics Settings", "surface_auth")
#             else:
#                 print(f"[{doc.name}] Unknown mode_of_transport: {dn.mode_of_transport}, skipping...")
#                 continue

#             payload = {
#                 "Auth": auth,
#                 "DocketNo": doc.delivery_note
#             }

#             # print(f"[{doc.name}] Payload========================: {payload}")
#             response = requests.post(url, headers=headers, json=payload)
#             # print(f"[{doc.name}] Response status code: ==================={response.status_code}")

#             if response.status_code == 200:
#                 data = response.json()
#                 print(f"[{doc.name}] Response: {data}")

#                 docket_data = data.get("data", {})
#                 docket_details = docket_data.get("docketDetails", {})

#                 # Fix: If docket_details is not a dict, skip
#                 if not isinstance(docket_details, dict):
#                     print(f"[{doc.name}] Invalid docketDetails format: {docket_details}")
#                     continue

#                 remark = docket_details.get("Booking_Status", {}).get("Remark")
#                 if remark:
#                     frappe.db.set_value("Delivery Charges", doc.name, "remark_status", remark)
#                     frappe.db.commit()
#                     print(f"[{doc.name}] Updated remark_status to: {remark}")
#                 else:
#                     print(f"[{doc.name}] No remark found in response.")
#             else:
#                 print(f"[{doc.name}] API returned status code: {response.status_code}")

#         except Exception as e:
#             print(f"[{doc.name}] Error: {str(e)}")

@frappe.whitelist()
def criticalog_awb_number_tracking_status():
    docs = frappe.get_all(
        "Delivery Charges",
        filters={
            "awb_number": ["!=", ""],
            "remark_status": ["!=", "Delivered"]
        },
        fields=["name", "awb_number", "delivery_note", "courier_service"]
    )

    url = "https://www.ecritica.co/eFreightLive/api/tracking.php"
    # url = "https://testing.ecritica.co/eFreightLive/api/tracking.php"
    headers = {"Content-Type": "application/json"}


    for doc in docs:
        # Only proceed if courier_service is CriticaLog
        if doc.courier_service != "CriticaLog":
            print(f"[{doc.name}] Skipping because courier_service is not CriticaLog")
            continue

        if not doc.delivery_note:
            print(f"[{doc.name}] Delivery Note not found, skipping...")
            continue

        try:
            dn = frappe.get_doc("Delivery Note", doc.delivery_note)
            mode = (dn.mode_of_transfer or "").lower()

            if "air" in mode:
                auth = frappe.db.get_single_value("Logistics Settings", "air_auth")
            elif "surface" in mode or "road" in mode:
                auth = frappe.db.get_single_value("Logistics Settings", "surface_auth")
            else:
                print(f"[{doc.name}] Unknown mode_of_transfer: {dn.mode_of_transfer}, skipping...")
                continue

            payload = {
                "Auth": auth,
                "DocketNo": doc.delivery_note
            }
            print(f"[{doc.name}] Payload========================: {payload}")

            response = requests.post(url, headers=headers, json=payload)

            if response.status_code == 200:
                data = response.json()
                print(f"[{doc.name}] Response: {data}")

                docket_data = data.get("data", {})
                docket_details = docket_data.get("docketDetails", {})

                if not isinstance(docket_details, dict):
                    print(f"[{doc.name}] Invalid docketDetails format: {docket_details}")
                    continue

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


    # Fetch Delivery Charges entries with valid AWB number and not Delivered
    docs = frappe.get_all(
        "Delivery Charges",
        filters={
            "awb_number": ["!=", ""],
            "remark_status": ["!=", "Delivered"]
        },
        fields=["name", "awb_number"]
    )

    # Get Shiprocket auth token
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
        try:
            res = requests.get(url, headers=headers, timeout=15)
        except Exception as e:
            print(f"[{doc.name}] Exception during request: {str(e)}")
            continue

        if res.status_code != 200:
            print(f"[{doc.name}] Failed to get tracking for AWB {awb}")
            continue

        response = res.json()
        print("response:--------159", response)
        tracking_data = response.get("tracking_data", {})
        shipment_track = tracking_data.get("shipment_track", [])
        activities = tracking_data.get("shipment_track_activities", [])

        current_status = None
        activity = None
        location = None
        delivered_date = None

        if shipment_track:
            current_status = shipment_track[0].get("current_status")
            delivered_date = shipment_track[0].get("delivered_date")
        if activities:
            activity = activities[0].get("activity")
            location = activities[0].get("location")

        print(f"[{doc.name}] current_status: {current_status}, activity: {activity}, location: {location}")

        if current_status or activity or location:
            delivery_doc = frappe.get_doc("Delivery Charges", doc.name)
            delivery_doc.remark_status = current_status
            delivery_doc.delivered_date = delivered_date
            delivery_doc.activity = activity
            delivery_doc.location = location

            # Check for final status or 30+ days after picked_date
            picked_date = delivery_doc.picked_date
            print("picked_date:=============================", picked_date)
            send_due_to_age = False
            
            if picked_date:
                try:
                    # Ensure picked_date is a datetime object
                    if isinstance(picked_date, str):
                        picked_date = datetime.strptime(picked_date, "%d-%m-%Y %H:%M:%S")  # format based on your example
                        print("parsed picked_date:=============================", picked_date)

                    if picked_date <= datetime.now() - timedelta(days=30):
                        send_due_to_age = True
                except Exception as e:
                    print(f"Error parsing picked_date for {delivery_doc.name}: {e}")

            # ✅ Send email if status is final OR picked_date > 30 days ago
            if current_status in ["Delivered", "RTO Delivered", "Lost"] or send_due_to_age:
                delivery_doc.send_email = 1
                print("delivery_doc.send_email set due to status or 30+ days:===========================", delivery_doc.send_email)

            # # ✅ Auto-check send_email if final status
            # if current_status in ["Delivered", "RTO Delivered", "Lost"]:
            #     delivery_doc.send_email = 1
            #     print("delivery_doc.send_email==========================================================", delivery_doc.send_email)
            # Check and add to child table if uniqueunique
            exists = False
            for row in delivery_doc.item_tracking_table:
                if row.activity == activity and row.location == location:
                    exists = True
                    break

            if not exists and (activity or location):
                delivery_doc.append("item_tracking_table", {
                    "activity": activity,
                    "location": location,
                    "timestamp": datetime.now()  # Ensure you have a 'timestamp' field in child table
                })

            delivery_doc.save(ignore_permissions=True)
            frappe.db.commit()



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
            # print("post second api data==========================================", post_result)

        except requests.exceptions.RequestException as e:
            frappe.logger().error(f"[{dc.name}] Shopify API connection error: {str(e)}")
            continue

