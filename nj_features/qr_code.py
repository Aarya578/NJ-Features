import pyqrcode
import png
import frappe
import os
from pyqrcode import QRCode 

@frappe.whitelist()        
def generate_and_save_qrcode(serial_no, format='png'):

    try:
        url = pyqrcode.create(serial_no) 

        url.png(f"{serial_no}.png", scale=8)

        base_directory = frappe.get_site_path("public", "files")
        file_path = os.path.join(base_directory, f"{serial_no}.png")
        
        if os.path.exists(file_path):
            os.remove(file_path)
        url.png(file_path, scale=8)

    except Exception as e:
        return f"Error in generating QR code: {e}"