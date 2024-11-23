import os
import json
import frappe
import random

@frappe.whitelist()
def on_submit(doc, handler=""):
    crt_amzsl_inv(doc.name)
   # crt_amzdn(doc.name)

@frappe.whitelist()
def crt_amzsl_inv(sales_order_name):
    so = frappe.get_doc("Sales Order", sales_order_name)
    if so.naming_series == "SO-Amazon-" and so.order_type == "Sales":
        si = frappe.new_doc("Sales Invoice")
        si.update({ 
            "customer": so.customer,
            "naming_series": 'SINV-',
            "sales_channel": 'Amazon',
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.add_days(frappe.utils.today(), 30),  # Adjust the due date as needed
            "items": []
        })
        for item in so.items:
            si.append("items", {
                "item_code": item.item_code,
                "rate": item.rate,
                "qty": item.qty,
                "sales_order": sales_order_name
            })
        si.insert(ignore_permissions=True)
        si.save()
        frappe.msgprint(frappe._("Sales invoice created",si.name), indicator="green", alert=True)
        # frappe.db.commit()
        return si.name
    else:
        pass

@frappe.whitelist()
def search_for_serial_or_batch_or_barcode_no(search_value):
    serial_no_data = frappe.db.get_value(
        "Serial No", search_value, 
        ["name as serial_no", "item_code", "warehouse", "delivery_document_no", "delivery_document_type"], 
        as_dict=True
    )
    if serial_no_data and (serial_no_data.get("delivery_document_type") or serial_no_data.get("delivery_document_no")):
        return {"message": "Delivered items can't be moved"}
    
    if serial_no_data:
        return {"serial_no": serial_no_data.get("serial_no"), "item_code": serial_no_data.item_code, "warehouse": serial_no_data.warehouse, "scan": 0}

    return {"scan": 1}


@frappe.whitelist()
def serializer_or_notserializer(item_code=None):
    if item_code:
        has_serial_no = frappe.db.get_value(
            "Item", {"name": item_code}, ["has_serial_no"], as_dict=True
        )
        return has_serial_no.has_serial_no if has_serial_no else 0
    return 0  # Return 0 if item code or has_serial_no is not found or is None

# Barcode Printing in Purchase Receipt:

# def generate_and_save_barcode(serial_no, format='png'):
#     my_code = Code128(serial_no, writer=CustomImgWriter())

#     # Create BytesIO to store barcode SVG
#     barcode_bytes = BytesIO()
#     my_code.write(barcode_bytes)

#     # Set the directory to save the file
#     base_directory = frappe.get_site_path("public", "files")
#     file_path = os.path.join(base_directory, f"{serial_no}.{format}")

#     # Check if the file already exists
#     if os.path.exists(file_path):
#         os.remove(file_path)

#     # Save the SVG content to a file
#     with open(file_path, 'wb') as f:
#         f.write(barcode_bytes.getvalue())

@frappe.whitelist()
def get_max_cop(item_code, serial_no, print_cpy):
    item_group = frappe.get_value('Item', {'name': item_code}, 'item_group')
    
    # width = frappe.get_value('Item Group', {'name': item_group}, 'width')
    # height = frappe.get_value('Item Group', {'name': item_group}, 'height')
    max_cop = frappe.get_value('Item Group', {'name': item_group}, 'maximum_copy')
    print_format = frappe.get_value('Item Group', {'name': item_group}, 'print_format')
    
    try:
        # Parse the serial_no string as a JSON array
        serial_numbers = json.loads(serial_no)
        
        # Check if serial_numbers is a list
        if isinstance(serial_numbers, list):
            for sn in serial_numbers:
                serialno_doc = frappe.get_doc("Serial No", sn.strip())  # Strip to remove whitespace
                if serialno_doc:
                    serialno_doc.last_qr_count = int(print_cpy)
                    serialno_doc.save()
                else:
                    frappe.msgprint(f"Serial No.: <strong>{sn}</strong> not found.")
        else:  # If only one serial_no is passed
            serialno_doc = frappe.get_doc("Serial No", serial_no)
            if serialno_doc:
                serialno_doc.last_qr_count = int(print_cpy)
                serialno_doc.save()
            else:
                frappe.msgprint(f"Serial No.: <strong>{serial_no}</strong> not found.")
    except json.JSONDecodeError:
        
        serialno_doc = frappe.get_doc("Serial No", serial_no)
        if serialno_doc:
            serialno_doc.last_qr_count = int(print_cpy)
            serialno_doc.save()
        else:
            frappe.msgprint(f"Serial No.: <strong>{serial_no}</strong> not found.")
    
    return max_cop, print_format

