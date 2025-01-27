import traceback
import requests as rs
import frappe
import json

def get_grading_Authentication(doc, method=None):
    try:
        inspection_type=frappe.db.get_value("NJ Settings",{'parameter':'bb_inspection_type'},'value')
        # print("inspection_type",inspection_type,doc.inspection_type)
        if doc.inspection_type==inspection_type:
            url=frappe.db.get_value("NJ Settings",{'parameter':'bb_login_url'},'value')
            username=frappe.db.get_value("NJ Settings",{'parameter':'bb_userID'},'value')
            data_url=frappe.db.get_value("NJ Settings",{'parameter':'bb_data_url'},'value')
            password=frappe.db.get_value("NJ Settings",{'parameter':'bb_password'},'value')
            
            print(url)
            print(username)
            print(password)
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
                    print("grading results",grading_results)
                    results = extract_values(grading_results)
                    if not results:
                        frappe.throw("No BB tool results found for this serial number")

                    for result in results:
                        if isinstance(result, dict):
                            if type(result['value']) == str:
                                if 'value' in result and len(result['value']) > 140:
                                    result['value'] = result['value'][:140]  # Truncate to 140 characters

                    for result in results:
                        doc.append('njqca_result_parameters', result)

                
                
    except Exception as e:
        print("Error in get_grading_Authentication", str(e))
        return traceback.format_exc()
    
def extract_values(data, result=None):
    if result is None:
        result = []

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                result.extend(extract_values(value))
            else:
                result.append({
                    "parameter": key,
                    "value": value,
                })
    elif isinstance(data, list):
        for item in data:
            result.extend(extract_values(item))

    return result


   
   




























    

  