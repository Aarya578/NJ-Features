import frappe

def create_batch(doc, method=None):
    batch_doc = frappe.new_doc('Batch')
    batch_doc.batch_id = doc.name
    if doc.items:
        batch_doc.item = doc.items[0].item_code
    batch_doc.save()