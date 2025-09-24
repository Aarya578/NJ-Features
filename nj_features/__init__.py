
__version__ = '0.0.1'

import socket
import requests
import frappe
@frappe.whitelist()
def verify_domain_matches_server_ip(domain: str, debug: bool = False):
    try:
        resolved_ip = socket.gethostbyname(domain)
    except socket.gaierror:
        if debug:
            return {
                "domain": domain,
                "error": f"Could not resolve domain: {domain}",
                "match": False
            }

        return False

    try:
        server_ip = requests.get("https://api.ipify.org").text.strip()
    except requests.RequestException:
        if debug:
            return {
                "domain": domain,
                "resolved_ip": resolved_ip,
                "error": "Could not determine server's public IP",
                "match": False
            }
        return False

    is_match = resolved_ip == server_ip

    if debug:
        return {
            "domain": domain,
            "resolved_ip": resolved_ip,
            "server_ip": server_ip,
            "match": is_match
        }

    return is_match


def boot_monkey_patches():
    try:
        import ecommerce_integrations.shopify.order as shopify_order
        from nj_features.overrides import order as nj_order


        import ecommerce_integrations.shopify.product as shopify_product
        from nj_features.overrides import product as nj_product 

        shopify_order.sync_sales_order = nj_order.sync_sales_order
        shopify_order.create_order = nj_order.create_order
        shopify_order.create_sales_order = nj_order.create_sales_order
        shopify_product.get_item_code = nj_product.get_item_code


        frappe.whitelisted["ecommerce_integrations.shopify.order.sync_sales_order"] = nj_order.sync_sales_order
        frappe.whitelisted["ecommerce_integrations.shopify.order.create_order"] = nj_order.create_order
        frappe.whitelisted["ecommerce_integrations.shopify.order.create_sales_order"] = nj_order.create_sales_order
        frappe.whitelisted["ecommerce_integrations.shopify.product.create_product"] = nj_product.get_item_code

        frappe.logger().info("✅ NJ Features successfully patched Shopify order methods")
    except Exception as e:
        frappe.logger().error(f"❌ Failed to patch Shopify order methods: {e}")

boot_monkey_patches()


