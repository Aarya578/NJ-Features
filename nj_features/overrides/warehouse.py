import frappe
from erpnext.stock.doctype.warehouse.warehouse import Warehouse as CoreWarehouse

class CustomWarehouse(CoreWarehouse):
    def validate(self):
        pass
    #     super().validate()

    #     if self.is_group:
    #         return
        
    #     old_doc = self.get_doc_before_save()
        
    #     if (
    #         old_doc and (
    #             self.max_capacity != old_doc.max_capacity
    #             or self.item_group != old_doc.item_group
    #             or self.brand != old_doc.brand
    #         )
    #     ):
    #         self.update_available_capacity_in_warehouse()

    
    # def update_available_capacity_in_warehouse(self):
    #     query = "SELECT COUNT(*) as qty FROM `tabSerial No` WHERE warehouse = %s"
    #     params = [self.name]

    #     item_groups = [row.part for row in self.item_group]
    #     if item_groups:
    #         placeholders = ','.join(['%s'] * len(item_groups))
    #         query += f" AND item_group IN ({placeholders})"
    #         params += item_groups

    #     brands = [row.brand for row in self.brand]
    #     if brands:
    #         placeholders = ','.join(['%s'] * len(brands))
    #         query += f" AND brand IN ({placeholders})"
    #         params += brands

    #     result = frappe.db.sql(query, tuple(params), as_dict=True)
    #     qty_after_transaction = result[0].qty if result else 0

    #     max_capacity = self.max_capacity or 0
    #     available_capacity = int(max_capacity) - int(qty_after_transaction or 0)

    #     existing = frappe.get_value("Warehouse Qty", {"warehouse": self.name}, "name")

    #     if existing:
    #         frappe.db.set_value("Warehouse Qty", existing, {
    #             "max_capacity": max_capacity,
    #             "available_capacity": available_capacity,
    #             "qty_after_transaction": qty_after_transaction
    #         }, update_modified=False)
    #     else:
    #         frappe.get_doc({
    #             "doctype": "Warehouse Qty",
    #             "warehouse": self.name,
    #             "max_capacity": max_capacity,
    #             "available_capacity": available_capacity,
    #             "qty_after_transaction": qty_after_transaction
    #         }).insert(ignore_permissions=True)