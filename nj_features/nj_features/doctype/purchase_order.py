import frappe

def create_batch(doc, method=None):
    for item in doc.items:
        item_doc = frappe.get_doc("Item", item.item_code)
        if item_doc.has_batch_no:
            batch_doc = frappe.new_doc('Batch')
            batch_doc.batch_id = doc.name +'-'+ str(item.idx)
            batch_doc.item = item.item_code
            batch_doc.save()