# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import random
import frappe

from frappe.model.document import Document

class Inward(Document):
	pass

@frappe.whitelist()
def get_items_from_pr(pr):
    item_code = frappe.db.sql(
        """SELECT Item_code FROM `tabPurchase Receipt Item` WHERE parent = %s """, (pr), as_dict=True)

    return item_code

@frappe.whitelist()
def create_serial_no(item_code):
    is_serial = frappe.get_value('Item', {'name': item_code}, 'has_serial_no')
    if is_serial == 1:
        new_serial = generate_random_code()
        return new_serial
    else:
        return None

def generate_random_code():
    prefix = "NJ"
    random_code = prefix + str(random.randint(100000, 999999))
    return random_code