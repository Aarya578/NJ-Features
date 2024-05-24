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
        
        if '/' in data or '"' in data:
            encoded_data = base64.b64encode(data.encode()).decode()
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