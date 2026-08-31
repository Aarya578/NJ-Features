# apps/nj_features/nj_features/overrides/product_bundle.py

import time

import frappe
import requests
from frappe import _
from frappe.utils.background_jobs import enqueue
from erpnext.selling.doctype.product_bundle.product_bundle import ProductBundle
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error

SHOPIFY_SHOP_URL = "https://newjaisa.myshopify.com"
SHOPIFY_ACCESS_TOKEN = "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"
SHOPIFY_API_VERSION = "2025-07"

class CustomProductBundle(ProductBundle):
	def validate(self):
		self.handle_product_bundle_disable()
		self.deleting_rerord__if_table_modified()
		self.validating_pd_shopify_variant_id_and_item_shopify_variant_id()

	def handle_product_bundle_disable(self):
		shopify_variant_id = (getattr(self, 'shopify_variant_id', '') or '').strip()
		if not shopify_variant_id:
			return

		if getattr(self, "disable", 0) == 1:
			from frappe.utils import flt, now
			sync_docs = frappe.get_all(
				"NJ Inventory Sync Main",
				filters={"shopify_variant_id": shopify_variant_id},
				fields=["name", "shopify_quantity"]
			)
			for s in sync_docs:
				current_shopify_qty = flt(s.get("shopify_quantity") or 0)
				status = "Queued" if current_shopify_qty > 0 else "Completed"
				frappe.db.set_value("NJ Inventory Sync Main", s.name, {
					"actual_qty": 0,
					"updated_qty": 0,
					"shopify_pre_order_qty": 0,
					"shopify_pre_order_enabled": 0,
					"estimated_time_of_dispatch": "",
					"status": status,
					"is_active": 1 if status == "Queued" else 0,
					"sync_error": "[Disabled Bundle - Queued to 0]" if status == "Queued" else "[Disabled Bundle]",
					"modified": now(),
				})




	def validating_pd_shopify_variant_id_and_item_shopify_variant_id(self):
		item_code = self.new_item_code or self.name
		item_shopify_product_id = frappe.db.get_value(
			"Item", item_code, "shopify_product_id"
		)

		item_shopify_product_id = str(item_shopify_product_id or "").strip()
		product_bundle_shopify_variant_id = str(
			self.shopify_variant_id or ""
		).strip()

		if item_shopify_product_id != product_bundle_shopify_variant_id:
			frappe.throw(
				_(
					"Shopify ID mismatch for Item {0}: Item Shopify Product ID "
					"is {1}, but Product Bundle Shopify Variant ID is {2}."
				).format(
					frappe.bold(item_code),
					frappe.bold(item_shopify_product_id or _("Not Set")),
					frappe.bold(product_bundle_shopify_variant_id or _("Not Set")),
				),
				title=_("Shopify ID Mismatch"),
			)

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
			frappe.throw(f"Error fetching inventory records. Please check logs. Error: {str(e)}")

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


@frappe.whitelist()
def update_zero_quantity_product_bundles():
	"""Update enabled bundles using SO Quantity Check parent totals."""
	bundle_items = frappe.db.sql(
		"""
		SELECT pb.name AS bundle_name, pbi.item_code
		FROM `tabProduct Bundle` AS pb
		INNER JOIN `tabProduct Bundle Item` AS pbi ON pbi.parent = pb.name
		WHERE COALESCE(pb.disable, 0) = 0
			AND COALESCE(pbi.item_code, '') != ''
		""",
		as_dict=True,
	)

	bundle_items_map = {}
	for row in bundle_items:
		bundle_items_map.setdefault(row.bundle_name, set()).add(row.item_code)

	for bundle_name, bundle_item_codes in bundle_items_map.items():
		item_codes = sorted(bundle_item_codes)
		placeholders = ", ".join(["%s"] * len(item_codes))
		total_qty = frappe.db.sql(
			f"""
			SELECT COALESCE(SUM(so.update_qty2), 0) AS total_qty
			FROM `tabSO Quantity Check` AS so
			WHERE so.parent1 IN (
				SELECT DISTINCT matched_so.parent1
				FROM `tabSO Quantity Check` AS matched_so
				WHERE matched_so.item_code IN ({placeholders})
			)
			""",
			tuple(item_codes),
			as_dict=True,
		)[0].total_qty

		frappe.db.set_value(
			"Product Bundle",
			bundle_name,
			"quantity",
			total_qty,
			update_modified=False,
		)

