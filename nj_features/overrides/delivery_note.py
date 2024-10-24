# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import frappe
import json
from frappe import _


@frappe.whitelist()
def set_tracking_id_for_delivery_note(doc):

    if isinstance(doc, str):
        doc = json.loads(doc)

    dn_item = doc.get('items')[0].get('against_sales_order')

    sales_order_type = frappe.db.get_value('Sales Order', dn_item, 'sale_type')

    if sales_order_type == 'Amazon':
        return True
    
    return False