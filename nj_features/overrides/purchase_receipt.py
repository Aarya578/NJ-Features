# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from nj_lib.utils.common_utils import is_serialized
from nj_features.nj_features.api.qr_code import generate_and_save_qrcode

def get_batch(doc, method=None):
    for item in doc.items:
        item_has_batch_no = frappe.db.get_value('Item', {'name': item.item_code}, 'has_batch_no')
        if item_has_batch_no:
            batch_id = item.purchase_order + '-' + str(item.idx)
            item.batch_no = batch_id

            if frappe.db.exists('Batch', batch_id):
                batch_doc = frappe.get_doc('Batch', batch_id)
            else:
                batch_doc = frappe.new_doc('Batch')
                batch_doc.batch_id = batch_id
                batch_doc.item = item.item_code
                batch_doc.save()

        if item.serial_no:
            serial_numbers = item.serial_no.split('\n')
            for serial_number in serial_numbers:
                stripped_serial_number = serial_number.strip()
                if stripped_serial_number:
                    generate_and_save_qrcode(stripped_serial_number)
        elif item.truncated_item_code:
            generate_and_save_qrcode(item.truncated_item_code)

def before_save_purchase_receipt(doc, method):
    if doc.doctype == "Purchase Receipt":
        get_batch(doc, method)

def update_serial_no_on_pr_submit(doc, method=None):
    print('updating serial_no_on_pr_submit...', doc.as_dict())
    for item in doc.items:
        if item.item_code and item.qty and is_serialized(item.item_code) == 1:
            serial_nos = item.serial_no.split('\n') if item.serial_no else []
            for serial_no in serial_nos:
                update_serial_no(serial_no, doc, item)

def update_serial_no(serial_no, doc, item):
    print('updating serial_no...')
    serial_no_doc = frappe.get_doc('Serial No', serial_no)
    supplier_name = frappe.db.get_value('Supplier', {'name': doc.supplier}, 'supplier_name')
    
    if serial_no_doc:
        has_warrenty = frappe.db.get_value('Purchase Receipt', {'name': doc.name}, 'has_warranty')
        if has_warrenty:
           serial_no_doc.vendor_warranty_expiry_date = doc.warrenty_till_date
        else:
           serial_no_doc.vendor_warranty_expiry_date = None
        
        serial_no_doc.purchase_price = item.base_rate
        serial_no_doc.current_price = item.base_rate
        serial_no_doc.barcode = serial_no
        serial_no_doc.grade = item.grade
        serial_no_doc.supplier = doc.supplier
        serial_no_doc.purchase_warranty_days = doc.warranty_days
        serial_no_doc.warranty_days = doc.warranty_days
        serial_no_doc.purchase_order = item.purchase_order
        serial_no_doc.reference_doctype_no = doc.name
        serial_no_doc.supplier_name = supplier_name
        serial_no_doc.purchase_receipt = doc.name
        serial_no_doc.save()