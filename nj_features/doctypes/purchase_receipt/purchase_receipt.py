import frappe

@frappe.whitelist()
def check_existing_item(doc, method):
    items = doc.items
    for row in items:
        brand = row.brand
        model = row.model
        new_item = brand + " " + model
        # Check if an item with the same name already exists
        if not frappe.db.exists('Item', {'item_code': new_item}):
            frappe.throw("Item '{}' don't exists. Please contact a person with permission to create items. Do not delete or submit this document.".format(new_item))
        else:
            pass
