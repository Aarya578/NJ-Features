import re
import json
import time
import uuid
import base64
import frappe, requests
from datetime import datetime
from frappe.utils import getdate, nowdate, add_days
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
from nj_features.nj_features.api.shiprocket_api import get_auth_token, generate_awb, generate_label

logger = frappe.logger('SOLogger', allow_site=True, file_count=1)
SHOPIFY_URL = "https://newjaisa.myshopify.com/admin/api/2025-01/orders.json?name="
TOKEN = "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"
FULLFILMENT_ORDER_ID = "https://newjaisa.myshopify.com/admin/api/2025-01/orders/{shopify_order_id}/fulfillment_orders.json"
MAKE_FULLFILMENT = "https://newjaisa.myshopify.com/admin/api/2025-01/fulfillments.json"


class CustomSalesOrder(SalesOrder):

    def on_submit(self):
        if self.naming_series and self.naming_series.startswith("SO-Snapmint-"):
            return

        # self.total_item_group_sum()
        raw_order_id = None
        if self.order_type != "Maintenance":
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
        self.maintenance_order_validation()
        self.sale_type_validation()

        # Auto-calculate ETA for this SO immediately after submit
        try:
            calculate_dispatch_eta_for_sales_order(self.name)
            self.reload()
        except Exception:
            frappe.log_error(
                title="Sales Order submit ETA calculation failed",
                message=f"SO: {self.name}\n\n{frappe.get_traceback()}"
            )

    def total_item_group_sum(self):
        item_group_value = frappe.db.get_value(
            "NJ Settings",
            {"parameter": "Item Group Validation"},
            "value"
        )
        if not item_group_value:
            return

        allowed_item_groups = [group.strip() for group in item_group_value.split(",")]
        total_qty = 0
        for item in self.items:
            item_group = frappe.db.get_value("Item", item.item_code, "item_group")
            if item_group in allowed_item_groups:
                total_qty += item.qty

        self.item_group_qty = total_qty
        self.save(ignore_permissions=True)

    def payment_id_validation(self):
        nj_setting_value = frappe.db.get_value(
            "NJ Settings",
            {"parameter": "sale_type"},
            "value"
        )
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
                # Use DB update to avoid document save validation
                if self.docstatus == 1:  # Already submitted
                    frappe.db.set_value("Sales Order", self.name, "approve", 1)
                else:
                    self.save(ignore_permissions=True)

    # def maintenance_order_validation(self):
    #     nj_setting = frappe.db.get_value(
    #         "NJ Settings",
    #         {"parameter": "order_type"},
    #         "value"
    #     )
    #     if self.order_type != nj_setting:
    #         return
    #
    #     if self.grand_total < 500:
    #         self.approve = 1
    #     else:
    #         self.approve = 0
    #     self.save(ignore_permissions=True)

    def maintenance_order_validation(self):

        nj_setting = frappe.db.get_value(
            "NJ Settings",
            {"parameter": "order_type"},
            "value"
        )

        if self.order_type != nj_setting:
            return

        approve_value = 1 if self.grand_total < 500 else 0
        frappe.db.set_value("Sales Order", self.name, "approve", approve_value, update_modified=False)
        self.approve = approve_value

    def sale_type_validation(self):
        nj_setting_value = frappe.db.get_value(
            "NJ Settings",
            {"parameter": "sales_types"},
            "value"
        )

        if not nj_setting_value:
            return
        allowed_sale_types = [v.strip() for v in nj_setting_value.split(",")]

        if self.sale_type in allowed_sale_types:
            if not self.payment_id:
                frappe.throw("Payment ID is mandatory for Sale Type: {0}".format(self.sale_type))


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


"""Laptop Allocations Functions - Modified with Delivery Date Logic"""


@frappe.whitelist(allow_guest=True)
def calculate_dispatch_eta_for_sales_order(so_name=None):
    """Calculate dispatch ETA.
    - If so_name is passed: calculate only for that Sales Order
    - Else: calculate for all open Sales Orders
    """
    departments = get_departments()
    open_orders = get_open_sales_orders(so_name=so_name)

    so_eta_map = {}
    item_errors = []

    for order in open_orders:
        try:
            so_name_local = order.sales_order
            item_code = order.item_code
            ordered_qty = order.ordered_qty or 0
            delivery_date = order.delivery_date

            if not so_name_local or not item_code:
                continue

            delivered_qty = get_delivered_quantity(so_name_local, item_code) or 0
            net_pending = ordered_qty - delivered_qty

            if net_pending <= 0:
                continue

            if not delivery_date:
                msg = f"{so_name_local} | {item_code} | Missing delivery_date"
                item_errors.append(msg)
                continue

            # Calculate days to deliver
            days_to_deliver = (getdate(delivery_date) - getdate(nowdate())).days

            # Get eligible departments based on delivery date
            eligible_depts, remaining_depts = get_eligible_departments(
                departments, days_to_deliver
            )

            # Adjust serial allocations and get unallocated quantity
            unallocated_qty = adjust_serial_allocations(
                so_name_local, item_code, net_pending, eligible_depts, remaining_depts
            )

            # Calculate ETA for this item
            if unallocated_qty > 0:
                item_eta = calculate_item_eta(item_code, unallocated_qty, departments)
            else:
                item_eta = 0

            # Track max ETA per sales order safely
            if so_name_local not in so_eta_map:
                so_eta_map[so_name_local] = item_eta
            else:
                current_eta = so_eta_map[so_name_local]

                # If any item is "No Stock", whole SO becomes "No Stock"
                if current_eta is None or item_eta is None:
                    so_eta_map[so_name_local] = None
                else:
                    so_eta_map[so_name_local] = max(int(current_eta), int(item_eta))

        except Exception:
            error_message = (
                f"SO: {getattr(order, 'sales_order', None)}\n"
                f"Item: {getattr(order, 'item_code', None)}\n\n"
                f"{frappe.get_traceback()}"
            )
            item_errors.append(error_message)
            frappe.log_error(
                title="Dispatch ETA item processing failed",
                message=error_message
            )
            continue

    # Update only successfully processed SOs
    if so_eta_map:
        update_sales_order_etas(so_eta_map)

    # Log failed rows without rolling back successful updates
    if item_errors:
        frappe.log_error(
            title="Dispatch ETA batch completed with item errors",
            message="\n\n".join(item_errors[:20])
        )

    if so_name:
        return so_eta_map.get(so_name)

    return so_eta_map


