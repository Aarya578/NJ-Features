import requests as rs
import frappe
import json
from frappe.utils.password import get_decrypted_password

ORDER_URL = "https://apiv2.shiprocket.in/v1/external/orders?filter_by=channel_order_id&filter="
COURIER_AVAILABILITY = "https://apiv2.shiprocket.in/v1/external/courier/serviceability/"
GENERATE_AWB_TOKEN = "https://apiv2.shiprocket.in/v1/external/courier/assign/awb/"
ORDER_PICKUP = "https://apiv2.shiprocket.in/v1/external/courier/generate/pickup"
GENERATE_LABEL = "https://apiv2.shiprocket.in/v1/external/courier/generate/label"
AUTH_URL = "https://apiv2.shiprocket.in/v1/external/auth/login"
CACHE_KEY = "shiprocket_auth_token"
TOKEN_TTL_SECONDS = 10 * 24 * 60 * 60  # 10 days in seconds
@frappe.whitelist(allow_guest=True)
def get_auth_token(force_refresh=False):
    try:
        # Check cache if force_refresh is not requested
        if force_refresh:
            frappe.cache().delete_value(CACHE_KEY)
        else:
            cached_token = frappe.cache().get_value(CACHE_KEY)
            if cached_token:
                # Check JWT expiration
                try:
                    import base64, time
                    parts = cached_token.split(".")
                    if len(parts) == 3:
                        payload_b64 = parts[1] + ("=" * (-len(parts[1]) % 4))
                        payload_data = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
                        exp = payload_data.get("exp")
                        if exp and exp <= (time.time() + 60):
                            frappe.cache().delete_value(CACHE_KEY)
                            cached_token = None
                except Exception:
                    pass

            if cached_token:
                print(f"Using cached token: {cached_token[:20]}..." if len(cached_token) > 20 else cached_token)
                return {"token": cached_token, "source": "cache"}
            
        # Get settings and login
        settings = frappe.get_single("Ship Rocket Settings")
        email = settings.email
        password = get_decrypted_password("Ship Rocket Settings", "Ship Rocket Settings", "password")
        
        print(f"Attempting login with email: {email}")
        
        loginheaders = {
            "Content-Type": "application/json"
        }
        
        login_data = {"email": email, "password": password}
        print(f"Login payload: {login_data}")
        
        response = rs.post(AUTH_URL, headers=loginheaders, json=login_data)
        
        print(f"Auth response status: {response.status_code}")
        print(f"Auth response content: {response.text}")
        
        if response.status_code != 200:
            frappe.throw(f"Failed to authenticate with ShipRocket: {response.text}")
            
        response_data = response.json()
        token = response_data.get("token")
        
        if not token:
            frappe.throw(f"Token not found in response: {response.text}")
            
        print(f"Received fresh token: {token[:20]}..." if len(token) > 20 else token)
        print(f"Token segments count: {len(token.split('.'))}")
        
        # Validate JWT format (should have 3 segments separated by dots)
        if len(token.split('.')) != 3:
            frappe.throw(f"Invalid JWT token format. Expected 3 segments, got {len(token.split('.'))}. Token: {token}")
            
        # Cache the token for 10 days
        frappe.cache().set_value(CACHE_KEY, token, expires_in_sec=TOKEN_TTL_SECONDS)
        return {"token": token, "source": "fresh"}
        
    except Exception as e:
        frappe.log_error(f"Auth token error: {str(e)}", "ShipRocket Auth")
        frappe.throw(f"Error getting auth token: {str(e)}")


@frappe.whitelist(allow_guest=True)
def get_order_data(order_id):
    try:
        auth_token = get_auth_token().get("token")
        print("auth_token:", auth_token)
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "App-Version": "3.4.2",
            "Content-Type": "application/json"
        }
        response = rs.get(f"{ORDER_URL}{order_id}", headers=headers)
        # print("response:", response.json())
        return response.json()
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in get_order_data")
        return {"error": str(e)}
    
