# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class StockMovement(Document):
    def on_submit(self):
        try:
            if self.stock_entry_type == "Material Transfer":
                stock_entry_doc = frappe.new_doc('Stock Entry')
                stock_entry_doc.purpose = "Material Transfer"
                stock_entry_doc.stock_entry_type = "Material Transfer"
                stock_entry_doc.transfer_status = self.transfer_status
                stock_entry_doc.company = frappe.db.get_single_value("Global Defaults", "default_company")
                stock_entry_doc.reference_type = self.doctype
                stock_entry_doc.reference = self.name

                for item in self.items:
                    stock_entry_item = stock_entry_doc.append('items', {})
                    stock_entry_item.serial_no = item.serial_no
                    stock_entry_item.s_warehouse = item.s_warehouse
                    stock_entry_item.t_warehouse = item.t_warehouse
                    stock_entry_item.item_code = item.item_code
                    stock_entry_item.qty = item.qty
                    if item.reason is not None or item.reason != '':
                        stock_entry_item.reason = item.reason
                    # stock_entry_item.grade = item.grade
            
                stock_entry_doc.save()
                stock_entry_doc.submit()
                if stock_entry_doc.name:
                    base_url = frappe.utils.get_url()
                    stock_entry_link = f"{base_url}/app/stock-entry/{stock_entry_doc.name}"
                    frappe.msgprint(f"Stock Entry: <strong><a href='{stock_entry_link}'>{stock_entry_doc.name}</a></strong> has been submitted successfully.")
        except Exception as e:
            frappe.throw(f"Error in Stock Entry: {e}")

