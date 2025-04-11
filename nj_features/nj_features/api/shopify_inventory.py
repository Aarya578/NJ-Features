import requests as rs
import frappe
import json
shop = "https://newjaisa.myshopify.com"
location_id = 65940881590
@frappe.whitelist()
def fetch_and_stage_inventory_sync():
    results = frappe.db.sql("""
        SELECT 
            stock_data.item_code,
            stock_data.total_actual_qty,
            stock_data.item_group,
            GROUP_CONCAT(DISTINCT pb.shopify_variant_id ORDER BY pb.shopify_variant_id SEPARATOR ', ') AS variant_ids
        FROM 
        (
            SELECT
                i.item_code,
                i.item_group,
                CAST(SUM(b.actual_qty) AS DECIMAL(10,2)) AS total_actual_qty
            FROM
                `tabItem` i
            JOIN
                `tabBin` b ON i.item_code = b.item_code
            JOIN
                `tabWarehouse` w ON b.warehouse = w.name
            JOIN
                `tabDepartment` d ON w.department = d.name
            WHERE
                i.item_group IN ('Laptops', 'Chromebooks', 'MacBooks')
                AND i.has_variants = 0
                AND d.department_name IN ('Packing & Dispatch', 'BG - Adaptor QC')
            GROUP BY
                i.item_code, i.item_group
            HAVING
                total_actual_qty > 0
        ) AS stock_data
        JOIN 
            `tabProduct Bundle Item` pbi ON stock_data.item_code = pbi.item_code
        JOIN 
            `tabProduct Bundle` pb ON pb.name = pbi.parent
        GROUP BY 
            stock_data.item_code, stock_data.total_actual_qty, stock_data.item_group
        ORDER BY
            stock_data.total_actual_qty DESC;
    """, as_dict=True)

    print("results----------------", results)

    for row in results:
        if float(row.total_actual_qty) <= 0:
            continue 
        existing = frappe.get_all("NJ Inventory Sync Main", filters={
            "item_code": row.item_code
        }, fields=["name", "actual_qty", "sync_status", "is_active"])

        if existing:
            existing_doc = existing[0]
            if float(row.total_actual_qty) != float(existing_doc.actual_qty):
                frappe.db.set_value("NJ Inventory Sync Main", existing_doc.name, {
                    "actual_qty": row.total_actual_qty,
                    "sync_status": "Queued",
                    "is_active": 1
                })
        else:
            doc = frappe.new_doc("NJ Inventory Sync Main")
            doc.item_code = row.item_code
            doc.actual_qty = row.total_actual_qty
            doc.item_group = row.item_group
            doc.shopify_variant_id = row.variant_ids
            doc.sync_status = "Queued"
            doc.is_active = 1
            doc.insert()



@frappe.whitelist()
def sync_inventory_to_shopify():
    print("hii inside sync_inventory_to_shopify")
    token = "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"
    # shop = frappe.db.get_single_value("Shopify Settings", "shop_url")
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }
    print("headers-----71", headers)
    queued = frappe.get_all("NJ Inventory Sync Main", filters={
        "sync_status": "Queued",
        "is_active": 1
    }, fields=["name", "item_code", "actual_qty", "shopify_variant_id"])
    print("queued-----78", queued)
    for row in queued:
        variant_ids = [v.strip() for v in row.shopify_variant_id.split(",") if v.strip()]
        print("variant_ids-----80", variant_ids)
        if not variant_ids or float(row.actual_qty) <= 0:
            continue

        for variant_id in variant_ids:
            try:
                variant_url = f"{shop}/admin/api/2023-01/variants/{variant_id}.json"
                variant_resp = rs.get(variant_url, headers=headers)
                variant_data = variant_resp.json()

                inventory_item_id = variant_data["variant"]["inventory_item_id"]

                update_url = f"{shop}/admin/api/2023-01/inventory_levels/set.json"
                payload = {
                    "location_id": location_id,
                    "inventory_item_id": inventory_item_id,
                    "available": int(float(row.actual_qty))
                }

                update_resp = rs.post(update_url, headers=headers, data=json.dumps(payload))
                if update_resp.status_code != 200:
                    frappe.log_error(f"Shopify Inventory Update Error for {variant_id}", update_resp.text)

            except Exception as e:
                frappe.log_error(f"Inventory sync failed for {variant_id}", str(e))
                continue

        # Mark record as completed and inactive
        frappe.db.set_value("NJ Inventory Sync Main", row.name, {
            "sync_status": "Completed",
            "is_active": 0
        })
        frappe.db.commit()
