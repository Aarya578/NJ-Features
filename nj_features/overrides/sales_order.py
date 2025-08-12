import frappe , requests
import requests
import json
import base64
import frappe
import time
import datetime
from datetime import datetime
from frappe.utils import getdate
import json
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
from nj_features.nj_features.api.shiprocket_api import get_auth_token,generate_awb,generate_label
logger = frappe.logger('SOLogger', allow_site=True, file_count=1)
SHOPIFY_URL = "https://newjaisa.myshopify.com/admin/api/2025-01/orders.json?name=" 
TOKEN = "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"
FULLFILMENT_ORDER_ID = "https://newjaisa.myshopify.com/admin/api/2025-01/orders/{shopify_order_id}/fulfillment_orders.json"
MAKE_FULLFILMENT = "https://newjaisa.myshopify.com/admin/api/2025-01/fulfillments.json"
import uuid
class CustomSalesOrder(SalesOrder):
    
    def on_submit(self):
        if self.naming_series and self.naming_series.startswith("SO-Snapmint-"):
            return

 
        # self.total_item_group_sum()
        raw_order_id = None
        if self.order_type!="Maintenance":
            if self.shopify_order_id:
                stripped_id = self.shopify_order_id.lstrip('#')
                if len(stripped_id) < 7:
                    raw_order_id = self.shopify_order_id

            if not raw_order_id and self.shopify_order_number:
                raw_order_id = self.shopify_order_number

            order_id = raw_order_id.lstrip('#') if raw_order_id else None

            # if order_id:
            #     trigger_fulfillment(order_id)
        self.payment_id_validation()

    def total_item_group_sum(self):
    # Step 1: Get item groups from NJ Settings
        item_group_value = frappe.db.get_value(
            "NJ Settings", 
            {"parameter": "Item Group Validation"}, 
            "value"
        )
        
        if not item_group_value:
            return

        # Convert comma-separated value to list
        allowed_item_groups = [group.strip() for group in item_group_value.split(",")]

        # Step 2: Loop through items in Sales Order and calculate total qty
        total_qty = 0
        for item in self.items:
            item_group = frappe.db.get_value("Item", item.item_code, "item_group")
            if item_group in allowed_item_groups:
                total_qty += item.qty

        # Step 3: Update a custom field `item_group_qty` (you need to add this field in Sales Order)
        self.item_group_qty = total_qty
        self.save(ignore_permissions=True)   

    def payment_id_validation(self):
        nj_setting_value = frappe.db.get_value(
            "NJ Settings", 
            {"parameter": "sale_type"}, 
            "value"
        )

        # Skip if sale_type doesn't match NJ setting
        if self.sale_type != nj_setting_value:
            return

        if self.payment_id:
            existing_so = frappe.db.get_value(
                "Sales Order",
                {
                    "payment_id": self.payment_id,
                    "docstatus": 1,
                    "name": ["!=", self.name]  # exclude self
                },
                "name"
            )

            if existing_so:
                frappe.throw(
                    f"Payment ID '{self.payment_id}' is already used in Sales Order: {existing_so}"
                )
            else:
                self.approve = 1


        

@frappe.whitelist(allow_guest=True)
def trigger_fulfillment(order_id):
    try:
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": TOKEN
        }
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
# @frappe.whitelist()
# def total_item_group_sum(doc):
#     doc = frappe._dict(json.loads(doc))  

#     # Fetch full document to access child table objects
#     sales_order = frappe.get_doc("Sales Order", doc.name)

#     # Step 1: Get item groups from NJ Settings
#     item_group_value = frappe.db.get_value(
#         "NJ Settings",
#         {"parameter": "Item Group Validation"},
#         "value"
#     )
#     if not item_group_value:
#         return

#     # Step 2: Convert to list
#     allowed_item_groups = [group.strip() for group in item_group_value.split(",")]

#     # Step 3: Calculate total qty for allowed groups
#     total_qty = 0
#     for item in sales_order.items:
#         item_group = frappe.db.get_value("Item", item.item_code, "item_group")
#         if item_group in allowed_item_groups:
#             total_qty += item.qty
#     return {"item_group_qty": total_qty}
 
