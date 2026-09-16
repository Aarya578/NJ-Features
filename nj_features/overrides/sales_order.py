import re
import json
import time
import math
import uuid
import base64
import frappe, requests
from collections import defaultdict
from datetime import datetime
from frappe.utils import getdate, nowdate, add_days, flt
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
from nj_features.nj_features.api.shiprocket_api import get_auth_token, generate_awb, generate_label
from nj_features.services.model_compatibility import is_screen_type_compatible

logger = frappe.logger('SOLogger', allow_site=True, file_count=1)

# Extra days a unit needs when it has to be reconfigured (to_make != item_code)
# before it can ship. Production's route for a reconfig is Grade A -> Reliability
# -> FQC, so a rebuild is never ready as fast as a unit that already matches the
# order. Applied to estimated_delivery_date only - it must never be added to
# committed_delivery_date or delivery_date, which are human-owned.
# Change it here and it changes everywhere.
RECONFIG_SLA_DAYS = 3

# Once a serial is reserved to a Sales Order it stays on that order.
#
# The nightly job used to "upgrade" reservations: if any free machine sat in a
# department even one step closer to dispatch, it swapped. That was the only test
# - it never asked whether the order would have made its date anyway, never
# required the gain to be worth anything, and never checked whether production had
# already started rebuilding the unit it was taking away. Between 2026-09-09 and
# 2026-09-16 it swapped 498 times across 12-89 orders a day; SO-2026-09-00088 went
# through ten machines and SAL-ORD-2026-08447 through eight. A released unit keeps
# its to_make, so the work is not lost, but the shop floor is left building for an
# order that no longer owns the machine and no one downstream can plan.
#
# Reservations are still RELEASED when a machine genuinely cannot ship - it moved
# to a department that is not sellable, into a personal warehouse, or the order is
# over-allocated. That is trim_over_allocated_serials() / unassign_serials() and it
# is cleanup, not reallocation. What stops here is trading a working reservation
# for a marginally better one.
#
# Set True to restore the old behaviour; upgrade_order_reservations() is unchanged
# and can still be called by hand for a single order.
AUTO_UPGRADE_RESERVATIONS = False

# Departments a unit only enters when something has gone wrong: a part is
# missing, a QC step failed, a consumable ran out. They are holding states, not
# steps every machine walks through.
#
# compute_sales_order_delivery_date() prices a unit by summing the SLA of every
# applicable department between where it stands and dispatch. That charged each
# of these to every unit upstream of them, whether or not it would ever go near
# one. `Part waiting - NJ` alone carries the maximum 15-day SLA and sits at
# sequence 10, so every laptop below it was billed 15 days for a queue it may
# never join - a third of the whole ladder.
#
# That is why a Dell 3410 sitting in Chip Tech priced out at the 45-day cap, the
# same number used for "we have no machine at all", and why SO-2026-09-00002 read
# as 11-Nov against a 10-Sep promise while 19 of its 20 machines were nearly
# ready. The 62-day gap it produced is what kept triggering reallocation.
#
# A unit ACTUALLY sitting in one of these still gets that department's own SLA
# charged as its starting point - this only removes them from the forward ladder
# of units that are somewhere else.
#
# Matched on the department name, lower-cased. Production should review this list;
# it is a judgement about which steps are routine and which are exceptions.
_CONTINGENT_DEPT_MARKERS = (
    "part waiting",
    "partwating",
    "partwaiting",
    "consumable hold",
    "qc reject",
    "rejection",
    "screen repair",
    "technician repair",
)


def _is_contingent_dept(dept_name):
    """True for a holding/exception department (see _CONTINGENT_DEPT_MARKERS)."""
    name = (dept_name or "").lower()
    return any(marker in name for marker in _CONTINGENT_DEPT_MARKERS)
SHOPIFY_URL = "https://newjaisa.myshopify.com/admin/api/2025-01/orders.json?name="
TOKEN = "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"
FULLFILMENT_ORDER_ID = "https://newjaisa.myshopify.com/admin/api/2025-01/orders/{shopify_order_id}/fulfillment_orders.json"
MAKE_FULLFILMENT = "https://newjaisa.myshopify.com/admin/api/2025-01/fulfillments.json"
_COMPANY_HOLIDAYS_CACHE = {}

def get_company_holidays(year=None):
    """Fetch holiday dates for the given year from Holiday List."""
    global _COMPANY_HOLIDAYS_CACHE
    try:
        if not year:
            year = getdate(nowdate()).year

        if year in _COMPANY_HOLIDAYS_CACHE:
            return _COMPANY_HOLIDAYS_CACHE[year]

        hl_name = f"Holiday List {year}"
        if not frappe.db.exists("Holiday List", hl_name):
            hl_name = frappe.db.get_value("Company", "NewJaisa", "default_holiday_list")

        holidays = set()
        if hl_name:
            h_dates = frappe.db.sql_list("""
                SELECT holiday_date FROM `tabHoliday`
                WHERE parent = %s
            """, (hl_name,))
            holidays = set(getdate(d) for d in h_dates)

        _COMPANY_HOLIDAYS_CACHE[year] = holidays
        return holidays
    except Exception:
        return set()


def add_working_days(start_date, working_days):
    """Add working days to start_date, skipping Sundays and company holidays."""
    if not start_date:
        start_date = nowdate()
    try:
        working_days = int(working_days)
    except (ValueError, TypeError):
        return getdate(start_date)

    curr = getdate(start_date)
    if working_days <= 0:
        return curr

    added = 0
    step = 1 if working_days > 0 else -1
    abs_days = abs(working_days)
    iterations = 0

    while added < abs_days and iterations < 365:
        iterations += 1
        curr = getdate(add_days(curr, step))
        # Exclude Sundays
        if curr.weekday() == 6:
            continue
        # Exclude official company holidays
        holidays = get_company_holidays(curr.year)
        if curr in holidays:
            continue
        added += 1

    return curr


def _snap_to_working_day(d):
    """Nudge a date forward to the next non-Sunday, non-holiday date.

    Used only for an already-set incoming delivery/committed date (e.g. from
    Shopify checkout) that never passed through add_working_days() at all, so
    it can still land on a Sunday/holiday even though our own SLA math never
    would.
    """
    d = getdate(d)
    iterations = 0
    while iterations < 365:
        holidays = get_company_holidays(d.year)
        if d.weekday() != 6 and d not in holidays:
            return d
        d = add_days(d, 1)
        iterations += 1
    return d


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

        # Initialize committed_delivery_date if not already set, BEFORE running ETA calculation.
        # Customer promise date is based on explicit future delivery date or standard SLA (transaction_date + 4d).
        target_committed = None
        if frappe.db.has_column("Sales Order", "committed_delivery_date"):
            committed_val = frappe.db.get_value("Sales Order", self.name, "committed_delivery_date")
            if not committed_val:
                std_sla_date = add_working_days(self.transaction_date, 4) if self.transaction_date else add_working_days(nowdate(), 4)
                orig_dd = self.delivery_date
                max_item_dd = None
                if getattr(self, "items", None):
                    item_dates = [getdate(i.delivery_date) for i in self.items if getattr(i, "delivery_date", None)]
                    if item_dates:
                        max_item_dd = max(item_dates)
                
                candidate_date = max_item_dd or (getdate(orig_dd) if orig_dd else None)
                if candidate_date and candidate_date > getdate(std_sla_date):
                    # This already-set incoming date (e.g. from Shopify checkout) never
                    # passed through add_working_days(), so it can land on a Sunday or
                    # holiday - nudge it forward before locking it in as the promise.
                    target_committed = _snap_to_working_day(candidate_date)
                else:
                    target_committed = std_sla_date

                # committed_delivery_date is ESTABLISHED here, once, because it was
                # empty - and is never written again by any code path.
                #
                # delivery_date is deliberately NOT touched. It belongs to the user:
                # whatever the customer / Shopify / the sales team put there stays
                # there. If a date has to move, a human moves it by hand. The system
                # expresses its own opinion only through estimated_delivery_date.
                self.committed_delivery_date = target_committed
                frappe.db.set_value(
                    "Sales Order", self.name,
                    {"committed_delivery_date": target_committed},
                    update_modified=False,
                )
            else:
                target_committed = committed_val

        calculate_dispatch_eta_for_sales_order(self.name, do_commit=False)

        # A reconfig unit needs ~2 extra days. That cost is applied where it belongs -
        # in compute_sales_order_delivery_date(), which feeds estimated_delivery_date.
        # It is NOT baked back into committed_delivery_date or delivery_date: the
        # promise and the customer-facing date are human-owned and must not be moved
        # by the system. The reconfig surcharge therefore shows up as the estimate
        # pulling away from the promise, which is exactly the signal ops needs.

        calc_res = compute_sales_order_delivery_date(self.name, return_reason=True)
        if isinstance(calc_res, (list, tuple)):
            calc_dd, reason_text = calc_res
        else:
            calc_dd, reason_text = calc_res, str(calc_res)

        so_updates = {
            "estimated_delivery_date": str(calc_dd) if calc_dd else None
        }

        frappe.db.set_value("Sales Order", self.name, so_updates, update_modified=False)

        if calc_dd:
            frappe.enqueue(
                "nj_features.overrides.sales_order.push_delivery_date_to_shopify_order",
                queue="short",
                enqueue_after_commit=True,
                so_name=self.name,
                delivery_date=str(calc_dd),
            )
        self.reload()

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
            remarks = NULL,
            order_source = NULL
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
        # A reserved serial is NOT released just because of where it is standing.
        #
        # This used to strip the reservation off any reserved serial sitting in a
        # department with department_sequence = 0, or in an Employee Personal
        # Warehouse, and it wiped to_make / remarks / order_source with it.
        #
        # department_sequence = 0 does not mean "not stock". It means "not on the
        # sales pipeline", and that covers two completely different things:
        # departments where a unit genuinely stops being sellable (Asset,
        # Procurement, Admin, IT), and departments where a unit is actively being
        # WORKED ON for the very order that reserved it - Reconfiguration - NJ,
        # To Re-config - NJ, WIP - NJ, Stock Movement - NJ, Chip QC, BG - DR - a
        # technician's own warehouse. This could not tell them apart, so sending a
        # machine to be reconfigured destroyed its reservation within the hour, and
        # wiping to_make deleted the instruction saying what to rebuild it into
        # while it sat on the reconfig bench.
        #
        # The order then came up short and was given a different machine, while the
        # original became invisible (allocation only searches department_sequence > 0)
        # and came back later as untargeted free stock - to be allocated elsewhere and
        # reconfigured a second time. That is the rework SO-2026-09-00002 was hit with:
        # 20 units loaded with the 2M config, six re-allocated, the config work lost.
        #
        # Once a serial is reserved to an order it stays reserved to that order.
        # Genuine over-allocation (more serials than the order still needs) is still
        # trimmed below - that is counting, not a judgement about location.

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
                INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
                INNER JOIN `tabDepartment` dp ON w.department = dp.name
                WHERE sn.reserved_sales_order IN ({so_list_str})
                  AND sn.status = 'Active'
                  AND (IFNULL(dp.department_sequence, 0) != 0 OR sn.return_reason IN ('Repair', 'Replace', 'RTO Customer', 'RTO Delivery Partner'))
                  AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
                GROUP BY sn.reserved_sales_order, COALESCE(NULLIF(sn.to_make, ''), sn.item_code)
            ) res
            LEFT JOIN `tabSales Order` so ON so.name = res.reserved_sales_order
            -- Keep in sync with reservation_service.REFUND_BLOCKING_STATUSES
            LEFT JOIN `tabNJ Refund` njr ON njr.sales_order = res.reserved_sales_order AND njr.refund_status IN ('Paid', 'Refunded', 'Initiated', 'Debit Failed', 'Returned') AND njr.docstatus = 1
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
                            WHEN dn.is_return = 1 AND IFNULL(dn.cause_of_return, '') != 'Refund' THEN dni.qty
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
                  AND (return_reason IS NULL OR return_reason NOT IN ('Repair', 'Replace'))
                  AND (order_source IS NULL OR (
                      order_source NOT LIKE '%%- Repair%%'
                      AND order_source NOT LIKE '%%- Replace%%'
                      AND order_source NOT LIKE '%%- RTO Customer%%'
                      AND order_source NOT LIKE '%%- RTO Delivery Partner%%'
                  ))
                  AND status = 'Active'
                ORDER BY
                    CASE
                        WHEN return_reason IN ('Repair', 'Replace', 'RTO Customer', 'RTO Delivery Partner') THEN 2
                        WHEN (to_make IS NOT NULL AND to_make != '' AND to_make != item_code) THEN 1
                        ELSE 0
                    END ASC,
                    creation DESC
                LIMIT %s
            """, (row["so_name"], row["item_code"], row["item_code"], excess))

            if excess_serials:
                frappe.db.sql("""
                    UPDATE `tabSerial No`
                    SET reserved_sales_order = NULL,
                        to_make = NULL,
                        remarks = NULL,
                        order_source = NULL
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


