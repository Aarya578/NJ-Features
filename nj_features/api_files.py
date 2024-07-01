import frappe
import json
import random
import os
# from barcode import Code128
from nj_features.qr_code import generate_and_save_qrcode
# from io import BytesIO


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

# for stock entry
@frappe.whitelist()
def search_for_serial_or_batch_or_barcode_no(search_value):
    # Search serial number
    serial_no_data = frappe.db.get_value(
        "Serial No", search_value, ["name as serial_no", "item_code", "warehouse"], as_dict=True
    )
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

@frappe.whitelist()
def get_all_emp_warehouse(user):
    try:
        dept = frappe.db.get_value('Employee', {'user_id': user}, 'department')
        dept_values = frappe.db.get_value('Department', {'name': dept}, ['department_prefix', 'linked_warehouse'])
        if not dept_values:
            frappe.throw('Department values not found')

        if not dept_values[1]:
            frappe.throw("Enter <strong>Work Warehouse</strong> in Department: {}".format(dept))

        default_ww = dept_values[0] + '-Work-Warehouse - NJ' if dept_values[0] else ''
        all_emp_ware = frappe.db.get_all('Warehouse', {'parent_warehouse': dept_values[1], 'available_capacity': ('>', 0)}, ['name', 'available_capacity', 'max_capacity'])
        centralized_parent = frappe.db.get_value('Warehouse', {'centralized': 1}, 'name')
        centralized_ware = frappe.db.get_all('Warehouse', {'parent_warehouse': centralized_parent}, ['name', 'available_capacity'])
        recommended_warehouses = {}
        centralized_warehouses = {}

        for warehouse in all_emp_ware:
            recommended_warehouses[warehouse['name']] = warehouse['available_capacity']

        for warehouse in centralized_ware:
            centralized_warehouses[warehouse['name']] = warehouse['available_capacity']

        if default_ww in recommended_warehouses:
            del recommended_warehouses[default_ww]

        formatted_recommended = '\n'.join([f"{warehouse}  =>  {capacity} qty" for warehouse, capacity in recommended_warehouses.items()])
        formatted_centralized = '\n'.join([f"{warehouse} => {capacity} qty" for warehouse, capacity in centralized_warehouses.items()])
        warehouse = ','.join(recommended_warehouses.keys())
        return {
            'recommended': formatted_recommended,
            'centralized': formatted_centralized,
            'warehouse': warehouse
        }
        
    except Exception as e:
        return {'error in emp': str(e)}
    
# Barcode Printing in Purchase Receipt:
@frappe.whitelist()
def create_serial_no(item_code=None, attempt=0):
    MAX_ATTEMPTS = 4
    
    try:
        if attempt >= MAX_ATTEMPTS:
            frappe.msgprint("Maximum attempts reached. Unable to generate a unique serial number.")
            return None
        
        item_doc = frappe.get_doc('Item', item_code)
        if item_doc:
            has_serial_no = item_doc.has_serial_no
            item_group = item_doc.item_group
            
            if has_serial_no and item_group:
                serial_no_prefix = frappe.db.get_value("Item Group", item_group, "serial_no_prefix")
                
                if not serial_no_prefix:
                    frappe.msgprint(f"Serial No Prefix is not set for Item Group: {item_group}")
                    return None
                
                prefix = "NJ-"
                serial_no = prefix + serial_no_prefix + '-' + str(random.randint(100000, 999999))
                frappe.msgprint(f"Generated serial number: {serial_no}")

                if frappe.db.exists("Serial No", {"serial_no": serial_no}):
                    frappe.msgprint(f"Serial number {serial_no} already exists. Attempt {attempt + 1} of {MAX_ATTEMPTS}. Generating another one.")
                    return create_serial_no(item_code, attempt + 1)  # Recursive call with increased attempt count
                else:
                    generate_and_save_qrcode(serial_no)
                    return serial_no
            else:
                frappe.msgprint(f"Item Group or Serial No status is not defined for Item Code: <strong>{item_code}</strong>.")
                return None
        else:
            frappe.msgprint(f"Item with code <strong>{item_code}</strong> not found.")
            return None
    except Exception as e:
        frappe.msgprint(f"Error while creating Serial No: {e}")
        return None

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

