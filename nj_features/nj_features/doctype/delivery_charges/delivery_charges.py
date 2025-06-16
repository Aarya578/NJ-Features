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
def awb_number_tracking_status():
    # Get all Delivery Charges docs with AWB number
    docs = frappe.get_all("Delivery Charges", filters={"awb_number": ["!=", ""]}, fields=["name", "awb_number"])
    
    # Authenticate to Shiprocket
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
            print(f"Failed to get tracking for AWB {awb}")
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

        print("current_status========", current_status)
        print("activity========", activity)
        print("location========", location)

        if current_status or activity or location:
            delivery_doc = frappe.get_doc("Delivery Charges", doc.name)
            delivery_doc.current_status = current_status
            delivery_doc.activity = activity
            delivery_doc.location = location
            delivery_doc.save(ignore_permissions=True)
            frappe.db.commit()  # Commit after every save if running in batch
