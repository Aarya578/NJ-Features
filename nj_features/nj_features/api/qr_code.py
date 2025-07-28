# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import os
import random
import frappe
import pyqrcode
from frappe import _
from nj_lib.utils.common_utils import is_serialized

@frappe.whitelist()        
def generate_and_save_qrcode(data, format='png'):
    try:
        encoded_data = data
        template_item_code = frappe.db.exists('Item', encoded_data)
        qr_code_item_name = frappe.db.exists('QR Code Mapping', {'item_code': encoded_data})
        qr_code_serial_name = frappe.db.exists('QR Code Mapping', {'serial_no': encoded_data})

        if template_item_code:
            if not qr_code_item_name:
                qr_code_mapping_doc = frappe.new_doc('QR Code Mapping')
                qr_code_mapping_doc.item_code = encoded_data
                qr_code_mapping_doc.doctype1 = 'Item'
                qr_code_mapping_doc.save(ignore_permissions=True)
                encoded_data = qr_code_mapping_doc.name
            else:
                encoded_data = qr_code_item_name
        elif not qr_code_serial_name:
            qr_code_mapping_doc = frappe.new_doc('QR Code Mapping')
            qr_code_mapping_doc.serial_no = encoded_data
            qr_code_mapping_doc.doctype1 = 'Serial No'
            qr_code_mapping_doc.save(ignore_permissions=True)

            frappe.db.set_value('Serial No', encoded_data, 
                {'is_encrypted': True, 'qr_code_mapping': qr_code_mapping_doc.name}, update_modified=False)
            encoded_data = qr_code_mapping_doc.name
            
        elif qr_code_serial_name:
            encoded_data = qr_code_serial_name
        
        url = pyqrcode.create(encoded_data)
        filename = f"{encoded_data}.{format}"
        
        base_directory = frappe.get_site_path("public", "files")
        file_path = os.path.join(base_directory, filename)

        if os.path.exists(file_path):
            return encoded_data

        url.png(file_path, scale=8)
        return encoded_data
    
    except Exception as e:
        return f"Error in generating QR code: {e}"
    

@frappe.whitelist()
def get_print_format_role():
    try:
        user = frappe.session.user
        
        roles = frappe.db.get_all(
            "Has Role",
            filters={"parent": user},
            fields=["role"]
        )

        role_list = [r["role"] for r in roles]

        return "Print Format" in role_list

    except Exception as e:
        frappe.log_error(f"Error in get_print_format_role: {frappe.get_traceback()}")
        return False

@frappe.whitelist()
def print_barcode(doc):
    try:
        doc_dict = frappe.parse_json(doc)
        item_code = doc_dict.get('item_code') or doc_dict.get('component')
        serial_no = doc_dict.get('serial_no')
        qty = doc_dict.get('qty', 1)
        
        has_serial_no = is_serialized(item_code)
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
                return {"truncated_item_code": new_item_code, "decoded_item_code": decoded_item_code}
    
    except Exception as e:
        frappe.msgprint(f"Error printing barcode: {e}")

@frappe.whitelist()
def create_serial_no(item_code=None, attempt=0, rfq=False):
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
                attribute_prefix  = ''
                if item_code and item_group:
                    attribute_prefix = get_attribute_prefix(item_code, item_group)
                    if attribute_prefix:
                        attribute_prefix = attribute_prefix + '-'
                if not serial_no_prefix:
                    frappe.msgprint(f"Serial No Prefix is not set for Item Group: {item_group}")
                    return None
                
                prefix = ""

                if frappe.db.get_value("Item Group", item_group, "enable_nj_prefix"):
                    prefix = "NJ-"

                if rfq:
                    prefix = "EXT-"

                serial_no = prefix + serial_no_prefix + '-' + attribute_prefix + str(random.randint(100000, 999999))
                
                frappe.msgprint(f"Generated serial number: {serial_no}")

                if frappe.db.exists("Serial No", {"serial_no": serial_no}):
                    frappe.msgprint(f"Serial number {serial_no} already exists. Attempt {attempt + 1} of {MAX_ATTEMPTS}. Generating another one.")
                    return create_serial_no(item_code, attempt + 1)  # Recursive call with increased attempt count
                else:
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
    
def truncate_grade(input_string):
    parts = input_string.split('-')
    
    last_part = parts[-1].strip().upper()
    if last_part.endswith(('GRADE A', 'GRADE B', 'GRADE C', 'GRADE D')) or last_part == 'UNKNOWN':
        return '-'.join(parts[:-1])
    else:
        return input_string
    
@frappe.whitelist()
def adapter_repacked_serial_no(nj_serial_no):
    try:
        query="""
            SELECT tot_sed.serial_no as adapter_serial_no
            FROM `tabStock Entry Detail` AS sed
            INNER JOIN `tabStock Entry Detail` AS tot_sed ON tot_sed.parent = sed.parent
            INNER JOIN `tabStock Entry` AS stock_entry ON stock_entry.name = sed.parent
            WHERE
                (sed.serial_no = %(serial_no)s OR 
                    sed.serial_no LIKE CONCAT(%(serial_no)s, '\\n%%') OR 
                    sed.serial_no LIKE CONCAT('%%\\n', %(serial_no)s) OR 
                    sed.serial_no LIKE CONCAT('%%\\n', %(serial_no)s, '\\n%%')) AND
                stock_entry.purpose = 'Repack' AND 
                stock_entry.docstatus = 1 AND
                tot_sed.s_warehouse IS NOT NULL AND 
                tot_sed.item_group = 'Laptop Adaptors'
            ORDER BY stock_entry.creation DESC
            LIMIT 1
        """
        partlist_query="""
          Select component_serial_no as adapter_serial_no from `tabSerial No Component` where parent=%s and item_group="Laptop Adaptors" and component_serial_no <> "" order by item_group_idx desc limit 1;
        """
        if nj_serial_no is not None and nj_serial_no:

            data=frappe.db.sql(partlist_query, nj_serial_no, as_dict=1)
        
        if data is not None and data:  
            return data[0].get("adapter_serial_no")
        else:
            data=frappe.db.sql(query, {"serial_no": nj_serial_no}, as_dict=1)
            if data is not None and data:
                return data[0].get("adapter_serial_no")
            else:
                return "No repacked serial no found"
    except Exception as e:
        return str(e)

def get_attribute_prefix(item_code, item_group):
    attribute_names = frappe.get_all(
        "Variants of Item group",
        filters={
            "parent": item_group,
            "enable_item_attribute_for_serial_no_prefix": 1
        },
        fields=["variant"]
    )

    result_parts = []

    for row in attribute_names:
        attribute_name = row.variant

        attribute_value = frappe.db.get_value(
            "Item Variant Attribute",
            {
                "parent": item_code,
                "attribute": attribute_name
            },
            "attribute_value"
        )

        if attribute_value:
            # Add the first part before any space
            result_parts.append(attribute_value.split()[0])

    return "-".join(result_parts) if result_parts else ""

