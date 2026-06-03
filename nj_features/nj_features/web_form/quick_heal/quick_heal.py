from __future__ import unicode_literals
import re
import frappe

def get_context(context):
	# do your magic here
	pass

@frappe.whitelist()
def check_order_id(order_id):      
    serial_no_set = set()
    order_id_fields = frappe.db.get_value('NJ Settings', {'doc_type': 'Laptop Registration', 'parameter': 'order_id_fields'}, 'value')

    if order_id_fields:
        if ',' in order_id_fields:
            fieldnames = order_id_fields.split(',')
            for fieldname in fieldnames:
                fieldname = fieldname.strip()
                is_order_id_exists = frappe.db.exists('Sales Order', {fieldname: order_id, 'docstatus': 1})
                
                if is_order_id_exists:
                    items = frappe.db.get_list('Delivery Note Item', {'against_sales_order': is_order_id_exists, 'docstatus': 1}, 'serial_no')
                    for item in items:
                        if item.get('serial_no'):
                            serial_no_set.add(item.get('serial_no'))
        else:
            fieldname = order_id_fields.strip()
            is_order_id_exists = frappe.db.exists('Sales Order', {fieldname: order_id, 'docstatus': 1})
            
            if is_order_id_exists:
                items = frappe.db.get_list('Delivery Note Item', {'against_sales_order': is_order_id_exists, 'docstatus': 1}, 'serial_no')
                for item in items:
                    if item.get('serial_no'):
                        serial_no_set.add(item.get('serial_no'))
                        
    if not serial_no_set:
        return None
    return serial_no_set

@frappe.whitelist()
def find_laptop_registration(serial_no):
    registrated_serial_no = frappe.db.exists('Laptop Registration', {'serial_no': serial_no})
    if registrated_serial_no:
        return serial_no
    return "LR not found for Serial No."

@frappe.whitelist()
def validate_phone_no(phone_no):
    """Returns True if valid phone number"""
    if not phone_no:
        return False

    phone_number = phone_no.strip()
    match = re.match(r"([0-9\ \+\_\-\,\.\*\#\(\)]){1,20}$", phone_number)

    if not match or len(re.sub(r'\D', '', phone_number)) != 10:
        frappe.throw(
            frappe._("{0} is not a valid Phone Number").format(phone_number)
        )
        return False

    return True