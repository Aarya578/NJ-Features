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
#             "remark_status": ["!=", "Receiver's copy scan"]
#         },
#         fields=["name", "awb_number", "delivery_note", "courier_service"]
#     )

#     # url = "https://www.ecritica.co/eFreightLive/api/tracking.php"
#     url = "https://testing.ecritica.co/eFreightLive/api/tracking.php"
#     headers = {"    ": "application/json"}

#     for doc in docs:
#         # Only proceed if courier_service is CriticaLog
#         if doc.courier_service != "CriticaLog":
#             print(f"[{doc.name}] Skipping because courier_service is not CriticaLog")
#             continue

#         if not doc.delivery_note:
#             print(f"[{doc.name}] Delivery Note not found, skipping...")
#             continue

#         try:
#             dn = frappe.get_doc("Delivery Note", doc.delivery_note)
#             print("dn===================", dn)
#             mode = (dn.mode_of_transfer or "").lower()
#             print("mode===================", mode)

#             if "cod surface" in mode:
#                 auth = frappe.db.get_single_value("Logistics Settings", "air_auth")
#                 print("auth===================", auth)
#             elif "surface" in mode:
#                 auth = frappe.db.get_single_value("Logistics Settings", "surface_auth")
#                 print("auth===================", auth)
#             else:
#                 print(f"[{doc.name}] Unknown mode_of_transfer: {dn.mode_of_transfer}, skipping...")
#                 continue

#             payload = {
#                 "Auth": auth,
#                 "DocketNo": doc.delivery_note
#             }
#             print(f"=====================   [{doc.name}] Payload==========: {payload}")

#             response = requests.post(url, headers=headers, json=payload)
#             print("response===================", response)

#             if response.status_code == 200:
#                 data = response.json()
#                 print("data===================", data)

#                 docket_data = data.get("data", {})
#                 docket_details = docket_data.get("docketDetails", {})

#                 if not isinstance(docket_details, dict):
#                     print(f"[{doc.name}] Invalid docketDetails format: {docket_details}")
#                     continue

#                 remark = docket_details.get("last_event", {}).get("code")
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
            "remark_status": ["!=", "Receiver's copy scan"]
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
            print("dn===================", dn)
            mode = (dn.mode_of_transfer or "").lower()
            print("mode===================", mode)

            if "cod surface" in mode:
                auth = frappe.db.get_single_value("Logistics Settings", "air_auth")
                print("auth===================", auth)
            elif "surface" in mode:
                auth = frappe.db.get_single_value("Logistics Settings", "surface_auth")
                print("auth===================", auth)
            else:
                print(f"[{doc.name}] Unknown mode_of_transfer: {dn.mode_of_transfer}, skipping...")
                continue

            payload = {
                "Auth": auth,
                "DocketNo": doc.delivery_note
            }
            print(f"=====================   [{doc.name}] Payload==========: {payload}")

            response = requests.post(url, headers=headers, json=payload)
            print("response===================", response)

            if response.status_code == 200:
                data = response.json()
                print("data===================", data)

                docket_data = data.get("data", {})
                docket_details = docket_data.get("docketDetails", {})

                if not isinstance(docket_details, dict):
                    print(f"[{doc.name}] Invalid docketDetails format: {docket_details}")
                    continue

                # Get last event remark
                remark = docket_details.get("last_event", {}).get("Code")
                
                # Update remark_status
                if remark:
                    values = {"remark_status": remark}
                    if remark != doc.remark_status:
                        values["shopify_status_synced"] = 0
                    frappe.db.set_value("Delivery Charges", doc.name, values, update_modified=False)
                    print(f"[{doc.name}] Updated remark_status to: {remark}")
                
                # Get traversal data
                traversal_list = docket_details.get("traversal", [])
                
                # Process traversal data - only if there are entries
                if isinstance(traversal_list, list) and traversal_list:
                    # Sort by EventDate in descending order (latest first)
                    sorted_traversal = sorted(traversal_list, key=lambda x: x.get("EventDate", ""), reverse=True)
                    
                    # Load the document to check existing entries
                    delivery_charges_doc = frappe.get_doc("Delivery Charges", doc.name)
                    
                    new_activities_added = 0
                    for traversal_item in sorted_traversal:
                        activity = traversal_item.get("Code")
                        location = traversal_item.get("Location")
                        event_date = traversal_item.get("EventDate")
                        
                        if not activity or not location:
                            continue
                        
                        # Check if this activity already exists
                        exists = any(
                            row.activity == activity and row.location == location
                            for row in delivery_charges_doc.item_tracking_table
                        )
                        
                        if not exists:
                            timestamp = datetime.now()
                            if event_date:
                                try:
                                    # Parse the date format from API (DD-MM-YYYY HH:MM:SS)
                                    timestamp = datetime.strptime(event_date, "%d-%m-%Y %H:%M:%S")
                                except Exception as e:
                                    print(f"[{doc.name}] Error parsing event date {event_date}: {e}")
                            
                            delivery_charges_doc.append("item_tracking_table", {
                                "activity": activity,
                                "location": location,
                                "timestamp": timestamp,
                                "code_number": traversal_item.get("CodeNumber", "")
                            })
                            new_activities_added += 1
                    
                    if new_activities_added > 0:
                        delivery_charges_doc.save(ignore_permissions=True)
                        print(f"[{doc.name}] Added {new_activities_added} new tracking activities")
                    else:
                        print(f"[{doc.name}] No new tracking activities to add")
                
                frappe.db.commit()
                
            else:
                print(f"[{doc.name}] API returned status code: {response.status_code}")

        except Exception as e:
            print(f"[{doc.name}] Error: {str(e)}")
            frappe.log_error(frappe.get_traceback(), f"Tracking Status Error - {doc.name}")