def get_departments():
    """Get all departments with aging information"""
    return frappe.db.sql("""
        SELECT name, min_aging_days, department_sequence
        FROM `tabDepartment`
        WHERE department_sequence >= 1
        ORDER BY department_sequence DESC
    """, as_dict=True)


def get_eligible_departments(departments, days_to_deliver):
    """
    Determine eligible departments based on delivery date SLA
    Returns: (eligible_departments_reversed, remaining_departments)
    """
    eligible_depts = []
    cumulative_days = 0

    # Loop through departments in DESC order (as retrieved)
    for dept in departments:
        cumulative_days += dept.min_aging_days
        eligible_depts.append(dept)

        # Break when cumulative days >= days to deliver
        if cumulative_days >= days_to_deliver:
            break

    # Reverse the eligible departments for allocation (process in reverse order)
    eligible_depts_reversed = list(reversed(eligible_depts))

    # Get remaining departments (those not in eligible list)
    eligible_names = {d.name for d in eligible_depts}
    remaining_depts = [d for d in departments if d.name not in eligible_names]

    return eligible_depts_reversed, remaining_depts


def get_open_sales_orders(so_name=None):
    """Get all open sales orders with pending items.
    If so_name is passed, return only that Sales Order's items.
    """
    condition_direct = ""
    condition_bundle = ""
    params = []

    if so_name:
        condition_direct = " AND so.name = %s "
        condition_bundle = " AND so.name = %s "
        params.extend([so_name, so_name])

    query = f"""
        SELECT *
        FROM (
            -- 1. Direct stock items
            SELECT
                so.name AS sales_order,
                soi.item_code,
                SUM(soi.qty) AS ordered_qty,
                so.delivery_date
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
                {condition_direct}
            GROUP BY
                so.name, soi.item_code, so.delivery_date

            UNION ALL

            -- 2. Product bundle stock items
            SELECT
                so.name AS sales_order,
                pbi.item_code,
                pbi.qty * soi.qty AS ordered_qty,
                so.delivery_date
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
                {condition_bundle}
        ) AS combined
        ORDER BY combined.delivery_date ASC
    """

    if params:
        return frappe.db.sql(query, tuple(params), as_dict=True)
    return frappe.db.sql(query, as_dict=True)


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


def adjust_serial_allocations(so_name, item_code, net_pending, eligible_depts, remaining_depts):
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
        # First try eligible departments (in reverse order)
        allocated_in_eligible = assign_serials(so_name, item_code, to_allocate, eligible_depts)

        # If not fully allocated, try remaining departments
        if allocated_in_eligible < to_allocate:
            remaining_to_allocate = to_allocate - allocated_in_eligible
            allocated_in_remaining = assign_serials(so_name, item_code, remaining_to_allocate, remaining_depts)
            total_allocated = allocated_in_eligible + allocated_in_remaining
        else:
            total_allocated = allocated_in_eligible

        unallocated_qty = to_allocate - total_allocated

        if unallocated_qty > 0:
            create_unallocated_log(so_name, item_code, unallocated_qty, "Insufficient available stock")

    return unallocated_qty


