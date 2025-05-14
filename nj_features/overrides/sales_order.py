import frappe , requests
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
SHOPIFY_URL = "https://newjaisa.myshopify.com/admin/api/2025-01/orders.json?name=" 
TOKEN = "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"
FULLFILMENT_ORDER_ID = "https://newjaisa.myshopify.com/admin/api/2025-01/orders/{shopify_order_id}/fulfillment_orders.json"
MAKE_FULLFILMENT = "https://newjaisa.myshopify.com/admin/api/2025-01/fulfillments.json"
import uuid
class CustomSalesOrder(SalesOrder):
    def on_submit(self):
        if self.naming_series and self.naming_series.startswith("SO-Snapmint-"):
            return
        raw_order_id = None
        if self.order_type!="Maintenance":
            if self.shopify_order_id:
                stripped_id = self.shopify_order_id.lstrip('#')
                if len(stripped_id) < 7:
                    raw_order_id = self.shopify_order_id

            # if not raw_order_id and self.order_id:
            #     raw_order_id = self.order_id

            if not raw_order_id and self.shopify_order_number:
                raw_order_id = self.shopify_order_number

            order_id = raw_order_id.lstrip('#') if raw_order_id else None

            if order_id:
                trigger_fulfillment(order_id)

@frappe.whitelist(allow_guest=True)
def trigger_fulfillment(order_id):
    try:
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": TOKEN
        }
        print("order_id-----26---in so-", order_id)
        # Step 1: Fetch Order Details
        url = f"{SHOPIFY_URL}{order_id}"
        response = requests.get(url, headers=headers)  
        data = response.json()

        if "orders" in data and data["orders"]:
            order = data["orders"][0]  
            order_id_shopify = order.get("id")

            if not order_id_shopify:
                frappe.throw("Shopify Order ID not found.")

            full_filment_status = order.get("fulfillment_status")

            if full_filment_status == "fulfilled":
                return {"status": "already_fulfilled"}

            # Step 2: Fetch Fulfillment Order
            fulfillment_order_url = FULLFILMENT_ORDER_ID.format(shopify_order_id=order_id_shopify)
            fulfillment_order_response = requests.get(fulfillment_order_url, headers=headers)
            fulfillment_order_data = fulfillment_order_response.json()

            if "fulfillment_orders" in fulfillment_order_data and fulfillment_order_data["fulfillment_orders"]:
                fulfillment_order_id = fulfillment_order_data["fulfillment_orders"][0]["id"]

                # Dummy Tracking Info
                tracking_number = str(uuid.uuid4()).replace('-', '')[:12].upper()
                tracking_url = "https://criticalog.com/tracking/"
                tracking_company = "Criticalog"

                fulfillment_payload = {
                    "fulfillment": {
                        "line_items_by_fulfillment_order": [
                            {
                                "fulfillment_order_id": fulfillment_order_id
                            }
                        ],
                        "tracking_info": {
                            "number": tracking_number,
                            "company": tracking_company,
                            "url": tracking_url
                        },
                        "notify_customer": False
                    }
                }

                fulfillment_response = requests.post(MAKE_FULLFILMENT, headers=headers, json=fulfillment_payload)
                fulfillment_data = fulfillment_response.json()
                # print("fulfillment_data----75-", fulfillment_data)
                if "fulfillment" in fulfillment_data:
                    fulfillment_id = fulfillment_data["fulfillment"]["id"]
                    return {
                            "status": "success", "fulfillment_id": fulfillment_id
                        }
                else:
                    frappe.msgprint("Fulfillment creation failed.")
            else:
                frappe.msgprint("Fulfillment Order not found.")
        else:
            frappe.msgprint("Order not found.")
    except Exception as e:
        frappe.throw(str(e))

def calculate_dispatch_eta_for_sales_order():
    departments = frappe.db.sql("""
        SELECT 
            name, min_aging_days
        FROM
            `tabDepartment`
        WHERE
            department_sequence >= 1
        ORDER BY 
            department_sequence DESC
    """, as_dict=1)

    open_sales_orders = frappe.db.sql("""
        SELECT 
            so.name AS sales_order,
            soi.item_code
        FROM 
            `tabSales Order` so
        INNER JOIN 
            `tabSales Order Item` soi ON soi.parent = so.name
        INNER JOIN
            `tabItem` i ON soi.item_code = i.item_code
        WHERE
            (so.per_delivered < 100 OR so.per_billed < 100)
            AND so.docstatus = 1
            AND so.status NOT IN ('Completed', 'Closed', 'Cancelled')
            AND i.is_stock_item = 1
            AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')

        UNION ALL

        SELECT 
            so.name AS sales_order,
            pi.item_code
        FROM 
            `tabSales Order` so
        INNER JOIN 
            `tabSales Order Item` soi ON soi.parent = so.name
        INNER JOIN 
            `tabPacked Item` pi ON pi.parent = so.name AND pi.parent_detail_docname = soi.name
        INNER JOIN 
            `tabItem` i ON pi.item_code = i.item_code
        WHERE
            (so.per_delivered < 100 OR so.per_billed < 100)
            AND so.docstatus = 1
            AND so.status NOT IN ('Completed', 'Closed', 'Cancelled')
            AND soi.item_code IN (SELECT item_code FROM `tabItem` WHERE is_stock_item = 0)
            AND i.is_stock_item = 1
            AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')

        ORDER BY 
            sales_order DESC
    """, as_dict=1)

    for so in open_sales_orders:
        so_name = so["sales_order"]
        item_code = so["item_code"]

        accumulated_days = 0
        serial_found = False

        for dept in departments:
            dept_name = dept["name"]
            min_aging_days = dept.get("min_aging_days", 0)
            accumulated_days += min_aging_days

            warehouses = frappe.db.sql("""
                SELECT 
                    name
                FROM
                    `tabWarehouse`
                WHERE
                    department = %s
            """, (dept_name,), as_dict=1)

            for wh in warehouses:
                warehouse_name = wh["name"]

                serial_no = frappe.db.sql("""
                    SELECT 
                        name
                    FROM
                        `tabSerial No`
                    WHERE
                        item_code = %s AND warehouse = %s
                        AND (reserved_sales_order IS NULL OR reserved_sales_order = '')
                    LIMIT 1
                """, (item_code, warehouse_name), as_dict=1)

                if serial_no:
                    frappe.db.sql("""
                        UPDATE `tabSerial No` 
                        SET reserved_sales_order = %s
                        WHERE name = %s
                    """, (so_name, serial_no[0]["name"]))

                    frappe.db.sql("""
                        UPDATE `tabSales Order` 
                        SET eta_for_dispatch = %s
                        WHERE name = %s
                    """, (accumulated_days, so_name))

                    serial_found = True
                    break

            if serial_found:
                print("serial found for item_code", item_code)
                break