DELHIVERY_TRACKING_URL = "https://track.delhivery.com/api/v1/packages/json/"


@frappe.whitelist()
def delhivery_awb_number_tracking_status():
    """Poll Delhivery's tracking API and update remark_status + item_tracking_table."""
    from nj_features.nj_features.api.delhivery_api import _get_delhivery_settings

    docs = frappe.get_all(
        "Delivery Charges",
        filters={
            "awb_number": ["!=", ""],
            "courier_service": "Delhivery",
            "remark_status": ["!=", "Delivered"]
        },
        fields=["name", "awb_number", "courier_service", "remark_status"]
    )

    print(f"Delhivery tracking: {len(docs)} records to process")

    try:
        settings = _get_delhivery_settings()
    except Exception as e:
        print(f"Could not load Delhivery settings: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Delhivery Tracking Settings Error")
        return

    headers = {
        "Authorization": f'Token {settings["api_token"]}',
        "Content-Type": "application/json"
    }

    for doc in docs:
        try:
            params = {"waybill": doc.awb_number, "verbose": 2}
            response = requests.get(DELHIVERY_TRACKING_URL, headers=headers, params=params, timeout=15)

            if response.status_code != 200:
                print(f"[{doc.name}] API returned status code: {response.status_code}")
                continue

            data = response.json()
            shipment_data = data.get("ShipmentData", [])
            if not shipment_data:
                print(f"[{doc.name}] No ShipmentData found in response.")
                continue

            shipment = shipment_data[0].get("Shipment", {})
            status = shipment.get("Status", {}).get("Status")

            # Update remark_status
            if status:
                values = {"remark_status": status}
                if status != doc.remark_status:
                    values["shopify_status_synced"] = 0
                frappe.db.set_value("Delivery Charges", doc.name, values, update_modified=False)
                print(f"[{doc.name}] Updated remark_status to: {status}")
            else:
                print(f"[{doc.name}] No status found in response.")

            # Update tracking table with scan history
            scans = shipment.get("Scans", [])
            if isinstance(scans, list) and scans:
                delivery_charges_doc = frappe.get_doc("Delivery Charges", doc.name)

                new_activities_added = 0
                for scan_item in scans:
                    scan_detail = scan_item.get("ScanDetail", {})
                    activity = scan_detail.get("Scan")
                    location = scan_detail.get("ScannedLocation")
                    scan_datetime = scan_detail.get("ScanDateTime")

                    if not activity or not location:
                        continue

                    # Check if this activity already exists
                    exists = any(
                        row.activity == activity and row.location == location
                        for row in delivery_charges_doc.item_tracking_table
                    )

                    if not exists:
                        timestamp = datetime.now()
                        if scan_datetime:
                            try:
                                # Delhivery format: 2023-02-05T23:15:12.713000
                                timestamp = datetime.strptime(
                                    scan_datetime.split(".")[0], "%Y-%m-%dT%H:%M:%S"
                                )
                            except Exception as e:
                                print(f"[{doc.name}] Error parsing scan date {scan_datetime}: {e}")

                        delivery_charges_doc.append("item_tracking_table", {
                            "activity": activity,
                            "location": location,
                            "timestamp": timestamp,
                            "code_number": scan_detail.get("StatusCode", "")
                        })
                        new_activities_added += 1

                if new_activities_added > 0:
                    delivery_charges_doc.save(ignore_permissions=True)
                    print(f"[{doc.name}] Added {new_activities_added} new tracking activities")
                else:
                    print(f"[{doc.name}] No new tracking activities to add")

            frappe.db.commit()

        except Exception as e:
            print(f"[{doc.name}] Error: {str(e)}")
            frappe.log_error(frappe.get_traceback(), f"Delhivery Tracking Status Error - {doc.name}")