def calculate_dispatch_eta_for_sales_order():
    """Main function to calculate dispatch ETA for all open sales orders"""
    try:
        # Get department-wise min aging days (in descending order of department_sequence)
        departments = get_departments()
        
        # Get all open sales orders with their items (including product bundles)
        open_orders = get_open_sales_orders()

        # Dictionary to track max ETA per sales order
        so_eta_map = {}
        
        # Process each sales order item
        for order in open_orders:
            so_name = order.sales_order
            item_code = order.item_code
            ordered_qty = order.ordered_qty
            
            # Get delivered quantity
            delivered_qty = get_delivered_quantity(so_name, item_code)
            
            # Calculate pending quantity
            net_pending = ordered_qty - delivered_qty
            if net_pending <= 0:
                continue
                
            # Adjust serial allocations and get unallocated quantity
            unallocated_qty = adjust_serial_allocations(so_name, item_code, net_pending, departments)
            
            # Calculate ETA for this item (only if unallocated quantity exists)
            if unallocated_qty > 0:
                item_eta = calculate_item_eta(item_code, unallocated_qty, departments)
            else:
                item_eta = 0  # Fully allocated, no waiting time
            
            # Track max ETA per sales order
            if so_name not in so_eta_map or item_eta > so_eta_map[so_name]:
                so_eta_map[so_name] = item_eta
        
        # Update ETA for each sales order
        update_sales_order_etas(so_eta_map)
        
    except Exception as e:
        frappe.log_error(f"Error in calculate_dispatch_eta_for_sales_order: {str(e)}")
        frappe.db.rollback()

def get_departments():
    """Get all departments with aging information"""
    return frappe.db.sql("""
        SELECT name, min_aging_days, department_sequence
        FROM `tabDepartment`
        WHERE department_sequence >= 1
        ORDER BY department_sequence DESC
    """, as_dict=True)

def get_open_sales_orders():
    """Get all open sales orders with pending items (serialized items only)"""
    return frappe.db.sql("""
        -- 1. Direct stock items
            SELECT 
                so.name AS sales_order,
                soi.item_code,
                SUM(soi.qty) AS ordered_qty
            FROM 
                `tabSales Order` so
            INNER JOIN 
                `tabSales Order Item` soi ON soi.parent = so.name
            INNER JOIN 
                `tabItem` i ON soi.item_code = i.item_code
            WHERE
                so.docstatus = 1
                AND so.status NOT IN ('Completed', 'Closed', 'Cancelled', 'To Deliver')
                AND i.is_stock_item = 1
                AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
                AND so.creation >= DATE_SUB(CURDATE(), INTERVAL 20 DAY)
            GROUP BY 
                so.name, soi.item_code

            UNION ALL

            SELECT 
                so.name AS sales_order,
                pbi.item_code,
                pbi.qty * soi.qty AS ordered_qty
            FROM 
                `tabSales Order` so
            INNER JOIN 
                `tabSales Order Item` soi ON soi.parent = so.name
            INNER JOIN 
                `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code
            INNER JOIN 
                `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
            INNER JOIN 
                `tabItem` i ON pbi.item_code = i.item_code
            INNER JOIN 
                `tabItem` soi_item ON soi.item_code = soi_item.item_code
            WHERE
                so.docstatus = 1
                AND so.status NOT IN ('Completed', 'Closed', 'Cancelled', 'To Deliver')
                AND soi_item.is_stock_item = 0
                AND i.is_stock_item = 1
                AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes')
                AND so.creation >= DATE_SUB(CURDATE(), INTERVAL 20 DAY)
            ORDER BY 
                sales_order DESC
    """, as_dict=True)

def get_delivered_quantity(so_name, item_code):
    """Get delivered quantity for a sales order item"""
    result = frappe.db.sql("""
        SELECT SUM(dni.qty) 
        FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dni.parent = dn.name
        WHERE dni.against_sales_order = %s
            AND dni.item_code = %s
            AND dn.docstatus = 1
    """, (so_name, item_code))

    return result[0][0] if result and result[0][0] else 0

