import frappe

def get_batch(doc, method=None):
    for item in doc.items:
        item_doc = frappe.get_doc("Item", item.item_code)
        if item_doc.has_batch_no:
            item.batch_no = item.purchase_order +'-'+ str(item.idx)