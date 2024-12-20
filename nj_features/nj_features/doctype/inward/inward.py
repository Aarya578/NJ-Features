# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
import random
from frappe import _
from frappe.model.document import Document
from erpnext.controllers.item_variant import get_variant
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
from nj_lib.utils.common_utils import get_latest_item_wizard
from nj_features.nj_features.api.qr_code import generate_and_save_qrcode

class Inward(Document):
    def on_submit(self):
        self.make_stock_entry_using_nj_lib()
        generate_and_save_qrcode(self.serial_no)

    def make_stock_entry_using_nj_lib(self):
        stock_data = {
            "name": self.name,
            "doctype": self.doctype,
            "stock_entry_type": "Repack",
            "series": "STE-INW-.YYYY.-.MM.-",
            "repack_items": get_repack_items(self)
        }
        stock_data_str = json.dumps(stock_data)
        stock_entry = stock_entry_using_nj_lib(stock_data_str)
        
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
            serial_no_doc.purchase_order = po
            serial_no_doc.barcode = self.serial_no
            serial_no_doc.warranty_days = warranty_days
            serial_no_doc.supplier_name = supplier_name
            serial_no_doc.current_price = self.base_rate
            serial_no_doc.purchase_price = self.base_rate
            serial_no_doc.supplier = po_doc.get('supplier')
            serial_no_doc.purchase_warranty_days = warranty_days
            serial_no_doc.purchase_receipt = self.purchase_receipt
            serial_no_doc.reference_doctype_no = self.purchase_receipt
            serial_no_doc.vendor_warranty_expiry_date = po_doc.get('warranty_till_date')

            has_batch_no = frappe.db.get_value('Item', {'name': self.item_code}, 'has_batch_no')
            if has_batch_no:
                serial_no_doc.batch_no = self.batch_no

            serial_no_doc.save()
        else:
            frappe.throw(f"Serial No document not found for the given <b>Serial No. : {self.serial_no}</b>")

def get_repack_items(self):
    get_repack_items_list = []

    get_repack_items_dict = {
        "batch_no": self.batch_no,
		"repack_item_code": self.item_code,
		"repack_item_base_price": self.base_rate,
        "repack_item_source_warehouse": self.source_warehouse,
	}
    get_repack_items_list.append(get_repack_items_dict)

    get_unpack_items_dict = {
		"unpack_serial_no": self.serial_no,
		"unpack_item_base_price": self.base_rate,
		"unpack_item_code": self.repack_item_code,
        "unpack_item_target_warehouse": self.target_warehouse,
	}
    get_repack_items_list.append(get_unpack_items_dict)
    
    return get_repack_items_list

@frappe.whitelist()
def get_item_list_from_pr(pr):
    item_codes = frappe.db.get_list('Item', filters={'has_batch_no': 1}, pluck='item_code')
    pr_item_codes = frappe.db.get_list('Purchase Receipt Item', {'parent': pr}, ['item_code'])
    item_codes_in_pr = [item['item_code'] for item in pr_item_codes if item['item_code'] in item_codes]
    
    return item_codes_in_pr

@frappe.whitelist()
def get_repack_item_code(item_template):
    item_code_attributes = []
    item_code_attributes_data = frappe.db.get_value('NJ Settings', {'doc_type': 'Inward', 'parameter': 'item_code_attributes'}, 'value')
    item_code_attributes = item_code_attributes_data.split(',')
    
    attributes_list = frappe.db.get_list('NJ Settings', {'doc_type': 'Inward', 'parameter': ['in', item_code_attributes]},
                                        ['parameter', 'value'])
    attributes_dict = {attr['parameter']: attr['value'] for attr in attributes_list}
    repack_item_code = get_variant(item_template, attributes_dict)
    
    if repack_item_code is None or repack_item_code == '':
        attributes_dict = {attr['parameter']: attr['value'].upper() for attr in attributes_list}
        repack_item_code = get_variant(item_template, attributes_dict)
    
    return {"repack_item_code": repack_item_code}

