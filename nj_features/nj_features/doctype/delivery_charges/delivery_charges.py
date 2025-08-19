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
 

# @frappe.whitelist()
# def awb_number_tracking_status():
#     import time  # Add time import for delays
#     # Fetch ALL Delivery Charges entries with valid AWB number, skip only if Delivered
#     docs = frappe.get_all(
#         "Delivery Charges",
#         filters={
#             "awb_number": ["!=", ""],
#             "remark_status": ["!=", "Delivered"]  # Only skip Delivered records
#         },
#         fields=["name", "awb_number", "remark_status"]  # Added remark_status for debugging
#     )

#     print(f"Total records to process: {len(docs)}")

#     # Get Shiprocket auth token
#     auth_token = get_auth_token().get("token")
#     if not auth_token:
#         frappe.throw("Authentication token could not be retrieved from Shiprocket.")

#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {auth_token}"
#     }

#     success_count = 0
#     error_count = 0
#     rate_limit_count = 0

#     for i, doc in enumerate(docs):
#         awb = doc.awb_number
#         print(f"Processing [{i+1}/{len(docs)}] [{doc.name}] AWB: {awb}, Current Status: {doc.remark_status}")
        
#         # Add delay to avoid rate limiting - adjust as needed
#         if i > 0:  # Don't delay on first request
#             time.sleep(0.5)  # 500ms delay between requests
        
#         url = f"https://apiv2.shiprocket.in/v1/external/courier/track/awb/{awb}"
#         try:
#             res = requests.get(url, headers=headers, timeout=15)
#             print(f"[{doc.name}] API Response Status: {res.status_code}")
#         except Exception as e:
#             print(f"[{doc.name}] Exception during request: {str(e)}")
#             error_count += 1
#             continue

#         if res.status_code == 429:
#             print(f"[{doc.name}] Rate limit hit for AWB {awb}. Waiting 60 seconds...")
#             time.sleep(60)  # Wait 1 minute on rate limit
#             rate_limit_count += 1
            
#             # Retry the request once after waiting
#             try:
#                 res = requests.get(url, headers=headers, timeout=15)
#                 print(f"[{doc.name}] Retry API Response Status: {res.status_code}")
#             except Exception as e:
#                 print(f"[{doc.name}] Exception during retry: {str(e)}")
#                 error_count += 1
#                 continue
        
#         if res.status_code != 200:
#             print(f"[{doc.name}] Failed to get tracking for AWB {awb}, Status Code: {res.status_code}")
#             error_count += 1
#             continue

#         try:
#             response = res.json()
#             tracking_data = response.get("tracking_data", {})
#             shipment_track = tracking_data.get("shipment_track", [])
#             activities = tracking_data.get("shipment_track_activities", [])

#             # Initialize variables
#             current_status = None
#             delivered_date = None
#             latest_activity = None
#             latest_location = None

#             # Get current status and delivered date from shipment_track
#             if shipment_track and len(shipment_track) > 0:
#                 current_status = shipment_track[0].get("current_status")
#                 delivered_date = shipment_track[0].get("delivered_date")

#             # Get the latest activity and location from activities
#             if isinstance(activities, list) and activities:
#                 latest_activity = activities[0].get("activity")
#                 latest_location = activities[0].get("location")

#             print(f"[{doc.name}] API Data - current_status: {current_status}, latest_activity: {latest_activity}, latest_location: {latest_location}")

#             # Always try to update the record (don't skip based on empty values)
#             delivery_doc = frappe.get_doc("Delivery Charges", doc.name)
            
#             # Update main fields - use current_status primarily, fallback to latest_activity status
#             if current_status:
#                 delivery_doc.remark_status = current_status
#             elif latest_activity:
#                 # If no current_status, you might want to derive status from latest activity
#                 delivery_doc.remark_status = latest_activity

#             # Update other fields
#             if delivered_date and delivered_date != "":
#                 delivery_doc.delivered_date = delivered_date
            
#             if latest_activity:
#                 delivery_doc.activity = latest_activity
            
#             if latest_location:
#                 delivery_doc.location = latest_location

#             # Initialize picked_date logic
#             picked_date = delivery_doc.picked_date
#             send_due_to_age = False

