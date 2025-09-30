# apps/nj_features/nj_features/overrides/product_bundle.py

import frappe
from frappe import _
from erpnext.selling.doctype.product_bundle.product_bundle import ProductBundle

class CustomProductBundle(ProductBundle):
	def validate(self):
		self.deleting_rerord__if_table_modified()

	def deleting_rerord__if_table_modified(self):
		import re
		
		# Enhanced debug function
		def debug_string(s):
			return f"'{s}' (length: {len(s)}, hex: {s.encode('utf-8').hex()})"
		
		# Step 1: Get parent-level shopify_variant_id with validation
		shopify_variant_id = (getattr(self, 'shopify_variant_id', '') or '').strip()
		if not shopify_variant_id:
			frappe.msgprint("No Shopify Variant ID found in Product Bundle.")
			return
		
		frappe.logger().debug(f"Processing shopify_variant_id: {debug_string(shopify_variant_id)}")

		# Step 2: Fetch NJ Inventory Sync Main records
		try:
			sync_docs = frappe.get_all(
				"NJ Inventory Sync Main",
				filters={"shopify_variant_id": shopify_variant_id},
				fields=["name", "item_code"]
			)
			frappe.logger().debug(f"Found {len(sync_docs)} sync records")
		except Exception as e:
			frappe.log_error(f"Error fetching NJ Inventory Sync Main records: {str(e)}")
			frappe.throw("Error fetching inventory records. Please check logs.")

		if not sync_docs:
			frappe.msgprint("No matching NJ Inventory Sync Main record found.")
			return

		# Step 3: Get child items with rigorous cleaning
		child_items = self.get("product_bundle_item") or []
		child_item_codes = []
		
		for row in child_items:
			if not row or not getattr(row, 'item_code', None):
				continue
				
			# Aggressive cleaning of item_code
			cleaned_code = re.sub(r'\s+', ' ', str(row.item_code).strip()).lower()
			child_item_codes.append(cleaned_code)
			frappe.logger().debug(f"Child item: {debug_string(row.item_code)} → Cleaned: {debug_string(cleaned_code)}")

		# Step 4: Process sync records with detailed comparison
		deleted_records = []
		kept_records = []
		
		for sync_doc in sync_docs:
			if not sync_doc or not sync_doc.item_code:
				continue
				
			# Aggressive cleaning of sync item_code
			sync_item_code = re.sub(r'\s+', ' ', str(sync_doc.item_code).strip()).lower()
			original_code = sync_doc.item_code
			
			frappe.logger().debug(f"Checking sync record: {debug_string(original_code)} → Cleaned: {debug_string(sync_item_code)}")
			frappe.logger().debug(f"Child codes: {child_item_codes}")
			
			if sync_item_code in child_item_codes:
				kept_records.append(original_code)
				frappe.logger().debug(f"MATCH FOUND - Keeping: {debug_string(original_code)}")
			else:
				try:
					frappe.delete_doc("NJ Inventory Sync Main", sync_doc.name, force=1, delete_permanently=True)
					deleted_records.append(original_code)
					frappe.logger().debug(f"NO MATCH - Deleting: {debug_string(original_code)}")
				except Exception as e:
					error_msg = f"Error deleting {sync_doc.name}: {str(e)}"
					frappe.log_error(error_msg)
					frappe.msgprint(f"Failed to delete record for item {original_code}")

		# Detailed result reporting
		if deleted_records:
			msg = f"Deleted {len(deleted_records)} records: {', '.join(deleted_records)}"
			frappe.msgprint(msg)
		if kept_records:
			msg = f"Kept {len(kept_records)} records: {', '.join(kept_records)}"
			frappe.msgprint(msg)
		
		if not deleted_records and not kept_records:
			frappe.msgprint("No matching items found in child table")


# def deleting_rerord__if_table_modified(self):
#     import frappe
#     # Step 1: Get parent-level shopify_variant_id
#     shopify_variant_id = self.shopify_variant_id
#     if not shopify_variant_id:
#         frappe.msgprint("No Shopify Variant ID found in Product Bundle.")
#         return
    