def adjust_serial_allocations(so_name, item_code, net_pending, departments):
    """Adjust serial allocations and return unallocated quantity"""
    # Get already allocated count
    allocated_count = frappe.db.sql("""
        SELECT COUNT(*) 
        FROM `tabSerial No` 
        WHERE 
            reserved_sales_order = %s 
            AND item_code = %s
            AND NOT EXISTS (
                SELECT 1 
                FROM `tabDelivery Note Item` 
                WHERE serial_no = `tabSerial No`.name 
                    AND docstatus = 1
            )
    """, (so_name, item_code))[0][0] or 0

    # Calculate net to allocate
    to_allocate = net_pending - allocated_count
    unallocated_qty = 0

    # Unassign excess serial numbers
    if to_allocate < 0:
        unassign_serials(so_name, item_code, abs(to_allocate))
    
    # Allocate new serial numbers and track unallocated quantity
    elif to_allocate > 0:
        allocated_in_this_call = assign_serials(so_name, item_code, to_allocate, departments)
        unallocated_qty = to_allocate - allocated_in_this_call

        if unallocated_qty > 0:
            create_unallocated_log(so_name, item_code, unallocated_qty, "Insufficient available stock")
    
    return unallocated_qty

def assign_serials(so_name, item_code, to_allocate, departments):
    allocated_count = 0

    for dept in departments:
        if allocated_count >= to_allocate:
            break

        # Get warehouses in this department
        warehouses = frappe.db.sql_list("""
            SELECT name FROM `tabWarehouse` WHERE department = %s
        """, dept.name)

        if not warehouses:
            continue

        remaining = int(to_allocate - allocated_count)

        # Build SQL-safe string: 'Warehouse A','Warehouse B',...
        warehouses_str = ', '.join(f"'{w}'" for w in warehouses)

        query = f"""
            SELECT name 
            FROM `tabSerial No` 
            WHERE 
                item_code = '{item_code}'
                AND warehouse IN ({warehouses_str})
                AND (reserved_sales_order IS NULL OR reserved_sales_order = '')
                AND NOT EXISTS (
                    SELECT 1 
                    FROM `tabDelivery Note Item` 
                    WHERE serial_no = `tabSerial No`.name 
                        AND docstatus = 1
                )
            ORDER BY creation ASC 
            LIMIT {remaining}
        """

        available_serials = frappe.db.sql(query, as_dict=1)
        count_in_dept = len(available_serials)

        for serial in available_serials:
            serial_name = serial.get("name")
            frappe.db.set_value("Serial No", serial_name, "reserved_sales_order", so_name)

            # Calculate aging days
            so_creation = frappe.get_value("Sales Order", so_name, "creation")
            aging_days = (getdate() - getdate(so_creation)).days if so_creation else 0

            # Append aging detail
            serial_doc = frappe.get_doc("Serial No", serial_name)
            serial_doc.append("sales_order_details", {
                "sales_order": so_name,
                "aging_days": aging_days
            })
            serial_doc.save()

        allocated_count += count_in_dept

    return allocated_count


def unassign_serials(so_name, item_code, excess_qty):
    """Unassign excess serial numbers"""
    excess_serials = frappe.db.sql_list("""
        SELECT name 
        FROM `tabSerial No` 
        WHERE 
            reserved_sales_order = %s 
            AND item_code = %s
            AND NOT EXISTS (
                SELECT 1 
                FROM `tabDelivery Note Item` 
                WHERE serial_no = `tabSerial No`.name 
                    AND docstatus = 1
            )
        ORDER BY creation ASC 
        LIMIT %s
    """, (so_name, item_code, int(excess_qty)))
    
    if excess_serials:
        frappe.db.sql("""
            UPDATE `tabSerial No`
            SET sales_order = NULL, reserved_sales_order = NULL
            WHERE name IN %(serials)s
        """, {"serials": excess_serials})
        frappe.db.commit()

def create_unallocated_log(sales_order, item_code, pending_qty, reason):
    """Create a log entry in Unallocated Sales Order Item"""
    doc = frappe.new_doc("Unallocated Sales Order Item")
    doc.sales_order = sales_order
    doc.item_code = item_code
    doc.pending_qty = pending_qty
    doc.reason = reason
    doc.posting_date = frappe.utils.nowdate()
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

