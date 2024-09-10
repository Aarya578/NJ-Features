import os
import png
import base64
import frappe
import pyqrcode
# from pyqrcode import QRCode 

# @frappe.whitelist()        
# def generate_and_save_qrcode(serial_no, format='png'):

#     try:
#         url = pyqrcode.create(serial_no) 

#         url.png(f"{serial_no}.png", scale=8)

#         base_directory = frappe.get_site_path("public", "files")
#         file_path = os.path.join(base_directory, f"{serial_no}.png")
        
#         if os.path.exists(file_path):
#             os.remove(file_path)
#         url.png(file_path, scale=8)

#     except Exception as e:
#         return f"Error in generating QR code: {e}"

@frappe.whitelist()        
def generate_and_save_qrcode(data, format='png'):
    try:
        # For item codes
        encoded_data = data
        template_item_code = frappe.db.exists('Item', encoded_data)
        qr_code_mapping_name = frappe.db.exists('Non Serialized QR Code Mapping', {'item_code': encoded_data})
        
        if template_item_code:
            if not qr_code_mapping_name:
                qr_code_mapping_doc = frappe.new_doc('Non Serialized QR Code Mapping')
                qr_code_mapping_doc.item_code = encoded_data
                qr_code_mapping_doc.save()
                encoded_data = qr_code_mapping_doc.name
            else:
                encoded_data = qr_code_mapping_name
        
        url = pyqrcode.create(encoded_data)
        filename = f"{encoded_data}.{format}"
        
        # Define the file path
        base_directory = frappe.get_site_path("public", "files")
        file_path = os.path.join(base_directory, filename)

        # Remove the existing file if it exists
        if os.path.exists(file_path):
            return filename

        # Generate and save the QR code image
        url.png(file_path, scale=8)
        return filename
    
    except Exception as e:
        return f"Error in generating QR code: {e}"
    
@frappe.whitelist()
def get_print_format_role():
    try:
        user = frappe.session.user
        if not user:
            raise ValueError("User is not logged in.")
        user_id = frappe.db.get_value('User', {'name': user}, 'name')
        if not user_id:
            raise ValueError(f"No user found with email: {user}")
        query = """
            SELECT role
            FROM `tabHas Role`
            WHERE parent = %s
        """
        roles = frappe.db.sql(query, user_id, as_dict=True)
        role_list = [role['role'] for role in roles]
        return True if 'Print Format' in role_list else False
    except Exception as e:
        frappe.log_error(f"Error in get_print_format_role: {str(e)}")
        return []
