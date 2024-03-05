import frappe
from nj_features.api_files import serializer_or_notserializer

def get_batch(doc, method=None):
    for item in doc.items:
        item_doc = frappe.get_doc("Item", item.item_code)
        if item_doc.has_batch_no:
            item.batch_no = item.purchase_order +'-'+ str(item.idx)
            
def update_serial_no_on_pr_submit(doc, method=None):
    for item in doc.items:
        if item.item_code and item.qty and serializer_or_notserializer(item.item_code) == 1:
            serial_nos = item.serial_no.split('\n') if item.serial_no else []
            for serial_no in serial_nos:
                update_serial_no_prices(item.rate, serial_no)

def update_serial_no_prices(rate, serial_no):
    serial_no_doc = frappe.get_doc('Serial No', serial_no)
    if serial_no_doc:
        if rate:
            frappe.db.set_value('Serial No', serial_no_doc.name, 'purchase_price', rate)
            frappe.db.set_value('Serial No', serial_no_doc.name, 'current_price', rate)