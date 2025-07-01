# apps/nj_features/nj_features/overrides/product_bundle.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_link_to_form
from erpnext.selling.doctype.product_bundle.product_bundle import ProductBundle

class CustomProductBundle(ProductBundle):
    pass 



def update_product_bundle_quantities():
    # Step 1: Fetch item_code and count from Serial No
    
    data = frappe.db.sql("""
        SELECT 
            a.item_code,
            COUNT(a.item_code) AS item_code_count
        FROM 
            `tabSerial No` a
        INNER JOIN 
            `tabWarehouse` b ON a.warehouse = b.name
        WHERE 
            a.item_group IN ('Desktops', 'Chromeboxes', 'Laptops', 'Chromebooks', 'Full Set Desktops', 'MacBooks') 
            AND a.warehouse != ''
            AND b.department IN ('Packing & Dispatch - NJ', 'BG - Adaptor QC - NJ')
        GROUP BY 
            a.item_code
        ORDER BY item_code_count DESC
    """, as_dict=True)

    # Step 2: Create a mapping of item_code → item_code_count
    item_code_count_map = {
        row.item_code.strip(): row.item_code_count
        for row in data if row.item_code
    }

    # Step 3: Loop through all Product Bundles
    all_bundles = frappe.get_all("Product Bundle", fields=["name"])
    
    for pb in all_bundles:
        pb_doc = frappe.get_doc("Product Bundle", pb.name)

        # Step 4: Match child item codes with query item codes
        matched_codes = {
            d.item_code for d in pb_doc.items
            if d.item_code in item_code_count_map
        }
        print("matched_codes      =======",matched_codes)

        if not matched_codes:
            continue  # Skip if no matching item_code

        # Step 5: Sum the item_code_count for matched codes
        total_count = sum(item_code_count_map[code] for code in matched_codes)
        print("total_count      =======",total_count)

        if total_count:
            pb_doc.quantity = total_count
            pb_doc.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"Updated {pb_doc.name}: Quantity = {total_count}")
        else:
            print(f"Skipped {pb_doc.name}: No valid item_code_count found.")