def run_daily_eta_drift_reallocation():
    """Once-a-day entry point (scheduled at midnight) for the ETA-drift
    reallocation check. This is the ONLY path that may reallocate an
    already-allocated serial - every other run of calculate_dispatch_eta_for_sales_order
    (hourly cron, on_submit, manual triggers) must only recompute displayed
    ETAs and must never touch an existing reservation or to_make.
    """
    return calculate_dispatch_eta_for_sales_order(so_name=None, do_commit=True, allow_reallocation=True)


@frappe.whitelist(allow_guest=True)
def calculate_dispatch_eta_for_sales_order(so_name=None, do_commit=True, allow_reallocation=False):
    """Calculate dispatch ETA.

    - If so_name is passed: calculate only for that Sales Order
    - Else: calculate for all open Sales Orders

    Display ETA is based on the theoretical prediction from calculate_item_eta()
    using full pending quantity, not on whether the order is already reserved /
    allocated. Allocation is still executed for reservation side effects.

    allow_reallocation: passed through to update_sales_order_etas(). Only the
    once-a-day midnight job (run_daily_eta_drift_reallocation) sets this True -
    every other caller (hourly cron, on_submit, etc.) must leave it False so an
    already-allocated serial's reservation/to_make is never touched outside
    that one daily check.
    """
    job = None
    try:
        from rq import get_current_job
        job = get_current_job()
    except Exception:
        pass

    # If running inside a non-long background worker (like the scheduler's default 5-min worker)
    # and calculating for all orders, delegate to the 'long' queue (1800s timeout) so it won't be killed.
    if not so_name and job and getattr(job, "origin", "") != "long":
        frappe.enqueue(
            "nj_features.overrides.sales_order.calculate_dispatch_eta_for_sales_order",
            queue="long",
            timeout=1800,
            job_name="calculate_dispatch_eta_for_all_sales_orders",
            do_commit=do_commit,
            allow_reallocation=allow_reallocation,
        )
        logger.info("Delegated full dispatch ETA calculation to 'long' queue worker (timeout=1800s)")
        return {}

    global _DEPT_WAREHOUSES_CACHE, _DEPT_AVAILABLE_SERIALS_CACHE, _POOL_CFG_CACHE
    _DEPT_WAREHOUSES_CACHE = None
    _DEPT_AVAILABLE_SERIALS_CACHE = None
    # Derived from the serial pool, so it must die with it - otherwise a later
    # run would match against item codes from a stale pool.
    _POOL_CFG_CACHE = None
    _ALLOCATION_MATCHER_CACHE.clear()

    # Safety net: trim any over-allocated serials before processing
    if not so_name:
        trim_over_allocated_serials()
        # Reallocation must only happen via the ETA-drift check (see ETA_DRIFT
        # below) - never as a blanket opportunistic sweep here. An already
        # allocated serial should not be swapped out just because a
        # closer-department candidate exists; doing so invalidates any
        # physical kitting/rework already committed against it.

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
                delivery_date = add_working_days(nowdate(), 1)

            item_group = frappe.db.get_value("Item", item_code, "item_group")
            item_depts = [d for d in departments if _is_dept_applicable(d, item_group)]

            days_to_deliver = (getdate(delivery_date) - getdate(nowdate())).days

            if days_to_deliver > 50:
                # Orders exceeding 50 days should NOT hold or allocate serial reservations
                unassign_serials(so_name_local, item_code, 999999)
                logger.info(f"[SKIP_ALLOCATION_50D] {so_name_local} item {item_code}: days_to_deliver={days_to_deliver} > 50")
                continue

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

            eff_item_eta = display_item_eta if display_item_eta is not None else 45
            if so_name_local not in so_eta_map:
                so_eta_map[so_name_local] = eff_item_eta
            else:
                current_eta = so_eta_map[so_name_local]
                current_val = 45 if current_eta is None else int(current_eta)
                so_eta_map[so_name_local] = max(current_val, int(eff_item_eta))

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
        update_sales_order_etas(so_eta_map, so_breakdown_map, do_commit=do_commit, allow_reallocation=allow_reallocation)

    if item_errors:
        frappe.log_error(
            title="Dispatch ETA batch completed with item errors",
            message="\n\n".join(item_errors[:20])
        )

    if so_name:
        return so_eta_map.get(so_name)

    return so_eta_map


_DEPT_WAREHOUSES_CACHE = None
_DEPT_AVAILABLE_SERIALS_CACHE = None

def get_dept_warehouses(dept_name):
    """Return list of active non-personal warehouse names for a department, cached in memory."""
    global _DEPT_WAREHOUSES_CACHE
    if _DEPT_WAREHOUSES_CACHE is None:
        rows = frappe.db.sql("""
            SELECT name, department
            FROM `tabWarehouse`
            WHERE IFNULL(warehouse_type, '') != 'Employee Personal Warehouse'
              AND department IS NOT NULL AND department != ''
        """, as_dict=True)
        _DEPT_WAREHOUSES_CACHE = defaultdict(list)
        for r in rows:
            _DEPT_WAREHOUSES_CACHE[r["department"]].append(r["name"])
    return _DEPT_WAREHOUSES_CACHE.get(dept_name, [])


def get_dept_available_serials(dept_name):
    """Return mutable list of active unreserved serial records for a department, cached in memory per batch."""
    global _DEPT_AVAILABLE_SERIALS_CACHE
    if _DEPT_AVAILABLE_SERIALS_CACHE is None:
        _DEPT_AVAILABLE_SERIALS_CACHE = defaultdict(list)
        rows = frappe.db.sql("""
            SELECT sn.name, sn.item_code, sn.to_make, sn.creation, sn.purchase_date, sn.warehouse, w.department
            FROM `tabSerial No` sn
            INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
            INNER JOIN `tabDepartment` dp ON w.department = dp.name
            WHERE
                (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '')
                AND sn.status = 'Active'
                -- 'Repair' and 'Replace' are excluded; RTO Customer and RTO Delivery
                -- Partner are NOT. Keep this list identical to the one in
                -- so_quantity_check.py and shopify_inventory_targeted.py - those decide
                -- what Shopify advertises, and any reason excluded here but counted
                -- there becomes phantom stock: the listing sells it, then allocation
                -- refuses it and the order lands on the fallback SLA.
                --
                -- Repair/Replace units are owed to the customer who returned them, so
                -- no other order may take them. RTO units never reached a customer, so
                -- they are ordinary sellable stock.
                AND (sn.return_reason IS NULL OR sn.return_reason = '' OR sn.return_reason NOT IN ('Repair', 'Replace'))
                AND IFNULL(dp.department_sequence, 0) != 0
                AND dp.sla_item_groups IS NOT NULL AND dp.sla_item_groups != ''
                AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
                AND (
                    (IFNULL(sn.is_replace, 0) = 0 AND (sn.return_reason IS NULL OR sn.return_reason = ''))
                    OR (sn.sales_order_id IS NOT NULL AND sn.sales_order_id != '')
                    OR IFNULL(dp.department_sequence, 0) >= 10
                )
            ORDER BY COALESCE(sn.purchase_date, sn.creation) ASC, sn.name ASC
        """, as_dict=True)

        for r in rows:
            _DEPT_AVAILABLE_SERIALS_CACHE[r["department"]].append(r)
    return _DEPT_AVAILABLE_SERIALS_CACHE[dept_name]