@frappe.whitelist()
def update_variant_status(run_now=False):
	"""Queue Product Bundle shopify_status sync from Shopify product status."""
	if frappe.parse_json(run_now):
		return _update_variant_status_job()

	enqueue(
		method="nj_features.overrides.product_bundle._update_variant_status_job",
		queue="long",
		timeout=3600,
		job_name="update_product_bundle_shopify_status",
	)
	return "Product Bundle Shopify status update queued"


def _update_variant_status_job(batch_size=50, commit_every=500):
	if not frappe.get_meta("Product Bundle").has_field("shopify_status"):
		log_error("Field shopify_status not found in Product Bundle", "update_variant_status")
		return {"updated": 0, "failed": 0, "skipped": 0}

	variant_rows = frappe.db.sql(
		"""
		SELECT DISTINCT TRIM(shopify_variant_id) AS shopify_variant_id
		FROM `tabProduct Bundle`
		WHERE IFNULL(TRIM(shopify_variant_id), '') != ''
		ORDER BY shopify_variant_id
		""",
		as_dict=True,
	)
	variant_ids = [row.shopify_variant_id for row in variant_rows if row.shopify_variant_id]
	if not variant_ids:
		log_error("No Product Bundle records found with shopify_variant_id", "update_variant_status", "Info")
		return {"updated": 0, "failed": 0, "skipped": 0}

	updated = 0
	failed = 0
	skipped = 0
	status_by_variant = {}
	url = f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
	headers = {
		"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
		"Content-Type": "application/json",
	}
	batch_size = int(batch_size or 50)
	commit_every = int(commit_every or 500)

	for index in range(0, len(variant_ids), batch_size):
		batch = variant_ids[index:index + batch_size]
		try:
			batch_statuses = _fetch_shopify_product_statuses_for_variants(url, headers, batch)
		except Exception:
			failed += len(batch)
			log_error(frappe.get_traceback(), "update_variant_status batch fetch")
			continue

		for variant_id in batch:
			status = batch_statuses.get(str(variant_id))
			if not status:
				skipped += 1
				continue

			status_by_variant[str(variant_id)] = status
			frappe.db.sql(
				"""
				UPDATE `tabProduct Bundle`
				SET shopify_status = %s
				WHERE shopify_variant_id = %s
				AND IFNULL(shopify_status, '') != %s
				""",
				(status, variant_id, status),
			)
			updated += frappe.db.sql("SELECT ROW_COUNT()", as_list=True)[0][0]

		if (index + len(batch)) % commit_every == 0:
			frappe.db.commit()

	frappe.db.commit()
	message = (
		f"Product Bundle Shopify status sync completed. "
		f"Variants: {len(variant_ids)}, updated rows: {updated}, "
		f"statuses found: {len(status_by_variant)}, skipped: {skipped}, failed: {failed}"
	)
	log_error(message, "update_variant_status", "Info")
	return {"updated": updated, "failed": failed, "skipped": skipped}


def _fetch_shopify_product_statuses_for_variants(url, headers, variant_ids):
	gids = [f"gid://shopify/ProductVariant/{variant_id}" for variant_id in variant_ids]
	batch_ids = ",\n".join(f'"{gid}"' for gid in gids)
	query = f"""
	{{
		nodes(ids: [
			{batch_ids}
		]) {{
			... on ProductVariant {{
				id
				product {{
					status
				}}
			}}
		}}
	}}
	"""

	for attempt in range(3):
		response = requests.post(url, headers=headers, json={"query": query}, timeout=60)
		if response.status_code == 429 or response.status_code >= 500:
			time.sleep(2 ** attempt)
			continue

		if response.status_code != 200:
			frappe.throw(f"Shopify API error {response.status_code}: {response.text}")

		payload = response.json()
		errors = payload.get("errors") or []
		if errors:
			error_text = str(errors)
			if "THROTTLED" in error_text and attempt < 2:
				time.sleep(2 ** attempt)
				continue
			frappe.throw(f"Shopify GraphQL error: {error_text}")

		statuses = {}
		for node in payload.get("data", {}).get("nodes", []) or []:
			if not node:
				continue

			variant_gid = node.get("id") or ""
			variant_id = variant_gid.split("/")[-1]
			status = (node.get("product") or {}).get("status")
			if variant_id and status:
				statuses[variant_id] = status.lower()

		return statuses

	frappe.throw("Shopify API throttled or unavailable after 3 attempts")
