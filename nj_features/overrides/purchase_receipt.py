# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
from datetime import timedelta
from frappe.utils import getdate, nowdate
from nj_lib.utils.common_utils import is_serialized
from nj_features.nj_features.api.qr_code import generate_and_save_qrcode
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt

class CustomPurchaseReceipt(PurchaseReceipt):

    def on_submit(self):
        super(CustomPurchaseReceipt, self).on_submit()
        self.set_registry_no_on_submit()
    
    def on_cancel(self):
        super(CustomPurchaseReceipt, self).on_cancel()
        self.set_registry_no_on_cancel()

    def set_registry_no_on_submit(self):

        total_qty = 0
        for item in self.items:
            total_qty += item.qty
            if item.sir_registry_no:
                sir_registry_no = item.sir_registry_no.split(',')
                sir_actual_qty = item.sir_actual_qty.split(',')

                sir_list = [{'sir_registry_no': sr.strip(), 'actual_qty': int(qty.strip())} for sr, qty in zip(sir_registry_no, sir_actual_qty)]
                item_qty = item.qty

                if len(sir_list) == 1:
                    frappe.db.sql("""
                            UPDATE `tabSecurity Inward Registry Child`
                            SET actual_qty = GREATEST(actual_qty - %s, 0)
                            WHERE parent = %s 
                            AND item_code = %s 
                            AND item_group = %s
                        """, (item.qty, sir_list[0].get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)
                elif len(sir_list) > 1:
                    for sir in sir_list:
                        if int(item.qty) > sum([int(row['actual_qty']) for row in sir_list]) and item_qty > 0:
                                frappe.db.sql("""
                                    UPDATE `tabSecurity Inward Registry Child`
                                    SET actual_qty = GREATEST(actual_qty - %s, 0)
                                    WHERE parent = %s 
                                    AND item_code = %s 
                                    AND item_group = %s
                                """, (item_qty, sir.get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)
                                item_qty -= sir.get('actual_qty')

                        elif int(item.qty) < sum([int(row['actual_qty']) for row in sir_list]) and item_qty > 0:
                            frappe.db.sql("""
                                UPDATE `tabSecurity Inward Registry Child`
                                SET actual_qty = GREATEST(actual_qty - %s, 0)
                                WHERE parent = %s 
                                AND item_code = %s 
                                AND item_group = %s
                            """, (item_qty, sir.get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)
                            item_qty -= sir.get('actual_qty')

                        elif int(item.qty) == sum([int(row['actual_qty']) for row in sir_list]) and item_qty > 0:
                            frappe.db.sql("""
                                UPDATE `tabSecurity Inward Registry Child`
                                SET actual_qty = GREATEST(actual_qty - %s, 0)
                                WHERE parent = %s 
                                AND item_code = %s 
                                AND item_group = %s
                            """, (item_qty, sir.get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)
                            item_qty -= sir.get('actual_qty')

    def set_registry_no_on_cancel(self):
        for item in self.items:
            if item.sir_registry_no:
                sir_registry_no = item.sir_registry_no.split(',')
                sir_actual_qty = item.sir_actual_qty.split(',')
                sir_list = [{'sir_registry_no': sr.strip(), 'actual_qty': int(qty.strip())} 
                        for sr, qty in zip(sir_registry_no, sir_actual_qty)]
                
                if len(sir_list) == 1:
                    get_sir_data = frappe.db.sql("""
                                SELECT actual_qty, received_qty FROM `tabSecurity Inward Registry Child`
                                WHERE parent = %s 
                                AND item_code = %s 
                                AND item_group = %s
                            """, (sir_list[0].get('sir_registry_no'), item.item_code, item.item_group), as_dict=1)
                    
                    if get_sir_data:
                        if int(get_sir_data[0].get('actual_qty')) + int(sir_list[0].get('actual_qty')) == int(get_sir_data[0].get('received_qty')):

                            frappe.db.sql("""
                                UPDATE `tabSecurity Inward Registry Child`
                                SET actual_qty = actual_qty + %s
                                WHERE parent = %s
                                AND item_code = %s
                                AND item_group = %s
                            """, (sir_list[0].get('actual_qty'), sir_list[0].get('sir_registry_no'), 
                                item.item_code, item.item_group), debug=0, explain=0)
                        else:
                            updated_qty = int(item.qty) + int(get_sir_data[0].get('actual_qty'))
                            frappe.db.sql("""
                                UPDATE `tabSecurity Inward Registry Child`
                                SET actual_qty = %s
                                WHERE parent = %s
                                AND item_code = %s
                                AND item_group = %s
                            """, (updated_qty, sir_list[0].get('sir_registry_no'), 
                                item.item_code, item.item_group), debug=0, explain=0)
                        
                elif len(sir_list) > 1:
                    for sir in sir_list:
                        get_sir_data = frappe.db.sql("""
                                SELECT actual_qty, received_qty FROM `tabSecurity Inward Registry Child`
                                WHERE parent = %s 
                                AND item_code = %s 
                                AND item_group = %s
                            """, (sir.get('sir_registry_no'), item.item_code, item.item_group), as_dict=1)
                        
                        if get_sir_data:

                            if int(sir.get('actual_qty')) + int(get_sir_data[0].get('actual_qty')) == int(get_sir_data[0].get('received_qty')):

                                frappe.db.sql("""
                                    UPDATE `tabSecurity Inward Registry Child`
                                    SET actual_qty = actual_qty + %s
                                    WHERE parent = %s
                                    AND item_code = %s
                                    AND item_group = %s
                                """, (sir.get('actual_qty'), sir.get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)

                                if int(item.qty) == int(sir.get('actual_qty')):
                                    break

                            elif int(sir.get('actual_qty')) + int(get_sir_data[0].get('actual_qty')) != int(get_sir_data[0].get('received_qty')):

                                updated_qty = 0
                                for r in sir_list:
                                    if r.get('sir_registry_no') != sir.get('sir_registry_no'):
                                        updated_qty += r.get('actual_qty')
                                    else:
                                        break

                                resulting_val = abs(item.qty - updated_qty)

                                frappe.db.sql("""
                                    UPDATE `tabSecurity Inward Registry Child`
                                    SET actual_qty = actual_qty + %s
                                    WHERE parent = %s
                                    AND item_code = %s
                                    AND item_group = %s
                                    """, (resulting_val, sir.get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)
                                
                                if int(updated_qty) + int(resulting_val) == int(item.qty): 
                                    break

def generate_batch_no(doc, method=None):
    for item in doc.items:
        set_registry_no(item)

        has_batch_no = frappe.db.get_value('Item', item.item_code, 'has_batch_no')

        if has_batch_no and item.idx:
            batch_id = f"{item.purchase_order}-{item.idx}"
            item.batch_no = batch_id

            if frappe.db.exists('Batch', batch_id):
                batch_doc = frappe.get_doc('Batch', batch_id)
            else:
                batch_doc = frappe.new_doc('Batch')
                batch_doc.batch_id = batch_id
                batch_doc.item = item.item_code
                batch_doc.save()
                                
def get_batch(doc, method=None):
    for item in doc.items:
        qr_code_mappings = []

        if item.item_code and item.qty and is_serialized(item.item_code) == 1:
            serial_nos = item.serial_no.split('\n') if item.serial_no else []
            for serial_no in serial_nos:
                if serial_no.strip():
                    update_serial_no(serial_no.strip(), doc, item)

        if item.serial_no:
            for serial in item.serial_no.split('\n'):
                serial = serial.strip()
                if serial:
                    qr_code_mappings.append(generate_and_save_qrcode(serial))
        elif item.truncated_item_code:
            generate_and_save_qrcode(item.truncated_item_code)

        qr_code_mapping_str = '\n'.join(qr_code_mappings)
        frappe.db.sql("""
            UPDATE `tabPurchase Receipt Item` 
            SET qr_code_mapping = %s 
            WHERE name = %s
        """, (qr_code_mapping_str, item.name))

def before_save_purchase_receipt(doc, method):
    if doc.doctype == "Purchase Receipt":
        get_batch(doc, method)

def update_serial_no_on_pr_submit(doc, method=None):
    for item in doc.items:
        if item.item_code and item.qty and is_serialized(item.item_code) == 1:
            serial_nos = item.serial_no.split('\n') if item.serial_no else []
            for serial_no in serial_nos:
                update_serial_no(serial_no, doc, item)

def update_serial_no(serial_no, doc, item):

    serial_no_doc = frappe.get_doc('Serial No', serial_no, for_update=True)
    supplier_name = frappe.db.get_value('Supplier', {'name': doc.supplier}, 'supplier_name')
    
    if serial_no_doc:

        get_purc_warranty_data = get_purchase_warranty_data(item, item.purchase_order)

        has_warrenty = frappe.db.get_value('Purchase Receipt', {'name': doc.name}, 'has_warranty')
        if has_warrenty:
           serial_no_doc.vendor_warranty_expiry_date = get_purc_warranty_data.get('vendor_warranty_expiry_date') if get_purc_warranty_data.get('vendor_warranty_expiry_date') else doc.warrenty_till_date
        else:
           serial_no_doc.vendor_warranty_expiry_date = None

        serial_no_doc.purchase_price = item.base_rate
        serial_no_doc.current_price = item.base_rate
        serial_no_doc.barcode = serial_no
        serial_no_doc.grade = item.grade
        serial_no_doc.supplier = doc.supplier
        serial_no_doc.purchase_warranty_days = get_purc_warranty_data.get('warranty_days') if get_purc_warranty_data.get('warranty_days') else doc.warranty_days
        serial_no_doc.purchase_order = item.purchase_order
        serial_no_doc.reference_doctype_no = doc.name
        serial_no_doc.supplier_name = supplier_name
        serial_no_doc.purchase_receipt = doc.name
        serial_no_doc.save()

def get_purchase_warranty_data(item, purchase_order):

    purc_doc = frappe.get_doc('Purchase Order', purchase_order)
    matching_warranty = {}

    if purc_doc:
        for row in purc_doc.get("purchase_order_warrenty_for_specific_parts"):
            if row.get("item_group") == item.item_group:
                matching_warranty["vendor_warranty_expiry_date"] = purc_doc.get("transaction_date") + timedelta(days=row.get("warranty_days"))
                matching_warranty["warranty_days"] = row.get("warranty_days")

    return matching_warranty

def set_registry_no(item):

    query = """
        SELECT name FROM `tabSecurity Inward Registry` 
        WHERE reference_po_number = %s AND docstatus = 1 AND total_qty > 0
    """
    
    get_sir_data = frappe.db.sql(query, (item.purchase_order,), as_dict=1)

    if get_sir_data:
        sir_names = []
        sir_actual_qty = []

        for data in get_sir_data:

            get_registry_doc = frappe.get_doc('Security Inward Registry', data.get('name'))

            if get_registry_doc.get('registry_type') == "Accept Registry":
                for row in get_registry_doc.get('purchase_inward_registry_child'):
                    if row.get('item_code') == item.item_code and row.get('item_group') == item.item_group and int(row.get('received_qty')) > 0:
                        sir_names.append(row.get('parent'))
                        sir_actual_qty.append(row.get('actual_qty'))

        if sir_names:
            item.sir_registry_no = ', '.join(sir_names)
            item.sir_actual_qty = ', '.join(sir_actual_qty)

@frappe.whitelist()
def check_for_warranty_validity(doc):
    
    if isinstance(doc, str):
        doc = json.loads(doc)

    name = doc.get("name")
    vendor_warranty_expiry_date = doc.get("vendor_warranty_expiry_date")

    if not vendor_warranty_expiry_date or not name:
        return

    expiry_date = getdate(vendor_warranty_expiry_date)
    today = getdate(nowdate())

    is_warranty_valid = 1 if expiry_date >= today else 0

    frappe.db.set_value(doc.get("doctype"), name, "warranty_valid_check", is_warranty_valid)

    return {"warranty_valid_check": is_warranty_valid}