def is_serial_already_delivered(serial_no):
    """True when this serial has shipped on a submitted Delivery Note that was not
    later returned - i.e. it is physically with a customer.

    Checked per candidate at the moment of allocation rather than as a filter on
    the whole pool: the pool holds ~24k serials of which only a handful are in
    this state, and filtering them all up front cost 4-8s (and 82s as a correlated
    NOT EXISTS) on a path Sales Order.on_submit() runs synchronously. One indexed
    lookup on the few serials we actually try to reserve is far cheaper.
    """
    if not serial_no:
        return False
    try:
        return bool(frappe.db.sql("""
            SELECT 1
            FROM `tabDelivery Note Item` dni
            JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            WHERE dni.serial_no = %s
              AND dni.docstatus = 1
              AND dn.is_return = 0
              AND dn.status NOT IN ('Return Issued', 'Closed')
              AND NOT EXISTS (
                  SELECT 1 FROM `tabDelivery Note` ret
                  WHERE ret.return_against = dn.name
                    AND ret.is_return = 1 AND ret.docstatus = 1
              )
            LIMIT 1
        """, (serial_no,)))
    except Exception as e:
        logger.warning("Delivered-check failed for serial %s: %s", serial_no, e)
        return False


def _get_dept_effective_sla(dept):
    """Return effective department turnaround SLA in days."""
    d_name = (dept.get("name") or "").lower() if isinstance(dept, dict) else (dept.name or "").lower()
    if "packing & dispatch" in d_name or "sales" in d_name:
        return 1
    elif "inward" in d_name:
        return 45
    sla = dept.get("department_sla") if isinstance(dept, dict) else getattr(dept, "department_sla", None)
    if sla is None or int(sla or 0) <= 0:
        sla = dept.get("min_aging_days") if isinstance(dept, dict) else getattr(dept, "min_aging_days", 1)
    return min(max(int(sla or 1), 1), 15)


def get_departments():
    """Get all departments with aging information (includes Inward sequence 1)"""
    return frappe.db.sql("""
        SELECT name, min_aging_days, department_sequence, department_sla, sla_item_groups
        FROM `tabDepartment`
        WHERE department_sequence > 0
        ORDER BY department_sequence DESC
    """, as_dict=True)


def get_eligible_departments(departments, days_to_deliver):
    """
    Determine eligible departments based on delivery date SLA.
    
    - If days_to_deliver > 0:
      Accumulates SLA starting from highest sequence (Packing & Dispatch) upstream
      until reaching days_to_deliver.
      Returns: (eligible_departments_reversed, remaining_departments)
      where eligible_departments_reversed is ordered from the earliest eligible upstream
      department down to Packing & Dispatch (e.g. FQC -> RTS Reconfig -> Adaptor QC -> Packing & Dispatch).
      remaining_departments is the deeper upstream departments (e.g. Inventory Optimization -> L2 -> ... -> Inward).
      
    - If days_to_deliver <= 0:
      Returns (list(departments), []) in downstream-first order.
    """
    if days_to_deliver <= 0:
        return list(departments), []

    eligible_depts = []
    cumulative_days = 0

    for dept in departments:
        sla_val = _get_dept_effective_sla(dept)
        cumulative_days += sla_val
        eligible_depts.append(dept)

        if cumulative_days >= days_to_deliver:
            break

    eligible_names = {d.get("name") if isinstance(d, dict) else d.name for d in eligible_depts}
    remaining_depts = [d for d in departments if (d.get("name") if isinstance(d, dict) else d.name) not in eligible_names]

    # Reverse eligible departments so search starts from earliest eligible upstream department down to dispatch
    eligible_depts_reversed = list(reversed(eligible_depts))

    return eligible_depts_reversed, remaining_depts


def get_open_sales_orders(so_name=None):
    """Get all open sales orders with pending items.
    If so_name is passed, return only that Sales Order's items.
    """
    from nj_features.services.reservation_service import REFUND_EXCLUSION_SQL

    condition_direct = ""
    condition_bundle = ""
    params_direct = []
    params_bundle = []

    if so_name:
        # A refunded order can be manually reopened (status flips back to
        # "To Deliver") without this function knowing why — the refund check
        # must apply here too, not just in the bulk/hourly branch below,
        # otherwise on_submit()'s direct calculate_dispatch_eta_for_sales_order
        # call would still allocate a fresh serial to a refunded order.
        condition_direct = " AND so.name = %s " + REFUND_EXCLUSION_SQL
        condition_bundle = " AND so.name = %s " + REFUND_EXCLUSION_SQL
        params_direct.append(so_name)
        params_bundle.append(so_name)
    else:
        active_filter = """
            AND (
                so.creation > CURDATE() - INTERVAL 100 DAY
                OR so.name IN (
                    SELECT DISTINCT reserved_sales_order
                    FROM `tabSerial No`
                    WHERE reserved_sales_order IS NOT NULL AND reserved_sales_order != ''
                )
            )
            AND so.name NOT IN (
                SELECT DISTINCT dni.against_sales_order
                FROM `tabDelivery Note Item` dni
                JOIN `tabDelivery Note` dn ON dn.name = dni.parent
                WHERE dn.docstatus = 1 AND dn.is_return = 1 AND dn.cause_of_return IN ('Repair', 'Refund')
                  AND dni.against_sales_order IS NOT NULL AND dni.against_sales_order != ''
            )
        """ + REFUND_EXCLUSION_SQL
        condition_direct = active_filter
        condition_bundle = active_filter

    # 1. Direct stock items
    # IMPORTANT: Use delivery_date (original customer delivery date) for days_to_deliver calc.
    # committed_delivery_date is only used when it is a real future date (>today).
    # If committed_delivery_date is today or in the past, it means it was incorrectly auto-set
    # on SO submit and we must fallback to delivery_date to avoid days_to_deliver=0
    # which causes ALL departments (including Inward) to become eligible for allocation.
    query_direct = f"""
        SELECT
            so.name AS sales_order,
            soi.item_code,
            SUM(soi.qty) AS ordered_qty,
            CASE
                WHEN so.committed_delivery_date IS NOT NULL
                     AND so.committed_delivery_date != ''
                     AND so.committed_delivery_date > CURDATE()
                THEN so.committed_delivery_date
                ELSE so.delivery_date
            END AS delivery_date
        FROM
            `tabSales Order` so
        INNER JOIN
            `tabSales Order Item` soi ON soi.parent = so.name
        INNER JOIN
            `tabItem` i ON soi.item_code = i.item_code
        WHERE
            so.docstatus = 1
            AND so.status NOT IN ('Completed', 'Closed', 'Cancelled')
            AND IFNULL(so.per_delivered, 0) < 100
            AND i.is_stock_item = 1
            AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes', 'AIO', 'Full Set Desktops', 'MacBooks', 'Full Set Desktops(Bundle)', 'AIO(Bundle)', 'MacBooks(Bundle)', 'Desktops(Bundle)', 'Chromebooks(Bundle)', 'Laptops(Bundle)', 'Chromeboxes(Bundle)')
            {condition_direct}
        GROUP BY
            so.name, soi.item_code,
            CASE
                WHEN so.committed_delivery_date IS NOT NULL
                     AND so.committed_delivery_date != ''
                     AND so.committed_delivery_date > CURDATE()
                THEN so.committed_delivery_date
                ELSE so.delivery_date
            END
    """
    direct_rows = frappe.db.sql(query_direct, tuple(params_direct), as_dict=True) if params_direct else frappe.db.sql(query_direct, as_dict=True) or []

    # 2. Bundle items matched by pb.name = soi.item_code
    query_bundle_name = f"""
        SELECT
            so.name AS sales_order,
            pbi.item_code,
            SUM(pbi.qty * soi.qty) AS ordered_qty,
            CASE
                WHEN so.committed_delivery_date IS NOT NULL
                     AND so.committed_delivery_date != ''
                     AND so.committed_delivery_date > CURDATE()
                THEN so.committed_delivery_date
                ELSE so.delivery_date
            END AS delivery_date
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
            AND so.status NOT IN ('Completed', 'Closed', 'Cancelled')
            AND IFNULL(so.per_delivered, 0) < 100
            AND soi_item.is_stock_item = 0
            AND i.is_stock_item = 1
            AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes', 'AIO', 'Full Set Desktops', 'MacBooks', 'Full Set Desktops(Bundle)', 'AIO(Bundle)', 'MacBooks(Bundle)', 'Desktops(Bundle)', 'Chromebooks(Bundle)', 'Laptops(Bundle)', 'Chromeboxes(Bundle)')
            {condition_bundle}
        GROUP BY
            so.name, pbi.item_code,
            CASE
                WHEN so.committed_delivery_date IS NOT NULL
                     AND so.committed_delivery_date != ''
                     AND so.committed_delivery_date > CURDATE()
                THEN so.committed_delivery_date
                ELSE so.delivery_date
            END
    """
    bundle_name_rows = frappe.db.sql(query_bundle_name, tuple(params_bundle), as_dict=True) if params_bundle else frappe.db.sql(query_bundle_name, as_dict=True) or []

    # 3. Bundle items matched by pb.new_item_code = soi.item_code (avoid duplicates if already in bundle_name_rows)
    matched_so_items = {(r["sales_order"], r["item_code"]) for r in bundle_name_rows}
    query_bundle_new = f"""
        SELECT
            so.name AS sales_order,
            pbi.item_code,
            SUM(pbi.qty * soi.qty) AS ordered_qty,
            CASE
                WHEN so.committed_delivery_date IS NOT NULL
                     AND so.committed_delivery_date != ''
                     AND so.committed_delivery_date > CURDATE()
                THEN so.committed_delivery_date
                ELSE so.delivery_date
            END AS delivery_date
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
            AND so.status NOT IN ('Completed', 'Closed', 'Cancelled')
            AND IFNULL(so.per_delivered, 0) < 100
            AND soi_item.is_stock_item = 0
            AND i.is_stock_item = 1
            AND i.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes', 'AIO', 'Full Set Desktops', 'MacBooks', 'Full Set Desktops(Bundle)', 'AIO(Bundle)', 'MacBooks(Bundle)', 'Desktops(Bundle)', 'Chromebooks(Bundle)', 'Laptops(Bundle)', 'Chromeboxes(Bundle)')
            {condition_bundle}
        GROUP BY
            so.name, pbi.item_code,
            CASE
                WHEN so.committed_delivery_date IS NOT NULL
                     AND so.committed_delivery_date != ''
                     AND so.committed_delivery_date > CURDATE()
                THEN so.committed_delivery_date
                ELSE so.delivery_date
            END
    """
    bundle_new_raw = frappe.db.sql(query_bundle_new, tuple(params_bundle), as_dict=True) if params_bundle else frappe.db.sql(query_bundle_new, as_dict=True) or []
    bundle_new_rows = [r for r in bundle_new_raw if (r["sales_order"], r["item_code"]) not in matched_so_items]

    combined = direct_rows + bundle_name_rows + bundle_new_rows
    combined.sort(key=lambda r: str(r.get("delivery_date") or "9999-12-31"))
    return combined