@frappe.whitelist()
def create_reason_copy(serial_no, item_code, name, copies, reason, comment, doctype):
    #max_cop = frappe.get_value('Item', {'name': item_code}, 'maximum_copy')
    #if float(copies) > float(max_cop):
        #reason = frappe.get_prompt("Select the Reason", "reason", fieldtype="Link", options="cancel Reason")
        # comment = frappe.get_prompt("comment: ")
    new_doc = frappe.new_doc("Deviation History")
    new_doc.user = frappe.session.user
    new_doc.reason = reason
    new_doc.comment = comment
    new_doc.serial_no = serial_no
    new_doc.item_code = item_code
    new_doc.referance_doctype = doctype
    new_doc.document_name = name
    new_doc.save()
    return new_doc.name

# @frappe.whitelist()
# def battery_data(bios_serial_no):
#     serialno_doc = frappe.get_doc("Serial No", {"bios_serial_no": bios_serial_no})
    
#     if not serialno_doc:
#         frappe.throw("Serial No document not found for the given BIOS serial number.")
    
#     # Retrieve data from the serial_no_component table
#     serial_no_components = []
#     if hasattr(serialno_doc, 'serial_no_component'):
#         for component in serialno_doc.serial_no_component:
#             serial_no_components.append({
#                 "component_name": component.component_name,
#                 "component_serial_no": component.component_serial_no,
#                 "status": component.status
#             })
    
#     return serial_no_components
# @frappe.whitelist(allow_guest=True)
# def battery_data():
#     bios_serial_no = frappe.local.form_dict.get('bios_serial_no')
    
#     if not bios_serial_no:
#         frappe.throw("BIOS Serial No is required.")
    
#     serialno_doc = frappe.get_doc("Serial No", {"bios_serial_no": bios_serial_no})
    
#     if not serialno_doc:
#         frappe.throw("Serial No document not found for the given BIOS serial number.")
    
#     # Retrieve data from the serial_no_component table
#     if hasattr(serialno_doc, 'serial_no_component'):
#         for component in serialno_doc.serial_no_component:
#            if component.item_group = 'BATTERY':
#                 battery_serial_no = component.component_serial_no
#     if battery_serial_no:
#         njqca_doc = frappe.db.sql("""SELECT backup_duration_cycle_3 from `tabNJQCA` where serial_no = %s """,battery_serial_no)

@frappe.whitelist(allow_guest=True)
def battery_data():
    bios_serial_no = frappe.local.form_dict.get('bios_serial_no')
    
    if not bios_serial_no:
        frappe.throw("BIOS Serial No is required.")
    
    serialno_doc = frappe.get_doc("Serial No", {"bios_serial_no": bios_serial_no})
    
    if not serialno_doc:
        frappe.throw("Serial No document not found for the given BIOS serial number.")
    
    # Initialize battery_serial_no to avoid issues if no component is found
    battery_serial_no = None
    
    # Retrieve data from the serial_no_component table
    if hasattr(serialno_doc, 'serial_no_component'):
        for component in serialno_doc.serial_no_component:
            if component.item_group == 'BATTERY':  # Corrected comparison operator
                battery_serial_no = component.component_serial_no
                break 
    
    # If battery_serial_no is found, fetch data from NJQCA
    if battery_serial_no:
        njqca_doc = frappe.db.sql("""SELECT backup_duration_cycle_3 FROM `tabNJQCA` WHERE serial_no = %s""", battery_serial_no, as_dict=True)
        return njqca_doc[0].get('backup_duration_cycle_3')
    else:
        battery_serial_no = ""