# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

# import frappe
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
from frappe.model.document import Document
from nj_features.nj_features.api.shiprocket_api import get_auth_token,generate_awb,generate_label

class LogisticsSettings(Document):
	pass



@frappe.whitelist()
def shiprocket_shiprocket_courier_name(doc):
    import json
    import requests
    
    doc = frappe._dict(json.loads(doc))
    print("doc:----55===============================================", doc)
    
    auth_token = get_auth_token().get("token")
    print("auth_token:----55===============================================", auth_token)
    
    if not auth_token:
        frappe.throw("Authentication token could not be retrieved from Shiprocket.")
    
    url = "https://apiv2.shiprocket.in/v1/external/courier/courierListWithCounts"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token.strip()}"
    }
    
    # Optional: define request data, even empty dict if not required
    data = {}
    
    try:
        response = requests.get(url, headers=headers, json=data)
        response_data = response.json()
        print("response:----55===============================================", response_data)
        
        # Check if response is successful
        if response.status_code == 200 and 'courier_data' in response_data:
            # Get the parent document
            parent_doc = frappe.get_doc("Logistics Settings", doc.get("name"))
            
            # Clear existing child table records
            parent_doc.set("shiprocket_courier_names", [])
            
            # Add new records from API response
            for courier in response_data['courier_data']:
                child_row = parent_doc.append("shiprocket_courier_names", {})
                child_row.courier_name = courier.get('name', '')  # Map name to courier_name (Data field)
                child_row.courier_id = courier.get('id', 0)       # Map id to courier_id (Int field)
            
            # Save the document
            parent_doc.save()
            frappe.db.commit()
            
            frappe.msgprint(f"Successfully updated {len(response_data['courier_data'])} courier records.")
            
            return {
                "status": "success",
                "message": f"Successfully fetched and stored {len(response_data['courier_data'])} courier records",
                "total_couriers": response_data.get('total_courier_count', 0)
            }
        else:
            frappe.throw(f"API Error: {response.status_code} - {response.text}")
            
    except requests.exceptions.RequestException as e:
        frappe.log_error(frappe.get_traceback(), "Shiprocket API Request Error")
        frappe.throw(f"Network error while fetching courier data: {str(e)}")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Shiprocket Courier Name Fetch Error")
        frappe.throw(f"Error fetching courier name: {str(e)}")
