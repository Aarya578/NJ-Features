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
                    "name": ["!=", self.name]
                },
                "name"
            )

            if existing_so:
                frappe.throw(
                    f"Payment ID '{self.payment_id}' is already used in Sales Order: {existing_so}"
                )
            else:
                self.approve = 1
                if self.docstatus == 1:
                    frappe.db.set_value("Sales Order", self.name, "approve", 1)
                else:
                    self.save(ignore_permissions=True)

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

    def update_status(self, status):
        super().update_status(status)
        if status in ("Closed", "Cancelled", "Completed"):
            _release_serial_reservations(self.name)

    def on_update_after_submit(self):
        if self.status in ("Closed", "Cancelled", "Completed"):
            _release_serial_reservations(self.name)


def _release_serial_reservations(so_name):
    """Clear reserved_sales_order on serials tied to a Closed/Cancelled/Completed SO."""
    reserved_serials = frappe.db.sql_list("""
        SELECT name
        FROM `tabSerial No`
        WHERE reserved_sales_order = %s
    """, so_name)

    if not reserved_serials:
        return

    frappe.db.sql("""
        UPDATE `tabSerial No`
        SET reserved_sales_order = NULL
        WHERE name IN %(serials)s
    """, {"serials": reserved_serials})
    frappe.db.commit()

    frappe.log_error(
        title=f"Serial reservations released — SO Closed/Cancelled/Completed: {so_name}",
        message=f"Released {len(reserved_serials)} serial(s): {', '.join(reserved_serials)}"
    )    

@frappe.whitelist(allow_guest=True)
def trigger_fulfillment(order_id):
    try:
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": TOKEN
        }

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

            fulfillment_order_url = FULLFILMENT_ORDER_ID.format(shopify_order_id=order_id_shopify)
            fulfillment_order_response = requests.get(fulfillment_order_url, headers=headers)
            fulfillment_order_data = fulfillment_order_response.json()

            if "fulfillment_orders" in fulfillment_order_data and fulfillment_order_data["fulfillment_orders"]:
                fulfillment_order_id = fulfillment_order_data["fulfillment_orders"][0]["id"]

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


