import re
import json
import time
import math
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
        raw_order_id = None
        if self.order_type != "Maintenance" and not (self.naming_series and self.naming_series.startswith("SO-Snapmint-")):
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
            calc_res = compute_sales_order_delivery_date(self.name, return_reason=True)
            if isinstance(calc_res, (list, tuple)):
                calc_dd, reason_text = calc_res
            else:
                calc_dd, reason_text = calc_res, str(calc_res)

            so_updates = {
                "delivery_date": calc_dd,
                "estimated_delivery_date": reason_text
            }
            if frappe.db.has_column("Sales Order", "committed_delivery_date"):
                committed_val = frappe.db.get_value("Sales Order", self.name, "committed_delivery_date")
                if not committed_val:
                    so_updates["committed_delivery_date"] = calc_dd

            frappe.db.set_value("Sales Order", self.name, so_updates, update_modified=False)
            frappe.db.sql("""
                UPDATE `tabSales Order Item`
                SET delivery_date = %s
                WHERE parent = %s
            """, (calc_dd, self.name))
            frappe.db.commit()
            push_delivery_date_to_shopify_order(self.name, calc_dd)
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
        SET reserved_sales_order = NULL,
            remarks = NULL
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
                    to_make = NULL,
                    remarks = NULL
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
                GREATEST(0, CASE WHEN so.name IS NULL OR so.status IN ('Closed', 'Cancelled', 'Completed') OR njr.name IS NOT NULL THEN 0 ELSE IFNULL(soi_data.so_qty, 0) - IFNULL(dn_data.dn_qty, 0) END) AS net_pending
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
            LEFT JOIN `tabNJ Refund` njr ON njr.sales_order = res.reserved_sales_order AND njr.refund_status IN ('Paid', 'Refunded') AND njr.docstatus = 1
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
                LEFT JOIN `tabProduct Bundle` pb ON (pb.new_item_code = soi.item_code OR pb.name = soi.item_code)
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
                    SUM(
                        CASE
                            WHEN IFNULL(dn.is_return, 0) = 0 THEN dni.qty
                            WHEN dn.is_return = 1 AND dn.cause_of_return IN ('Repair', 'Replace') THEN dni.qty
                            ELSE 0
                        END
                    ) AS dn_qty
                FROM `tabDelivery Note Item` dni
                INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
                INNER JOIN `tabSales Order Item` soi ON dni.so_detail = soi.name
                INNER JOIN `tabItem` it_so ON it_so.name = soi.item_code
                LEFT JOIN `tabProduct Bundle` pb ON (pb.new_item_code = soi.item_code OR pb.name = soi.item_code)
                    AND IFNULL(it_so.is_stock_item, 0) = 0
                LEFT JOIN `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
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
                    SET reserved_sales_order = NULL,
                        remarks = NULL
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



def _is_dept_applicable(dept_row, item_grp):
    """
    Checks if a department SLA applies to the given item group.
    - Packing & Dispatch always applies (SLA = 1).
    - If sla_item_groups is empty / None / blank -> False (Ignored).
    - Otherwise, item_grp must be explicitly listed in sla_item_groups.
    """
    dept_name = str(dept_row.get("name") or "").lower()
    if "packing & dispatch" in dept_name:
        return True
    if not item_grp:
        return False
    groups_str = str(dept_row.get("sla_item_groups") or "").strip()
    if not groups_str or groups_str.lower() in ("none", "null"):
        return False  # Strictly ignore if empty
    allowed = [g.strip().lower() for g in groups_str.split(",") if g.strip()]
    return item_grp.strip().lower() in allowed


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

            item_group = frappe.db.get_value("Item", item_code, "item_group")
            item_depts = [d for d in departments if _is_dept_applicable(d, item_group)]

            days_to_deliver = (getdate(delivery_date) - getdate(nowdate())).days

            eligible_depts, remaining_depts = get_eligible_departments(
                item_depts, days_to_deliver
            )

            display_item_eta = calculate_item_eta(item_code, net_pending, item_depts)
            display_breakdown = get_item_eta_breakdown(item_code, net_pending, item_depts)
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
                    so_eta_map[so_name_local] = min(int(current_eta), int(display_item_eta))

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
    """Get all departments with aging information (excludes Inward sequence <= 1)"""
    return frappe.db.sql("""
        SELECT name, min_aging_days, department_sequence, sla_item_groups
        FROM `tabDepartment`
        WHERE department_sequence > 1
        ORDER BY department_sequence DESC
    """, as_dict=True)


def get_eligible_departments(departments, days_to_deliver):
    """
    Determine eligible departments based on delivery date SLA.
    Returns: (eligible_departments, remaining_departments) in downstream-first order
    (Packing & Dispatch -> Adaptor QC -> FQC -> upstream).
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

    eligible_names = {d.name for d in eligible_depts}
    remaining_depts = [d for d in departments if d.name not in eligible_names]

    return eligible_depts, remaining_depts


def get_open_sales_orders(so_name=None):
    """Get all open sales orders with pending items.
    If so_name is passed, return only that Sales Order's items.
    """
    condition_direct = ""
    condition_bundle = ""
    params_direct = []
    params_bundle = []

    if so_name:
        condition_direct = " AND so.name = %s "
        condition_bundle = " AND so.name = %s "
        params_direct.append(so_name)
        params_bundle.append(so_name)

    # 1. Direct stock items
    query_direct = f"""
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
            AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes', 'AIO', 'Full Set Desktops', 'MacBooks', 'Full Set Desktops(Bundle)', 'AIO(Bundle)', 'MacBooks(Bundle)', 'Desktops(Bundle)', 'Chromebooks(Bundle)', 'Laptops(Bundle)', 'Chromeboxes(Bundle)')
            AND so.creation >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
            {condition_direct}
        GROUP BY
            so.name, soi.item_code, so.delivery_date
    """
    direct_rows = frappe.db.sql(query_direct, tuple(params_direct), as_dict=True) if params_direct else frappe.db.sql(query_direct, as_dict=True) or []

    # 2. Bundle items matched by pb.name = soi.item_code
    query_bundle_name = f"""
        SELECT
            so.name AS sales_order,
            pbi.item_code,
            SUM(pbi.qty * soi.qty) AS ordered_qty,
            so.delivery_date
        FROM
            `tabSales Order` so
        INNER JOIN
            `tabSales Order Item` soi ON soi.parent = so.name
        INNER JOIN
            `tabItem` soi_item ON soi.item_code = soi_item.item_code
        INNER JOIN
            `tabProduct Bundle Item` pbi ON pbi.parent = soi.item_code
        INNER JOIN
            `tabItem` i ON pbi.item_code = i.item_code
        WHERE
            so.docstatus = 1
            AND so.status NOT IN ('Completed', 'Closed', 'Cancelled', 'To Deliver')
            AND soi_item.is_stock_item = 0
            AND i.is_stock_item = 1
            AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes', 'AIO', 'Full Set Desktops', 'MacBooks', 'Full Set Desktops(Bundle)', 'AIO(Bundle)', 'MacBooks(Bundle)', 'Desktops(Bundle)', 'Chromebooks(Bundle)', 'Laptops(Bundle)', 'Chromeboxes(Bundle)')
            AND so.creation >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
            {condition_bundle}
        GROUP BY
            so.name, pbi.item_code, so.delivery_date
    """
    bundle_name_rows = frappe.db.sql(query_bundle_name, tuple(params_bundle), as_dict=True) if params_bundle else frappe.db.sql(query_bundle_name, as_dict=True) or []

    # 3. Bundle items matched by pb.new_item_code = soi.item_code (avoid duplicates if already in bundle_name_rows)
    matched_so_items = {(r["sales_order"], r["item_code"]) for r in bundle_name_rows}
    query_bundle_new = f"""
        SELECT
            so.name AS sales_order,
            pbi.item_code,
            SUM(pbi.qty * soi.qty) AS ordered_qty,
            so.delivery_date
        FROM
            `tabSales Order` so
        INNER JOIN
            `tabSales Order Item` soi ON soi.parent = so.name
        INNER JOIN
            `tabItem` soi_item ON soi.item_code = soi_item.item_code
        INNER JOIN
            `tabProduct Bundle` pb ON pb.new_item_code = soi.item_code
        INNER JOIN
            `tabProduct Bundle Item` pbi ON pbi.parent = pb.name
        INNER JOIN
            `tabItem` i ON pbi.item_code = i.item_code
        WHERE
            so.docstatus = 1
            AND so.status NOT IN ('Completed', 'Closed', 'Cancelled', 'To Deliver')
            AND soi_item.is_stock_item = 0
            AND i.is_stock_item = 1
            AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes', 'AIO', 'Full Set Desktops', 'MacBooks', 'Full Set Desktops(Bundle)', 'AIO(Bundle)', 'MacBooks(Bundle)', 'Desktops(Bundle)', 'Chromebooks(Bundle)', 'Laptops(Bundle)', 'Chromeboxes(Bundle)')
            AND so.creation >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
            {condition_bundle}
        GROUP BY
            so.name, pbi.item_code, so.delivery_date
    """
    bundle_new_raw = frappe.db.sql(query_bundle_new, tuple(params_bundle), as_dict=True) if params_bundle else frappe.db.sql(query_bundle_new, as_dict=True) or []
    bundle_new_rows = [r for r in bundle_new_raw if (r["sales_order"], r["item_code"]) not in matched_so_items]

    combined = direct_rows + bundle_name_rows + bundle_new_rows
    combined.sort(key=lambda r: str(r.get("delivery_date") or "9999-12-31"))
    return combined


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

    to_allocate = int(net_pending - allocated_count)
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
    """Assign serial numbers using department-first multi-priority search across departments."""
    to_allocate = int(to_allocate or 0)
    if to_allocate <= 0 or not departments:
        return 0

    from nj_features.nj_features.doctype.nj_production_planning.nj_production_planning import (
        _get_shopify_variant_id,
        _get_variant_bundle_item_codes,
        _cfg_tuple_from_item,
        _get_equivalent_parent_models,
    )

    allocated_count = 0
    needed_qty = to_allocate

    def _do_assign(sn_name, remarks_text=None, sn_dict=None, dept_name=None):
        nonlocal allocated_count, needed_qty
        try:
            update_data = {
                "reserved_sales_order": so_name,
                "to_make": item_code
            }
            if remarks_text:
                update_data["remarks"] = remarks_text
            frappe.db.set_value("Serial No", sn_name, update_data, update_modified=False)
            allocated_count += 1
            needed_qty -= 1

            curr_ic = sn_dict.get("item_code") if sn_dict else frappe.db.get_value("Serial No", sn_name, "item_code")
            curr_wh = sn_dict.get("warehouse") if sn_dict else frappe.db.get_value("Serial No", sn_name, "warehouse")
            curr_dept = dept_name or (sn_dict.get("department") if sn_dict else frappe.db.get_value("Serial No", sn_name, "department"))

            log_msg = (
                f"Sales Order: {so_name}\n"
                f"Target Order Item Code: {item_code}\n"
                f"Allocated Serial No: {sn_name}\n"
                f"Serial Current Item Code: {curr_ic}\n"
                f"Department: {curr_dept}\n"
                f"Warehouse: {curr_wh}\n"
                f"Detailed Reason: {remarks_text}"
            )
            frappe.log_error(title="ALlocation log for debug", message=log_msg)
        except Exception as e:
            frappe.log_error(title=f"Serial reservation failed {sn_name}", message=str(e))

    dept_candidates = {}
    for dept in departments:
        dept_name = dept.get("name") if isinstance(dept, dict) else getattr(dept, "name", str(dept))
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
            ORDER BY COALESCE(sn.purchase_date, sn.creation) ASC, sn.name ASC
        """, (tuple(wh_list),), as_dict=True)
        dept_candidates[dept_name] = serials or []

    variant_id = _get_shopify_variant_id(item_code)
    p2_codes = set(_get_variant_bundle_item_codes(variant_id)) - {item_code} if variant_id else set()

    target_cfg_tuple = None
    target_model = None
    try:
        target_cfg_tuple = _cfg_tuple_from_item(item_code)
        if target_cfg_tuple:
            target_model = (target_cfg_tuple[0], target_cfg_tuple[1])
    except Exception:
        pass

    parent_variant_id = _get_shopify_variant_id(item_code)
    p4_codes = set()
    if parent_variant_id:
        p4_codes = set(_get_variant_bundle_item_codes(parent_variant_id)) - {item_code} - p2_codes

    # Department-First: Exhaust all 4 priorities within current department before moving to next
    for dept in departments:
        if needed_qty <= 0:
            break
        dept_name = dept.get("name") if isinstance(dept, dict) else getattr(dept, "name", str(dept))
        pool = dept_candidates.get(dept_name, [])
        if not pool:
            continue

        # --- Priority 1: Exact Item Code Match in THIS department ---
        matches_p1 = [s for s in pool if s.get("item_code") == item_code or s.get("to_make") == item_code]
        for s in matches_p1[:needed_qty]:
            pool.remove(s)
            remarks_text = f"Allocated to SO {so_name} (Priority 1: Exact Item Code match '{item_code}') | to_make: {item_code}"
            _do_assign(s["name"], remarks_text=remarks_text, sn_dict=s, dept_name=dept_name)

        # --- Priority 2: Same Shopify Variant ID Item Codes in THIS department ---
        if needed_qty > 0 and p2_codes:
            matches_p2 = [s for s in pool if s.get("item_code") in p2_codes or s.get("to_make") in p2_codes]
            for s in matches_p2[:needed_qty]:
                pool.remove(s)
                curr_ic = s.get("item_code")
                remarks_text = f"Allocated to SO {so_name} (Priority 2: Matched via Shopify Variant ID {variant_id}, current '{curr_ic}') | to_make: {item_code}"
                _do_assign(s["name"], remarks_text=remarks_text, sn_dict=s, dept_name=dept_name)

        # --- Priority 3: Same Parent Reconfiguration (Model + Processor) in THIS department ---
        if needed_qty > 0 and target_model:
            target_tmpl, target_proc = target_model[0], target_model[1]
            equiv_templates = _get_equivalent_parent_models(target_tmpl)
            p3_matches = []
            for s in pool:
                try:
                    scfg = _cfg_tuple_from_item(s.get("item_code"))
                    if scfg and scfg[1] == target_proc and scfg[0] in equiv_templates:
                        p3_matches.append(s)
                except Exception:
                    pass
            for s in p3_matches[:needed_qty]:
                pool.remove(s)
                curr_ic = s.get("item_code")
                remarks_text = f"Allocated to SO {so_name} (Priority 3: Parent Reconfig match for Model '{target_cfg_tuple[0]}', CPU '{target_cfg_tuple[1]}', current '{curr_ic}') | to_make: {item_code}"
                _do_assign(s["name"], remarks_text=remarks_text, sn_dict=s, dept_name=dept_name)

        # --- Priority 4: Parent's Shopify Variant ID Item Codes in THIS department ---
        if needed_qty > 0 and p4_codes:
            matches_p4 = [s for s in pool if s.get("item_code") in p4_codes or s.get("to_make") in p4_codes]
            for s in matches_p4[:needed_qty]:
                pool.remove(s)
                curr_ic = s.get("item_code")
                remarks_text = f"Allocated to SO {so_name} (Priority 4: Matched via Parent Shopify Variant ID {parent_variant_id}, current '{curr_ic}') | to_make: {item_code}"
                _do_assign(s["name"], remarks_text=remarks_text, sn_dict=s, dept_name=dept_name)

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
            SET sales_order = NULL, reserved_sales_order = NULL, remarks = NULL
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

        item_group = frappe.db.get_value("Item", item_code, "item_group")
        item_depts = [d for d in departments if _is_dept_applicable(d, item_group)]

        predicted_eta = calculate_item_eta(item_code, net_pending, item_depts)
        breakdown = get_item_eta_breakdown(item_code, net_pending, item_depts)

        result.append({
            "sales_order": order.sales_order,
            "item_code": item_code,
            "pending_qty": net_pending,
            "predicted_eta": predicted_eta,
            "breakdown": breakdown
        })

    return result


def compute_sales_order_delivery_date(so_name, return_reason=False):
    """
    Calculate Delivery Date for a Sales Order based on allocated serials' department SLA.
    - Packing & Dispatch (Seq 20) -> SLA = 1 (curdate + 1).
    - Upstream department -> cumulative SLA from that department to Packing & Dispatch.
    - 10% buffer applied to cumulative SLA (rounded up).
    - If reconfigured item (Priority 2, 3, 4) -> adds +2 days extra.
    - Updates individual Serial No.estimated_delivery_date for each reserved serial.
    - Multiple units -> takes the MAX SLA across units (bottleneck logic).
    - Returns target delivery date (and formatted explanatory reason if return_reason=True).
    """
    try:
        depts_data = frappe.db.sql("""
            SELECT name, department_sequence, department_sla, sla_item_groups
            FROM `tabDepartment`
            WHERE department_sequence > 1
            ORDER BY department_sequence ASC
        """, as_dict=True)

        if not depts_data:
            fallback_date = add_days(nowdate(), 1)
            reason = f"{fallback_date} (Default SLA: 1d)"
            return (fallback_date, reason) if return_reason else fallback_date

        for d in depts_data:
            if "packing & dispatch" in (d.get("name") or "").lower():
                d["department_sla"] = 1

        def _dept_sla(cand_dept_name, cand_dept_seq, item_grp=None, is_reconfig=False):
            if not cand_dept_name or not cand_dept_seq:
                return 3 if is_reconfig else 1
            is_pd = "packing & dispatch" in (cand_dept_name or "").lower()
            cand_sla = 1 if is_pd else 0
            for d in depts_data:
                if d.get("name") == cand_dept_name:
                    cand_sla = d.get("department_sla", 0)
                    break

            app_depts = [d for d in depts_data if _is_dept_applicable(d, item_grp)]
            seq_max_sla = {}
            for d in app_depts:
                seq = d.get("department_sequence")
                sla = d.get("department_sla") or 0
                if seq not in seq_max_sla or sla > seq_max_sla[seq]:
                    seq_max_sla[seq] = sla

            max_seq = max(seq_max_sla.keys()) if seq_max_sla else 1

            total = cand_sla
            for s in range(cand_dept_seq + 1, max_seq + 1):
                if s in seq_max_sla:
                    total += seq_max_sla[s]
            sla_with_buffer = math.ceil(total * 1.10)
            if is_reconfig:
                sla_with_buffer += 2
            return sla_with_buffer

        # Check reserved serials for this Sales Order
        reserved_serials = frappe.db.sql("""
            SELECT 
                sn.name, sn.item_code, sn.to_make, sn.remarks,
                dp.name AS dept_name, dp.department_sequence, dp.department_sla,
                i.item_group
            FROM `tabSerial No` sn
            INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
            INNER JOIN `tabDepartment` dp ON w.department = dp.name
            LEFT JOIN `tabItem` i ON i.item_code = COALESCE(NULLIF(sn.to_make, ''), sn.item_code)
            WHERE sn.reserved_sales_order = %s
        """, (so_name,), as_dict=True)

        # Get direct and bundle item codes for this SO
        so_direct_items = set(frappe.db.sql_list("""
            SELECT DISTINCT item_code FROM `tabSales Order Item` WHERE parent = %s
        """, so_name))
        bundle_items = set(frappe.db.sql_list("""
            SELECT DISTINCT pbi.item_code
            FROM `tabSales Order Item` soi
            INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = soi.item_code
            WHERE soi.parent = %s
        """, so_name))
        so_all_target_items = so_direct_items | bundle_items

        has_serial_eta_col = frappe.db.has_column("Serial No", "estimated_delivery_date")

        if reserved_serials:
            sla_list = []
            serial_reasons = []
            for s in reserved_serials:
                curr_ic = s.get("item_code")
                to_make = s.get("to_make")
                remarks = s.get("remarks") or ""
                item_grp = s.get("item_group")
                dept_name = s.get("dept_name") or "Unknown"
                dept_seq = s.get("department_sequence") or 1

                # Check if exact match or reconfigured
                is_reconfig = False
                if to_make and to_make != curr_ic:
                    is_reconfig = True
                elif curr_ic not in so_all_target_items:
                    is_reconfig = True
                elif "Priority 2" in remarks or "Priority 3" in remarks or "Priority 4" in remarks or "Reconfig" in remarks:
                    is_reconfig = True

                sn_sla = _dept_sla(dept_name, dept_seq, item_grp=item_grp, is_reconfig=is_reconfig)
                sn_est_date = add_days(nowdate(), sn_sla)
                sla_list.append(sn_sla)

                reconfig_tag = " [Reconfig +2d]" if is_reconfig else ""
                day_unit = "day" if sn_sla == 1 else "days"

                # Standard format for Serial No: YYYY-MM-DD | Department: <dept> (SLA: <N> days)
                sn_reason_str = f"{sn_est_date} | Department: {dept_name} (SLA: {sn_sla} {day_unit}){reconfig_tag}"
                if len(sn_reason_str) > 250:
                    sn_reason_str = sn_reason_str[:247] + "..."

                # Update individual Serial No's estimated_delivery_date
                if has_serial_eta_col:
                    frappe.db.set_value("Serial No", s.get("name"), "estimated_delivery_date", sn_reason_str, update_modified=False)

                serial_reasons.append(f"SN: {s.get('name')} in {dept_name}{reconfig_tag} (SLA: {sn_sla}d -> {sn_est_date})")

            # Delivery date takes MIN SLA; Estimated delivery date takes MAX SLA
            min_sla = min(sla_list) if sla_list else 1
            max_sla = max(sla_list) if sla_list else 1

            delivery_date = add_days(nowdate(), min_sla)
            max_est_date = add_days(nowdate(), max_sla)

            reason_str = f"{max_est_date} | " + "; ".join(serial_reasons)
            if len(reason_str) > 250:
                reason_str = reason_str[:247] + "..."

            return (delivery_date, reason_str) if return_reason else delivery_date

        # Fallback: check tabSO Quantity Check SLA for items in this SO
        if so_all_target_items:
            soqc_slas = frappe.db.sql_list("""
                SELECT sla FROM `tabSO Quantity Check` WHERE item_code IN %s AND sla > 0
            """, (tuple(so_all_target_items),))
            if soqc_slas:
                min_sla = min(soqc_slas)
                max_sla = max(soqc_slas)
                delivery_date = add_days(nowdate(), min_sla)
                max_est_date = add_days(nowdate(), max_sla)
                reason_str = f"{max_est_date} (Unallocated - SO Quantity Check SLA: {max_sla}d)"
                if len(reason_str) > 250:
                    reason_str = reason_str[:247] + "..."
                return (delivery_date, reason_str) if return_reason else delivery_date

        fallback_date = add_days(nowdate(), 1)
        reason_str = f"{fallback_date} (Default SLA: 1d)"
        return (fallback_date, reason_str) if return_reason else fallback_date

    except Exception:
        frappe.log_error(title=f"compute_sales_order_delivery_date failed for {so_name}", message=frappe.get_traceback())
        fallback_date = add_days(nowdate(), 1)
        reason_str = f"{fallback_date} (Fallback on error: 1d)"
        return (fallback_date, reason_str) if return_reason else fallback_date


def update_sales_order_etas(so_eta_map, so_breakdown_map=None):
    """Update delivery_date, eta_for_dispatch, estimated_delivery_date and breakdown text on Sales Orders."""
    breakdown_fieldname = get_eta_breakdown_fieldname()
    has_eta_date_col = frappe.db.has_column("Sales Order", "estimated_delivery_date")

    for so_name, eta in so_eta_map.items():
        update_values = {}
        calc_res = compute_sales_order_delivery_date(so_name, return_reason=True)
        if isinstance(calc_res, (list, tuple)):
            calc_delivery_date, reason_text = calc_res
        else:
            calc_delivery_date, reason_text = calc_res, str(calc_res)

        update_values["delivery_date"] = calc_delivery_date

        if eta is None:
            update_values["eta_for_dispatch"] = "No Stock"
            if has_eta_date_col:
                update_values["estimated_delivery_date"] = reason_text or "No Stock"
        else:
            try:
                eta_days = int(eta) if eta is not None else 0
            except (ValueError, TypeError):
                eta_days = 0

            update_values["eta_for_dispatch"] = eta
            if has_eta_date_col:
                update_values["estimated_delivery_date"] = reason_text

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

        frappe.db.sql("""
            UPDATE `tabSales Order Item`
            SET delivery_date = %s
            WHERE parent = %s
        """, (calc_delivery_date, so_name))

        push_delivery_date_to_shopify_order(so_name, calc_delivery_date)

    frappe.db.commit()


def push_delivery_date_to_shopify_order(so_name, delivery_date):
    """Push confirmed Estimated Delivery Date back to Shopify Order note attributes."""
    try:
        shopify_order_number = frappe.db.get_value("Sales Order", so_name, "shopify_order_number")
        if not shopify_order_number:
            return

        from nj_features.nj_features.api.shopify_inventory import get_shopify_settings
        settings = get_shopify_settings()
        if not settings:
            return

        shop = settings.get("shop")
        token = settings.get("token")
        if not shop or not token:
            return

        url = f"{shop}/admin/api/2025-01/orders/{shopify_order_number}.json"
        headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json"
        }
        payload = {
            "order": {
                "id": int(shopify_order_number),
                "note_attributes": [
                    {
                        "name": "Estimated Delivery Date",
                        "value": str(delivery_date)
                    }
                ]
            }
        }
        resp = requests.put(url, headers=headers, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.warning(
                "Could not push delivery date to Shopify order %s: %s",
                shopify_order_number,
                resp.text
            )
    except Exception as e:
        frappe.log_error(
            title=f"push_delivery_date_to_shopify_order failed for {so_name}",
            message=str(e)
        )


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