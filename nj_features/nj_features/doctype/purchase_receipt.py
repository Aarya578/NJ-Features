# import frappe
# from nj_features.qr_code import generate_and_save_qrcode

# def get_batch(doc, method=None):
#     for item in doc.items:
#         item_doc = frappe.get_doc("Item", item.item_code)
#         if item_doc.has_batch_no and not item.batch_no:
#             item.batch_no = item.purchase_order +'-'+ str(item.idx)
#             batch_doc = frappe.new_doc('Batch')
#             batch_doc.batch_id = item.purchase_order +'-'+ str(item.idx)
#             batch_doc.item = item.item_code
#             batch_doc.save()
        
#         if item.serial_no:
#             serial_numbers = item.serial_no.split('\n')
#             for serial_number in serial_numbers:
#                 stripped_serial_number = serial_number.strip()
#                 if stripped_serial_number:
#                     generate_and_save_qrcode(stripped_serial_number)
#         elif item.truncated_item_code:
#             generate_and_save_qrcode(item.truncated_item_code)
# import frappe
# from nj_features.qr_code import generate_and_save_qrcode

import frappe
from nj_features.qr_code import generate_and_save_qrcode

def get_batch(doc, method=None):
    print(f'doc ==> {doc}')
    for item in doc.items:
        item_doc = frappe.get_doc("Item", item.item_code)
        if item_doc.has_batch_no and not item.batch_no:
            batch_id = item.purchase_order + '-' + str(item.idx)
            item.batch_no = batch_id

            if frappe.db.exists('Batch', batch_id):
                print(f'Batch {batch_id} already exists. Updating existing batch.')
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