def calculate_item_eta(item_code, required_qty, departments):
    """Calculate ETA for a specific item quantity"""
    accumulated_days = 0
    remaining_qty = required_qty
    
    for dept in departments:
        accumulated_days += dept.min_aging_days

        # Get warehouses in this department
        warehouses = frappe.db.sql_list("""
            SELECT name FROM `tabWarehouse` WHERE department = %s
        """, dept.name)

        if not warehouses:
            continue

        # Generate placeholders for warehouses
        placeholders = ', '.join(['%s'] * len(warehouses))
        
        # Compose the SQL query with dynamic placeholders
        query = f"""
            SELECT COUNT(*)
            FROM `tabSerial No`
            WHERE 
                item_code = %s
                AND warehouse IN ({placeholders})
                AND (reserved_sales_order IS NULL OR reserved_sales_order = '')
                AND NOT EXISTS (
                    SELECT 1 
                    FROM `tabDelivery Note Item` 
                    WHERE serial_no = `tabSerial No`.name 
                        AND docstatus = 1
                )
        """

        # Combine item_code and warehouses into a single params list
        params = [item_code] + warehouses

        # Execute the query
        available_count = frappe.db.sql(query, params)[0][0] or 0

        # Check if enough stock in this department
        if available_count >= remaining_qty:
            return accumulated_days
        else:
            remaining_qty -= available_count

    # Return total accumulated days if not enough stock

    return accumulated_days

def update_sales_order_etas(so_eta_map):
    """Update ETA for dispatch on sales orders using direct SQL UPDATE"""
    for so_name, eta in so_eta_map.items():
        frappe.db.sql("""
            UPDATE `tabSales Order`
            SET eta_for_dispatch = %s
            WHERE name = %s
        """, (eta, so_name))
    frappe.db.commit()

# @frappe.whitelist()
# def get_item_group_taxes(item_code):
#     # Get the Item Group from the Item
#     item_group = frappe.db.get_value("Item", item_code, "item_group")
#     if not item_group:
#         return []

#     # Fetch taxes from Item Group's taxes table
#     tax_rows = frappe.get_all("Item Group Tax",  # Doctype of the child table
#         filters={"parent": item_group, "parenttype": "Item Group"},
#         fields=["charge_type", "account_head", "rate", "description", "cost_center"]
#     )

#     return tax_rows


# @frappe.whitelist()
# def get_item_group_tax_and_hsn(items):
#     print("inside the function==========================")
#     items = json.loads(items)

#     tax_result = {
#         "hsn_map": {},    # Maps item_code to HSN
#         "taxes": []       # Final taxes list
#     }
#     print("tax_result==========================",tax_result)

#     added_item_groups = set()

#     for row in items:
#         item_code = row.get("item_code")
#         print("item_code===========",item_code)
#         if not item_code:
#             continue

#         # Fetch item group
#         item_group = frappe.db.get_value("Item", item_code, "item_group")
#         print("item_group===========",item_group)
#         if not item_group:
#             continue

#         # Fetch HSN from Item Group
#         gst_hsn_code = frappe.db.get_value("Item Group", item_group, "gst_hsn_code")
#         print("gst_hsn_code===========",gst_hsn_code)
#         if gst_hsn_code:
#             tax_result["hsn_map"][item_code] = gst_hsn_code

#         # Avoid duplicating tax rows for same item group
#         if item_group in added_item_groups:
#             continue

#         # ✅ Fetch taxes from the "Taxes" child table of Item Group
#         # tax_rows = frappe.get_all("Item Group",  # <-- This must be the child table Doctype name
#         #     filters={"parent": item_group, "parenttype": "Item Group"},
#         #     fields=["charge_type", "account_head", "rate", "description", "cost_center"]
#         # )
#         # print("tax_rows===========",tax_rows)

#         # tax_result["taxes"].extend(tax_rows)
#         added_item_groups.add(item_group)

#     return tax_result