AWB_TRACKING_BATCH_SIZE = 20
AWB_TRACKING_JOB_TIMEOUT = 1200
AWB_TRACKING_RUNNING_KEY = "awb_number_tracking_status_running"


@frappe.whitelist()
def awb_number_tracking_status():
    """Scheduler entry point: start one non-overlapping tracking batch chain."""
    cache = frappe.cache()
    if cache.get_value(AWB_TRACKING_RUNNING_KEY):
        print("AWB tracking is already queued or running; skipping this scheduler run.")
        return {"queued": False, "reason": "already_running"}

    # The expiry is a crash safeguard. Each batch refreshes it while the chain is active.
    cache.set_value(AWB_TRACKING_RUNNING_KEY, 1, expires_in_sec=12 * 60 * 60)
    try:
        frappe.enqueue(
            method="nj_features.nj_features.doctype.delivery_charges.delivery_charges.process_awb_tracking_batch",
            queue="long",
            timeout=AWB_TRACKING_JOB_TIMEOUT,
            job_name="shiprocket_awb_tracking_batch",
            cursor=None,
            batch_size=AWB_TRACKING_BATCH_SIZE,
        )
    except Exception:
        cache.delete_value(AWB_TRACKING_RUNNING_KEY)
        raise

    return {"queued": True, "batch_size": AWB_TRACKING_BATCH_SIZE}


