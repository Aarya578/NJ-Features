# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
import traceback
from frappe.utils import flt
from frappe.model.mapper import get_mapped_doc

def create_batch(doc, method=None):
    for item in doc.items:
        item_doc = frappe.get_doc("Item", item.item_code)
        if item_doc.has_batch_no:
            batch_doc = frappe.new_doc('Batch')
            batch_doc.batch_id = doc.name +'-'+ str(item.idx)
            batch_doc.item = item.item_code
            batch_doc.save()
            
@frappe.whitelist()
def check_billed_and_closed_amount(purchase_order, po_grand_total):
    po_grand_total = float(po_grand_total)
    
    total_billed_amount_query = """SELECT SUM(net_amount) AS total_billed_amount FROM `tabPurchase Receipt Item`
                                WHERE purchase_order = %s AND docstatus = 1"""
    total_billed_amount = frappe.db.sql(total_billed_amount_query, (purchase_order), as_dict=1)
    
    total_closed_amount_query = """SELECT SUM(net_amount) AS total_closed_amount FROM `tabPurchase Invoice Item` 
                                WHERE purchase_order = %s AND docstatus = 1"""
    total_closed_amount = frappe.db.sql(total_closed_amount_query, (purchase_order), as_dict=1)
    
    parameters_dict = {}
    po_nj_settings = frappe.db.get_all('NJ Settings', {'module': 'NJ Features', 'doc_type': 'Purchase Order'}, ['parameter', 'value'])
    
    for param in po_nj_settings:
        if param.parameter == 'purchase_receipt_value':
            parameters_dict[param.parameter] = float(param.value)
        else:
            parameters_dict[param.parameter] = param.value
            
    tolerance_amount = parameters_dict.get('purchase_receipt_value', 0)
    if parameters_dict.get('purchase_receipt_type').lower() == 'percentage':
        tolerance_amount = po_grand_total * (parameters_dict.get('purchase_receipt_value', 0) / 100)
    
    return {'po_grand_total':po_grand_total, 'tolerance_amount': tolerance_amount,
        'total_billed_amount': total_billed_amount[0].total_billed_amount, 'total_closed_amount': total_closed_amount[0].total_closed_amount}

@frappe.whitelist()
def make_purchase_receipt(source_name, target_doc=None, sir_name=None):
    try:
        def update_item(obj, target, source_parent):
            if sir_name:
                sir_doc = frappe.get_doc('Security Inward Registry', sir_name)
                for sir_item in sir_doc.get('transfer_registry', []):
                    if sir_item.get('item_code') == obj.item_code:
                        target.qty = sir_item.get('actual_qty')
                        
            # target.qty = flt(obj.qty) - flt(obj.received_qty)
            target.stock_qty = (flt(obj.qty) - flt(obj.received_qty)) * flt(obj.conversion_factor)
            target.amount = (flt(obj.qty) - flt(obj.received_qty)) * flt(obj.rate)
            target.base_amount = (
                (flt(obj.qty) - flt(obj.received_qty)) * flt(obj.rate) * flt(source_parent.conversion_rate)
            )

        doc = get_mapped_doc(
            "Purchase Order",
            source_name,
            {
                "Purchase Order": {
                    "doctype": "Purchase Receipt",
                    "field_map": {"supplier_warehouse": "supplier_warehouse"},
                    "validation": {
                        "docstatus": ["=", 1],
                    },
                },
                "Purchase Order Item": {
                    "doctype": "Purchase Receipt Item",
                    "field_map": {
                        "name": "purchase_order_item",
                        "parent": "purchase_order",
                        "bom": "bom",
                        "material_request": "material_request",
                        "material_request_item": "material_request_item",
                    },
                    "postprocess": update_item,
                    "condition": lambda doc: abs(doc.received_qty) < abs(doc.qty)
                    and doc.delivered_by_supplier != 1,
                },
                "Purchase Taxes and Charges": {"doctype": "Purchase Taxes and Charges", "add_if_empty": True},
            },
            target_doc,
            set_missing_values,
        )

        doc.set_onload("ignore_price_list", True)

        return doc

    except Exception as e:
        traceback_info = traceback.format_exc()
        return {'error': str(e), 'traceback': traceback_info}
    


def validate_mandatory_links(doc, method=None):

    core_item_groups = ['Laptops', 'Chromeboxes', 'Chromebooks', 'Desktops']
    requires_links = False
    
    for item in doc.items:
        item_group = frappe.db.get_value('Item', item.item_code, 'item_group')
        if item_group in core_item_groups:
            requires_links = True
            break  
    
    if requires_links:
        if not doc.qc_link or not doc.pricing_link or not doc.npd_approval_:
            frappe.throw("QC Link,Pricing Link and NPD Approval is mandatory when core products are included in the Purchase Order.")
      
def set_missing_values(source, target):
	target.run_method("set_missing_values")
	target.run_method("calculate_taxes_and_totals")