def get_delivered_quantity(so_name, item_code):
    """Get delivered quantity for a sales order item (supports direct stock items and bundled packed items)"""
    dni_result = frappe.db.sql("""
        SELECT SUM(dni.qty)
        FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dni.parent = dn.name
        LEFT JOIN `tabSales Order Item` soi ON dni.so_detail = soi.name
        WHERE (dni.against_sales_order = %s OR soi.parent = %s)
            AND (dni.item_code = %s OR soi.item_code = %s)
            AND dn.docstatus = 1
    """, (so_name, so_name, item_code, item_code))

    dni_qty = flt(dni_result[0][0]) if dni_result and dni_result[0][0] is not None else 0.0

    packed_result = frappe.db.sql("""
        SELECT SUM(pi.qty)
        FROM `tabPacked Item` pi
        INNER JOIN `tabDelivery Note` dn ON pi.parent = dn.name
        INNER JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name AND dni.name = pi.parent_detail_docname
        WHERE dni.against_sales_order = %s
            AND pi.item_code = %s
            AND dn.docstatus = 1
    """, (so_name, item_code))

    packed_qty = flt(packed_result[0][0]) if packed_result and packed_result[0][0] is not None else 0.0

    return max(0.0, dni_qty + packed_qty)


HARDWARE_ITEM_GROUPS = {
    "Laptops", "Chromebooks", "MacBooks", "Desktops", "AIO", "Full Set Desktops", "Chromeboxes",
    "Laptops(Bundle)", "Chromebooks(Bundle)", "MacBooks(Bundle)", "Desktops(Bundle)", "AIO(Bundle)", "Full Set Desktops(Bundle)", "Chromeboxes(Bundle)"
}


def is_repair_sales_order(so_name):
    """Check if the sales order has an active return delivery note with cause Repair."""
    return bool(frappe.db.sql("""
        SELECT 1
        FROM `tabDelivery Note Item` dni
        JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dni.against_sales_order = %s
          AND dn.docstatus = 1
          AND dn.is_return = 1
          AND (dn.cause_of_return = 'Repair' OR dn.return_reason IN ('Repair', 'In-House Repair'))
        LIMIT 1
    """, (so_name,)))


def is_customer_return_sales_order(so_name):
    """Check if the sales order has an active return delivery note with Repair or RTO causes."""
    return bool(frappe.db.sql("""
        SELECT 1
        FROM `tabDelivery Note Item` dni
        JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dni.against_sales_order = %s
          AND dn.docstatus = 1
          AND dn.is_return = 1
          AND dn.cause_of_return IN ('Repair', 'RTO Customer', 'RTO Delivery Partner')
        LIMIT 1
    """, (so_name,)))