def trim_over_allocated_serials():
    """Safety net: find all SOs where reserved serial count > net pending qty, and release excess.

    This prevents over-allocation caused by any race condition or mismatch between
    the hourly allocator and the production planner. It runs at the start of every
    hourly allocation cycle. Runs very fast by targeting only active reserved Sales Orders.
    """
    try:
        # CLEANUP: Release reservations for any serials in sequence 0 departments
        # or Employee Personal Warehouses
        invalid_serials = frappe.db.sql_list("""
            SELECT sn.name
            FROM `tabSerial No` sn
            INNER JOIN `tabDepartment` dp ON sn.department = dp.name
            INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
            WHERE sn.reserved_sales_order IS NOT NULL
              AND sn.reserved_sales_order != ''
              AND sn.status = 'Active'
              AND (
                  IFNULL(dp.department_sequence, 0) = 0
                  OR IFNULL(w.warehouse_type, '') = 'Employee Personal Warehouse'
              )
        """)
        if invalid_serials:
            frappe.db.sql("""
                UPDATE `tabSerial No`
                SET reserved_sales_order = NULL,
                    to_make = NULL
                WHERE name IN %s
            """, (tuple(invalid_serials),))
            frappe.db.commit()
            logger.info("Released %s invalid serials in sequence 0 departments or Employee Personal Warehouses", len(invalid_serials))

        # Get active reserved Sales Orders to avoid querying the whole system history
        active_reserved_sos = frappe.db.sql_list("""
            SELECT DISTINCT reserved_sales_order 
            FROM `tabSerial No` 
            WHERE reserved_sales_order IS NOT NULL 
              AND reserved_sales_order != ''
              AND status = 'Active'
        """)
        if not active_reserved_sos:
            return

        so_list_str = ", ".join(f"'{so}'" for so in active_reserved_sos)

        # Get all SOs that have serial reservations, with their ordered & delivered qtys
        over_allocated = frappe.db.sql(f"""
            SELECT
                res.reserved_sales_order AS so_name,
                res.item_code            AS item_code,
                res.reserved_count,
                IFNULL(soi_data.so_qty, 0)   AS so_qty,
                IFNULL(dn_data.dn_qty, 0)    AS dn_qty,
                GREATEST(0, CASE WHEN so.name IS NULL OR so.status IN ('Closed', 'Cancelled', 'Completed') THEN 0 ELSE IFNULL(soi_data.so_qty, 0) - IFNULL(dn_data.dn_qty, 0) END) AS net_pending
            FROM (
                SELECT
                    sn.reserved_sales_order,
                    COALESCE(NULLIF(sn.to_make, ''), sn.item_code) AS item_code,
                    COUNT(*) AS reserved_count
                FROM `tabSerial No` sn
                INNER JOIN `tabDepartment` dp ON sn.department = dp.name
                INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
                WHERE sn.reserved_sales_order IN ({so_list_str})
                  AND sn.status = 'Active'
                  AND IFNULL(dp.department_sequence, 0) != 0
                  AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
                GROUP BY sn.reserved_sales_order, COALESCE(NULLIF(sn.to_make, ''), sn.item_code)
            ) res
            LEFT JOIN `tabSales Order` so ON so.name = res.reserved_sales_order
            LEFT JOIN (
                SELECT
                    soi.parent AS sales_order,
                    CASE
                        WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                        ELSE pbi.item_code
                    END AS item_code,
                    SUM(
                        CASE
                            WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.qty
                            ELSE IFNULL(pbi.qty, 0) * soi.qty
                        END
                    ) AS so_qty
                FROM `tabSales Order Item` soi
                INNER JOIN `tabSales Order` so ON so.name = soi.parent
                INNER JOIN `tabItem` it_so ON it_so.name = soi.item_code
                LEFT JOIN `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code
                    AND IFNULL(it_so.is_stock_item, 0) = 0
                LEFT JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
                WHERE so.name IN ({so_list_str})
                GROUP BY soi.parent,
                    CASE
                        WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                        ELSE pbi.item_code
                    END
            ) soi_data
                ON soi_data.sales_order = res.reserved_sales_order
               AND soi_data.item_code   = res.item_code

            LEFT JOIN (
                SELECT
                    dni.against_sales_order AS sales_order,
                    CASE 
                        WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                        ELSE pbi.item_code
                    END AS item_code,
                    SUM(dni.qty) AS dn_qty
                FROM `tabDelivery Note Item` dni
                INNER JOIN `tabSales Order Item` soi ON dni.so_detail = soi.name
                INNER JOIN `tabItem` it_so ON it_so.name = soi.item_code
                LEFT JOIN `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code
                    AND IFNULL(it_so.is_stock_item, 0) = 0
                LEFT JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
                    AND pbi.item_code = dni.item_code
                WHERE dni.docstatus = 1 AND dni.against_sales_order IN ({so_list_str})
                GROUP BY dni.against_sales_order, 
                    CASE 
                        WHEN IFNULL(it_so.is_stock_item, 0) = 1 THEN soi.item_code
                        ELSE pbi.item_code
                    END
            ) dn_data
                ON dn_data.sales_order = res.reserved_sales_order
               AND dn_data.item_code   = res.item_code

            HAVING res.reserved_count > net_pending
        """, as_dict=True)

        total_released = 0
        for row in over_allocated:
            excess = int(row["reserved_count"] - row["net_pending"])
            if excess <= 0:
                continue

            # Release excess serials (prefer releasing exact-match serials first,
            # keep reconfig serials since they have production plan work orders)
            excess_serials = frappe.db.sql_list("""
                SELECT name
                FROM `tabSerial No`
                WHERE reserved_sales_order = %s
                  AND (item_code = %s OR (to_make IS NOT NULL AND to_make != '' AND to_make = %s))
                  AND status = 'Active'
                ORDER BY
                    CASE WHEN (to_make IS NULL OR to_make = '' OR to_make = item_code) THEN 0 ELSE 1 END ASC,
                    creation DESC
                LIMIT %s
            """, (row["so_name"], row["item_code"], row["item_code"], excess))

            if excess_serials:
                frappe.db.sql("""
                    UPDATE `tabSerial No`
                    SET reserved_sales_order = NULL
                    WHERE name IN %(serials)s
                """, {"serials": excess_serials})
                total_released += len(excess_serials)
                logger.info(
                    "Trimmed %d excess serials from SO %s / item %s (had %d, need %d)",
                    len(excess_serials), row["so_name"], row["item_code"],
                    int(row["reserved_count"]), int(row["net_pending"])
                )

        if total_released:
            frappe.db.commit()
            logger.info("trim_over_allocated_serials: released %d excess serials total", total_released)

    except Exception:
        frappe.log_error(
            title="trim_over_allocated_serials failed",
            message=frappe.get_traceback()
        )



