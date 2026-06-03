# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class CustomerResponse(Document):
	pass
@frappe.whitelist()     
def after_insert(doc, method):
    """Auto-update Quotation when Customer Response is created."""
    if not doc.quotation_name:
        return

    # Fetch Quotation
    quotation = frappe.get_doc("Quotation", doc.quotation_name)
    print("quotation=================",quotation)
    

    # Update reply
    quotation.customer_replay = doc.response
    print("quotation.customer_reply=================",quotation.customer_replay)

    # Save and submit (if needed)
    quotation.save(ignore_permissions=True)
    # frappe.db.commit()