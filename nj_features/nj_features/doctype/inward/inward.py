# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
import random
from frappe.model.document import Document
from nj_features.qr_code import generate_and_save_qrcode
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
# import os
# from barcode import Code128
# from nj_features.barcode import CustomImgWriter
# from io import BytesIO

class Inward(Document):
    def on_submit(self):
        self.make_stock_entry_using_nj_lib()

    def make_stock_entry_using_nj_lib(self):
        stock_data = {
            "name": self.name,
            "item_code": self.item_code,
            "stock_entry_type": "Repack",
            "doctype": self.doctype,
            "series": "NJ-STE-INW-",
            "stock_entry_for_material_transfer_or_repack_items": stock_entry_for_material_transfer_or_repack_items_data(self),
            "repack_items": get_repack_items(self)
        }

        stock_entry = stock_entry_using_nj_lib(stock_data)
        
        if stock_entry:
            self.update_serial_no_details()
        else:
            frappe.throw("Repack process failed. Cannot submit Inward document.")

    def update_serial_no_details(self):
        serial_no_doc = frappe.get_doc('Serial No', self.serial_no)
        
        if serial_no_doc:
            po_doc = frappe.get_doc('Purchase Receipt', self.purchase_receipt)
            warranty_days = po_doc.get('warranty_days')
            supplier_name = frappe.db.get_value('Supplier', {'name': po_doc.get('supplier')}, 'supplier_name')
            po = frappe.db.get_value('Purchase Receipt Item', {'parent': self.purchase_receipt, 'item_code': self.item_code}, 'purchase_order')
            
            serial_no_doc.brand = self.brand
            serial_no_doc.purchase_price = self.base_rate
            serial_no_doc.current_price = self.base_rate
            serial_no_doc.barcode = self.serial_no
            serial_no_doc.supplier = po_doc.get('supplier')
            serial_no_doc.batch_no = self.batch_no
            serial_no_doc.warranty_period = warranty_days
            serial_no_doc.purchase_warranty_days = warranty_days
            serial_no_doc.warranty_days = warranty_days
            serial_no_doc.purchase_order = po
            serial_no_doc.supplier_name = supplier_name
            serial_no_doc.purchase_receipt = self.purchase_receipt
            serial_no_doc.save()
        else:
            frappe.throw("Serial No document not found for the given serial number.")


def stock_entry_for_material_transfer_or_repack_items_data(self):
	stock_entry_for_material_transfer_or_repack_items_list = []
	stock_entry_for_material_transfer_or_repack_items_dict = {
		"item_code": self.item_code,
		"basic_rate": self.base_rate,
        "s_warehouse": self.source_warehouse
	}
	stock_entry_for_material_transfer_or_repack_items_list.append(stock_entry_for_material_transfer_or_repack_items_dict)
	return stock_entry_for_material_transfer_or_repack_items_list

def get_repack_items(self):
    get_repack_items_list = []
    get_repack_items_dict = {
		"repack_item_code": self.repack_item_code,
		"serial_no": self.serial_no,
		"repack_base_price": self.base_rate,
        "repack_warehouse": self.target_warehouse
	}
    get_repack_items_list.append(get_repack_items_dict)
    
    return get_repack_items_list

@frappe.whitelist()
def get_item_list_from_pr(pr):
    # return frappe.db.get_list('Purchase Receipt Item', {'parent': pr}, ['item_code'])
    item_codes = frappe.db.get_list('Item', filters={'has_batch_no': 1}, pluck='item_code')
    pr_item_codes = frappe.db.get_list('Purchase Receipt Item', {'parent': pr}, ['item_code'])
    # Get item codes associated with the given purchase receipt
    # Filter out only those item codes from purchase receipt which have batch numbers
    item_codes_in_pr = [item['item_code'] for item in pr_item_codes if item['item_code'] in item_codes]
    return item_codes_in_pr

# @frappe.whitelist()
# def get_item_list_from_po(po):
#     return frappe.db.get_list('Purchase Order Item', {'parent': po}, ['item_code'])

# @frappe.whitelist()
# def get_stock_data_from_po(po, item_code=None):
#     get_serial_no = ''
#     supplier=None
#     if po and item_code:
#         pr = frappe.db.get_value('Purchase Receipt Item', {'item_code': item_code, 'purchase_order': po}, 'parent')
#         sql_query = """
#                 SELECT 
#                     item_code, warehouse, incoming_rate, posting_date, posting_time, batch_no, serial_no
#                 FROM
#                     `tabStock Ledger Entry`
#                 WHERE
#                     voucher_no = %s and item_code = %s
#                     AND is_cancelled = 0 AND voucher_type = 'Purchase Receipt'
#                 ORDER BY
#                     posting_date DESC, posting_time DESC, creation DESC
#                 LIMIT 1
#             """
#         sle = frappe.db.sql(sql_query, (pr, item_code), as_dict=1)
        
#         item_group = frappe.db.get_value("Item", {"name": sle[0]['item_code']}, "item_group")
        
