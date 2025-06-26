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

    url = "https://testing.ecritica.co/eFreightLive/api/tracking.php"
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
