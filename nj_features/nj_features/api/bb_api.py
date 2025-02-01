import traceback
import requests as rs
import frappe
import json

def get_grading_Authentication(doc, method=None):
    try:
        print("entered this method ----------get_grading_Authentication-")
        inspection_type=frappe.db.get_value("NJ Settings",{'parameter':'bb_inspection_type'},'value')
        # print("inspection_type",inspection_type,doc.inspection_type)
        if doc.inspection_type==inspection_type:
            url=frappe.db.get_value("NJ Settings",{'parameter':'bb_login_url'},'value')
            username=frappe.db.get_value("NJ Settings",{'parameter':'bb_userID'},'value')
            data_url=frappe.db.get_value("NJ Settings",{'parameter':'bb_data_url'},'value')
            password=frappe.db.get_value("NJ Settings",{'parameter':'bb_password'},'value')
            
            # print(url)
            # print(username)
            # print(password)
            if(not url or not username or not password):
                frappe.throw("Please set the BB login url, username and password in NJ Settings")
                return
            
            loginurl=url
            loginheaders = {
                "App-Version": "3.4.2",
                "Content-Type": "application/json"
            }
            

            loginbody= {
                "user": {
                    "email": username,
                    "password": password
                }
            }
            # print("loginbody",loginbody,type(loginbody))
            loginresponse = rs.post(loginurl, headers=loginheaders, json=loginbody)
            # print("loginresponse header",loginresponse.headers)
            if loginresponse.status_code == 200:
                # print("loginresponse header",loginresponse.headers)
                # print("loginresponse header",loginresponse.headers.get("Authorization"))
                token=loginresponse.headers.get("Authorization")
                
                # print(loginresponse.json())
                # tokendata=loginresponse.json()
                # jsontoken=json.load(tokendata)
                # token=jsontoken.get("Token")

                if(token):
                    result_headers={
                        "Authorization":token
                    }
                bios_serial_no=doc.bios_serialno
                # print("bios number:",bios_serial_no)
            
                params={
                    "serial_number":bios_serial_no
                }

                resultresponse=rs.get(data_url,params=params,headers=result_headers)

                if resultresponse.status_code==200:
                    # print(resultresponse, type(resultresponse))
                    grading_results=resultresponse.json()
                    print("grading results------------65-----------",grading_results)
                    results = extract_test_values(grading_results)
                    # print("results------------68-----------",results)
                    if not results:
                        frappe.throw("No BB tool results found for this serial number")
                        return

                    for result in results:
                        print("results are adding to the table -----------74")
                        doc.append('njqca_result_parameters', {
                            "parameter": result["parameter"],
                            "value": result["value"],
                            "item_group": result.get("item_group", "") ,
                            "score": result["score"]

                        })
 
    except Exception as e:
        print("Error in get_grading_Authentication", str(e))
        return traceback.format_exc()
    

def extract_test_values(data):
    """
    Extracts test results and Battery Health % from the grading data
    Returns a list of dictionaries with parameter, value, item_group, and score
    """
    result = []
    item_group_mapping = get_item_group_mapping()

    if isinstance(data, dict) and 'grading_results' in data:
        for grading_result in data['grading_results']:
            if 'details' in grading_result:
                battery_health_value = None
                
                # First, find Battery Health % in System Info
                for detail in grading_result['details']:
                    if isinstance(detail, dict) and 'System Info' in detail:
                        system_info = detail['System Info']
                        if 'Battery Health %' in system_info:
                            battery_health_value = system_info['Battery Health %']
                            result.append({
                                "parameter": "Battery Health %",
                                "value": battery_health_value,
                                "item_group": "BATTERY",
                                "score": 0  
                            })
                
                # Then process Tests data
                for detail in grading_result['details']:
                    if isinstance(detail, dict) and 'Tests' in detail:
                        tests = detail['Tests']
                        for test_key, test_value in tests.items():
                            result.append({
                                "parameter": test_key,
                                "value": test_value,
                                "item_group": item_group_mapping.get(test_key, "MISC"),
                                "score": get_score_for_value(test_value)
                            })
    return result

def get_item_group_mapping():
    """Returns a dictionary mapping test parameters to their corresponding item groups"""
    return {
        "CPU": "Laptops",
        "RAM": "LAPTOP RAM",
        "BIOS": "MOTHERBOARD",
        "Disk": "LAPTOP STORAGE",
        "Wifi": "WIFI CARD",
        "Video": "CAMERA",
        "Camera": "CAMERA",
        "Memory": "LAPTOP RAM",
        "Battery": "BATTERY",
        "Speaker": "SPEAKER",
        "Keyboard": "KEYBOARD",
        "Bluetooth": "WIFI CARD",
        "Processor": "Laptops",
        "Touch Pad": "TOUCHPAD",
        "Audio Jack": "SPEAKER",
        "Dead Pixel": "DISPLAY",
        "Sound Card": "SPEAKER",
        "MotherBoard": "MOTHERBOARD",
        "Motherboard": "MOTHERBOARD",
        "Temperature": "MOTHERBOARD",
        "USB Devices": "MOTHERBOARD",
        "Charging Port": "MOTHERBOARD",
        "Graphics Card": "Laptops",
        "Battery Charge": "BATTERY",
        "Optical Driver": "MOTHERBOARD",
        "Stress Battery": "BATTERY",
        "Network Adapter": "BATTERY",
        "Battery Health %": "BATTERY",
        "Storage Controller": "LAPTOP STORAGE",
        "Ethernet Controller": "MOTHERBOARD",
        "Heating Temperature": "MOTHERBOARD",
        "Battery Health %": "BATTERY",
    }


def get_score_for_value(value):
    """Returns score based on test value"""
    if value == "Pass":
        return 0
    elif value in ["Fail", "N/A"]:
        return 41
    return 0  