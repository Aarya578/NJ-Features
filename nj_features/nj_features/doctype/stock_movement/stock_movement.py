# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class StockMovement(Document):
    def on_submit(self):
        if self.stock_entry_type == "Material Transfer":
            stock_entry_doc = frappe.new_doc('Stock Entry')
            stock_entry_doc.purpose = "Material Transfer"
            stock_entry_doc.stock_entry_type = "Material Transfer"
            stock_entry_doc.company = frappe.db.get_single_value("Global Defaults", "default_company")

            for item in self.items:
                stock_entry_item = stock_entry_doc.append('items', {})
                stock_entry_item.serial_no = item.serial_no
                stock_entry_item.s_warehouse = item.s_warehouse
                stock_entry_item.t_warehouse = item.t_warehouse
                stock_entry_item.item_code = item.item_code
                stock_entry_item.qty = item.qty
                # stock_entry_item.grade = item.grade
            stock_entry_doc.insert()
            print(f"stock_entry_doc: {stock_entry_doc}")
            stock_entry_doc.submit()