#             try:
#                 if picked_date:
#                     # Parse if string
#                     if isinstance(picked_date, str):
#                         picked_date = datetime.strptime(picked_date, "%d-%m-%Y %H:%M:%S")

#                     # Check if more than 30 days have passed
#                     if datetime.now() - picked_date > timedelta(days=30):
#                         if current_status and current_status not in ["Delivered", "RTO Delivered"]:
#                             send_due_to_age = True

#             except Exception as e:
#                 print(f"Error parsing picked_date for {delivery_doc.name}: {e}")

#             # Final check for Lost status or delay
#             if current_status == "Lost" or send_due_to_age:
#                 delivery_doc.send_email = 1

#             # Process activities - always process if valid activities exist
#             if isinstance(activities, list) and activities:
#                 # Sort activities by date in descending order (newest first)
#                 sorted_activities = sorted(activities, key=lambda x: x.get("date", ""), reverse=True)

#                 new_activities_added = 0
#                 # Process all activities from shipment_track_activities
#                 for activity_data in sorted_activities:
#                     activity = activity_data.get("activity")
#                     location = activity_data.get("location")
#                     activity_date = activity_data.get("date")

#                     # Skip if activity or location is empty
#                     if not activity or not location:
#                         continue

#                     # Check if this combination already exists in the child table
#                     exists = any(
#                         row.activity == activity and row.location == location
#                         for row in delivery_doc.item_tracking_table
#                     )

#                     # If not exists, add new row to child table
#                     if not exists:
#                         # Parse the activity date for timestamp
#                         timestamp = datetime.now()
#                         if activity_date:
#                             try:
#                                 timestamp = datetime.strptime(activity_date, "%Y-%m-%d %H:%M:%S")
#                             except Exception as e:
#                                 print(f"Error parsing activity date {activity_date}: {e}")

#                         delivery_doc.append("item_tracking_table", {
#                             "activity": activity,
#                             "location": location,
#                             "timestamp": timestamp,
#                             "status": activity_data.get("status", ""),
#                             "sr_status": activity_data.get("sr-status", ""),
#                             "sr_status_label": activity_data.get("sr-status-label", "")
#                         })
#                         new_activities_added += 1

#                 print(f"[{doc.name}] Added {new_activities_added} new activities")

#             # Save the document
#             update_rto_reason_in_delivery_charges()
#             delivery_doc.save(ignore_permissions=True)
#             frappe.db.commit()
#             success_count += 1
#             print(f"[{doc.name}] Updated successfully. New status: {delivery_doc.remark_status}")

#         except Exception as e:
#             print(f"[{doc.name}] Error processing response: {str(e)}")
#             error_count += 1
#             continue

#     print(f"Processing completed. Success: {success_count}, Errors: {error_count}, Rate Limits: {rate_limit_count}, Total: {len(docs)}")
#     return {
#         "success": success_count,
#         "errors": error_count,
#         "rate_limits": rate_limit_count,
#         "total": len(docs)
#     }

# @frappe.whitelist()
# def awb_number_tracking_status():
#     # Get all Delivery Charges entries with valid AWB number
#     docs = frappe.get_all(
#         "Delivery Charges",
#         filters={"awb_number": ["!=", ""]},
#         fields=["name", "awb_number", "remark_status"]
#     )

#     # Get Shiprocket auth token
#     auth_token = get_auth_token().get("token")
#     if not auth_token:
#         frappe.throw("Authentication token could not be retrieved from Shiprocket.")

#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {auth_token}"
#     }

#     for doc in docs:
#         awb = doc.awb_number

#         # Skip only if remark_status is exactly 'Delivered'
#         if doc.get("remark_status") == "Delivered":
#             # print(f"[{doc.name}] Skipping (already Delivered)")
#             continue
        
#         if doc.courier_service == "CriticaLog":
#             # print(f"[{doc.name}] Skipping (courier is CriticaLog)")
#             continue

#         url = f"https://apiv2.shiprocket.in/v1/external/courier/track/awb/{awb}"
#         try:
#             res = requests.get(url, headers=headers, timeout=15)
#             print(f"[{doc.name}] Fetched response from Shiprocket")
#         except Exception as e:
#             print(f"[{doc.name}] Exception during request: {str(e)}")
#             continue

