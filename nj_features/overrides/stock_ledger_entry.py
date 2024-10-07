# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from erpnext.stock.doctype.stock_ledger_entry.stock_ledger_entry import StockLedgerEntry

class CustomStockLedgerEntry(StockLedgerEntry):
    def db_update(self):
        super().db_update()
        self.update_available_capacity_in_warehouse()
        
    def update_available_capacity_in_warehouse(self):
        warehouse_doc_data = frappe.get_doc('Warehouse', self.warehouse)
        if warehouse_doc_data:
            available_capacity = int(warehouse_doc_data.max_capacity or 0) - int(self.qty_after_transaction or 0)
            warehouse_doc_data.db_set('available_capacity', available_capacity)
            warehouse_doc_data.db_set('qty_after_transaction', self.qty_after_transaction)