def process_awb_tracking_batch(cursor=None, batch_size=AWB_TRACKING_BATCH_SIZE):
    """Process one batch and enqueue the next batch using the document-name cursor."""
    import time
    from datetime import datetime, timedelta
    import requests

    batch_size = max(1, min(int(batch_size), 100))
    filters = {
        "awb_number": ["!=", ""],
        "remark_status": ["!=", "Delivered"],
        "courier_service": ["not in", ["CriticaLog", "Delhivery"]]
    }
    if cursor:
        filters["name"] = [">", cursor]

    docs = frappe.get_all(
        "Delivery Charges",
        filters=filters,
        fields=["name", "awb_number", "remark_status", "courier_service"],
        order_by="name asc",
        limit_page_length=batch_size,
    )

    print(f"AWB tracking batch: {len(docs)} records after cursor {cursor or '<start>'}")

    if not docs:
        frappe.cache().delete_value(AWB_TRACKING_RUNNING_KEY)
        return {"success": 0, "errors": 0, "rate_limits": 0, "total": 0, "complete": True}

    try:
        auth_response = get_auth_token() or {}
        auth_token = auth_response.get("token")
    except Exception:
        frappe.cache().delete_value(AWB_TRACKING_RUNNING_KEY)
        raise

    if not auth_token:
        frappe.cache().delete_value(AWB_TRACKING_RUNNING_KEY)
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
            previous_status = delivery_doc.remark_status

            if current_status:
                delivery_doc.remark_status = current_status
            elif latest_activity:
                delivery_doc.remark_status = latest_activity

            if delivery_doc.remark_status != previous_status:
                delivery_doc.shopify_status_synced = 0

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

    result = {
        "success": success_count,
        "errors": error_count,
        "rate_limits": rate_limit_count,
        "total": len(docs),
        "complete": len(docs) < batch_size,
    }

    if len(docs) == batch_size:
        frappe.cache().set_value(AWB_TRACKING_RUNNING_KEY, 1, expires_in_sec=12 * 60 * 60)
        frappe.enqueue(
            method="nj_features.nj_features.doctype.delivery_charges.delivery_charges.process_awb_tracking_batch",
            queue="long",
            timeout=AWB_TRACKING_JOB_TIMEOUT,
            job_name="shiprocket_awb_tracking_batch",
            cursor=docs[-1].name,
            batch_size=batch_size,
            enqueue_after_commit=True,
        )
        result["next_cursor"] = docs[-1].name
    else:
        frappe.cache().delete_value(AWB_TRACKING_RUNNING_KEY)

    print(f"AWB tracking batch completed: {result}")
    return result

# def update_status_in_shopify():
#     token = "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"
#     base_url = "https://newjaisa.myshopify.com/admin/api/2023-10"

#     # Fetch all Delivery Charges
#     delivery_charges = frappe.get_all("Delivery Charges", fields=["name", "sales_order", "remark_status"])

#     for dc in delivery_charges:
#         shopify_order_number = frappe.db.get_value("Sales Order", dc.sales_order, "shopify_order_number")
#         if not shopify_order_number:
#             continue

#         fulfillment_url = f"{base_url}/orders/{shopify_order_number}/fulfillments.json"
#         headers = {
#             "X-Shopify-Access-Token": token,
#             "Content-Type": "application/json"
#         }

#         try:
#             get_response = requests.get(fulfillment_url, headers=headers)

#             # Check if the response is valid JSON
#             if get_response.status_code != 200:
#                 frappe.logger().error(f"[{dc.name}] Shopify response status: {get_response.status_code}, body: {get_response.text}")
#                 continue

#             if "application/json" not in get_response.headers.get("Content-Type", ""):
#                 frappe.logger().error(f"[{dc.name}] Invalid Content-Type. Response: {get_response.text}")
#                 continue

#             try:
#                 fulfillments = get_response.json().get("fulfillments", [])
#                 # print("fulfillments===================================",fulfillments)
#             except json.JSONDecodeError:
#                 frappe.logger().error(f"[{dc.name}] Failed to parse JSON. Raw Response: {get_response.text}")
#                 continue

#             if not fulfillments:
#                 continue

#             fulfillment = fulfillments[0]
#             fulfillment_id = fulfillment.get("id")
#             if not fulfillment_id:
#                 continue

#             shipment_status_raw = fulfillment.get("shipment_status")
#             shipment_status = shipment_status_raw.lower() if shipment_status_raw else ""

#             if shipment_status == "delivered":
#                 continue

#             shopify_delivery_status = frappe.db.get_value(
#                 "Shopify Status Update",
#                 {
#                     "parent": "Logistics Settings",
#                     "shiprocket_status": dc.remark_status
#                 },
#                 "shopify_delivery_status"
#             )
#             print("shopify_delivery_status=================================",shopify_delivery_status)

#             if not shopify_delivery_status:
#                 logistics_settings = frappe.get_doc("Logistics Settings")
#                 for row in logistics_settings.shopify_status_update:
#                     if (
#                         row.shiprocket_status and
#                         dc.remark_status and
#                         row.shiprocket_status.strip().lower() == dc.remark_status.strip().lower()
#                     ):
#                         shopify_delivery_status = row.shopify_delivery_status
#                         break