#         if res.status_code != 200:
#             print(f"[{doc.name}] Failed to get tracking for AWB {awb}")
#             continue

#         response = res.json()
#         tracking_data = response.get("tracking_data", {})
#         shipment_track = tracking_data.get("shipment_track", [])
#         activities = tracking_data.get("shipment_track_activities", [])

#         current_status = None
#         delivered_date = None

#         if shipment_track:
#             current_status = shipment_track[0].get("current_status")
#             delivered_date = shipment_track[0].get("delivered_date")

#         # Get latest activity and location
#         latest_activity = None
#         latest_location = None
#         if isinstance(activities, list) and activities:
#             latest_activity = activities[0].get("activity")
#             latest_location = activities[0].get("location")

#         print(f"[{doc.name}] Status: {current_status}, Activity: {latest_activity}, Location: {latest_location}")

#         # Update document
#         delivery_doc = frappe.get_doc("Delivery Charges", doc.name)
#         delivery_doc.remark_status = current_status
#         delivery_doc.delivered_date = delivered_date
#         delivery_doc.activity = latest_activity
#         delivery_doc.location = latest_location

#         # Check for overdue (30+ days)
#         picked_date = delivery_doc.picked_date
#         send_due_to_age = False

#         try:
#             if picked_date:
#                 if isinstance(picked_date, str):
#                     picked_date = datetime.strptime(picked_date, "%Y-%m-%d %H:%M:%S")

#                 if datetime.now() - picked_date > timedelta(days=50):
#                     if current_status not in ["Delivered", "RTO Delivered"]:
#                         send_due_to_age = True
#         except Exception as e:
#             print(f"[{doc.name}] Error parsing picked_date: {e}")

#         if current_status == "Lost" or send_due_to_age:
#             delivery_doc.send_email = 1

#         # Process activity table
#         if isinstance(activities, list) and activities:
#             sorted_activities = sorted(activities, key=lambda x: x.get("date", ""), reverse=True)

#             for activity_data in sorted_activities:
#                 activity = activity_data.get("activity")
#                 location = activity_data.get("location")
#                 activity_date = activity_data.get("date")

#                 if not activity or not location:
#                     continue

#                 exists = any(
#                     row.activity == activity and row.location == location
#                     for row in delivery_doc.item_tracking_table
#                 )

#                 if not exists:
#                     timestamp = datetime.now()
#                     if activity_date:
#                         try:
#                             timestamp = datetime.strptime(activity_date, "%Y-%m-%d %H:%M:%S")
#                         except Exception as e:
#                             print(f"[{doc.name}] Error parsing activity date {activity_date}: {e}")

#                     delivery_doc.append("item_tracking_table", {
#                         "activity": activity,
#                         "location": location,
#                         "timestamp": timestamp,
#                         "status": activity_data.get("status", ""),
#                         "sr_status": activity_data.get("sr-status", ""),
#                         "sr_status_label": activity_data.get("sr-status-label", "")
#                     })

#         delivery_doc.save(ignore_permissions=True)
#         frappe.db.commit()
#         print(f"[{doc.name}] Updated successfully.")



                # update_rto_reason_in_delivery_charges()
# def update_rto_reason_in_delivery_charges():
#     delivery_charges_docs = frappe.get_all(
#         "Delivery Charges",
#         filters={"docstatus": ("!=", 2)},
#         fields=["name"]
#     )

#     for dc in delivery_charges_docs:
#         doc = frappe.get_doc("Delivery Charges", dc.name)

#         # Step 1: Check for "RTO" in item_tracking_table
#         found_rto = False
#         all_activities = []

#         for row in doc.get("item_tracking_table", []):
#             activity = (row.activity or "").strip()
#             all_activities.append(activity)
#             if "RTO" in activity.upper():
#                 found_rto = True

#         if not found_rto:
#             continue

#         # Step 2: Get return_reason activities from Logistics Settings
#         logistics_settings = frappe.get_single("Logistics Settings")
#         return_reason_activities = [
#             (r.activity or "").strip() for r in logistics_settings.get("return_reason") or []
#         ]

#         # Step 3: Match any activity with return_reason list
#         matched = any(activity in return_reason_activities for activity in all_activities)
#         doc.rto_reason = "RTO Customer" if matched else "RTO Courier"
#         doc.save(ignore_permissions=True)