def assign_serials(so_name, item_code, to_allocate, departments):
    """Assign serial numbers from given departments"""
    print("\n\n⚙️ Assigning serial numbers for {}".format(so_name))
    allocated_count = 0

    for dept in departments:
        if allocated_count >= to_allocate:
            break

        # Get warehouses for this department
        warehouses = frappe.db.sql_list("""
            SELECT name FROM `tabWarehouse` WHERE department = %s
        """, dept.name)

        if not warehouses:
            continue

        remaining = int(to_allocate - allocated_count)

        # Build SQL-safe string
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

        print(f"\n🔹 Department: {dept.name}, Found {count_in_dept} serials to allocate")

        for serial in available_serials:
            serial_name = serial.get("name")
            serial_doc = frappe.get_doc("Serial No", serial_name)

            print("is_replace:", serial_doc.is_replace)
            print("return_reason:", serial_doc.return_reason)

            # Determine which Sales Order ID to reserve
            if serial_doc.is_replace or serial_doc.return_reason:
                print("🧩 Updating (replacement case)")
                sales_order_id = serial_doc.get("sales_order_id")
                serial_doc.reserved_sales_order = sales_order_id
            else:
                print("⚙️ Updating (normal case)")
                print("so_name:", so_name)
                print("serial_name:", serial_name)
                serial_doc.reserved_sales_order = so_name

            # Calculate aging days
            so_creation = frappe.db.get_value("Sales Order", so_name, "creation")
            aging_days = (getdate() - getdate(so_creation)).days if so_creation else 0

            # Append aging detail
            serial_doc.append("sales_order_details", {
                "sales_order": so_name,
                "aging_days": aging_days
            })

            # Save changes properly
            serial_doc.save(ignore_permissions=True)

        # Commit once per department batch
        frappe.db.commit()

        allocated_count += count_in_dept

    print("✅ Successfully returned from assign_serials()")
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
    """Calculate ETA in days for a specific item quantity.

    Returns:
        int   — days until stock is ready (0 = ready now)
        None  — no stock at all found across all eligible departments
                (distinguishes "needs aging" from "genuinely no stock")
    """
    accumulated_days = 0
    remaining_qty = required_qty
    total_available = 0

    for dept in departments:
        accumulated_days += dept.min_aging_days

        warehouses = frappe.db.sql_list("""
            SELECT name FROM `tabWarehouse` WHERE department = %s
        """, dept.name)

        if not warehouses:
            continue

        placeholders = ', '.join(['%s'] * len(warehouses))

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

        params = [item_code] + warehouses
        available_count = frappe.db.sql(query, params)[0][0] or 0
        total_available += available_count

        if available_count >= remaining_qty:
            return accumulated_days
        else:
            remaining_qty -= available_count

    # Some stock exists but not enough → return max aging days
    # No stock at all anywhere → return None so UI can show "No Stock"
    return accumulated_days if total_available > 0 else None


def update_sales_order_etas(so_eta_map):
    """Update eta_for_dispatch and estimated_delivery_date on Sales Orders.

    ETA logic:
        None  → no stock at all → eta_for_dispatch = 'No Stock', estimated_delivery_date = NULL
        int   → days from today until stock is ready
                estimated_delivery_date = today + eta_days
                (uses nowdate() so estimate is always future-facing)
    """
    for so_name, eta in so_eta_map.items():

        if eta is None:
            frappe.db.sql("""
                UPDATE `tabSales Order`
                SET
                    eta_for_dispatch = 'No Stock',
                    estimated_delivery_date = NULL
                WHERE name = %s
            """, so_name)
            continue

        try:
            eta_days = int(eta) if eta is not None else 0
        except (ValueError, TypeError):
            eta_days = 0

        estimated_delivery_date = add_days(nowdate(), eta_days)

        frappe.db.sql("""
            UPDATE `tabSales Order`
            SET
                eta_for_dispatch = %s,
                estimated_delivery_date = %s
            WHERE name = %s
        """, (eta, estimated_delivery_date, so_name))

    frappe.db.commit()


"""Ending of Laptop Allocations Functions"""


@frappe.whitelist()
def setting_sales_channel_value(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)

    sales_type = doc.get("sale_type")
    if sales_type == "Flipkart":
        doc["sales_channel"] = "Flipkart"
    elif sales_type == "NJ-Direct-B2B" or sales_type == "NJ-Direct-B2C":
        doc["sales_channel"] = "Store"
    elif sales_type == "NJ-Website-B2C":
        doc["sales_channel"] = "Shopify"
    elif sales_type == "Amazon":
        doc["sales_channel"] = "Amazon"
    return doc


@frappe.whitelist()
def fetch_payment_id_from_shopify(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)

    token = "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"
    base_url = "https://newjaisa.myshopify.com/admin/api/2025-01/orders"

    shopify_order_number = doc.get("shopify_order_number")
    if not shopify_order_number:
        frappe.throw("Shopify Order Number not found in Sales Order")

    order_url = f"{base_url}/{shopify_order_number}.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    response = requests.get(order_url, headers=headers)

    if response.status_code != 200:
        frappe.throw(f"Failed to fetch Shopify Order: {response.text}")

    order_data = response.json()
    order = order_data.get("order", {})

    source_identifier = None

    tags = order.get("tags", "")
    match = re.search(r"snapmint_(\d+)", tags)
    if match:
        source_identifier = match.group(1)
    else:
        source_identifier = order.get("source_identifier")

    if not source_identifier:
        frappe.throw("No payment identifier found in Shopify order response")

    frappe.db.set_value(
        "Sales Order",
        doc.get("name"),
        "payment_id",
        source_identifier,
        update_modified=True
    )
    frappe.db.commit()

    return {"payment_id": source_identifier}