@frappe.whitelist()
def print_barcode(doc):
    try:
        doc_dict = frappe.parse_json(doc)
        item_code = doc_dict.get('item_code') or doc_dict.get('component')
        serial_no = doc_dict.get('serial_no')
        qty = doc_dict.get('qty')
        
        if serial_no:
            generate_and_save_qrcode(serial_no)
        
        has_serial_no = serializer_or_notserializer(item_code)
        has_batch_no = frappe.db.get_value('Item', {'name': item_code}, 'has_batch_no')

        if has_serial_no == 1:
            serial_no_list = doc_dict.get('serial_no').split('\n') if doc_dict.get('serial_no') else []
            current_serial_count = len(serial_no_list)
            remaining_qty = qty - current_serial_count
            
            if remaining_qty > 0:
                for _ in range(remaining_qty):
                    serial_no = create_serial_no(item_code)
                    serial_no_list.append(serial_no)
                
                unique_serial_no = list(set(serial_no_list))
                updated_serial_no = '\n'.join(unique_serial_no)
                return {"serial_no": updated_serial_no}
            
            elif remaining_qty < 0:
                serial_no_list = serial_no_list[:qty]  # Keep only the required quantity
                updated_serial_no = '\n'.join(serial_no_list)
                return {"serial_no": updated_serial_no}
            else:
                row_idx = doc_dict.get('idx', '')
                frappe.msgprint(f"All serial numbers are already entered for this row: <strong># {row_idx}</strong>.")
        
        elif has_batch_no == 1 and has_serial_no == 0:
            frappe.msgprint(f"Serial No can't be generated for Item Code: <strong>{item_code}</strong> with 'Has Batch No'")
        
        else:
            new_item_code = truncate_grade(item_code)
            if new_item_code:
                decoded_item_code = generate_and_save_qrcode(new_item_code)
                print(decoded_item_code)
                return {"truncated_item_code": new_item_code, "decoded_item_code": decoded_item_code}
    
    except Exception as e:
        frappe.msgprint(f"Error printing barcode: {e}")

# def print_barcode(doc):
#     try:
#         doc_dict = frappe.parse_json(doc)
#         item_code = doc_dict.get('item_code') or doc_dict.get('component') 
#         serial_no=doc_dict.get('serial_no')
#         if serial_no:
#             generate_and_save_qrcode(serial_no)
        
#         # if serial_no:
#         #     serial_no_list = serial_no.split('\n')
#         #     for serial in serial_no_list:
#         #         if  serial.startswith("NJ-"):
#         #             frappe.throw("Serial numbers entered manually must not  start with 'Nj'")
#         #         generate_and_save_qrcode(serial)

#         qty = doc_dict.get('qty')
#         has_serial_no = serializer_or_notserializer(item_code)
#         has_batch_no = frappe.db.get_value('Item', {'name': item_code}, 'has_batch_no')
#         if has_serial_no == 1:
#             serial_no_list = doc_dict.get('serial_no').split('\n') if doc_dict.get('serial_no') else []
#             remaining_qty = qty - len(serial_no_list)
#             if remaining_qty > 0:
#                 for _ in range(remaining_qty):
#                     serial_no = create_serial_no(item_code)
#                     serial_no_list.append(serial_no)
#                     unique_serial_no = list(set(serial_no_list))
#                 updated_serial_no = '\n'.join(unique_serial_no)
                
#                 # for serial_no in serial_no_list[-remaining_qty:]:
#                 #     generate_and_save_qrcode(serial_no)
#                 return {"serial_no": updated_serial_no}
                   
