# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import cint, flt
from erpnext.stock.doctype.stock_ledger_entry.stock_ledger_entry import StockLedgerEntry


class CustomStockLedgerEntry(StockLedgerEntry):

    pass

    # def db_update(self):
    #     # Run core SLE update
    #     super().db_update()

    #     # Then custom capacity logic
    #     try:
    #         self.update_available_capacity_in_warehouse()
    #     except Exception:
    #         frappe.log_error(
    #             frappe.get_traceback(),
    #             "Warehouse Qty Capacity Update Failed"
    #         )

    # # Small helper to have consistent logs
    # def log(self, msg: str):
    #     frappe.logger("NJStockLedgerEntryLogger").debug(f"[CAPACITY TRACE] {msg}")

    # def update_available_capacity_in_warehouse(self):
    #     warehouse_name = self.warehouse
    #     if not warehouse_name:
    #         return

    #     self.log(
    #         f"==== START Capacity Update for SLE {self.name} | "
    #         f"Item: {self.item_code} | Warehouse: {warehouse_name} ===="
    #     )

    #     warehouse_doc = frappe.get_doc("Warehouse", warehouse_name)

    #     # Skip group warehouses
    #     if warehouse_doc.is_group:
    #         self.log("Warehouse is a group. Skipping.")
    #         return

    #     # Only track serialized items (remove this check if you want all items)
    #     serial_nos = (self.serial_no or "").strip()
    #     if not serial_nos:
    #         self.log("No serial numbers on this SLE. Skipping Warehouse Qty update.")
    #         return

    #     change = cint(flt(self.actual_qty or 0))  # +1 for in, -1 for out
    #     self.log(f"SLE.actual_qty (change) = {change}")

    #     # ------------------------------------------------------------------
    #     # 1) Check if Warehouse Qty already exists (we'll update incrementally)
    #     # ------------------------------------------------------------------
    #     existing = frappe.db.sql(
    #         """
    #         SELECT name, qty_after_transaction
    #         FROM `tabWarehouse Qty`
    #         WHERE warehouse = %s
    #         FOR UPDATE
    #         """,
    #         (warehouse_name,),
    #         as_dict=True,
    #     )

    #     if existing:
    #         # Incremental update from stored qty
    #         row = existing[0]
    #         name = row.name
    #         qty_before = cint(row.qty_after_transaction or 0)

    #         self.log(f"Existing Warehouse Qty record: {name}")
    #         self.log(f"Qty BEFORE this SLE (from Warehouse Qty) = {qty_before}")

    #         qty_after_transaction = qty_before + change
    #         if qty_after_transaction < 0:
    #             self.log(
    #                 f"Computed qty_after_transaction {qty_after_transaction} < 0. "
    #                 "Resetting to 0."
    #             )
    #             qty_after_transaction = 0

    #     else:
    #         # No record yet → bootstrap from Serial No table once
    #         self.log("No Warehouse Qty record. Bootstrapping from Serial No count.")

    #         query = "SELECT COUNT(*) as qty FROM `tabSerial No` WHERE warehouse = %s"
    #         params = [warehouse_name]

    #         item_groups = [row.part for row in warehouse_doc.item_group]
    #         if item_groups:
    #             placeholders = ",".join(["%s"] * len(item_groups))
    #             query += f" AND item_group IN ({placeholders})"
    #             params += item_groups

    #         brands = [row.brand for row in warehouse_doc.brand]
    #         if brands:
    #             placeholders = ",".join(["%s"] * len(brands))
    #             query += f" AND brand IN ({placeholders})"
    #             params += brands

    #         self.log(f"Bootstrap SQL Query: {query}")
    #         self.log(f"Bootstrap SQL Params: {params}")

    #         result = frappe.db.sql(query, tuple(params), as_dict=True)
    #         current_qty = cint(result[0].qty) if result else 0

    #         self.log(f"Bootstrap Serial No Count = {current_qty}")

    #         # Take that as our starting true qty
    #         qty_after_transaction = current_qty

    #     # ------------------------------------------------------------------
    #     # 2) Capacity calculations
    #     # ------------------------------------------------------------------
    #     max_capacity = cint(warehouse_doc.max_capacity or 0)
    #     available_capacity = max_capacity - qty_after_transaction
    #     if available_capacity < 0:
    #         available_capacity = 0

    #     self.log(f"Max Capacity: {max_capacity}")
    #     self.log(f"Final Total Qty (After Movement) = {qty_after_transaction}")
    #     self.log(f"Available Capacity = {available_capacity}")

    #     # ------------------------------------------------------------------
    #     # 3) Write back into Warehouse Qty
    #     # ------------------------------------------------------------------
    #     if existing:
    #         name = existing[0].name
    #         self.log(f"UPDATE Warehouse Qty: {name}")

    #         frappe.db.sql(
    #             """
    #             UPDATE `tabWarehouse Qty`
    #             SET max_capacity = %s,
    #                 available_capacity = %s,
    #                 qty_after_transaction = %s
    #             WHERE name = %s
    #             """,
    #             (max_capacity, available_capacity, qty_after_transaction, name),
    #         )
    #     else:
    #         self.log("INSERT new Warehouse Qty record")

    #         frappe.get_doc(
    #             {
    #                 "doctype": "Warehouse Qty",
    #                 "warehouse": warehouse_name,
    #                 "max_capacity": max_capacity,
    #                 "available_capacity": available_capacity,
    #                 "qty_after_transaction": qty_after_transaction,
    #             }
    #         ).insert(ignore_permissions=True)

    #     self.log(
    #         f"==== END Capacity Update for SLE {self.name} | "
    #         f"Warehouse: {warehouse_name} ===="
    #     )