def adjust_serial_allocations(so_name, item_code, net_pending, eligible_depts, remaining_depts):
    """Adjust serial allocations and return unallocated quantity.

    Counts ALL serials reserved for this SO + item, including reconfig serials
    where to_make matches the target item_code (consistent with the production
    planner's COALESCE(NULLIF(to_make, ''), item_code) logic).
    """
    item_group = frappe.db.get_value("Item", item_code, "item_group")
    if not item_group or item_group not in HARDWARE_ITEM_GROUPS:
        return 0

    # Count serials already committed to THIS line, keyed on where each serial is
    # going - to_make when set, otherwise its current item_code. This is the same
    # key the production planner and the Shopify quantity query use.
    #
    # It must not be "item_code = X OR to_make = X". A serial mid-rebuild satisfies
    # both halves of that OR and is then counted against two different lines of the
    # same order: the line it is actually becoming, and the line it happens to be
    # sitting in today. On an order with several lines of one base model the counts
    # add up to more serials than are reserved, each line looks full, and the
    # allocator stops - leaving dispatch-ready machines untouched while the order
    # runs late. Observed on SO-2026-04-00203-1 (GMIT): 9 machines double-counted,
    # the 16-unit line read as full with only 7 serials behind it.
    allocated_count = frappe.db.sql("""
        SELECT COUNT(*)
        FROM `tabSerial No` sn
        INNER JOIN `tabWarehouse` w ON sn.warehouse = w.name
        INNER JOIN `tabDepartment` dp ON w.department = dp.name
        WHERE
            sn.reserved_sales_order = %s
            AND COALESCE(NULLIF(sn.to_make, ''), sn.item_code) = %s
            AND sn.status = 'Active'
            AND (IFNULL(dp.department_sequence, 0) != 0 OR sn.return_reason IN ('Repair', 'Replace', 'RTO Customer', 'RTO Delivery Partner'))
            AND IFNULL(w.warehouse_type, '') != 'Employee Personal Warehouse'
    """, (so_name, item_code))[0][0] or 0

    to_allocate = int(net_pending - allocated_count)
    unallocated_qty = 0

    # Priority 0: For customer return orders (Repair / RTO), bind any active returned serials first
    if to_allocate > 0 and is_customer_return_sales_order(so_name):
        returned_serials = frappe.db.sql("""
            SELECT DISTINCT sn.name, dn.cause_of_return
            FROM `tabDelivery Note Item` dni
            JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            JOIN `tabSerial No` sn ON (dni.serial_no = sn.name OR dni.serial_no LIKE CONCAT('%%', sn.name, '%%'))
            WHERE dni.against_sales_order = %s
              AND dn.docstatus = 1
              AND dn.is_return = 1
              AND dn.cause_of_return IN ('Repair', 'RTO Customer', 'RTO Delivery Partner')
              AND sn.status = 'Active'
              AND (sn.reserved_sales_order IS NULL OR sn.reserved_sales_order = '' OR sn.reserved_sales_order = %s)
        """, (so_name, so_name), as_dict=True)

        if returned_serials:
            so_sale_type = frappe.db.get_value("Sales Order", so_name, "sale_type") or ""
            for r_sn in returned_serials:
                if to_allocate <= 0:
                    break
                cause = r_sn.get("cause_of_return") or "Return"
                eff_source = f"{so_sale_type} - {cause}" if (so_sale_type and cause) else (so_sale_type or cause)
                frappe.db.set_value(
                    "Serial No",
                    r_sn["name"],
                    {
                        "reserved_sales_order": so_name,
                        "to_make": item_code,
                        "return_reason": cause,
                        "order_source": eff_source,
                        "remarks": f"Allocated to SO {so_name} (Return - {cause}) | to_make: {item_code}"
                    },
                    update_modified=True
                )
                # Set initial_allocated_department once — first allocation wins, never overwritten
                r_dept = r_sn.get("department") or frappe.db.get_value("Serial No", r_sn["name"], "department")
                if r_dept:
                    frappe.db.sql("""
                        UPDATE `tabSerial No`
                        SET initial_allocated_department = %s
                        WHERE name = %s
                          AND (initial_allocated_department IS NULL OR initial_allocated_department = '')
                    """, (r_dept, r_sn["name"]))
                to_allocate -= 1
                allocated_count += 1


    if to_allocate < 0:
        # Only unassign exact-match serials (don't touch production planner reconfigs)
        unassign_serials(so_name, item_code, abs(to_allocate))

    elif to_allocate > 0:
        if is_customer_return_sales_order(so_name):
            # Customer return orders (Repair / RTO) must only be fulfilled by their specific returned unit(s).
            # Do not allocate generic inventory from warehouse pools.
            create_unallocated_log(so_name, item_code, to_allocate, "Waiting for returned customer unit")
            return to_allocate

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

    item_group = frappe.db.get_value("Item", item_code, "item_group")
    if not item_group or item_group not in HARDWARE_ITEM_GROUPS:
        return 0

    from nj_features.nj_features.doctype.nj_production_planning.nj_production_planning import (
        _get_shopify_variant_id,
        _get_variant_bundle_item_codes,
        _cfg_tuple_from_item,
        _get_equivalent_parent_models,
    )
    from nj_features.services.reservation_service import get_effective_order_source

    allocated_count = 0
    needed_qty = to_allocate

    def _do_assign(sn_name, remarks_text=None, sn_dict=None, dept_name=None):
        nonlocal allocated_count, needed_qty
        try:
            # Never reserve a machine that has already shipped to a customer. The
            # Shopify quantity query excludes these, but the allocation pool did
            # not - so an order could be "allocated" to a unit that was physically
            # gone and then simply never dispatch.
            if is_serial_already_delivered(sn_name):
                return False

            # A Non-Touch panel cannot be rebuilt into a Touch one. Checked here
            # rather than inside each condition because C1b matches on to_make and
            # C2/C4 match on Shopify variant grouping - none of them look at the
            # screen, so all three can pair a Touch order with an NT machine.
            if not is_screen_type_compatible(
                (sn_dict or {}).get("item_code"), item_code
            ):
                return False

            effective_source = get_effective_order_source(so_name)
            frappe.db.sql("""
                UPDATE `tabSerial No`
                SET reserved_sales_order = %s,
                    to_make = %s,
                    order_source = %s,
                    return_reason = NULL,
                    is_replace = 0,
                    remarks = %s
                WHERE name = %s
                  AND (reserved_sales_order IS NULL OR reserved_sales_order = '')
                  AND status = 'Active'
                  AND is_replace = 0
                  AND (return_reason IS NULL OR return_reason = '' OR return_reason NOT IN ('Repair', 'Replace'))
            """, (so_name, item_code, effective_source, remarks_text or None, sn_name))

            if getattr(frappe.db, "_cursor", None) and frappe.db._cursor.rowcount <= 0:
                return False

            allocated_count += 1
            needed_qty -= 1

            curr_ic = sn_dict.get("item_code") if sn_dict else frappe.db.get_value("Serial No", sn_name, "item_code")
            curr_wh = sn_dict.get("warehouse") if sn_dict else frappe.db.get_value("Serial No", sn_name, "warehouse")
            curr_dept = dept_name or (sn_dict.get("department") if sn_dict else frappe.db.get_value("Serial No", sn_name, "department"))

            # Set initial_allocated_department once — first allocation wins, never overwritten
            if curr_dept:
                frappe.db.sql("""
                    UPDATE `tabSerial No`
                    SET initial_allocated_department = %s
                    WHERE name = %s
                      AND (initial_allocated_department IS NULL OR initial_allocated_department = '')
                """, (curr_dept, sn_name))

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
            return True
        except Exception as e:
            frappe.log_error(title=f"Serial reservation failed {sn_name}", message=str(e))
            return False


    dept_candidates = {}
    for dept in departments:
        dept_name = dept.get("name") if isinstance(dept, dict) else getattr(dept, "name", str(dept))
        dept_candidates[dept_name] = get_dept_available_serials(dept_name)

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

    # -------------------------------------------------------------------------
    # ALLOCATION LOGIC: Department-first, condition-second.
    #
    # For each department (highest seq → lowest seq, i.e. closest to dispatch first):
    #   Check condition 1 (exact item_code)
    #   Check condition 2 (same Shopify variant)
    #   Check condition 3 (same parent model + CPU)
    #   Check condition 4 (parent's Shopify variant)
    #   → If ANY condition found a serial → allocated. Move to next qty needed.
    #   → If NOTHING found in this dept → move to next dept.
    #
    # This means: a VARIANT match at Reliability (seq 17, 3 days away)
    # ALWAYS beats an EXACT match at Inward (seq 1, 45 days away).
    # -------------------------------------------------------------------------

    # `departments` (built by get_eligible_departments) is already in the SLA-aware
    # priority order: starting near the department that matches this order's
    # delivery urgency and working toward Packing & Dispatch, then falling back to
    # the remaining departments. Do NOT re-sort by department_sequence here — that
    # would discard the urgency-based ordering and make every order (urgent or not)
    # search Packing & Dispatch first, defeating the point of computing it.
    downstream_depts = list(departments)

    # Pre-compute variant/model lookups once
    equiv_templates = None
    target_tmpl, target_proc = None, None
    if target_model:
        target_tmpl, target_proc = target_model[0], target_model[1]
        equiv_templates = _get_equivalent_parent_models(target_tmpl)

    # --- Department-first allocation loop ---
    for dept in downstream_depts:
        if needed_qty <= 0:
            break

        dept_name = dept.get("name") if isinstance(dept, dict) else getattr(dept, "name", str(dept))
        pool = dept_candidates.get(dept_name, [])

        if not pool:
            continue

        allocated_in_dept = False

        # -- Condition 1: Exact physical item_code match --
        for s in list(pool):
            if needed_qty <= 0:
                break
            if s.get("item_code") == item_code:
                remarks_text = f"Allocated to SO {so_name} (C1: Exact item_code match in {dept_name}) | to_make: {item_code}"
                if _do_assign(s["name"], remarks_text=remarks_text, sn_dict=s, dept_name=dept_name):
                    pool.remove(s)
                    allocated_in_dept = True

        if needed_qty <= 0:
            break

        # -- Condition 1b: Active WIP reconfig (to_make == item_code) --
        for s in list(pool):
            if needed_qty <= 0:
                break
            if s.get("to_make") == item_code:
                remarks_text = f"Allocated to SO {so_name} (C1b: WIP reconfig to_make match in {dept_name}) | to_make: {item_code}"
                if _do_assign(s["name"], remarks_text=remarks_text, sn_dict=s, dept_name=dept_name):
                    pool.remove(s)
                    allocated_in_dept = True

        if needed_qty <= 0:
            break

        # -- Condition 2: Same Shopify Variant ID --
        if p2_codes:
            for s in list(pool):
                if needed_qty <= 0:
                    break
                if s.get("item_code") in p2_codes or s.get("to_make") in p2_codes:
                    curr_ic = s.get("item_code")
                    remarks_text = f"Allocated to SO {so_name} (C2: Shopify Variant ID {variant_id}, current '{curr_ic}' in {dept_name}) | to_make: {item_code}"
                    if _do_assign(s["name"], remarks_text=remarks_text, sn_dict=s, dept_name=dept_name):
                        pool.remove(s)
                        allocated_in_dept = True

        if needed_qty <= 0:
            break

        # -- Condition 3: Same parent model + CPU (reconfig match) --
        if target_model and equiv_templates:
            for s in list(pool):
                if needed_qty <= 0:
                    break
                try:
                    scfg = _cfg_tuple_from_item(s.get("item_code"))
                    if scfg and scfg[1] == target_proc and scfg[0] in equiv_templates:
                        curr_ic = s.get("item_code")
                        remarks_text = f"Allocated to SO {so_name} (C3: Parent model '{target_tmpl}' CPU '{target_proc}' match in {dept_name}, current '{curr_ic}') | to_make: {item_code}"
                        if _do_assign(s["name"], remarks_text=remarks_text, sn_dict=s, dept_name=dept_name):
                            pool.remove(s)
                            allocated_in_dept = True
                except Exception:
                    pass

        if needed_qty <= 0:
            break

        # -- Condition 4: Parent's Shopify Variant ID --
        if p4_codes:
            for s in list(pool):
                if needed_qty <= 0:
                    break
                if s.get("item_code") in p4_codes or s.get("to_make") in p4_codes:
                    curr_ic = s.get("item_code")
                    remarks_text = f"Allocated to SO {so_name} (C4: Parent Shopify Variant ID {parent_variant_id}, current '{curr_ic}' in {dept_name}) | to_make: {item_code}"
                    if _do_assign(s["name"], remarks_text=remarks_text, sn_dict=s, dept_name=dept_name):
                        pool.remove(s)
                        allocated_in_dept = True

    return allocated_count


def unassign_serials(so_name, item_code, excess_qty):
    """Unassign excess serial numbers"""
    excess_serials = frappe.db.sql_list("""
        SELECT name
        FROM `tabSerial No`
        WHERE
            reserved_sales_order = %s
            AND (
                item_code = %s
                OR (to_make IS NOT NULL AND to_make != '' AND to_make = %s)
            )
            AND (return_reason IS NULL OR return_reason NOT IN ('Repair', 'Replace'))
            AND (order_source IS NULL OR (
                order_source NOT LIKE '%%- Repair%%'
                AND order_source NOT LIKE '%%- Replace%%'
                AND order_source NOT LIKE '%%- RTO Customer%%'
                AND order_source NOT LIKE '%%- RTO Delivery Partner%%'
            ))
            AND NOT EXISTS (
                SELECT 1
                FROM `tabDelivery Note Item`
                WHERE serial_no = `tabSerial No`.name
                    AND docstatus = 1
            )
        ORDER BY
            CASE
                WHEN return_reason IN ('Repair', 'Replace', 'RTO Customer', 'RTO Delivery Partner') THEN 2
                WHEN (to_make IS NOT NULL AND to_make != '' AND to_make != item_code) THEN 1
                ELSE 0
            END ASC,
            creation ASC
        LIMIT %s
    """, (so_name, item_code, item_code, int(excess_qty)))

    if excess_serials:
        frappe.db.sql("""
            UPDATE `tabSerial No`
            SET sales_order = NULL,
                reserved_sales_order = NULL,
                to_make = NULL,
                remarks = NULL,
                order_source = NULL
            WHERE name IN %(serials)s
        """, {"serials": excess_serials})


def create_unallocated_log(sales_order, item_code, pending_qty, reason):
    """Create a log entry in Unallocated Sales Order Item"""
    doc = frappe.new_doc("Unallocated Sales Order Item")
    doc.sales_order = sales_order
    doc.item_code = item_code
    doc.pending_qty = pending_qty
    doc.reason = reason
    doc.posting_date = frappe.utils.nowdate()
    doc.insert(ignore_permissions=True)