#             else:
#                 row_idx = doc_dict.get('idx', '')
#                 frappe.msgprint(f"All serial numbers are already entered for this row: <strong># {row_idx}</strong>.")
#         elif has_batch_no == 1 and has_serial_no ==0 :
#             frappe.msgprint(f"Serial No can't be generated for Item Code: <strong>{item_code}</strong> with 'Has Batch No'")
#         else:
#             new_item_code = truncate_grade(item_code)
#             if new_item_code:
#                 decoded_item_code = generate_and_save_qrcode(new_item_code)
#                 return {"truncated_item_code": new_item_code, "decoded_item_code": decoded_item_code}
#             # frappe.msgprint(f"QR Code is generated for Non-Serialized Item Code as: <strong>{new_item_code}</strong>")
#     except Exception as e:
#         frappe.msgprint(f"Error printing barcode: {e}")

def truncate_grade(input_string):
    parts = input_string.split('-')
    
    last_part = parts[-1].strip().upper()
    if last_part.endswith(('GRADE A', 'GRADE B', 'GRADE C', 'GRADE D')) or last_part == 'UNKNOWN':
        return '-'.join(parts[:-1])
    else:
        return input_string

# @frappe.whitelist()
# def print_barcode(doc):
#     try:
#         doc_dict = frappe.parse_json(doc)
#         item_code = doc_dict.get('item_code')
#         qty = doc_dict.get('qty')
#         has_serial_no = serializer_or_notserializer(item_code)
        
#         if has_serial_no == 1:
#             serial_no_list = doc_dict.get('serial_no').split('\n') if doc_dict.get('serial_no') else []
#             remaining_qty = qty - len(serial_no_list)
#             if remaining_qty > 0:
#                 for _ in range(remaining_qty):
#                     serial_no = create_serial_no(item_code)
#                     serial_no_list.append(serial_no)
                
#                 updated_serial_no = '\n'.join(serial_no_list)
                
#                 for serial_no in serial_no_list[-remaining_qty:]:
#                     generate_and_save_qrcode(serial_no)
#                 return updated_serial_no
                    
#             else:
#                 row_idx = doc_dict.get('idx', '')
#                 frappe.msgprint(f"All serial numbers are already entered for this row: <strong># {row_idx}</strong>.")
#         else:
#             frappe.msgprint(f"Serial No can't be generated for Non-Serialized Item Code: <strong>{item_code}</strong>")
#     except Exception as e:
#         frappe.msgprint(f"Error printing barcode: {e}")
        
def update_serial_no_on_pr_submit(doc, method=None):
    print(f'update_serial_no_on_pr_submit ====> {doc}')
    for item in doc.items:
        if item.item_code and item.qty and serializer_or_notserializer(item.item_code) == 1:
            serial_nos = item.serial_no.split('\n') if item.serial_no else []
            for serial_no in serial_nos:
                update_serial_no(serial_no, doc, item)

def update_serial_no(serial_no, doc, item):
    print(f'doc ===> {doc}')
    serial_no_doc = frappe.get_doc('Serial No', serial_no)
    supplier_name = frappe.db.get_value('Supplier', {'name': doc.supplier}, 'supplier_name')
    
    if serial_no_doc:
        # warranty expiry date check for serial_no 
        has_warrenty = frappe.db.get_value('Purchase Receipt', {'name': doc.name}, 'has_warranty')
        if has_warrenty:
           serial_no_doc.vendor_warranty_expiry_date = doc.warrenty_till_date
        else:
           serial_no_doc.vendor_warranty_expiry_date = None
        
        serial_no_doc.purchase_price = item.base_rate
        serial_no_doc.current_price = item.base_rate
        serial_no_doc.barcode = serial_no
        serial_no_doc.supplier = doc.supplier
        serial_no_doc.purchase_warranty_days = doc.warranty_days
        serial_no_doc.warranty_days = doc.warranty_days
        serial_no_doc.purchase_order = item.purchase_order
        serial_no_doc.reference_doctype_no = doc.name
        serial_no_doc.supplier_name = supplier_name
        serial_no_doc.purchase_receipt = doc.name
        serial_no_doc.save()