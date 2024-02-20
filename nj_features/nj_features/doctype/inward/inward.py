# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import random
# from apps.backup.nj_features.nj_features.nj_features.doctype.iqc.iqc import generate_random_code
import frappe
from nj_features.nj_features.repack import repack
from frappe.model.document import Document
import os
from barcode import Code128
from nj_features.barcode import CustomImgWriter
from io import BytesIO

class Inward(Document):
    def on_submit(self):
        stock_entry = repack(self.name)
        if stock_entry:
            self.submit()
        else:
            frappe.throw("Repack process failed. Cannot submit Inward document.")

@frappe.whitelist()
def get_items_from_pr(pr,item_code=None):
    base_rate=''
    key = {}
    if pr:
        result = frappe.db.sql(
            """SELECT item_code, warehouse FROM `tabPurchase Receipt Item` WHERE parent = %s """, (pr), as_dict=True)
      
        for i in result:
            key[i['item_code']] = i['warehouse']
         
    if item_code:
        base_rate_result = frappe.db.sql(
            """SELECT base_rate FROM `tabPurchase Receipt Item` WHERE item_code = %s AND parent = %s """, (item_code, pr), as_dict=True)
        if base_rate_result:
            base_rate = base_rate_result[0].get('base_rate', '')
    return {"result":result, "base_rate": base_rate,"key":key}

@frappe.whitelist()
def fetch_item_group(item_code):
    item_group = frappe.db.get_value("Item", {"name": item_code}, "item_group")
    return {"item_group": item_group}


@frappe.whitelist()
def create_serial_no():
    prefix = "NJ"
    serial_no = prefix + str(random.randint(100000, 999999))
    generate_and_save_barcode(serial_no)
    return serial_no

def generate_and_save_barcode(serial_no, format='png'):
    my_code = Code128(serial_no, writer=CustomImgWriter())

    # Create BytesIO to store barcode SVG
    barcode_bytes = BytesIO()
    my_code.write(barcode_bytes)

    # Set the directory to save the file
    base_directory = frappe.get_site_path("public", "files")
    file_path = os.path.join(base_directory, f"{serial_no}.{format}")

    # Check if the file already exists
    if os.path.exists(file_path):
        os.remove(file_path)

    # Save the SVG content to a file
    with open(file_path, 'wb') as f:
        f.write(barcode_bytes.getvalue())