_POOL_CFG_CACHE = None
_ALLOCATION_MATCHER_CACHE = {}


def _get_pool_cfg_map():
    """{item_code: (template, processor)} for every code present in the serial pool.

    Built with ONE bulk _prime_item_cache() pass. Calling _cfg_tuple_from_item()
    per candidate serial instead costs a DB round-trip for every uncached item
    code - measured at 141s for a single ETA call, which is fatal because
    Sales Order.on_submit() calls calculate_dispatch_eta_for_sales_order()
    synchronously.
    """
    global _POOL_CFG_CACHE
    if _POOL_CFG_CACHE is not None:
        return _POOL_CFG_CACHE

    from nj_features.nj_features.doctype.nj_production_planning.nj_production_planning import (
        _cfg_tuple_from_item,
        _prime_item_cache,
    )

    if _DEPT_AVAILABLE_SERIALS_CACHE is None:
        get_dept_available_serials("")

    codes = set()
    for rows in (_DEPT_AVAILABLE_SERIALS_CACHE or {}).values():
        for r in rows:
            if r.get("item_code"):
                codes.add(r["item_code"])
            if r.get("to_make"):
                codes.add(r["to_make"])

    codes = list(codes)
    for start in range(0, len(codes), 2000):
        try:
            _prime_item_cache(codes[start:start + 2000])
        except Exception as e:
            logger.warning("Could not prime item cache chunk for ETA matching: %s", e)

    cfg_map = {}
    for c in codes:
        try:
            cfg = _cfg_tuple_from_item(c)
            cfg_map[c] = (cfg[0], cfg[1]) if cfg else (None, None)
        except Exception:
            cfg_map[c] = (None, None)

    _POOL_CFG_CACHE = cfg_map
    return _POOL_CFG_CACHE


def _build_allocation_matcher(item_code):
    """Pre-compute the lookups assign_serials() uses for conditions C2/C3/C4.

    The ETA prediction must judge "is there stock for this order" using the SAME
    rules the allocator uses, otherwise the two disagree: a plain item_code count
    is blind to every reconfig candidate the allocator would happily take (too
    pessimistic) while also counting Repair/Replace/RTO, is_replace, personal
    warehouse and already-delivered units the allocator can never touch (too
    optimistic).
    """
    cached = _ALLOCATION_MATCHER_CACHE.get(item_code)
    if cached is not None:
        return cached

    from nj_features.nj_features.doctype.nj_production_planning.nj_production_planning import (
        _get_shopify_variant_id,
        _get_variant_bundle_item_codes,
        _cfg_tuple_from_item,
        _get_equivalent_parent_models,
    )

    variant_id = _get_shopify_variant_id(item_code)
    p2_codes = set(_get_variant_bundle_item_codes(variant_id)) - {item_code} if variant_id else set()

    target_tmpl, target_proc = None, None
    try:
        cfg = _cfg_tuple_from_item(item_code)
        if cfg:
            target_tmpl, target_proc = cfg[0], cfg[1]
    except Exception:
        pass

    equiv_templates = _get_equivalent_parent_models(target_tmpl) if target_tmpl else set()

    p4_codes = set()
    if variant_id:
        p4_codes = set(_get_variant_bundle_item_codes(variant_id)) - {item_code} - p2_codes

    matcher = {
        "item_code": item_code,
        "p2_codes": p2_codes,
        "p4_codes": p4_codes,
        "target_proc": target_proc,
        "equiv_templates": equiv_templates or set(),
    }
    _ALLOCATION_MATCHER_CACHE[item_code] = matcher
    return matcher


def _serial_matches_allocation(serial_row, matcher):
    """True when assign_serials() could allocate this serial to matcher's item_code.

    Mirrors conditions C1, C1b, C2, C3 and C4 in assign_serials(), in that order.
    """
    item_code = matcher["item_code"]
    curr_ic = serial_row.get("item_code")
    to_make = serial_row.get("to_make")

    # C1: exact physical item_code — C1b: active WIP reconfig already aimed at it
    if curr_ic == item_code or to_make == item_code:
        return True

    # C2: same Shopify variant
    if matcher["p2_codes"] and (curr_ic in matcher["p2_codes"] or to_make in matcher["p2_codes"]):
        return True

    # C3: same parent model + CPU (reconfig match). Pure dict lookup against the
    # bulk-primed map - never a per-serial DB call.
    if matcher["target_proc"] and matcher["equiv_templates"]:
        scfg = _get_pool_cfg_map().get(curr_ic)
        if scfg and scfg[1] == matcher["target_proc"] and scfg[0] in matcher["equiv_templates"]:
            return True

    # C4: parent's Shopify variant
    if matcher["p4_codes"] and (curr_ic in matcher["p4_codes"] or to_make in matcher["p4_codes"]):
        return True

    return False


def _count_allocatable_in_dept(dept_name, matcher):
    """How many serials in this department the allocator could actually take.

    Uses get_dept_available_serials(), the allocator's own pool, so every
    exclusion it applies (reserved, status, return_reason, is_replace, personal
    warehouse, already-delivered, department sequence) applies here too.
    """
    try:
        pool = get_dept_available_serials(dept_name) or []
    except Exception:
        return 0
    return sum(1 for s in pool if _serial_matches_allocation(s, matcher))


def calculate_item_eta(item_code, required_qty, departments):
    """Calculate ETA in days for a specific item quantity."""
    accumulated_days = 0
    remaining_qty = required_qty
    total_available = 0
    matcher = _build_allocation_matcher(item_code)

    for dept in departments:
        dept_name = dept.get("name") if isinstance(dept, dict) else getattr(dept, "name", str(dept))

        if not get_dept_warehouses(dept_name):
            # No warehouses means no unit can be sitting here, so this department
            # cannot contribute to the wait. Skip BEFORE adding its SLA - charging
            # its days anyway inflated every ETA that fell through to a later
            # department.
            continue

        accumulated_days += _get_dept_effective_sla(dept)

        available_count = _count_allocatable_in_dept(dept_name, matcher)
        total_available += available_count

        if available_count >= remaining_qty:
            return accumulated_days
        else:
            remaining_qty -= available_count

    return accumulated_days if total_available > 0 else 45


