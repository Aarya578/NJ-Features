import frappe

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
        
    tolerance_amount = po_grand_total * (parameters_dict.get('purchase_receipt_value', 0) / 100)
    
    return {'po_grand_total':po_grand_total, 'tolerance_amount': tolerance_amount,
        'total_billed_amount': total_billed_amount[0].total_billed_amount, 'total_closed_amount': total_closed_amount[0].total_closed_amount}