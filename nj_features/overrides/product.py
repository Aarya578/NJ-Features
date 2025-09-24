import json
import frappe

logger = frappe.logger('ProductNJfeatures', allow_site=True, file_count=1)

logger.debug("executing logger file...")

@frappe.whitelist()
def get_item_code(shopify_item):
    """
    Get item code using shopify_item dict.
    Check product bundles in order, find the one with highest quantity > 0.
    If all have quantity = 0, use the first product bundle.
    If no product bundles found, fallback to 'Item Not Found'.
    """
    variant_id = shopify_item.get("variant_id")
    
    if variant_id:
        # Fetch product bundles (quantity is treated as string)
        product_bundles = frappe.db.sql("""
            SELECT DISTINCT pb.name, pb.quantity
            FROM `tabItem` AS i
            INNER JOIN `tabProduct Bundle` AS pb
            ON i.shopify_product_id = pb.shopify_variant_id
            WHERE i.shopify_product_id = %s
            ORDER BY pb.quantity DESC, pb.name
        """, variant_id, as_dict=1)

        logger.info(f"==========product_bundles=========={product_bundles}")
        
        if product_bundles:
            # First check if any bundle has quantity > 0
            for pb in product_bundles:
                quantity_str = str(pb.get("quantity") or "0").strip()
                try:
                    quantity = int(quantity_str)
                    if quantity > 0:
                        return pb.name
                except ValueError:
                    # Skip if quantity is not a valid integer (e.g., empty or non-numeric)
                    continue

            # If none have quantity > 0, return the first one
            return product_bundles[0].name

    # Fallback to "Item Not Found" if no match
    try:
        fallback = frappe.get_doc("Item", "Item Not Found")
        if fallback:
            fallback.description = f"Shopify Variant ID: {variant_id}"
            logger.info(f"==========fallback.description=========={fallback.description}")
            fallback.save(ignore_permissions=True)
            return fallback.item_code
    except frappe.DoesNotExistError:
        pass

    frappe.log_error("Fallback item 'Item Not Found' not present in database", "Product Bundle Lookup Error")
    return "Item Not Found"