def get_item_eta_breakdown(item_code, required_qty, departments):
    """Return department-wise ETA ladder for one item.

    Counts candidates exactly as calculate_item_eta() does (and therefore exactly
    as assign_serials() would), so the displayed explanation matches the predicted
    ETA instead of telling a different story.
    """
    breakdown = []
    accumulated_days = 0
    remaining_qty = required_qty
    matcher = _build_allocation_matcher(item_code)

    for dept in departments:
        dept_name = dept.get("name") if isinstance(dept, dict) else getattr(dept, "name", str(dept))

        if not get_dept_warehouses(dept_name):
            continue

        sla_val = _get_dept_effective_sla(dept)
        accumulated_days += sla_val

        available_count = _count_allocatable_in_dept(dept_name, matcher)

        before_remaining = remaining_qty

        if available_count >= remaining_qty:
            remaining_qty = 0
            status = "enough_here"
        else:
            remaining_qty -= available_count
            status = "not_enough"

        breakdown.append({
            "department": dept_name,
            "min_aging_days": sla_val,
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


def _determine_serial_reconfig_status(curr_ic, to_make, remarks, so_all_target_items):
    """Shared reconfig-detection logic.

    Used by both compute_sales_order_delivery_date() and
    _sales_order_has_reconfig_match() (called from CustomSalesOrder.on_submit())
    so the two never disagree about whether a matched serial needs reconfiguring.
    """
    remarks = remarks or ""
    if to_make and to_make != curr_ic:
        return True, f"Reconfig required: target '{to_make}', current '{curr_ic}'"
    if curr_ic not in so_all_target_items:
        target_display = to_make or (list(so_all_target_items)[0] if so_all_target_items else curr_ic)
        return True, f"Reconfig required: target '{target_display}', current '{curr_ic}'"
    if "Priority 2" in remarks or "Priority 3" in remarks or "Priority 4" in remarks or "Reconfig" in remarks or "(C2:" in remarks or "(C3:" in remarks or "(C4:" in remarks:
        if "Priority 2" in remarks or "(C2:" in remarks:
            return True, "Reconfig required (+2d); Matched via Shopify Variant ID"
        if "Priority 3" in remarks or "(C3:" in remarks:
            return True, "Reconfig required (+2d); Matched via Base Model & Processor"
        if "Priority 4" in remarks or "(C4:" in remarks:
            return True, "Reconfig required (+2d); Matched via Parent Shopify Variant ID"
        return True, "Reconfig required (+2d)"
    return False, "Exact item match"


def _get_so_all_target_items(so_name):
    so_direct_items = set(frappe.db.sql_list("""
        SELECT DISTINCT item_code FROM `tabSales Order Item` WHERE parent = %s
    """, so_name))
    bundle_items = set(frappe.db.sql_list("""
        SELECT DISTINCT pbi.item_code
        FROM `tabSales Order Item` soi
        INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = soi.item_code
        WHERE soi.parent = %s
    """, so_name))
    return so_direct_items | bundle_items


def _sales_order_has_reconfig_match(so_name):
    """True if any serial currently reserved for so_name needs reconfiguring.

    NOTE: this no longer feeds committed_delivery_date. The system does not move
    the customer promise or delivery_date under any circumstance - those are
    human-owned. The RECONFIG_SLA_DAYS cost is applied only inside
    compute_sales_order_delivery_date(), i.e. to estimated_delivery_date.
    Kept as a reporting/diagnostic helper.
    """
    reserved = frappe.db.sql("""
        SELECT sn.item_code, sn.to_make, sn.remarks
        FROM `tabSerial No` sn
        WHERE sn.reserved_sales_order = %s
    """, (so_name,), as_dict=True)
    if not reserved:
        return False

    so_all_target_items = _get_so_all_target_items(so_name)

    for s in reserved:
        is_reconfig, _ = _determine_serial_reconfig_status(
            s.get("item_code"), s.get("to_make"), s.get("remarks"), so_all_target_items
        )
        if is_reconfig:
            return True
    return False


def compute_sales_order_delivery_date(so_name, return_reason=False):
    """
    Calculate Delivery Date for a Sales Order based on allocated serials' department SLA.
    - Packing & Dispatch (Seq 20) -> SLA = 1 (curdate + 1).
    - Upstream department -> cumulative SLA from that department to Packing & Dispatch.
    - 10% buffer applied to cumulative SLA (rounded up).
    - If reconfigured item (Priority 2, 3, 4) -> adds RECONFIG_SLA_DAYS extra.
    - Updates individual Serial No.estimated_delivery_date for each reserved serial.
    - Multiple units -> takes the MAX SLA across units (bottleneck logic).
    - Returns target delivery date (and formatted explanatory reason if return_reason=True).
    """
    try:
        depts_data = frappe.db.sql("""
            SELECT name, department_sequence, department_sla, sla_item_groups
            FROM `tabDepartment`
            WHERE department_sequence > 0
            ORDER BY department_sequence ASC
        """, as_dict=True)

        if not depts_data:
            fallback_date = add_working_days(nowdate(), 1)
            reason = str(fallback_date)
            return (fallback_date, reason) if return_reason else fallback_date

        # Override in code: Packing & Dispatch = 1, Sales = 1, Inward = 45, intermediate depts capped at 15
        for d in depts_data:
            d_name = (d.get("name") or "").lower()
            if "packing & dispatch" in d_name or "sales" in d_name:
                d["department_sla"] = 1
            elif "inward" in d_name:
                d["department_sla"] = 45
            else:
                d["department_sla"] = min(max(int(d.get("department_sla") or 0), 0), 15)

        def _dept_sla(cand_dept_name, cand_dept_seq, item_grp=None, is_reconfig=False):
            if not cand_dept_name:
                return (1 + RECONFIG_SLA_DAYS) if is_reconfig else 1
            d_name_lower = (cand_dept_name or "").lower()
            if "packing & dispatch" in d_name_lower or "sales" in d_name_lower:
                return (1 + RECONFIG_SLA_DAYS) if is_reconfig else 1
            if "inward" in d_name_lower:
                return 45
            if not cand_dept_seq:
                # A recognized department but with no defined pipeline sequence
                # (e.g. a generic WIP/holding department, sequence 0) means we
                # don't actually know how close this unit is to being ready.
                # Treat it the same as Inward (worst case) rather than
                # ready-to-ship, so it doesn't get a falsely near-term ETA.
                return 45

            cand_sla = 0
            for d in depts_data:
                if d.get("name") == cand_dept_name:
                    cand_sla = d.get("department_sla", 0)
                    break

            app_depts = [d for d in depts_data if _is_dept_applicable(d, item_grp)]
            seq_max_sla = {}
            for d in app_depts:
                if "inward" in (d.get("name") or "").lower():
                    continue
                # Exception/holding departments are not part of every unit's route -
                # see _CONTINGENT_DEPT_MARKERS. The unit standing in one is still
                # charged that department's SLA below, via cand_sla.
                if _is_contingent_dept(d.get("name")):
                    continue
                seq = d.get("department_sequence")
                sla = d.get("department_sla") or 0
                if seq not in seq_max_sla or sla > seq_max_sla[seq]:
                    seq_max_sla[seq] = sla

            max_seq = max(seq_max_sla.keys()) if seq_max_sla else 1

            total = cand_sla
            for s in range(cand_dept_seq + 1, max_seq + 1):
                if s in seq_max_sla:
                    total += seq_max_sla[s]
            sla_with_buffer = min(math.ceil(total * 1.10), 45)
            if is_reconfig:
                sla_with_buffer = min(sla_with_buffer + RECONFIG_SLA_DAYS, 45)
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

        # How long each reserved serial has already been sitting in its current
        # department (working days, holiday-aware) — mirrors the exact method
        # stock_movement.py already uses for department SLA-violation checks
        # (same stock_enty_date_and_time field, same holiday list), so aging is
        # counted consistently everywhere in the system rather than introducing
        # a second, different definition of "how old is this unit here."
        dwell_days_by_serial = {}
        reserved_serial_names = [s.get("name") for s in reserved_serials if s.get("name")]
        if reserved_serial_names:
            from nj_features.nj_features.doctype.stock_movement.stock_movement import (
                DEPARTMENT_SLA_HOLIDAY_LIST,
            )
            placeholders = ", ".join(["%s"] * len(reserved_serial_names))
            dwell_rows = frappe.db.sql(
                f"""
                SELECT
                    sn.name AS serial_no,
                    GREATEST(
                        TIMESTAMPDIFF(
                            DAY,
                            sn.stock_enty_date_and_time,
                            DATE_ADD(NOW(), INTERVAL 330 MINUTE)
                        ) - COUNT(DISTINCT holiday.holiday_date),
                        0
                    ) AS dwell_days
                FROM `tabSerial No` sn
                LEFT JOIN `tabHoliday` holiday
                    ON holiday.parent = %s
                    AND holiday.holiday_date > DATE(sn.stock_enty_date_and_time)
                    AND holiday.holiday_date <= CURDATE()
                WHERE sn.name IN ({placeholders})
                  AND sn.stock_enty_date_and_time IS NOT NULL
                GROUP BY sn.name, sn.stock_enty_date_and_time
                """,
                tuple([DEPARTMENT_SLA_HOLIDAY_LIST] + reserved_serial_names),
                as_dict=True,
            )
            dwell_days_by_serial = {r["serial_no"]: int(r["dwell_days"] or 0) for r in dwell_rows}

        # Get direct and bundle item codes for this SO
        so_all_target_items = _get_so_all_target_items(so_name)

        has_serial_eta_col = frappe.db.has_column("Serial No", "estimated_delivery_date")
        has_child_table = frappe.db.table_exists("Estimated Delivery Date Details")

        # Determine total pending serialized units for this Sales Order.
        #
        # "Needs a serial allocated" must mean the SAME thing here as it does in
        # assign_serials(), which only ever allocates item groups in
        # HARDWARE_ITEM_GROUPS. Counting every has_serial_no=1 item instead meant
        # serialised spare parts (Laptop RAM, BATTERY, KEYBOARD, Display,
        # MOTHERBOARD, ...) were counted as pending forever - allocation can never
        # satisfy them - so missing_units stayed > 0 and pinned the order's ETA to
        # the 45-day shortage SLA permanently.
        hardware_group_placeholders = ', '.join(['%s'] * len(HARDWARE_ITEM_GROUPS))
        hardware_groups = list(HARDWARE_ITEM_GROUPS)

        total_pending_serialized_qty = 0
        try:
            direct_pending = frappe.db.sql(f"""
                SELECT SUM(GREATEST(0, soi.qty - COALESCE(soi.delivered_qty, 0)))
                FROM `tabSales Order Item` soi
                INNER JOIN `tabItem` i ON i.item_code = soi.item_code
                WHERE soi.parent = %s AND i.has_serial_no = 1
                  AND i.item_group IN ({hardware_group_placeholders})
            """, tuple([so_name] + hardware_groups))[0][0] or 0
            total_pending_serialized_qty += direct_pending

            bundle_parents = frappe.db.sql("""
                SELECT soi.item_code, GREATEST(0, soi.qty - COALESCE(soi.delivered_qty, 0)) AS pending_qty
                FROM `tabSales Order Item` soi
                INNER JOIN `tabItem` i ON i.item_code = soi.item_code
                WHERE soi.parent = %s AND i.has_serial_no = 0 AND EXISTS (
                    SELECT 1 FROM `tabProduct Bundle` pb WHERE pb.name = soi.item_code
                )
            """, (so_name,), as_dict=True)

            for bp in bundle_parents:
                b_items = frappe.db.sql(f"""
                    SELECT SUM(pbi.qty * %s)
                    FROM `tabProduct Bundle Item` pbi
                    INNER JOIN `tabItem` i ON i.item_code = pbi.item_code
                    WHERE pbi.parent = %s AND i.has_serial_no = 1
                      AND i.item_group IN ({hardware_group_placeholders})
                """, tuple([bp.pending_qty, bp.item_code] + hardware_groups))[0][0] or 0
                total_pending_serialized_qty += b_items
            total_pending_serialized_qty = int(total_pending_serialized_qty)
        except Exception:
            total_pending_serialized_qty = len(reserved_serials)

        so_req_date = (
            frappe.db.get_value("Sales Order", so_name, "committed_delivery_date")
            or frappe.db.get_value("Sales Order", so_name, "delivery_date")
        )

        if reserved_serials:
            sla_list = []
            child_rows = []

            for s in reserved_serials:
                curr_ic = s.get("item_code")
                to_make = s.get("to_make")
                remarks = s.get("remarks") or ""
                item_grp = s.get("item_group")
                dept_name = s.get("dept_name") or "Unknown"
                # Only coerce a genuinely missing sequence to 1 (earliest/safest
                # assumption) - a real 0 (e.g. a generic WIP/holding department
                # that isn't part of the defined pipeline) must reach _dept_sla()
                # as-is so it gets treated as worst-case, not as position 1.
                dept_seq = s.get("department_sequence")
                if dept_seq is None:
                    dept_seq = 1

                # Check if exact match or reconfigured
                is_reconfig, match_desc = _determine_serial_reconfig_status(
                    curr_ic, to_make, remarks, so_all_target_items
                )

                sn_sla_full = _dept_sla(dept_name, dept_seq, item_grp=item_grp, is_reconfig=is_reconfig)
                dwell_days = dwell_days_by_serial.get(s.get("name"), 0)
                sn_sla = max(0, sn_sla_full - dwell_days)
                sn_est_date = add_working_days(nowdate(), sn_sla)
                sla_list.append(sn_sla)

                reconfig_tag = f" [Reconfig +{RECONFIG_SLA_DAYS}d]" if is_reconfig else ""
                day_unit = "day" if sn_sla == 1 else "days"
                aging_note = f", present {dwell_days}d of {sn_sla_full}d SLA" if dwell_days > 0 else ""

                # Standard format for Serial No: YYYY-MM-DD | Department: <dept> (SLA: <N> days)
                sn_reason_str = f"{sn_est_date} | Department: {dept_name} (SLA: {sn_sla} {day_unit}{aging_note}){reconfig_tag}"
                if len(sn_reason_str) > 250:
                    sn_reason_str = sn_reason_str[:247] + "..."

                # Update individual Serial No's estimated_delivery_date
                if has_serial_eta_col:
                    frappe.db.set_value("Serial No", s.get("name"), "estimated_delivery_date", sn_reason_str, update_modified=False)

                # Format human-readable remarks for child table
                if dwell_days > 0:
                    aging_detail = f"; Received in {dept_name} {dwell_days} working day{'s' if dwell_days != 1 else ''} ago, {sn_sla} of {sn_sla_full}d SLA remaining"
                else:
                    aging_detail = ""

                if "packing & dispatch" in dept_name.lower():
                    if is_reconfig:
                        detail_remarks = f"Stock in Packing & Dispatch [Reconfiguration: +{RECONFIG_SLA_DAYS} days, Total SLA: {sn_sla} {day_unit}; {match_desc}{aging_detail}]"
                    else:
                        detail_remarks = f"Ready stock in Packing & Dispatch (Exact item match, SLA: {sn_sla} {day_unit}{aging_detail})"
                else:
                    if is_reconfig:
                        detail_remarks = f"Allocated from {dept_name} [Reconfiguration: +{RECONFIG_SLA_DAYS} days, Total SLA: {sn_sla} {day_unit}; {match_desc}{aging_detail}]"
                    else:
                        detail_remarks = f"Allocated from {dept_name} [Exact item match, Total SLA: {sn_sla} {day_unit}{aging_detail}]"

                child_rows.append({
                    "serial_no": s.get("name"),
                    "item_code": to_make or curr_ic,
                    "department": dept_name,
                    "estimated_delivery_date": sn_est_date,
                    "requested_delivery_date": so_req_date,
                    "remarks": detail_remarks
                })

            # If partially allocated, missing units require Inward / procurement SLA (45 working days)
            missing_units = max(0, total_pending_serialized_qty - len(reserved_serials))
            if missing_units > 0:
                unalloc_sla = 45
                sla_list.append(unalloc_sla)

            # Populate child table tabEstimated Delivery Date Details for allocated serials
            if has_child_table:
                frappe.db.sql("DELETE FROM `tabEstimated Delivery Date Details` WHERE parent = %s", so_name)
                for idx, r in enumerate(child_rows, 1):
                    frappe.db.sql("""
                        INSERT INTO `tabEstimated Delivery Date Details`
                        (name, creation, modified, modified_by, owner, docstatus, parent, parentfield, parenttype, idx, serial_no, item_code, department, estimated_delivery_date, requested_delivery_date, remarks)
                        VALUES (%s, NOW(), NOW(), 'Administrator', 'Administrator', 0, %s, 'estimated_delivery_date_details', 'Sales Order', %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        frappe.generate_hash(length=10),
                        so_name,
                        idx,
                        r["serial_no"],
                        r["item_code"],
                        r["department"],
                        r["estimated_delivery_date"],
                        r["requested_delivery_date"],
                        r["remarks"]
                    ))

            # Maximum Estimated delivery date takes MAX SLA (bottleneck across all units)
            max_sla = max(sla_list) if sla_list else 45
            max_est_date = add_working_days(nowdate(), max_sla)

            return (max_est_date, str(max_est_date)) if return_reason else max_est_date

        if has_child_table:
            frappe.db.sql("DELETE FROM `tabEstimated Delivery Date Details` WHERE parent = %s", so_name)

        # No reserved serials AND nothing on this order that allocation would ever
        # reserve one for (services, accessories, non-hardware item groups) means
        # there is no stock shortage to price in - the 45-day procurement SLA below
        # is about waiting for a machine to come through the pipeline, and this
        # order isn't waiting for one. Quoting ~45 working days on a pure service
        # order is simply wrong, so use the standard dispatch turnaround instead.
        if not total_pending_serialized_qty:
            no_stock_dependency_date = add_working_days(nowdate(), 1)
            return (
                (no_stock_dependency_date, str(no_stock_dependency_date))
                if return_reason else no_stock_dependency_date
            )

        # Fallback: check tabSO Quantity Check SLA for items in this SO, default 45 working days
        max_sla = 45
        if so_all_target_items:
            soqc_slas = frappe.db.sql_list("""
                SELECT sla FROM `tabSO Quantity Check` WHERE item_code IN %s AND sla > 0
            """, (tuple(so_all_target_items),))
            if soqc_slas:
                max_sla = max(soqc_slas)

        max_est_date = add_working_days(nowdate(), max_sla)
        return (max_est_date, str(max_est_date)) if return_reason else max_est_date

    except Exception:
        frappe.log_error(title=f"compute_sales_order_delivery_date failed for {so_name}", message=frappe.get_traceback())
        fallback_date = add_working_days(nowdate(), 45)
        return (fallback_date, str(fallback_date)) if return_reason else fallback_date


def update_sales_order_etas(so_eta_map, so_breakdown_map=None, do_commit=True, allow_reallocation=False):
    """Update eta_for_dispatch, estimated_delivery_date and breakdown text on Sales Orders.
    delivery_date and committed_delivery_date remain locked to the initial customer promise date.

    allow_reallocation: only True for the once-a-day midnight reallocation run
    (see run_daily_eta_drift_reallocation). The hourly ETA-refresh pass must
    never trigger a reallocation itself - an already-allocated serial's
    reservation/to_make must not change outside that one daily check.
    """
    breakdown_fieldname = get_eta_breakdown_fieldname()
    has_eta_date_col = frappe.db.has_column("Sales Order", "estimated_delivery_date")

    for so_name, eta in so_eta_map.items():
        update_values = {}
        calc_res = compute_sales_order_delivery_date(so_name, return_reason=True)
        if isinstance(calc_res, (list, tuple)):
            calc_delivery_date, reason_text = calc_res
        else:
            calc_delivery_date, reason_text = calc_res, str(calc_res)

        old_est_dd = frappe.db.get_value("Sales Order", so_name, "estimated_delivery_date")

        # This job updates the ESTIMATE and nothing else. The only fields it writes are
        # estimated_delivery_date, eta_for_dispatch and the ETA breakdown text.
        # delivery_date and committed_delivery_date are never written here - not to
        # change them, and not to fill them in.

        if eta is None:
            update_values["eta_for_dispatch"] = "45"
            if has_eta_date_col:
                update_values["estimated_delivery_date"] = str(calc_delivery_date) if calc_delivery_date else None
        else:
            try:
                eta_days = int(eta) if eta is not None else 45
            except (ValueError, TypeError):
                eta_days = 45

            update_values["eta_for_dispatch"] = eta
            if has_eta_date_col:
                update_values["estimated_delivery_date"] = str(calc_delivery_date) if calc_delivery_date else None

        if so_breakdown_map and breakdown_fieldname:
            update_values[breakdown_fieldname] = "\n\n".join(
                so_breakdown_map.get(so_name, [])
            )

        if frappe.db.has_column("Sales Order", "committed_delivery_date"):
            # Read only - used for the drift check below. This job no longer stamps a
            # promise onto an order that never had one: reconstructing a customer
            # promise after the fact (transaction_date + 4d) invents history, and once
            # written nothing could ever correct it. An order with no committed date
            # falls back to its delivery_date wherever that value is read
            # (see get_open_sales_orders), and orders submitted from now on get their
            # promise recorded once, in CustomSalesOrder.on_submit().
            target_committed = frappe.db.get_value(
                "Sales Order", so_name, "committed_delivery_date"
            )

            # Drift check. An order whose estimate has pulled more than 2 days away
            # from the promise is at risk, and that is worth recording - but it is
            # NOT a reason to take its machine away. Drift is reported; the
            # reservation is left alone (see AUTO_UPGRADE_RESERVATIONS).
            if allow_reallocation and calc_delivery_date and target_committed:
                drift_days = abs((getdate(calc_delivery_date) - getdate(target_committed)).days)
                if drift_days > 2:
                    if AUTO_UPGRADE_RESERVATIONS:
                        frappe.enqueue(
                            "nj_features.services.reservation_service.upgrade_order_reservations",
                            queue="short",
                            enqueue_after_commit=True,
                            so_name=so_name,
                        )
                    logger.info(
                        f"[ETA_DRIFT] {so_name}: estimated={calc_delivery_date} "
                        f"committed={target_committed} drift={drift_days}d "
                        f"(reservation kept; swap={'on' if AUTO_UPGRADE_RESERVATIONS else 'off'})"
                    )

        frappe.db.set_value(
            "Sales Order",
            so_name,
            update_values,
            update_modified=False
        )

        if reason_text and reason_text != "No Stock" and str(old_est_dd) != str(reason_text):
            frappe.enqueue(
                "nj_features.overrides.sales_order.push_delivery_date_to_shopify_order",
                queue="short",
                enqueue_after_commit=True,
                so_name=so_name,
                delivery_date=str(reason_text),
            )

    if do_commit:
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
