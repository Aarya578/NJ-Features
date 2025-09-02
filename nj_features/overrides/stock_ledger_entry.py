# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from erpnext.stock.doctype.stock_ledger_entry.stock_ledger_entry import StockLedgerEntry

class CustomStockLedgerEntry(StockLedgerEntry):
    def db_update(self):
        super().db_update()
        self.update_available_capacity_in_warehouse()
        
    def update_available_capacity_in_warehouse(self):

        warehouse_name = self.warehouse
        warehouse_doc = frappe.get_doc('Warehouse', warehouse_name)

        if warehouse_doc.is_group:
            return

        query = "SELECT COUNT(*) as qty FROM `tabSerial No` WHERE warehouse = %s"
        params = [warehouse_name]

        item_groups = [row.part for row in warehouse_doc.item_group]
        if item_groups:
            placeholders = ','.join(['%s'] * len(item_groups))
            query += f" AND item_group IN ({placeholders})"
            params += item_groups

        brands = [row.brand for row in warehouse_doc.brand]
        if brands:
            placeholders = ','.join(['%s'] * len(brands))
            query += f" AND brand IN ({placeholders})"
            params += brands

        result = frappe.db.sql(query, tuple(params), as_dict=True)
        qty_after_transaction = result[0].qty if result else 0

        max_capacity = warehouse_doc.max_capacity or 0
        available_capacity = int(max_capacity) - int(qty_after_transaction or 0)

        existing = frappe.get_value("Warehouse Qty", {"warehouse": warehouse_name}, "name")

        if existing:
            frappe.db.set_value("Warehouse Qty", existing, {
                "available_capacity": available_capacity,
                "qty_after_transaction": qty_after_transaction
            }, update_modified=False)
        else:
            frappe.get_doc({
                "doctype": "Warehouse Qty",
                "warehouse": warehouse_name,
                "max_capacity": max_capacity,
                "available_capacity": available_capacity,
                "qty_after_transaction": qty_after_transaction
            }).insert(ignore_permissions=True)