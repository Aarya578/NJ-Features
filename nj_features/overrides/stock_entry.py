
import frappe
from frappe import _
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

class CustomStockEntry(StockEntry):
    def validate(self):
        # Call parent validation
        super().validate()

        # Validate each row in the 'items' child table
        for item in self.items:
            if not item.source_role_profile:
                # Fetch role profile for the source warehouse
                role_profiles = self.get_target_warehouse_role_profile(item.s_warehouse, item.t_warehouse)                
                if role_profiles.get("source_role_profile"):
                    item.source_role_profile = role_profiles["source_role_profile"]
                if role_profiles.get("target_role_profile"):
                    item.target_role_profile = role_profiles["target_role_profile"]
    

    @frappe.whitelist()
    def get_target_warehouse_role_profile(self, s_warehouse,t_warehouse):
        source_role_profile = ""
        target_role_profile = ""
        if s_warehouse:
        # Query the Employee doctype for the role profile
            source_role_profile = frappe.db.get_value('Employee', {"work_warehouse": s_warehouse}, "role_profile")
        if t_warehouse:
            target_role_profile = frappe.db.get_value('Employee', {"work_warehouse": t_warehouse}, "role_profile")

            return {'source_role_profile':source_role_profile,"target_role_profile":target_role_profile }