#     # Step 2: Fetch ALL NJ Inventory Sync Main records using shopify_variant_id
#     sync_docs = frappe.get_all(
#         "NJ Inventory Sync Main",
#         filters={"shopify_variant_id": shopify_variant_id},
#         fields=["name", "item_code"]
#     )
#     if not sync_docs:
#         frappe.msgprint("No matching NJ Inventory Sync Main record found.")
#         return
    
#     # Step 3: Get child items
#     child_items = self.get("product_bundle_item") or []
#     child_item_codes = [row.item_code for row in child_items if row.item_code]
    
#     # Step 4: Delete records where item_code is NOT in child table
#     deleted_records = []
#     for sync_doc in sync_docs:
#         sync_item_code = sync_doc.item_code
        
#         # Only delete if item_code NOT found in child table
#         if sync_item_code not in child_item_codes:
#             frappe.delete_doc("NJ Inventory Sync Main", sync_doc.name, force=1, delete_permanently=True)
#             deleted_records.append(sync_item_code)
    
#     if deleted_records:
#         frappe.msgprint(f"Deleted {len(deleted_records)} records in NJ Inventory Sync Main")
#     else:
#         frappe.msgprint("No changes in child table")
		
# def update_product_bundle_quantities():
#     # Step 1: Fetch item_code and count from Serial No
	
#     data = frappe.db.sql("""
#         SELECT 
#             a.item_code,
#             COUNT(a.item_code) AS item_code_count
#         FROM 
#             `tabSerial No` a
#         INNER JOIN 
#             `tabWarehouse` b ON a.warehouse = b.name
#         WHERE 
#             a.item_group IN ('Desktops', 'Chromeboxes', 'Laptops', 'Chromebooks', 'Full Set Desktops', 'MacBooks') 
#             AND a.warehouse != ''
#             AND b.department IN ('Packing & Dispatch - NJ', 'BG - Adaptor QC - NJ')
#         GROUP BY 
#             a.item_code
#         ORDER BY item_code_count DESC
#     """, as_dict=True)

#     # Step 2: Create a mapping of item_code → item_code_count
#     item_code_count_map = {
#         row.item_code.strip(): row.item_code_count
#         for row in data if row.item_code
#     }

#     # Step 3: Loop through all Product Bundles
#     all_bundles = frappe.get_all("Product Bundle", fields=["name"])
	
#     for pb in all_bundles:
#         pb_doc = frappe.get_doc("Product Bundle", pb.name)

#         # Step 4: Match child item codes with query item codes
#         matched_codes = {
#             d.item_code for d in pb_doc.items
#             if d.item_code in item_code_count_map
#         }

#         if not matched_codes:
#             continue  # Skip if no matching item_code

#         # Step 5: Sum the item_code_count for matched codes
#         total_count = sum(item_code_count_map[code] for code in matched_codes)

#         if total_count:
#             pb_doc.quantity = total_count
#             pb_doc.save(ignore_permissions=True)
#             frappe.db.commit()


@frappe.whitelist()
def update_product_bundle_quantities():
	# Step 1: Fetch item_code and update_qty2 from SO Quantity Check
	data = frappe.db.sql("""
		SELECT item_code, update_qty2 AS item_code_count FROM `tabSO Quantity Check`
	""", as_dict=True)

	# Step 2: Convert item_code_count to int and create item_code → count map
	item_code_count_map = {
		row.item_code.strip(): int(row.item_code_count or 0)
		for row in data if row.item_code
	}

	# Step 3: Get all Product Bundles
	all_bundles = frappe.get_all("Product Bundle", fields=["name"])

	for pb in all_bundles:
		pb_doc = frappe.get_doc("Product Bundle", pb.name)

		# Step 4: Find matched item codes in bundle that are present in item_code_count_map
		matched_codes = {
			d.item_code for d in pb_doc.items
			if d.item_code in item_code_count_map
		}

		# Step 5: Sum item_code_count values for all matched codes
		total_count = sum(item_code_count_map[code] for code in matched_codes) if matched_codes else 0

		# Step 6: Update and save Product Bundle quantity
		frappe.db.set_value("Product Bundle", pb.name, "quantity", total_count, update_modified=False)