@frappe.whitelist(allow_guest=True)
def check_courie_service(order_id):
    try:
        auth_token = get_auth_token().get("token")
        print("auth_token:----55", auth_token)
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "App-Version": "3.4.2",
            "Content-Type": "application/json"
        }
        courier_data = get_order_data(order_id)
        pickup_postcode = courier_data['data'][0]['pickup_address_detail'].get('pin_code')
        print("pickup_postcode:------------", pickup_postcode)
        customer_pincode = courier_data['data'][0].get('customer_pincode')
        shipment_id = courier_data['data'][0]['shipments'][0].get('id')
        weight = courier_data['data'][0]['shipments'][0].get('volumetric_weight') or courier_data['data'][0]['shipments'][0].get('weight')
        print("weight:------------55", weight,"customer_pincode:----------",customer_pincode)
        cod = courier_data['data'][0].get('cod')
        print("pickup_postcode:------------61", pickup_postcode,"customer_pincode-------",customer_pincode,"weight:",weight,"cod:",cod)
        body={
            "pickup_postcode": pickup_postcode,
            "weight": weight,
            "cod": cod,
            "delivery_postcode": customer_pincode
        }
        response = rs.get(f"{COURIER_AVAILABILITY}", headers=headers,json=body)
        response_data = response.json()
        # print("response:", response.json())
        if 'data' in response_data and 'available_courier_companies' in response_data['data']:
            courier_name_erp = frappe.db.sql("select * from `tabShipment Packages` where weight=%s",2,as_dict=1)
            print("courier_name_erp:", courier_name_erp)
            sorted_couriers = sorted(
                response_data['data']['available_courier_companies'],
                key=lambda x: (-x.get('rating', 0), x.get('rate', float('inf')))
            )
            print("sorted_couriers:----------", sorted_couriers)
            # Replace the original list with the sorted list
            # response_data['data']['available_courier_companies'] = sorted_couriers
            courier_company_id =  sorted_couriers[0].get('courier_company_id')
            awb = generate_awb(shipment_id, courier_company_id)
            print("awb:-----------89", awb)
            label = generate_label(shipment_id)
            return {'awb':awb,'label':label}
            # return {"courier_company_id": sorted_couriers[0].get('courier_company_id')}

            # return response_data['data']['available_courier_companies']

        return None
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in check_courie_service")
        return {"error": str(e)}
@frappe.whitelist(allow_guest=True)
def generate_awb(shipment_id):
    try:
        print("shipment_id:---------102", shipment_id,"courier_company_id:---102")
        auth_token = get_auth_token().get("token")
        print("auth_token:----55", auth_token)
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "App-Version": "3.4.2",
            "Content-Type": "application/json"
        }
        body = {
            "shipment_id": shipment_id,
            
        }
        response = rs.post(GENERATE_AWB_TOKEN, headers=headers, json=body)
        response_data = response.json()
        print("response:--------116", response.json())
        return response_data
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in generate_awb")
        print("error in generating awb in dn ------118",e)
        return {"error": str(e)}
    
@frappe.whitelist(allow_guest=True)
def get_so_data(doc,method=None):
    print("hii inside submit")
    print("doc.ship_rocket_reqd",doc.ship_rocket_reqd)
    try:
        auth_token = get_auth_token().get("token")
        print("auth_token:----55", auth_token)
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "App-Version": "3.4.2",
            "Content-Type": "application/json"
        }
        response = rs.get(f"{ORDER_URL}{doc.name}", headers=headers)
        # print("response:", response.json())
        return response.json()
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in get_so_data")
        return {"error": str(e)}
@frappe.whitelist(allow_guest=True)
def generate_label(shipment_id):
    print("shipment_id:---------102", shipment_id,)
    try:
        auth_token = get_auth_token().get("token")
        print("auth_token:----55", auth_token)
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "App-Version": "3.4.2",
            "Content-Type": "application/json"
        }
        body = {
            "shipment_id":[ shipment_id],
        }
        response = rs.post(GENERATE_LABEL, headers=headers, json=body)
        response_data = response.json()
        print("response:--------159", response.json())
        return response_data
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in generate_awb")
        print("error in generating awb in dn ------118",e)
        return {"error": str(e)}
# @frappe.whitelist(allow_guest=True)
# def get_auth_token():
#     try:
#         settings = frappe.get_single("Ship Rocket Settings")
#         email = settings.user 
        
#         password = get_decrypted_password("Ship Rocket Settings", "Ship Rocket Settings", "password")

#         print(f"Email: {email}, Password: {password}")  
#         loginheaders = {
#                 "App-Version": "3.4.2",
#                 "Content-Type": "application/json"
#             }
#         response = rs.post(AUTH_URL, headers=loginheaders, json={"email": email, "password": password})

#         print("Response:", response.json())  
#         return response.json()

#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), "Error in get_auth_token")
#         return {"error": str(e)}