#             if not shopify_delivery_status:
#                 frappe.logger().warning(f"[{dc.name}] No Shopify delivery status mapped for remark_status: '{dc.remark_status}'")
#                 continue

#             post_url = f"{base_url}/orders/{shopify_order_number}/fulfillments/{fulfillment_id}/events.json"
#             post_body = {
#                 "event": {
#                     "status": shopify_delivery_status.strip().lower().replace(" ", "_")

#                 }
#             }

#             post_response = requests.post(post_url, headers=headers, json=post_body)
#             if post_response.status_code != 201:
#                 frappe.logger().error(f"[{dc.name}] Failed to post fulfillment event. Status: {post_response.status_code}, Response: {post_response.text}")
#                 continue

#             post_result = post_response.json()
#             print("post second api data==========================================", post_result)

#         except requests.exceptions.RequestException as e:
#             frappe.logger().error(f"[{dc.name}] Shopify API connection error: {str(e)}")
#             continue


# def update_status_in_shopify():
#     """
#     Scheduler entry point.
#     Fetch limited Delivery Charges and enqueue each separately.
#     """

#     delivery_charges = frappe.get_all(
#         "Delivery Charges",
#         filters={
#             "remark_status": ["is", "set"],
#             "shopify_status_synced": 0   # Add this custom checkbox field (recommended)
#         },
#         fields=["name"],
#         limit_page_length=20  # Process only 20 per run
#     )

#     for dc in delivery_charges:
#         frappe.enqueue(
#             "nj_features.nj_features.doctype.delivery_charges.delivery_charges.process_single_delivery_charge",
#             queue="short",
#             timeout=180,
#             dc_name=dc.name
#         )

# import frappe
# import requests


# def process_single_delivery_charge(dc_name):
#     try:
#         print(f"\n===== Processing Delivery Charge: {dc_name} =====")
#         frappe.logger().info(f"Processing Delivery Charge: {dc_name}")

#         dc = frappe.get_doc("Delivery Charges", dc_name)

#         # 🔴 Hardcoded token (testing only)
#         token = "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"

#         base_url = "https://newjaisa.myshopify.com/admin/api/2023-10"

#         shopify_order_number = frappe.db.get_value(
#             "Sales Order",
#             dc.sales_order,
#             "shopify_order_number"
#         )

#         if not shopify_order_number:
#             print(f"[{dc.name}] No Shopify order number found")
#             frappe.logger().error(f"[{dc.name}] No Shopify order number found")
#             return

#         print(f"[{dc.name}] Shopify Order Number: {shopify_order_number}")
#         frappe.logger().info(f"[{dc.name}] Shopify Order Number: {shopify_order_number}")

#         fulfillment_url = f"{base_url}/orders/{shopify_order_number}/fulfillments.json"

#         headers = {
#             "X-Shopify-Access-Token": token,
#             "Content-Type": "application/json"
#         }

#         # ✅ GET Fulfillments
#         print(f"[{dc.name}] Calling Shopify GET API")
#         frappe.logger().info(f"[{dc.name}] Calling Shopify GET API")

#         get_response = requests.get(
#             fulfillment_url,
#             headers=headers,
#             timeout=15
#         )

#         print(f"[{dc.name}] GET Status Code: {get_response.status_code}")
#         frappe.logger().info(f"[{dc.name}] GET Status Code: {get_response.status_code}")

#         if get_response.status_code != 200:
#             print(f"[{dc.name}] Shopify GET failed: {get_response.text}")
#             frappe.logger().error(f"[{dc.name}] Shopify GET failed: {get_response.text}")
#             return

#         fulfillments = get_response.json().get("fulfillments", [])

#         if not fulfillments:
#             print(f"[{dc.name}] No fulfillments found")
#             frappe.logger().warning(f"[{dc.name}] No fulfillments found")
#             return

#         fulfillment = fulfillments[0]
#         fulfillment_id = fulfillment.get("id")