@frappe.whitelist(allow_guest=True)
def calculate_dispatch_eta_for_sales_order(so_name=None):
    """Calculate dispatch ETA.

    - If so_name is passed: calculate only for that Sales Order
    - Else: calculate for all open Sales Orders

    Display ETA is based on the theoretical prediction from calculate_item_eta()
    using full pending quantity, not on whether the order is already reserved /
    allocated. Allocation is still executed for reservation side effects.
    """
    # Safety net: trim any over-allocated serials before processing
    if not so_name:
        trim_over_allocated_serials()

    departments = get_departments()
    open_orders = get_open_sales_orders(so_name=so_name)

    so_eta_map = {}
    so_breakdown_map = {}
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

            days_to_deliver = (getdate(delivery_date) - getdate(nowdate())).days

            eligible_depts, remaining_depts = get_eligible_departments(
                departments, days_to_deliver
            )

            display_item_eta = calculate_item_eta(item_code, net_pending, departments)
            display_breakdown = get_item_eta_breakdown(item_code, net_pending, departments)
            display_breakdown_text = format_eta_breakdown_text(
                item_code=item_code,
                required_qty=net_pending,
                predicted_eta=display_item_eta,
                breakdown=display_breakdown
            )

            # Keep reservation side effects
            adjust_serial_allocations(
                so_name_local, item_code, net_pending, eligible_depts, remaining_depts
            )

            if so_name_local not in so_eta_map:
                so_eta_map[so_name_local] = display_item_eta
            else:
                current_eta = so_eta_map[so_name_local]
                if current_eta is None or display_item_eta is None:
                    so_eta_map[so_name_local] = None
                else:
                    so_eta_map[so_name_local] = max(int(current_eta), int(display_item_eta))

            so_breakdown_map.setdefault(so_name_local, [])
            so_breakdown_map[so_name_local].append(display_breakdown_text)

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

    if so_eta_map:
        update_sales_order_etas(so_eta_map, so_breakdown_map)

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
    if days_to_deliver <= 0:
        return list(departments), []
    eligible_depts = []
    cumulative_days = 0

    for dept in departments:
        cumulative_days += dept.min_aging_days
        eligible_depts.append(dept)

        if cumulative_days >= days_to_deliver:
            break

    eligible_depts_reversed = list(reversed(eligible_depts))

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
                AND so.creation >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
                {condition_direct}
            GROUP BY
                so.name, soi.item_code, so.delivery_date

            UNION ALL

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
                AND so.creation >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
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
        INNER JOIN `tabSales Order Item` soi ON dni.so_detail = soi.name
        WHERE soi.parent = %s
            AND (soi.item_code = %s OR dni.item_code = %s)
            AND dn.docstatus = 1
    """, (so_name, item_code, item_code))

    return result[0][0] if result and result[0][0] else 0


def adjust_serial_allocations(so_name, item_code, net_pending, eligible_depts, remaining_depts):
    """Adjust serial allocations and return unallocated quantity.

    Counts ALL serials reserved for this SO + item, including reconfig serials
    where to_make matches the target item_code (consistent with the production
    planner's COALESCE(NULLIF(to_make, ''), item_code) logic).
    """
    # Count serials where either the current item_code matches OR the
    # serial is being reconfigured into this item (to_make = item_code).
    # This prevents over-allocation when the production planner has already
    # reserved reconfig serials for this Sales Order.
    allocated_count = frappe.db.sql("""
        SELECT COUNT(*)
        FROM `tabSerial No` sn
        INNER JOIN `tabDepartment` dp ON sn.department = dp.name
        INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
        WHERE
            sn.reserved_sales_order = %s
            AND (
                sn.item_code = %s
                OR (sn.to_make IS NOT NULL AND sn.to_make != '' AND sn.to_make = %s)
            )
            AND sn.status = 'Active'
            AND IFNULL(dp.department_sequence, 0) != 0
            AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
    """, (so_name, item_code, item_code))[0][0] or 0

    to_allocate = net_pending - allocated_count
    unallocated_qty = 0

    if to_allocate < 0:
        # Only unassign exact-match serials (don't touch production planner reconfigs)
        unassign_serials(so_name, item_code, abs(to_allocate))

    elif to_allocate > 0:
        search_order = (eligible_depts or []) + (remaining_depts or [])
        total_allocated = assign_serials(so_name, item_code, to_allocate, search_order)
        unallocated_qty = to_allocate - total_allocated

        if unallocated_qty > 0:
            create_unallocated_log(so_name, item_code, unallocated_qty, "Insufficient available stock")

    return unallocated_qty


def assign_serials(so_name, item_code, to_allocate, departments):
    """Assign serial numbers using multi-pass priority across search_order departments."""
    if to_allocate <= 0 or not departments:
        return 0

    from nj_features.nj_features.doctype.nj_production_planning.nj_production_planning import (
        _get_shopify_variant_id,
        _get_variant_bundle_item_codes,
        _cfg_tuple_from_item,
    )

    allocated_count = 0
    needed_qty = to_allocate

    def _do_assign(sn_name):
        nonlocal allocated_count, needed_qty
        try:
            sdoc = frappe.get_doc("Serial No", sn_name)
            sdoc.reserved_sales_order = so_name
            sdoc.to_make = item_code
            so_creation = frappe.db.get_value("Sales Order", so_name, "creation")
            aging_days = (getdate() - getdate(so_creation)).days if so_creation else 0
            already_logged = any(
                row.sales_order == so_name
                for row in sdoc.get("sales_order_details", [])
            )
            if not already_logged:
                sdoc.append("sales_order_details", {
                    "sales_order": so_name,
                    "aging_days": aging_days
                })
            sdoc.save(ignore_permissions=True)
            allocated_count += 1
            needed_qty -= 1
        except Exception as e:
            frappe.log_error(title=f"Serial reservation failed {sn_name}", message=str(e))

    dept_candidates = {}
    for dept in departments:
        dept_name = getattr(dept, "name", str(dept))
        wh_list = frappe.db.sql_list("""
            SELECT name FROM `tabWarehouse` 
            WHERE department = %s
              AND IFNULL(warehouse_type, '') != 'Employee Personal Warehouse'
        """, dept_name)
        if not wh_list:
            dept_candidates[dept_name] = []
            continue

        serials = frappe.db.sql("""
            SELECT sn.name, sn.item_code, sn.to_make, sn.creation, sn.purchase_date
            FROM `tabSerial No` sn
            INNER JOIN `tabDepartment` dp ON sn.department = dp.name
            INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
            WHERE
                sn.warehouse IN %s
                AND (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '')
                AND sn.status = 'Active'
                AND IFNULL(dp.department_sequence, 0) != 0
                AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
                AND NOT (
                    (sn.is_replace = 1 OR (sn.return_reason IS NOT NULL AND sn.return_reason != ''))
                    AND (sn.sales_order_id IS NULL OR sn.sales_order_id = '')
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM `tabDelivery Note Item`
                    WHERE serial_no = sn.name
                        AND docstatus = 1
                )
            ORDER BY COALESCE(sn.purchase_date, sn.creation) ASC, sn.name ASC
        """, (tuple(wh_list),), as_dict=True)
        dept_candidates[dept_name] = serials or []

    # --- Priority 1: Exact Item Code Match across search_order ---
    for dept in departments:
        if needed_qty <= 0:
            break
        dept_name = getattr(dept, "name", str(dept))
        pool = dept_candidates.get(dept_name, [])
        matches = [s for s in pool if s.get("item_code") == item_code or s.get("to_make") == item_code]
        for s in matches[:needed_qty]:
            pool.remove(s)
            _do_assign(s["name"])

    # --- Priority 2: Same Shopify Variant ID Item Codes across search_order ---
    variant_id = _get_shopify_variant_id(item_code)
    p2_codes = set(_get_variant_bundle_item_codes(variant_id)) - {item_code} if variant_id else set()
    if needed_qty > 0 and p2_codes:
        for dept in departments:
            if needed_qty <= 0:
                break
            dept_name = getattr(dept, "name", str(dept))
            pool = dept_candidates.get(dept_name, [])
            matches = [s for s in pool if s.get("item_code") in p2_codes or s.get("to_make") in p2_codes]
            for s in matches[:needed_qty]:
                pool.remove(s)
                _do_assign(s["name"])

    # --- Priority 3: Same Parent Reconfiguration (Model + Processor) across search_order ---
    if needed_qty > 0:
        try:
            target_cfg_tuple = _cfg_tuple_from_item(item_code)
            target_model = (target_cfg_tuple[0], target_cfg_tuple[1])
            for dept in departments:
                if needed_qty <= 0:
                    break
                dept_name = getattr(dept, "name", str(dept))
                pool = dept_candidates.get(dept_name, [])
                p3_matches = []
                for s in pool:
                    try:
                        scfg = _cfg_tuple_from_item(s.get("item_code"))
                        if (scfg[0], scfg[1]) == target_model:
                            p3_matches.append(s)
                    except Exception:
                        pass
                for s in p3_matches[:needed_qty]:
                    pool.remove(s)
                    _do_assign(s["name"])
        except Exception:
            pass

    # --- Priority 4: Parent's Shopify Variant ID Item Codes across search_order ---
    if needed_qty > 0:
        parent_variant_id = _get_shopify_variant_id(item_code)
        if parent_variant_id:
            p4_codes = set(_get_variant_bundle_item_codes(parent_variant_id)) - {item_code} - p2_codes
            if p4_codes:
                for dept in departments:
                    if needed_qty <= 0:
                        break
                    dept_name = getattr(dept, "name", str(dept))
                    pool = dept_candidates.get(dept_name, [])
                    matches = [s for s in pool if s.get("item_code") in p4_codes or s.get("to_make") in p4_codes]
                    for s in matches[:needed_qty]:
                        pool.remove(s)
                        _do_assign(s["name"])

    frappe.db.commit()
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
    """Calculate ETA in days for a specific item quantity."""
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

    return accumulated_days if total_available > 0 else None


def get_item_eta_breakdown(item_code, required_qty, departments):
    """Return department-wise ETA ladder for one item."""
    breakdown = []
    accumulated_days = 0
    remaining_qty = required_qty

    for dept in departments:
        accumulated_days += dept.min_aging_days

        warehouses = frappe.db.sql_list("""
            SELECT name
            FROM `tabWarehouse`
            WHERE department = %s
        """, dept.name)

        available_count = 0

        if warehouses:
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

        before_remaining = remaining_qty

        if available_count >= remaining_qty:
            remaining_qty = 0
            status = "enough_here"
        else:
            remaining_qty -= available_count
            status = "not_enough"

        breakdown.append({
            "department": dept.name,
            "min_aging_days": dept.min_aging_days,
            "cumulative_eta_days": accumulated_days,
            "available_qty": available_count,
            "required_before_this_dept": before_remaining,
            "remaining_after_this_dept": remaining_qty,
            "status": status
        })

        if remaining_qty <= 0:
            break

    return breakdown


def format_eta_breakdown_text(item_code, required_qty, predicted_eta, breakdown):
    """Make a compact human-readable ETA summary for Sales Order display."""
    if not breakdown:
        return (
            f"Item: {item_code}\n"
            f"Required Qty: {required_qty}\n"
            f"Predicted ETA: {'No Stock' if predicted_eta is None else predicted_eta}"
        )

    enough_row = next((row for row in breakdown if row.get("status") == "enough_here"), None)

    lines = []
    lines.append(f"Item: {item_code}")
    lines.append(f"Required Qty: {required_qty}")
    lines.append(f"Predicted ETA: {'No Stock' if predicted_eta is None else str(predicted_eta) + ' days'}")

    if enough_row:
        lines.append(f"Stock becomes available at: {enough_row['department']}")
        lines.append(f"Available Qty there: {enough_row['available_qty']}")
        lines.append(f"Estimated Delivery Date Basis: today + {predicted_eta} days")

    lines.append("")
    lines.append("ETA Timeline:")

    timeline_parts = []
    for row in breakdown:
        if row.get("min_aging_days"):
            timeline_parts.append(f"{row['department']} (+{row['min_aging_days']})")

    if timeline_parts:
        lines.append(" -> ".join(timeline_parts))
    else:
        lines.append("Ready stock available immediately")

    if enough_row:
        lines.append("")
        lines.append("Department-wise Summary:")
        for row in breakdown:
            status_text = "Reached here" if row["status"] == "enough_here" else "Waiting"
            lines.append(
                f"- {row['department']}: "
                f"min {row['min_aging_days']} day(s), "
                f"cumulative {row['cumulative_eta_days']} day(s), "
                f"available {row['available_qty']}, "
                f"remaining {row['remaining_after_this_dept']} "
                f"({status_text})"
            )

    return "\n".join(lines)


def get_eta_breakdown_fieldname():
    """Find the Sales Order custom fieldname for ETA breakdown by label."""
    rows = frappe.get_all(
        "Custom Field",
        filters={
            "dt": "Sales Order",
            "label": "ETA Department Breakdown"
        },
        fields=["fieldname"],
        order_by="creation desc",
        limit=1
    )

    if rows:
        return rows[0].fieldname

    if frappe.db.has_column("Sales Order", "eta_department_breakdown"):
        return "eta_department_breakdown"

    return None


@frappe.whitelist()
def get_sales_order_eta_breakdown(so_name):
    """Whitelisted helper if you want to fetch SO ETA breakdown from UI later."""
    departments = get_departments()
    open_orders = get_open_sales_orders(so_name=so_name)

    result = []

    for order in open_orders:
        item_code = order.item_code
        ordered_qty = order.ordered_qty or 0
        delivered_qty = get_delivered_quantity(order.sales_order, item_code) or 0
        net_pending = ordered_qty - delivered_qty

        if net_pending <= 0:
            continue

        predicted_eta = calculate_item_eta(item_code, net_pending, departments)
        breakdown = get_item_eta_breakdown(item_code, net_pending, departments)

        result.append({
            "sales_order": order.sales_order,
            "item_code": item_code,
            "pending_qty": net_pending,
            "predicted_eta": predicted_eta,
            "breakdown": breakdown
        })

    return result


def update_sales_order_etas(so_eta_map, so_breakdown_map=None):
    """Update eta_for_dispatch, estimated_delivery_date and breakdown text on Sales Orders."""
    breakdown_fieldname = get_eta_breakdown_fieldname()
    has_eta_date_col = frappe.db.has_column("Sales Order", "estimated_delivery_date")

    for so_name, eta in so_eta_map.items():
        update_values = {}

        if eta is None:
            update_values["eta_for_dispatch"] = "No Stock"
            if has_eta_date_col:
                update_values["estimated_delivery_date"] = None
        else:
            try:
                eta_days = int(eta) if eta is not None else 0
            except (ValueError, TypeError):
                eta_days = 0

            update_values["eta_for_dispatch"] = eta
            if has_eta_date_col:
                update_values["estimated_delivery_date"] = add_days(nowdate(), eta_days)

        if so_breakdown_map and breakdown_fieldname:
            update_values[breakdown_fieldname] = "\n\n".join(
                so_breakdown_map.get(so_name, [])
            )

        frappe.db.set_value(
            "Sales Order",
            so_name,
            update_values,
            update_modified=False
        )

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