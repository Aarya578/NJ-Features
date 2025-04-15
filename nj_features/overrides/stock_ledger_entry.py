# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from erpnext.stock.doctype.stock_ledger_entry.stock_ledger_entry import StockLedgerEntry

class CustomStockLedgerEntry(StockLedgerEntry):
    def db_update(self):
        super().db_update()
        self.update_available_capacity_in_warehouse()
        # self.notify_warehouse_owner_if_applicable()
        
    def update_available_capacity_in_warehouse(self):
        warehouse_doc_data = frappe.get_doc('Warehouse', self.warehouse)
        if warehouse_doc_data:
            available_capacity = int(warehouse_doc_data.max_capacity or 0) - int(self.qty_after_transaction or 0)
            warehouse_doc_data.db_set('available_capacity', available_capacity)
            warehouse_doc_data.db_set('qty_after_transaction', self.qty_after_transaction)

    def notify_warehouse_owner_if_applicable(self):
        warehouse_doc = frappe.get_doc('Warehouse', self.warehouse)
        warehouse_owner = warehouse_doc.warehouse_owner

        if self.actual_qty > 0 and self.is_cancelled == 0:
            subject = f"Stock has been received in your Warehouse ({self.warehouse})"
            message = f"""
                A Stock Entry - {self.voucher_no} was created:<br>
                <b>Item:</b> {self.item_code}<br>
                <b>Qty:</b> {self.actual_qty}<br>
                <b>Serial No(s):</b> {self.serial_no}<br>
                <b>Balance Qty:</b> {self.qty_after_transaction}
            """
            frappe.get_doc({
                "doctype": "Notification Log",
                "subject": subject,
                "email_content": message,
                "for_user": warehouse_owner,
                "document_type": self.doctype,
                "document_name": self.name,
                "type": "Alert",
            }).insert(ignore_permissions=True)