#         print(f"[{dc.name}] Fulfillment ID: {fulfillment_id}")
#         frappe.logger().info(f"[{dc.name}] Fulfillment ID: {fulfillment_id}")

#         shipment_status_raw = fulfillment.get("shipment_status")
#         shipment_status = shipment_status_raw.lower() if shipment_status_raw else ""

#         print(f"[{dc.name}] Shipment Status: {shipment_status}")
#         frappe.logger().info(f"[{dc.name}] Shipment Status: {shipment_status}")

#         # Skip delivered
#         if shipment_status == "delivered":
#             print(f"[{dc.name}] Already delivered. Marking synced.")
#             frappe.logger().info(f"[{dc.name}] Already delivered. Marking synced.")
#             frappe.db.set_value("Delivery Charges", dc.name, "shopify_status_synced", 1)
#             return

#         # 🔎 Mapping status
#         shopify_delivery_status = frappe.db.get_value(
#             "Shopify Status Update",
#             {
#                 "parent": "Logistics Settings",
#                 "shiprocket_status": dc.remark_status
#             },
#             "shopify_delivery_status"
#         )

#         if not shopify_delivery_status:
#             print(f"[{dc.name}] No mapping found for remark_status: {dc.remark_status}")
#             frappe.logger().warning(
#                 f"[{dc.name}] No mapping found for remark_status: {dc.remark_status}"
#             )
#             return

#         print(f"[{dc.name}] Mapped Shopify Status: {shopify_delivery_status}")
#         frappe.logger().info(f"[{dc.name}] Mapped Shopify Status: {shopify_delivery_status}")

#         post_url = f"{base_url}/orders/{shopify_order_number}/fulfillments/{fulfillment_id}/events.json"

#         post_body = {
#             "event": {
#                 "status": shopify_delivery_status.strip().lower().replace(" ", "_")
#             }
#         }

#         # ✅ POST Fulfillment Event
#         print(f"[{dc.name}] Calling Shopify POST API")
#         frappe.logger().info(f"[{dc.name}] Calling Shopify POST API")

#         post_response = requests.post(
#             post_url,
#             headers=headers,
#             json=post_body,
#             timeout=15
#         )

#         print(f"[{dc.name}] POST Status Code: {post_response.status_code}")
#         frappe.logger().info(f"[{dc.name}] POST Status Code: {post_response.status_code}")

#         if post_response.status_code != 201:
#             print(f"[{dc.name}] Shopify POST failed: {post_response.text}")
#             frappe.logger().error(
#                 f"[{dc.name}] Shopify POST failed: {post_response.text}"
#             )
#             return

#         frappe.db.set_value("Delivery Charges", dc.name, "shopify_status_synced", 1)

#         print(f"[{dc.name}] ✅ Shopify status updated successfully")
#         frappe.logger().info(f"[{dc.name}] Shopify status updated successfully")

#     except requests.exceptions.Timeout:
#         print(f"[{dc_name}] Shopify request timed out")
#         frappe.logger().error(f"[{dc_name}] Shopify request timed out")

#     except requests.exceptions.RequestException as e:
#         print(f"[{dc_name}] Shopify connection error: {str(e)}")
#         frappe.logger().error(f"[{dc_name}] Shopify connection error: {str(e)}")

#     except Exception as e:
#         print(f"[{dc_name}] Unexpected error: {str(e)}")
#         frappe.logger().error(f"[{dc_name}] Unexpected error: {str(e)}")
SHOPIFY_STATUS_BATCH_SIZE = 20
SHOPIFY_STATUS_JOB_TIMEOUT = 1200
SHOPIFY_STATUS_RUNNING_KEY = "update_status_in_shopify_running"


