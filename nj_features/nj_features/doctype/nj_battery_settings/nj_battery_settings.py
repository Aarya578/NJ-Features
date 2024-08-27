import json
import frappe
from frappe.model.document import Document

class NJBatterySettings(Document):
    pass     

@frappe.whitelist()
def update_nj_battery_settings(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)
    
    fields = {
        "battery_video_file": "BatteryVideoFile",
        "max_charging_time": "MAX_Charging_Time",
        "max_discharging_time": "MAX_discharging_Time",
        "percentage_checking_time": "Percentage_Checking_Time"
    }
    
    for field_key, field_value in fields.items():
        set_nj_settings(field_value, doc, field_key)

def set_nj_settings(field_value, doc, field_key):
    nj_settings_record = frappe.db.get_value('NJ Settings', 
        {'parameter': field_value, 'department': doc.get('department')}, 'name')

    if nj_settings_record:
        new_value = doc.get(field_key, None)
        if new_value is not None:
            frappe.db.set_value('NJ Settings', nj_settings_record, 'value', new_value)
    else:
        frappe.throw(f"No NJ Settings found for field: {field_value} and department: {doc.get('department')}")
        
@frappe.whitelist()
def get_nj_settings(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)
        
    result = {}
    fields = {
        "battery_video_file": "BatteryVideoFile",
        "max_charging_time": "MAX_Charging_Time",
        "max_discharging_time": "MAX_discharging_Time",
        "percentage_checking_time": "Percentage_Checking_Time"
    }
        
    for field_key, field_value in fields.items():
        nj_settings_record = frappe.db.get_value('NJ Settings', 
            {'parameter': field_value, 'department': doc.get('department')}, 'value')

        if nj_settings_record:
            result[field_key] = nj_settings_record

    return result