@frappe.whitelist()
def get_stock_data_from_pr(pr, item_code=None):
    try:
        get_serial_no = ''
        if pr:
            pri_query = """ SELECT b.name, pri.item_group FROM `tabPurchase Receipt Item` pri
                            INNER JOIN `tabBatch` b ON b.name = pri.batch_no
                            WHERE pri.parent = %s AND pri.item_code = %s AND pri.docstatus = 1
                            AND b.batch_qty > 0
                            LIMIT 1"""
            pri_data = frappe.db.sql(pri_query, (pr, item_code), as_dict=True)

            if not pri_data:
                frappe.throw("No Batch Found for the given Item Code: <b>" + item_code + "</b> in Purchase Receipt: <b>" + pr + "</b>!</b>.")
            
            sql_query = """
                SELECT item_code, warehouse, incoming_rate, serial_no, batch_no
                FROM `tabStock Ledger Entry`
                WHERE
                    voucher_no = %s and item_code = %s and batch_no = %s
                    AND is_cancelled = 0 AND voucher_type = 'Purchase Receipt'
                ORDER BY posting_date DESC, posting_time DESC, creation DESC
                LIMIT 1
            """
            sle = frappe.db.sql(sql_query, (pr, item_code, pri_data[0]['name']), as_dict=1)
            
            if sle and sle[0].get('serial_no'):
                get_serial_no = frappe.db.sql(
                    """SELECT name FROM `tabSerial No` WHERE item_code = %s 
                    AND delivery_document_no IS NULL AND warehouse = %s """,
                    (sle[0]['item_code'], sle[0]['warehouse']), as_dict=True
                )

            if sle:
                sle[0]['item_group'] = pri_data[0]['item_group']
                
        return {"result": sle[0], "serial_no": get_serial_no[0]['name'] if get_serial_no else None}
    except Exception as e:
        frappe.throw(str(e))
        return str(e)

@frappe.whitelist()
def create_serial_no_and_get_item_code(item_group, brand, model, serial_no=None):
    wizard_list = ''
    if serial_no is None:
        serial_no = create_serial_no(item_group)
    item_template = get_item_template(brand, model, item_group)
    if item_template:
        wizard_list = has_item_wizards(item_template)
        
    return {'serial_no': serial_no, 'item_template': item_template, 'wizard_list': wizard_list}

def get_item_template(brand, model, item_group):
    item_template = frappe.db.get_list('Item', {'brand': brand, 'item_model':model, 'has_variants': 1, 'item_group': item_group, 'disabled': 0}, 'name')
    if item_template:
        return item_template
    return None
    
def has_item_wizards(item_template):
    wizard_list = []
    for item in item_template:
        available_wizard = get_latest_item_wizard(item.get('name'))
        if available_wizard:
            wizard_list.append(item.get('name'))
    return wizard_list

def create_serial_no(item_group=None, attempt=0):
    MAX_ATTEMPTS = 4
    try:
        if attempt >= MAX_ATTEMPTS:
            frappe.msgprint("Maximum attempts reached. Unable to generate a unique serial number.")
            return None
        
        if item_group:
            serial_no_prefix = frappe.db.get_value("Item Group", {"name": item_group}, "serial_no_prefix")
            if not serial_no_prefix:
                frappe.msgprint(f"<b>Serial No Prefix</b> is not set for Item Group: <strong>{item_group}</strong>. Please contact <b>NPD Team</b>.")
                return None
            
            prefix = "NJ-"
            serial_no = prefix + serial_no_prefix + '-' + str(random.randint(100000, 999999))

            existing_serial = frappe.db.exists("Serial No", {"serial_no": serial_no})
            if existing_serial:
                return create_serial_no(item_group, attempt + 1)
            else:
                return serial_no
        else:
            frappe.msgprint("Item Group is not provided.")
            return None
    except Exception as e:
        frappe.log_error(f"Error while creating Serial No: {e}")
        return None
    
@frappe.whitelist()
def fetch_model_description(model):
    model_description = frappe.db.get_value('Models', {'name':model}, 'model_description')
    if model_description:
        return {"model_description": model_description}
    return {"model_description": None}

@frappe.whitelist()
def get_item_code_filtered_data(doctype, txt, searchfield, start, page_len, filters):
    """
    Query to fetch filtered options for the repack_item_code field.
    """
    item_group = filters.get("item_group")
    model = filters.get("model")
    brand = filters.get("brand")
    
    # Build the SQL query dynamically based on provided filters
    query = """
        SELECT name 
        FROM `tabItem`
        WHERE 1=1 AND has_variants = 0 AND disabled = 0
    """
    params = []
    
    if item_group:
        query += " AND item_group = %s"
        params.append(item_group)
    
    if model:
        query += " AND item_model = %s"
        params.append(model)
    
    if brand:
        query += " AND brand = %s"
        params.append(brand)
    
    query += " ORDER BY name LIMIT %s, %s"
    params.extend([start, page_len])

    return frappe.db.sql(query, params)
