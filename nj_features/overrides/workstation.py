import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
    add_days,
    cint,
    comma_and,
    flt,
    formatdate,
    getdate,
    time_diff_in_seconds,
    to_timedelta,
)
from erpnext.manufacturing.doctype.workstation.workstation import Workstation

class CustomeWorkstation(Workstation):
    def validate(self):
          self.update_table_equipments_from_layout()
    


    def update_table_equipments_from_layout(self):
        if self.table_layout:
            # Clear existing child table
            self.set("table_equipments", [])

            # Fetch child table records using SQL
            data = frappe.db.sql("""
                SELECT item_group, item_code, qty
                FROM `tabTable Equipments`
                WHERE parent = %s AND parenttype = 'Table Layout'
            """, (self.table_layout,), as_dict=True)
            # print("data=====================",data)
            # Add rows to current Workstation's child table
            for row in data:
                self.append("table_equipments", {
                    "item_group": row.item_group,
                    "item_code": row.item_code,
                    "qty": row.qty
                })

