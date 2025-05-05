# apps/nj_features/nj_features/overrides/product_bundle.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_link_to_form
from erpnext.selling.doctype.product_bundle.product_bundle import ProductBundle

class CustomeProductBundle(ProductBundle):
    pass  # your overrides here if needed

# ✅ This function must be at top level!

def update_product_bundle_quantities():
    # Run your SQL query
    data = frappe.db.sql("""
        SELECT 
            pb.shopify_variant_id,
            CAST(SUM(b.actual_qty) AS DECIMAL(10, 2)) AS total_actual_qty
        FROM 
            `tabProduct Bundle` pb
        LEFT JOIN 
            `tabProduct Bundle Item` pbi ON pb.name = pbi.parent
        LEFT JOIN 
            tabItem i ON pbi.item_code = i.item_code
        LEFT JOIN 
            tabBin b ON i.item_code = b.item_code
        LEFT JOIN 
            tabWarehouse w ON b.warehouse = w.name
        WHERE 
            i.item_group IN ('Laptops', 'Desktops', 'MacBooks','Chromebooks')
            AND w.department IN ('Packing & Dispatch - NJ', 'BG - Adaptor QC - NJ')
        GROUP BY 
            pb.shopify_variant_id
    """, as_dict=True)

    for row in data:
        if row.shopify_variant_id and row.total_actual_qty is not None:
            try:
                # Update the Product Bundle quantity
                pb_doc = frappe.get_doc("Product Bundle", {"shopify_variant_id": row.shopify_variant_id})
                print("pb_doc===============", pb_doc)
                pb_doc.quantity = row.total_actual_qty
                print(" pb_doc.quantity==============", pb_doc.quantity)
                pb_doc.save(ignore_permissions=True)
                frappe.db.commit()
                frappe.logger().info(f"Updated Product Bundle {pb_doc.name}: Quantity = {row.total_actual_qty}")
            except frappe.DoesNotExistError:
                frappe.logger().warning(f"No Product Bundle found for variant {row.shopify_variant_id}")
            except Exception as e:
                frappe.logger().error(f"Error updating Product Bundle: {e}")
