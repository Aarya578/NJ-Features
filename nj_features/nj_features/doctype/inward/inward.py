# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import random
# from apps.backup.nj_features.nj_features.nj_features.doctype.iqc.iqc import generate_random_code
import frappe
from nj_features.nj_features.repack import repack
from frappe.model.document import Document

class Inward(Document):
    def on_submit(self):
        repack(self.name)

@frappe.whitelist()
def get_items_from_pr(pr,item_code=None):
    base_rate=''
    if pr:
        result = frappe.db.sql(
            """SELECT Item_code, warehouse FROM `tabPurchase Receipt Item` WHERE parent = %s """, (pr), as_dict=True)
    if item_code:
        base_rate_result = frappe.db.sql(
            """SELECT base_rate FROM `tabPurchase Receipt Item` WHERE item_code = %s AND parent = %s """, (item_code, pr), as_dict=True)
        if base_rate_result:
            base_rate = base_rate_result[0].get('base_rate', '')
    print(f"------item code is {result}- ----------------- base rate is    {base_rate}--------------------")
    return {"result":result, "base_rate": base_rate}

@frappe.whitelist()
def fetch_item_group(item_code):
    item_group = frappe.db.get_value("Item", {"name": item_code}, "item_group")
    return {"item_group": item_group}


@frappe.whitelist()
def create_serial_no():
    prefix = "NJ"
    random_code = prefix + str(random.randint(100000, 999999))
    return random_code

# @frappe.whitelist
# def get_items(pr):
#     items=frappe.db.get_value("Purchase Receipt",{"name":pr},"total")
#     print(f"-------------{items}----------------------")
#     return items