def update_status_in_shopify():
    """Scheduler entry point: queue one non-overlapping Shopify sync chain."""
    cache = frappe.cache()
    if cache.get_value(SHOPIFY_STATUS_RUNNING_KEY):
        print("Shopify status sync is already queued or running; skipping this scheduler run.")
        return {"queued": False, "reason": "already_running"}

    cache.set_value(SHOPIFY_STATUS_RUNNING_KEY, 1, expires_in_sec=12 * 60 * 60)
    try:
        frappe.enqueue(
            method="nj_features.nj_features.doctype.delivery_charges.delivery_charges.process_shopify_status_batch",
            queue="long",
            timeout=SHOPIFY_STATUS_JOB_TIMEOUT,
            job_name="delivery_charges_shopify_status_batch",
            cursor=None,
            batch_size=SHOPIFY_STATUS_BATCH_SIZE,
        )
    except Exception:
        cache.delete_value(SHOPIFY_STATUS_RUNNING_KEY)
        raise

    return {"queued": True, "batch_size": SHOPIFY_STATUS_BATCH_SIZE}


def process_shopify_status_batch(cursor=None, batch_size=SHOPIFY_STATUS_BATCH_SIZE):
    shopify_settings = frappe.get_single("NJ Inventory Settings")
    token = shopify_settings.token
    shop = (shopify_settings.shop or "").strip().rstrip("/")
    if not token or not shop:
        frappe.cache().delete_value(SHOPIFY_STATUS_RUNNING_KEY)
        frappe.throw("Shopify shop or access token is missing in NJ Inventory Settings.")

    if not shop.startswith(("http://", "https://")):
        shop = f"https://{shop}"
    base_url = f"{shop}/admin/api/2026-10"

    batch_size = max(1, min(int(batch_size), 100))
    ALREADY_DONE_STATUSES = {"delivered"}
    filters = {"remark_status": ["!=", ""], "shopify_status_synced": 0}
    if cursor:
        filters["name"] = [">", cursor]

    delivery_charges = frappe.get_all(
        "Delivery Charges",
        filters=filters,
        fields=["name", "sales_order", "remark_status"],
        limit_page_length=batch_size,
        order_by="name asc"
    )

    print(f"Shopify status batch: {len(delivery_charges)} records after cursor {cursor or '<start>'}")

    if not delivery_charges:
        frappe.cache().delete_value(SHOPIFY_STATUS_RUNNING_KEY)
        return {"processed": 0, "complete": True}

    # Pre-fetch all Shopify status mappings ONCE
    logistics_settings = frappe.get_doc("Logistics Settings")
    status_map = {
        row.shiprocket_status.strip().lower(): row.shopify_delivery_status
        for row in logistics_settings.shopify_status_update
        if row.shiprocket_status
    }

    print(f"Status Map Loaded: {status_map}")

    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    session = requests.Session()

    for dc in delivery_charges:
        print(f"\n--- Processing: {dc.name} | Sales Order: {dc.sales_order} | Remark Status: {dc.remark_status} ---")

        shopify_order_number = frappe.db.get_value("Sales Order", dc.sales_order, "shopify_order_number")
        print(f"[{dc.name}] Shopify Order Number: {shopify_order_number}")

        if not shopify_order_number:
            print(f"[{dc.name}] Skipping — no Shopify order number found")
            continue

        shopify_delivery_status = status_map.get(
            dc.remark_status.strip().lower() if dc.remark_status else ""
        )
        print(f"[{dc.name}] Mapped Shopify Delivery Status: {shopify_delivery_status}")

        if not shopify_delivery_status:
            print(f"[{dc.name}] Skipping — no status mapped for remark_status: '{dc.remark_status}'")
            frappe.logger().warning(f"[{dc.name}] No status mapped for: '{dc.remark_status}'")
            continue

        try:
            # GET fulfillments
            fulfillment_url = f"{base_url}/orders/{shopify_order_number}/fulfillments.json"
            print(f"[{dc.name}] GET Request URL: {fulfillment_url}")
            get_response = session.get(fulfillment_url, headers=headers, timeout=15)
            print(f"[{dc.name}] GET Response Status: {get_response.status_code}")

            if get_response.status_code != 200:
                print(f"[{dc.name}] GET failed — Status: {get_response.status_code}, Body: {get_response.text}")
                frappe.logger().error(f"[{dc.name}] GET failed: {get_response.status_code}")
                continue

            try:
                fulfillments = get_response.json().get("fulfillments", [])
                print(f"[{dc.name}] Fulfillments found: {len(fulfillments)}")
            except json.JSONDecodeError:
                print(f"[{dc.name}] Failed to parse JSON. Raw Response: {get_response.text}")
                frappe.logger().error(f"[{dc.name}] Failed to parse JSON. Raw Response: {get_response.text}")
                continue

            if not fulfillments:
                print(f"[{dc.name}] Skipping — no fulfillments found")
                continue

            fulfillment = fulfillments[0]
            fulfillment_id = fulfillment.get("id")
            print(f"[{dc.name}] Fulfillment ID: {fulfillment_id}")

            if not fulfillment_id:
                print(f"[{dc.name}] Skipping — no fulfillment ID")
                continue

            shipment_status = (fulfillment.get("shipment_status") or "").lower()
            print(f"[{dc.name}] Current Shipment Status: {shipment_status}")

            if shipment_status in ALREADY_DONE_STATUSES:
                print(f"[{dc.name}] Already delivered — marking as synced and skipping")
                frappe.db.set_value("Delivery Charges", dc.name, "shopify_status_synced", 1)
                frappe.db.commit()
                continue

            # POST fulfillment event
            post_url = f"{base_url}/orders/{shopify_order_number}/fulfillments/{fulfillment_id}/events.json"
            post_body = {
                "event": {
                    "status": shopify_delivery_status.strip().lower().replace(" ", "_")
                }
            }
            print(f"[{dc.name}] POST Request URL: {post_url}")
            print(f"[{dc.name}] POST Request Body: {post_body}")

            post_response = session.post(post_url, headers=headers, json=post_body, timeout=15)
            print(f"[{dc.name}] POST Response Status: {post_response.status_code}")
            print(f"[{dc.name}] POST Response Body: {post_response.text}")

            if post_response.status_code != 201:
                print(f"[{dc.name}] POST failed — Status: {post_response.status_code}, Body: {post_response.text}")
                frappe.logger().error(f"[{dc.name}] POST failed: {post_response.status_code} — {post_response.text}")
                continue

            print(f"[{dc.name}] Successfully synced to Shopify with status: {shopify_delivery_status}")
            frappe.logger().info(f"[{dc.name}] Successfully synced to Shopify with status: {shopify_delivery_status}")

            # Mark as synced
            frappe.db.set_value("Delivery Charges", dc.name, "shopify_status_synced", 1)
            frappe.db.commit()
            print(f"[{dc.name}] Marked as shopify_status_synced = 1")

        except requests.exceptions.Timeout:
            print(f"[{dc.name}] Timeout on Shopify API")
            frappe.logger().error(f"[{dc.name}] Timeout on Shopify API")
            continue
        except requests.exceptions.RequestException as e:
            print(f"[{dc.name}] Request error: {str(e)}")
            frappe.logger().error(f"[{dc.name}] Request error: {str(e)}")
            continue

    result = {
        "processed": len(delivery_charges),
        "complete": len(delivery_charges) < batch_size,
    }
    if len(delivery_charges) == batch_size:
        frappe.cache().set_value(SHOPIFY_STATUS_RUNNING_KEY, 1, expires_in_sec=12 * 60 * 60)
        frappe.enqueue(
            method="nj_features.nj_features.doctype.delivery_charges.delivery_charges.process_shopify_status_batch",
            queue="long",
            timeout=SHOPIFY_STATUS_JOB_TIMEOUT,
            job_name="delivery_charges_shopify_status_batch",
            cursor=delivery_charges[-1].name,
            batch_size=batch_size,
            enqueue_after_commit=True,
        )
        result["next_cursor"] = delivery_charges[-1].name
    else:
        frappe.cache().delete_value(SHOPIFY_STATUS_RUNNING_KEY)

    print(f"Shopify status batch completed: {result}")
    return result