#         if sle and sle[0].get('serial_no'):
#             get_serial_no = frappe.db.sql(
#                 """SELECT name FROM `tabSerial No` WHERE item_code = %s 
#                 AND delivery_document_no IS NULL AND warehouse = %s """,
#                 (sle[0]['item_code'], sle[0]['warehouse']), as_dict=True
#             )
#     pr_doc = frappe.get_doc('Purchase Receipt', pr)
#     if pr_doc:
#         supplier = pr_doc.supplier
#     return {"result": sle[0], "serial_no": get_serial_no[0]['name'] if get_serial_no else None, "item_group": item_group if item_group else None, "supplier": supplier}

@frappe.whitelist()
def get_stock_data_from_pr(pr, item_code=None):
    get_serial_no = ''
    if pr:
        sql_query = """
                SELECT 
                    item_code, warehouse, incoming_rate, posting_date, posting_time, batch_no, serial_no
                FROM
                    `tabStock Ledger Entry`
                WHERE
                    voucher_no = %s and item_code = %s
                    AND is_cancelled = 0 AND voucher_type = 'Purchase Receipt'
                ORDER BY
                    posting_date DESC, posting_time DESC, creation DESC
                LIMIT 1
            """
        sle = frappe.db.sql(sql_query, (pr, item_code), as_dict=1)
        
        item_group = frappe.db.get_value("Item", {"name": sle[0]['item_code']}, "item_group")
        
        if sle and sle[0].get('serial_no'):
            get_serial_no = frappe.db.sql(
                """SELECT name FROM `tabSerial No` WHERE item_code = %s 
                AND delivery_document_no IS NULL AND warehouse = %s """,
                (sle[0]['item_code'], sle[0]['warehouse']), as_dict=True
            )
        # supplier = frappe.db.get_value('Purchase Receipt', {'name': pr}, 'supplier')
    return {"result": sle[0], "serial_no": get_serial_no[0]['name'] if get_serial_no else None, "item_group": item_group if item_group else None}

    
    # base_rate=''
    # key = {}
    
        # for i in sle:
        #     key[i['item_code']] = i['warehouse']
    
    # if pr:
    #     result = frappe.db.sql(
    #         """SELECT item_code, warehouse, purchase_order FROM `tabPurchase Receipt Item` WHERE parent = %s """, (pr), as_dict=True)
      
    #     for i in result:
    #         key[i['item_code']] = i['warehouse']
         
    # if item_code:
    #     base_rate_result = frappe.db.sql(
    #         """SELECT base_rate FROM `tabPurchase Receipt Item` WHERE item_code = %s AND parent = %s """, (item_code, pr), as_dict=True)
    #     if base_rate_result:
    #         base_rate = base_rate_result[0].get('base_rate', '')
    # return {"result":sle}

@frappe.whitelist()
def fetch_item_group(item_code):
    item_group = frappe.db.get_value("Item", {"name": item_code}, "item_group")
    return {"item_group": item_group}


@frappe.whitelist()
def create_serial_no(item_group=None, attempt=0):
    MAX_ATTEMPTS = 4
    try:
        if attempt >= MAX_ATTEMPTS:
            frappe.msgprint("Maximum attempts reached. Unable to generate a unique serial number.")
            return None
        
        if item_group:
            serial_no_prefix = frappe.db.get_value("Item Group", {"name": item_group}, "serial_no_prefix")
            if not serial_no_prefix:
                frappe.msgprint(f"Serial No Prefix is not set for Item Group: <strong>{item_group}</strong>")
                return None
            
            prefix = "NJ-"
            serial_no = prefix + serial_no_prefix + '-' + str(random.randint(100000, 999999))
            print(f"Generated serial number: {serial_no}")

            existing_serial = frappe.db.exists("Serial No", {"serial_no": serial_no})
            if existing_serial:
                print(f"Serial number {serial_no} already exists. Attempt {attempt + 1} of {MAX_ATTEMPTS}. Generating another one.")
                return create_serial_no(item_group, attempt + 1)  # Recursive call with increased attempt count
            else:
                generate_and_save_qrcode(serial_no)
                return serial_no
        else:
            frappe.msgprint("Item Group is not provided.")
            return None
    except Exception as e:
        frappe.log_error(f"Error while creating Serial No: {e}")
        return None
    

@frappe.whitelist()
def fetch_model_description(model):
    # Fetch the model description based on the selected model
    model_doc = frappe.get_doc("Models", model)
    if model_doc:
        return {"model_description": model_doc.model_description}
    else:
        return {"model_description": None}
    
# @frappe.whitelist()
# def get_supplier_and_batch_from_pr(pr):
#     try:
#         pr_doc = frappe.get_doc("Purchase Receipt", pr)
#         if pr_doc:
#             return {
#                 "supplier": pr_doc.supplier
#             }
#         else:
#             return {
#                 "supplier": None,
#             }
#     except Exception as e:
#         frappe.log_error(f"Error fetching supplier and batch number from Purchase Receipt: {e}")
#         return {
#             "supplier": None,
#         }
