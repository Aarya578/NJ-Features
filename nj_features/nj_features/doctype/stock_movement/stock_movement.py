# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib

class StockMovement(Document):
    def on_submit(self):
        try:
            material_transfer_items = []
            
            stock_entry_data = {
                "name": self.name,
                "doctype": self.doctype,
                "series": "STE-SM-.YYYY.-.MM.-",
                "transfer_status": self.transfer_status,
                "stock_entry_type": "Material Transfer",
                "material_transfer_items": material_transfer_items,
            }
            
            for row in self.items:
                material_transfer_items.append({
                    'qty': row.qty,
                    'item_code': row.item_code,
                    's_warehouse': row.s_warehouse,
                    't_warehouse': row.t_warehouse,
                    'reason': row.reason if row.reason else None,
                    'serial_no': row.serial_no if row.serial_no else None,
                })

            if material_transfer_items:
                return stock_entry_using_nj_lib(stock_entry_data)
            else:
                frappe.throw("None available in <b>Items</b> table.")

        except Exception as e:
            frappe.throw("Error while submitting Stock Entry: ", e)