#         # Step 4: Update the same reason in linked Delivery Note
#         if doc.delivery_note:
#             try:
#                 dn = frappe.get_doc("Delivery Note", doc.delivery_note)
#                 print(f"Updating Delivery Note==================== {dn.name} - return_reason: {dn.return_reason}")
#                 dn.return_reason = doc.rto_reason
#                 dn.save(ignore_permissions=True)
#                 # print(f"Updated Delivery Note {dn.name} - return_reason: {dn.return_reason}")
#             except Exception as e:
#                 print(f"Failed to update Delivery Note {doc.delivery_note}: {e}")

#         frappe.db.commit()
#         print(f"{doc.name} updated - rto_reason: {doc.rto_reason}")
@frappe.whitelist()
def awb_number_tracking_status():
    import time
    from datetime import datetime, timedelta
    import requests

    docs = frappe.get_all(
        "Delivery Charges",
        filters={
            "awb_number": ["!=", ""],
            "remark_status": ["!=", "Delivered"],
            "courier_service": ["!=", "CriticaLog"]
        },
        fields=["name", "awb_number", "remark_status", "courier_service"]
    )

    print(f"Total records to process: {len(docs)}")

    auth_token = get_auth_token().get("token")
    if not auth_token:
        frappe.throw("Authentication token could not be retrieved from Shiprocket.")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    }

    success_count = 0
    error_count = 0
    rate_limit_count = 0

    for i, doc in enumerate(docs):
        awb = doc.awb_number
        print(f"Processing [{i+1}/{len(docs)}] [{doc.name}] AWB: {awb}, Current Status: {doc.remark_status}")

        if i > 0:
            time.sleep(0.5)

        url = f"https://apiv2.shiprocket.in/v1/external/courier/track/awb/{awb}"
        try:
            res = requests.get(url, headers=headers, timeout=15)
            print(f"[{doc.name}] API Response Status: {res.status_code}")
        except Exception as e:
            print(f"[{doc.name}] Exception during request: {str(e)}")
            error_count += 1
            continue

        if res.status_code == 429:
            print(f"[{doc.name}] Rate limit hit for AWB {awb}. Waiting 20 seconds...")
            time.sleep(20)
            rate_limit_count += 1
            try:
                res = requests.get(url, headers=headers, timeout=15)
                print(f"[{doc.name}] Retry API Response Status: {res.status_code}")
            except Exception as e:
                print(f"[{doc.name}] Exception during retry: {str(e)}")
                error_count += 1
                continue

        if res.status_code != 200:
            print(f"[{doc.name}] Failed to get tracking for AWB {awb}, Status Code: {res.status_code}")
            error_count += 1
            continue

        try:
            response = res.json()
            tracking_data = response.get("tracking_data", {})
            shipment_track = tracking_data.get("shipment_track", [])
            activities = tracking_data.get("shipment_track_activities", [])

            current_status = None
            delivered_date = None
            latest_activity = None
            latest_location = None

            if shipment_track:
                current_status = shipment_track[0].get("current_status")
                delivered_date = shipment_track[0].get("delivered_date")

            if isinstance(activities, list) and activities:
                latest_activity = activities[0].get("activity")
                latest_location = activities[0].get("location")

            print(f"[{doc.name}] API Data - current_status: {current_status}, latest_activity: {latest_activity}, latest_location: {latest_location}")

            delivery_doc = frappe.get_doc("Delivery Charges", doc.name)

            if current_status:
                delivery_doc.remark_status = current_status
            elif latest_activity:
                delivery_doc.remark_status = latest_activity

            if delivered_date:
                delivery_doc.delivered_date = delivered_date

            if latest_activity:
                delivery_doc.activity = latest_activity

            if latest_location:
                delivery_doc.location = latest_location

            picked_date = delivery_doc.picked_date
            send_due_to_age = False

            try:
                if picked_date:
                    if isinstance(picked_date, str):
                        picked_date = datetime.strptime(picked_date, "%d-%m-%Y %H:%M:%S")

                    if datetime.now() - picked_date > timedelta(days=30):
                        if current_status and current_status not in ["Delivered", "RTO Delivered"]:
                            send_due_to_age = True

            except Exception as e:
                print(f"Error parsing picked_date for {delivery_doc.name}: {e}")

            if current_status == "Lost" or send_due_to_age:
                delivery_doc.send_email = 1

            if isinstance(activities, list) and activities:
                sorted_activities = sorted(activities, key=lambda x: x.get("date", ""), reverse=True)

                new_activities_added = 0
                for activity_data in sorted_activities:
                    activity = activity_data.get("activity")
                    location = activity_data.get("location")
                    activity_date = activity_data.get("date")

                    if not activity or not location:
                        continue

                    exists = any(
                        row.activity == activity and row.location == location
                        for row in delivery_doc.item_tracking_table
                    )

                    if not exists:
                        timestamp = datetime.now()
                        if activity_date:
                            try:
                                timestamp = datetime.strptime(activity_date, "%Y-%m-%d %H:%M:%S")
                            except Exception as e:
                                print(f"Error parsing activity date {activity_date}: {e}")

                        delivery_doc.append("item_tracking_table", {
                            "activity": activity,
                            "location": location,
                            "timestamp": timestamp,
                            "status": activity_data.get("status", ""),
                            "sr_status": activity_data.get("sr-status", ""),
                            "sr_status_label": activity_data.get("sr-status-label", "")
                        })
                        new_activities_added += 1

                print(f"[{doc.name}] Added {new_activities_added} new activities")


            # RTO Reason Update Logic (inlined)
            found_rto = False
            customer_issues_found = False
            all_activities = []

            # Get customer issues from NJ Settings
            customer_issues_setting = frappe.db.get_value(
                "NJ Settings", {"parameter": "customer_issues"}, "value"
            )
            customer_issues = [issue.strip() for issue in (customer_issues_setting or "").split(",")]
            # print(f"customer_issues=========================================: {customer_issues}")


            for row in delivery_doc.get("item_tracking_table", []):
                activity = (row.activity or "").strip()
                all_activities.append(activity)
                if "RTO" in activity.upper():
                    found_rto = True

                if activity in customer_issues:
                    customer_issues_found = True
                    # print(f"Found customer issue======================: {activity}")

            if found_rto:
                logistics_settings = frappe.get_single("Logistics Settings")
                return_reason_activities = [
                    (r.activity or "").strip()
                    for r in logistics_settings.get("return_reason") or []
                ]
                matched = any(activity in return_reason_activities for activity in all_activities)
                delivery_doc.rto_reason = "RTO Customer" if matched else "RTO Courier"

                if delivery_doc.delivery_note:
                    try:
                        dn = frappe.get_doc("Delivery Note", delivery_doc.delivery_note)
                        # print(f"Updating Delivery Note==================== {dn.name} - return_reason: {dn.return_reason}")
                        dn.return_reason = delivery_doc.rto_reason
                        dn.save(ignore_permissions=True)
                    except Exception as e:
                        print(f"Failed to update Delivery Note {delivery_doc.delivery_note}: {e}")

            # Handle customer issue logic
            if customer_issues_found and delivery_doc.delivery_note:
                try:
                    dn = frappe.get_doc("Delivery Note", delivery_doc.delivery_note)
                    print(f"dn==================== ==========={dn} ")
                    delivery_doc.customer_email = dn.email or dn.get("email_id")
                    print(f"delivery_doc.customer_email==================== ==========={delivery_doc.customer_email} ")
                    delivery_doc.customer_send_mail = 1  # Assumes this is a Check field or equivalent
                except Exception as e:
                    print(f"Failed to fetch customer email from Delivery Note {delivery_doc.delivery_note}: {e}")

            delivery_doc.save(ignore_permissions=True)
            frappe.db.commit()
            success_count += 1
            print(f"[{doc.name}] Updated successfully. New status: {delivery_doc.remark_status}")

        except Exception as e:
            print(f"[{doc.name}] Error processing response: {str(e)}")
            error_count += 1
            continue

    print(f"Processing completed. Success: {success_count}, Errors: {error_count}, Rate Limits: {rate_limit_count}, Total: {len(docs)}")
    return {
        "success": success_count,
        "errors": error_count,
        "rate_limits": rate_limit_count,
        "total": len(docs)
    }

def update_status_in_shopify():
    print("Updating status in Shopify...========================")
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
                # print("fulfillments===================================",fulfillments)
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

