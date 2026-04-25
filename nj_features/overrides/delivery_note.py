# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import json
import frappe
import base64
import requests
import traceback
import time
from frappe.utils import (
    flt, getdate, cint,add_days, nowdate, getdate
)
import math
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from frappe import _
from frappe.utils import now
from contextlib import contextmanager
#from __future__ import unicode_literals
from datetime import datetime, timedelta
from frappe.utils import now_datetime, get_datetime
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error
from nj_lib.utils.common_utils import get_latest_item_wizard
from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote
from nj_features.nj_features.api.shiprocket_api import get_auth_token,generate_awb,generate_label
from erpnext.controllers.status_updater import OverAllowanceError

# from nj_features.nj_features.api.shiprocket_api import generate_awb,check_courie_service , generate_label

SHOPIFY_URL = "https://newjaisa.myshopify.com/admin/api/2025-01/orders.json?name=" 
TOKEN = "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"
FULLFILMENT_ORDER_ID = "https://newjaisa.myshopify.com/admin/api/2025-01/orders/{shopify_order_id}/fulfillment_orders.json"
MAKE_FULLFILMENT = "https://newjaisa.myshopify.com/admin/api/2025-01/fulfillments.json"


logger = frappe.logger("deliverynotetimelog", allow_site=1, file_count=1)

@contextmanager
def log_time(label, docname=None):
    """Context manager to log execution time of code blocks."""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        prefix = f"[DN: {docname}] " if docname else ""
        logger.debug(f"{prefix}{label} took {duration:.4f} seconds")


class CustomDeliveryNote(DeliveryNote):
    def validate(self):
        super().validate()
        self.validate_is_service_serials()
        self.apply_patch()
        

    def validate_is_service_serials(self):
        is_service_flags = frappe.db.get_value(
            "NJ Settings",
            {"parameter": "is_service_flag"},
            "value"
        )
        if not self.cint_safe(is_service_flags):
            return

        all_serial_nos = []

        # Main items table
        for row in self.get("items") or []:
            row_serial_no = row.get("serial_no")
            if row_serial_no:
                all_serial_nos.extend(self.get_serial_list(row_serial_no))

        # Packed items table
        for row in self.get("packed_items") or []:
            row_serial_no = row.get("serial_no")
            if row_serial_no:
                all_serial_nos.extend(self.get_serial_list(row_serial_no))

        all_serial_nos = self.unique_list(all_serial_nos)

        if not all_serial_nos:
            return

        blocked_serials = frappe.get_all(
            "Serial No",
            filters={
                "name": ["in", all_serial_nos],
                "is_service": 1
            },
            pluck="name"
        )

        if blocked_serials:
            frappe.throw(
                _(
                    "The following Serial Nos are marked as Service, so this Delivery Note cannot be saved:<br><br>{0}"
                ).format("<br>".join(blocked_serials))
            )

    def get_serial_list(self, serial_value):
        if not serial_value:
            return []

        if not isinstance(serial_value, str):
            serial_value = str(serial_value)

        serial_value = serial_value.replace("\r", "\n")
        out = []

        for line in serial_value.split("\n"):
            line = (line or "").strip()
            if not line:
                continue

            for serial_no in line.split(","):
                serial_no = (serial_no or "").strip()
                if serial_no:
                    out.append(serial_no)

        return out

    def unique_list(self, values):
        seen = set()
        result = []

        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)

        return result

    def cint_safe(self, value):
        try:
            return int(value)
        except Exception:
            return 0

    def apply_patch(self):
        import erpnext.controllers.status_updater as status_updater
        status_updater.StatusUpdater.limits_crossed_error = custome_limits_crossed_error
        # print("\n=== Monkey Patch Applied: =============================limits_crossed_error overridden ===\n")

    def on_submit(self):
        total_start = time.perf_counter()
        logger.debug(f"[DN: {self.name}] on_submit started")
        try:
            # ------------------------------------------------------------------
            # Base on_submit
            # ------------------------------------------------------------------
            with log_time("super().on_submit()", self.name):
                super().on_submit()

            # ------------------------------------------------------------------
            # Get against_sales_order
            # ------------------------------------------------------------------
            with log_time("get against_sales_order", self.name):
                against_sales_order = frappe.get_value(
                    "Delivery Note Item",
                    {"parent": self.name},
                    "against_sales_order",
                )

            # ------------------------------------------------------------------
            # Basic validations
            # ------------------------------------------------------------------
            with log_time("tracking_id_validation", self.name):
                if not self.tracking_id:
                    frappe.throw("Tracking ID is mandatory or fill it any  other value ")

            # ------------------------------------------------------------------
            # Early return for Snapmint orders (if you re-enable this block)
            # ------------------------------------------------------------------
            # with log_time("Snapmint early-return block", self.name):
            #     if against_sales_order and against_sales_order.startswith("SO-Snapmint-"):
            #         self.rto_charges_update()
            #         self.fetching_tracking_details()
            #         # self.set_cit_image_from_sales_order()
            #         self.update_details_to_delivery_charege_doc()
            #         qi_mandatory_checks_on_dn_submit(self, method=None)
            #         # self.qc_nj_of_days_checking()
            #         if self.is_return == 0:
            #             send_sales_invoice_email_on_delivery_note(self, method=None)
            #
            #         if not self.is_return:
            #             self._process_customer_details()
            #         logger.debug(f"[DN: {self.name}] Snapmint early-return executed")
            #         total_duration = time.perf_counter() - total_start
            #         logger.debug(f"[DN: {self.name}] on_submit total time: {total_duration:.4f} seconds")
            #         return

            # ------------------------------------------------------------------
            # For non-Snapmint orders, proceed with normal flow
            #   - Fetch Shopify / order IDs
            # ------------------------------------------------------------------
            if self.tracking_id!="Deduction":
                with log_time("fetch shopify/order ids", self.name):
                    raw_order_id = frappe.get_value(
                        "Sales Order",
                        {"name": against_sales_order},
                        "shopify_order_id",
                    )
                    shopify_order_no = frappe.get_value(
                        "Sales Order",
                        {"name": against_sales_order},
                        "shopify_order_number",
                    )

                    order_id = None
                    if raw_order_id and len(raw_order_id.lstrip("#")) < 7:
                        order_id = raw_order_id.lstrip("#")
                    else:
                        raw_order_id = frappe.get_value(
                            "Sales Order",
                            {"name": against_sales_order},
                            "order_id",
                        )
                        if raw_order_id:
                            order_id = raw_order_id.lstrip("#")
                        else:
                            raw_order_id = frappe.get_value(
                                "Sales Order",
                                {"name": against_sales_order},
                                "shopify_order_number",
                            )
                            if raw_order_id:
                                order_id = raw_order_id.lstrip("#")

                    logger.debug(
                        f"[DN: {self.name}] Resolved order_id={order_id}, "
                        f"raw_order_id={raw_order_id}, shopify_order_no={shopify_order_no}"
                    )

            # ------------------------------------------------------------------
            # Trigger fulfillment conditionally
            # ------------------------------------------------------------------
                if order_id and self.is_return == 0:
                    with log_time("fetch Sales Order details (order_type, sale_type)", self.name):
                        order_details = frappe.db.sql(
                            """
                            SELECT so.order_type, so.sale_type
                            FROM `tabSales Order` so
                            JOIN `tabDelivery Note Item` dni
                                ON dni.against_sales_order = so.name
                            WHERE dni.parent = %s AND so.docstatus = 1
                            LIMIT 1
                            """,
                            (self.name,),
                            as_dict=True,
                        )

                    if order_details:
                        order_type = order_details[0].get("order_type")
                        sale_type = order_details[0].get("sale_type")
                        logger.debug(
                            f"[DN: {self.name}] Order Type: {order_type}, "
                            f"Sale Type: {sale_type}"
                        )
                        order_type = order_details[0].get("order_type")
                        # print(f"Order Type: {order_type}")
                        sale_type = order_details[0].get("sale_type")
                        # print(f"Sale Type: {sale_type}")

                        # Only trigger fulfillment if conditions are met
                        if order_type == "Sales" and sale_type == "NJ-Website-B2C":
                            trigger_fulfillment(order_id, raw_order_id, shopify_order_no, self.name)
                        else:
                            print(
                                f"Skipping fulfillment trigger for DN {self.name} - "
                                f"Order Type: {order_type}, Sale Type: {sale_type}"
                            )

                        # Only trigger fulfillment if conditions are met
                        if order_type == "Sales" and sale_type == "NJ-Website-B2C":
                            with log_time("trigger_fulfillment", self.name):
                                logger.debug(
                                    f"[DN: {self.name}] Triggering fulfillment "
                                    f"for order_id={order_id}"
                                )
                                trigger_fulfillment(
                                    order_id,
                                    raw_order_id,
                                    shopify_order_no,
                                    self.name,
                                )
                        else:
                            logger.debug(
                                f"[DN: {self.name}] Skipping fulfillment trigger - "
                                f"Order Type: {order_type}, Sale Type: {sale_type}"
                            )
                    else:
                        # print(f"No Sales Order found for DN {self.name}")
                        logger.debug(
                            f"[DN: {self.name}] No Sales Order found for DN {self.name}"
                        )

                # self.delete_department_history()
                # self.approve_unchecking_for_cod_orders()
                # self.return_dn_validation()
                # self.couse_of_return_validation()
                # # self.payment_validattion()
                # self.update_mail_from_address()
                # self.rto_charges_update()
                # self.approve_validation()
                # self.set_cit_image_from_sales_order()
                # self.fetching_tracking_details()

                # ------------------------------------------------------------------
                # Other operations (each timed)
                # ------------------------------------------------------------------
                   
                # self.validate_dn_vs_si()

                with log_time("delete_department_history", self.name):
                    self.delete_department_history()

                with log_time("approve_unchecking_for_cod_orders", self.name):
                    self.approve_unchecking_for_cod_orders()

                with log_time("return_dn_validation", self.name):
                    self.return_dn_validation()

                with log_time("couse_of_return_validation", self.name):
                    self.couse_of_return_validation()

                # with log_time("payment_validattion", self.name):
                #     self.payment_validattion()

                with log_time("update_mail_from_address", self.name):
                    self.update_mail_from_address()

                with log_time("rto_charges_update", self.name):
                    self.rto_charges_update()

                with log_time("approve_validation", self.name):
                    self.approve_validation()

                # with log_time("set_cit_image_from_sales_order", self.name):
                #     self.set_cit_image_from_sales_order()

                # with log_time("fetching_tracking_details", self.name):
                #     self.fetching_tracking_details()

                with log_time("update_details_to_delivery_charege_doc", self.name):
                    self.update_details_to_delivery_charege_doc()

                # with log_time("qi_mandatory_checks_on_dn_submit", self.name):
                #     qi_mandatory_checks_on_dn_submit(self)

                # with log_time("qc_nj_of_days_checking", self.name):
                #     self.qc_nj_of_days_checking()

                # ------------------------------------------------------------------
                # Post-processing based on return/non-return
                # ------------------------------------------------------------------
                if self.is_return == 0:
                    with log_time("_process_customer_details", self.name):
                        # send_sales_invoice_email_on_delivery_note(self, method=None)
                        self._process_customer_details()
                else:
                    with log_time("_process_serial_numbers", self.name):
                        self._process_serial_numbers()

                # ------------------------------------------------------------------
                # Total timing
                # ------------------------------------------------------------------
                total_duration = time.perf_counter() - total_start
                logger.debug(
                    f"[DN: {self.name}] on_submit total time: {total_duration:.4f} seconds"
                )

        except Exception as e:
            frappe.db.rollback()
            tb = traceback.format_exc()
            # Log to custom timing logger as well
            logger.error(
                f"[DN: {self.name}] Error in on_submit: {e}\n{tb}"
            )
            # Existing error logger hook
            log_error(tb, "Error in on_submit")
            # Raise a clean error message to user
            frappe.throw(f"Error in on_submit: {frappe.as_unicode(e)}")



    def _process_customer_details(self):
        try:
            serial_nos = set()
            dn_items = frappe.db.sql("""
                SELECT serial_no FROM `tabDelivery Note Item` WHERE parent = %s
                UNION
                SELECT serial_no FROM `tabPacked Item` WHERE parent = %s
            """, (self.name, self.name), as_dict=True)
            for row in dn_items:
                if row.serial_no:
                    serial_nos.update([s.strip() for s in row.serial_no.split(',') if s.strip()])
            for sn in serial_nos:
                frappe.db.set_value("Serial No", sn, {
                    "is_replace": 0,
                    "return_reason": ""
                })

            sales_order_info_map = {}

            for item in self.get('items', []):
                if not item.against_sales_order:
                    frappe.throw(f"Missing Sales Order reference for item: {item.item_code}")

                if item.against_sales_order not in sales_order_info_map:
                    sales_order_data = frappe.db.sql("""
                        SELECT 
                            TRIM(so.customer_name) AS customer,
                            TRIM(so.name) AS name,
                            TRIM(so.sale_type) AS sale_type,
                            TRIM(COALESCE(so.amazon_order_id, so.order_id, so.shopify_order_id)) AS order_id, 
                            so.transaction_date, 
                            so.delivery_date, 
                            TRIM(so.sales_channel) AS sales_channel,
                            TRIM(COALESCE(addr_ship.email_id, addr_cust.email_id, '')) AS email_id,
                            TRIM(COALESCE(addr_ship.phone, addr_cust.phone, '')) AS phone,
                            TRIM(IFNULL(so.shipping_address, so.address_display)) AS so_address
                        FROM `tabSales Order` so
                        LEFT JOIN `tabAddress` addr_ship ON addr_ship.name = so.shipping_address_name
                        LEFT JOIN `tabAddress` addr_cust ON addr_cust.name = so.customer_address
                        WHERE so.name = %s AND so.docstatus = 1 LIMIT 1
                    """, (item.against_sales_order,), as_dict=True)
                    if not sales_order_data:
                        frappe.throw(f"No Sales Order data found for {item.against_sales_order}")

                    sales_order_info_map[item.item_code] = {
                        "sales_order": item.against_sales_order,
                        "info": sales_order_data[0]
                    }

            def process_serials(item, child_table="Delivery Note Item"):
                serial_no = item.serial_no.strip() if item.serial_no else ""
                if not serial_no:
                    return

                serial_list = serial_no.split('\n')

                if child_table == "Packed Item":
                    order_entry = sales_order_info_map.get(item.parent_item)
                else:
                    order_entry = sales_order_info_map.get(item.item_code)

                if not order_entry:
                    frappe.throw(f"Cannot find Sales Order info for item: {item.item_code}")

                sales_order_info = order_entry["info"]

                for serial in serial_list:
                    serial = serial.strip()
                    if not serial:
                        continue

                    try:
                        serial_no_doc = frappe.get_doc('Serial No', serial, for_update=True)
                    except frappe.DoesNotExistError:
                        frappe.throw(f"Serial No {serial} not found in the system")
                    serial_no_doc.customer = sales_order_info.get("customer_name", "")
                    serial_no_doc.customer_name = sales_order_info.get("customer_name", "")
                    serial_no_doc.first_name = sales_order_info.get("customer_name", "")
                    serial_no_doc.sales_order_id = sales_order_info.get("name", "")
                    serial_no_doc.order_id = sales_order_info.get("order_id", "")
                    serial_no_doc.order_date = sales_order_info.get("transaction_date")
                    serial_no_doc.shipped_date = self.get("posting_date")
                    serial_no_doc.tracking_id = self.get("tracking_id")
                    serial_no_doc.courier_name = self.get("courier_service")
                    serial_no_doc.deliver_date = sales_order_info.get("delivery_date")
                    serial_no_doc.sales_channel = sales_order_info.get("sales_channel", "")
                    serial_no_doc.sale_type = sales_order_info.get("sale_type", "")
                    phone = sales_order_info.get("phone", "")
                    serial_no_doc.mobile_no = "" if phone.lower() == "na" else phone
                    serial_no_doc.email_id = sales_order_info.get("email_id", "")
                    serial_no_doc.address = sales_order_info.get("so_address", "")
                    serial_no_doc.warranty_start_date_ = self.get("posting_date")
                    serial_no_doc.reserved_sales_order = ""
                    serial_no_doc.return_reason = ""
                    serial_no_doc.is_replace = 0

                    posting_date_raw = self.get("posting_date")
                    if isinstance(posting_date_raw, str):
                        end_date = datetime.strptime(posting_date_raw, "%Y-%m-%d")
                    else:
                        end_date = posting_date_raw

                    serial_no_doc.end_date = end_date + timedelta(days=365)
                    # serial_no_doc.modified = now()

                    try:
                        serial_no_doc.save()
                    except Exception as e:
                        log_error(traceback.format_exc(), "Error in saving serial_no_doc")
                        frappe.throw("Error while updating Serial No", str(e))

            for item in self.get('items', []):
                process_serials(item)

            for item in self.get('packed_items', []):
                process_serials(item, "Packed Item")

        except Exception as e:
            log_error(traceback.format_exc(), "Error in _process_customer_details")
            frappe.throw(f"Error in _process_customer_details: {str(e)}")
    


    def validate_dn_vs_si(self):
        print("inside the function=================")

        # ✅ Skip for Return DN
        if self.is_return:
            print("Skipping validation for Return DN")
            return

        if not self.name:
            return

        # 🔹 Fetch SI from DB
        sales_invoices = frappe.db.get_all(
            "Delivery Note Item",
            filters={"parent": self.name},
            pluck="against_sales_invoice"
        )

        # Remove empty values
        sales_invoices = list(set([si for si in sales_invoices if si]))

        print("sales_invoices=================", sales_invoices)

        if not sales_invoices:
            frappe.throw(_("No Sales Invoice linked in Delivery Note Items"))

        if len(sales_invoices) > 1:
            frappe.throw(_("Multiple Sales Invoices linked. Not allowed."))

        sales_invoice = sales_invoices[0]

        # 🔹 Fetch SI Grand Total
        si_grand_total = frappe.db.get_value(
            "Sales Invoice",
            sales_invoice,
            "grand_total"
        ) or 0

        dn_grand_total = self.grand_total or 0

        print("SI Total=================", si_grand_total)
        print("DN Total=================", dn_grand_total)

        # 🔹 Compare totals
        if abs(si_grand_total - dn_grand_total) > 0.01:
            frappe.throw(_(
                f"""Grand Total mismatch!

    Sales Invoice: {sales_invoice} → {si_grand_total}
    Delivery Note: {dn_grand_total}

    Submission blocked."""
            ))
    def approve_unchecking_for_cod_orders(self):
        if self.is_store_pick_up != 1:
            return
        against_sales_order = frappe.get_value(
            "Delivery Note Item", {"parent": self.name}, "against_sales_order"
        )
        if not against_sales_order:
            return

        sales_order = frappe.get_doc("Sales Order", against_sales_order)
        if sales_order.is_cod != 1:
            return

        against_sales_invoice = frappe.get_value(
            "Delivery Note Item", {"parent": self.name}, "against_sales_invoice"
        )
        if not against_sales_invoice:
            return

        sales_invoice = frappe.get_doc("Sales Invoice", against_sales_invoice)
        if sales_invoice.approved == 1:
            sales_invoice.approved = 0
            sales_invoice.save(ignore_permissions=True)
            frappe.msgprint(f"This is an COD Order Please collect the remaining amount from Sales Invoice {sales_invoice.name} approve button is unchecked.")

    def return_dn_validation(self):
        if self.is_return == 1:
            forward_dn = frappe.db.get_value(
                "Delivery Note",
                self.return_against,
                ["grand_total", "total_taxes_and_charges"],
                as_dict=True
            )
            if not forward_dn:
                frappe.throw(_("Forward Delivery Note not found"))

            return_grand_total = abs(self.grand_total)
            return_taxes = abs(self.total_taxes_and_charges)

            if return_grand_total > forward_dn.grand_total:
                frappe.throw(
                    _(f"Return DN grand total {return_grand_total} is greater than "
                    f"the forward DN grand total {forward_dn.grand_total}")
                )

            if return_taxes > forward_dn.total_taxes_and_charges:
                frappe.throw(
                    _(f"Return DN taxes {return_taxes} are greater than "
                    f"the forward DN taxes {forward_dn.total_taxes_and_charges}")
                )
    def couse_of_return_validation(self):
        if not self.is_return:
            return

        against_sales_order = frappe.db.get_value(
            "Delivery Note Item", {"parent": self.name}, "against_sales_order"
        )
        if not against_sales_order:
            frappe.throw("No sales order found for this Delivery Note.")

        couse_of_return_values = frappe.db.get_value(
            "NJ Settings", {"parameter": "couse_of_returns"}, "value"
        )
        if not couse_of_return_values:
            return

        allowed_item_groups = [group.strip() for group in couse_of_return_values.split(",")]

        if self.cause_of_return and self.cause_of_return in allowed_item_groups:
            so_doc = frappe.get_doc("Sales Order", against_sales_order)
            if so_doc.is_cod and so_doc.payment_received:
                so_doc.payment_received = 0
                so_doc.save(ignore_permissions=True)
                
                frappe.msgprint(f"Payment Received unchecked in Sales Order {against_sales_order}.")

    def approve_validation(self):
        if self.is_return == 1:
            return
        against_sales_order = frappe.get_value("Delivery Note Item", {"parent": self.name}, "against_sales_order")
        if not against_sales_order:
            frappe.throw("No sales order found for this sales invoice.")

        query = """
            SELECT 
                dn.name AS delivery_note, 
                so.approve 
            FROM `tabDelivery Note` dn 
            INNER JOIN `tabDelivery Note Item` dni     
                ON dn.name = dni.parent 
            INNER JOIN `tabSales Order` so
                ON dni.against_sales_order = so.name 
            WHERE so.name = %s AND so.docstatus = 1
        """
        results = frappe.db.sql(query, (against_sales_order,), as_dict=True)        
        for row in results:        
            if not row.approve or int(row.approve) != 1:
                frappe.throw(f"Sales Order {against_sales_order} is not approved. Please approve it first.")
    def delete_department_history(self):
        if not self.is_return:
            return
        # Loop through each Delivery Note Item
        for item in self.items:
            if not item.serial_no:
                continue

            serial_nos = [s.strip() for s in item.serial_no.split("\n") if s.strip()]

            for serial_no in serial_nos:
                if frappe.db.exists("Serial No", serial_no):
                    serial_doc = frappe.get_doc("Serial No", serial_no)

                    # Delete all Department History rows
                    if serial_doc.get("department_history"):
                        serial_doc.department_history = []
                        serial_doc.save(ignore_permissions=True)
                        # frappe.db.commit()
    def _process_serial_numbers(self):
        sn_is_replace = 0
        sn_update = self.cause_of_return or ""

        if self.replacement_serial_no:
            sn_is_replace = 1

        serial_nos = set()

        dn_items = frappe.db.sql("""
            SELECT serial_no FROM `tabDelivery Note Item` WHERE parent = %s
            UNION
            SELECT serial_no FROM `tabPacked Item` WHERE parent = %s
        """, (self.name, self.name), as_dict=True)

        for row in dn_items:
            if row.serial_no:
                row_serials = str(row.serial_no).replace(",", "\n").split("\n")
                serial_nos.update([s.strip() for s in row_serials if s.strip()])

        for sn in serial_nos:
            frappe.db.set_value(
                "Serial No",
                sn,
                "return_reason",
                sn_update,
                update_modified=False
            )

        if self.replacement_serial_no:
            frappe.db.set_value(
                "Serial No",
                self.replacement_serial_no,
                "is_replace",
                sn_is_replace,
                update_modified=False
            )

        expense_account = frappe.db.get_single_value(
            "NewJaisa Configuration",
            "default_operational_cost_account"
        )

        processed = set()

        for sn in serial_nos:
            if sn in processed:
                continue
            processed.add(sn)

            cause = (self.cause_of_return or "").strip()

            if cause == "Repair":
                warehouse = frappe.db.get_value("Serial No", sn, "warehouse")

                if not warehouse:
                    sle = frappe.db.sql("""
                        SELECT warehouse
                        FROM `tabStock Ledger Entry`
                        WHERE serial_no = %s
                        AND is_cancelled = 0
                        AND qty_after_transaction > 0
                        ORDER BY posting_date DESC, posting_time DESC, creation DESC
                        LIMIT 1
                    """, (sn,), as_list=True)
                    warehouse = sle[0][0] if sle else None

                if not warehouse:
                    warehouse = frappe.db.get_value(
                        "Delivery Note Item",
                        {"parent": self.name, "serial_no": ["like", f"%{sn}%"]},
                        "warehouse"
                    )

                if not warehouse:
                    frappe.log_error(
                        f"Warehouse not found for serial no {sn} in return DN {self.name}.",
                        "Return DN Grade D Reset"
                    )
                    continue

                reset_only_motherboard_grade_to_d_on_return(
                    sn,
                    self.name,
                    warehouse,
                    expense_account
                )

            elif cause in ["RTO Customer", "RTO Delivery Partner"]:
                frappe.logger().info(
                    f"No grade change required for serial {sn} in Return DN {self.name}. "
                    f"cause_of_return={cause}"
                )

            elif cause in ["Replace", "Refund"]:
                warehouse = frappe.db.get_value("Serial No", sn, "warehouse")

                if not warehouse:
                    sle = frappe.db.sql("""
                        SELECT warehouse
                        FROM `tabStock Ledger Entry`
                        WHERE serial_no = %s
                        AND is_cancelled = 0
                        AND qty_after_transaction > 0
                        ORDER BY posting_date DESC, posting_time DESC, creation DESC
                        LIMIT 1
                    """, (sn,), as_list=True)
                    warehouse = sle[0][0] if sle else None

                if not warehouse:
                    warehouse = frappe.db.get_value(
                        "Delivery Note Item",
                        {"parent": self.name, "serial_no": ["like", f"%{sn}%"]},
                        "warehouse"
                    )

                if not warehouse:
                    frappe.log_error(
                        f"Warehouse not found for serial no {sn} in return DN {self.name}.",
                        "Return DN Grade Reset"
                    )
                    continue

                parent_item_code = frappe.db.get_value("Serial No", sn, "item_code")

                stock_qty = frappe.db.sql("""
                    SELECT actual_qty
                    FROM `tabBin`
                    WHERE item_code = %s
                    AND warehouse = %s
                    LIMIT 1
                """, (parent_item_code, warehouse), as_dict=True)

                actual_qty = stock_qty[0]["actual_qty"] if stock_qty else 0

                if actual_qty <= 0:
                    frappe.log_error(
                        f"Skipping grade reset for serial {sn}. "
                        f"Item {parent_item_code} has no stock in warehouse {warehouse}. "
                        f"Actual Qty: {actual_qty}",
                        "Return DN Grade Reset"
                    )
                    continue

                reset_part_grades_to_unknown_on_return(
                    sn,
                    self.name,
                    warehouse,
                    expense_account
                )

            else:
                frappe.logger().info(
                    f"No grade change rule matched for serial {sn} in Return DN {self.name}. "
                    f"cause_of_return={cause}"
                )

            # STEP 2: refresh parent laptop component table after repack
            try:
                serial_no_doc = frappe.get_doc("Serial No", sn)
                item_code = serial_no_doc.item_code

                item_template = frappe.db.get_value(
                    "Item",
                    {"name": item_code},
                    "variant_of"
                )

                if item_template:
                    latest_item_wizard = self._get_latest_item_wizard(item_template, item_code)
                    item_wizard_doc = frappe.get_doc("Item Wizards", latest_item_wizard)

                    self._update_components(
                        serial_no_doc,
                        item_wizard_doc,
                        self.doctype,
                        self.name
                    )
            except Exception as e:
                frappe.log_error(
                    f"Error refreshing parent serial components for {sn}: {str(e)}",
                    "CustomDeliveryNote Serial Number Update"
                )
                
            
    def _should_process_item(self, item):
       
        has_serial_no = frappe.db.get_value('Item', item.item_code, 'has_serial_no')
        
        return has_serial_no and item.serial_no
    
    def _update_serial_number_components(self, item):
       
        serial_list = item.serial_no.split('\n')
        
        for serial_no in serial_list:
            try:
                serial_no_doc = frappe.get_doc('Serial No', serial_no)
                
                item_template = frappe.db.get_value(
                    "Item", 
                    {'name': item.item_code}, 
                    'variant_of'
                )
                latest_item_wizard = self._get_latest_item_wizard(item_template, item.item_code)
                item_wizard_doc = frappe.get_doc('Item Wizards', latest_item_wizard)
                
                self._update_components(
                    serial_no_doc, 
                    item_wizard_doc, 
                    self.doctype, 
                    self.name
                )
                
            except Exception as e:
                frappe.log_error(
                    f"Error processing serial number {serial_no}: {str(e)}",
                    "CustomDeliveryNote Serial Number Update"
                )
    
    def _get_latest_item_wizard(self, item_template, item_code):

        return get_latest_item_wizard(item_template, item_code)
    
    def _update_components(self, serial_no_doc, item_wizard_doc, reference_doctype, reference_name):
        updated = False

        for item_component in item_wizard_doc.component:
            for serial_no_component in serial_no_doc.serial_no_component:
                if serial_no_component.item_group == item_component.get("component_type"):
                    serial_no_component.quantity = 1
                    updated = True

                    # only for serialized child parts -> relink child serial to parent laptop
                    if serial_no_component.component_serial_no:
                        frappe.db.set_value(
                            "Serial No",
                            serial_no_component.component_serial_no,
                            {
                                "parent_serial_no": serial_no_doc.name,
                                "status": "Delivered",
                                "warehouse": None,
                                "delivery_document_no": reference_name
                            },
                            update_modified=False
                        )

        if updated:
            frappe.db.set_value(
                "Serial No",
                serial_no_doc.name,
                {
                    "awb_no": '',
                    "address": '',
                    "end_date": '',
                    "email_id": '',
                    "order_id": '',
                    "mobile_no": '',
                    "last_name": '',
                    "first_name": '',
                    "customer": '',
                    "customer_name": '',
                    "order_date": '',
                    "tracking_id": '',
                    "shipped_date": '',
                    "deliver_date": '',
                    "courier_name": '',
                    "sales_channel": '',
                    "sale_type": '',
                    "sales_order_id": '',
                    "warranty_start_date_": '',
                    "reserved_sales_order": ''
                },
                update_modified=False
            )
            

    def update_mail_from_address(self):
        try:
            if not self.shipping_address_name:
                frappe.throw("Shipping address not set on Delivery Note.")
            
            address = frappe.get_doc("Address", self.shipping_address_name)            
            email_id = address.get("email_id")  # Use .get() for safer access
            if not email_id:
                frappe.throw(f"No email_id found in address {self.shipping_address_name}")       
            self.email = email_id
            self.save(ignore_permissions=True)
            return f"Email set to {email_id} for Delivery Note {self.name}"        
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Error in update_mail_from_address")
            frappe.throw(f"Error updating email from address: {str(e)}")
        


    def payment_validattion(self):
        if self.is_return:
            return
        order_id = self.shopify_order_number
        if not order_id:
            return

        # Shopify API details
        shopify_url = f"https://newjaisa.myshopify.com/admin/api/2025-01/orders/{order_id}.json"
        headers = {
            "X-Shopify-Access-Token": "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"
        }

        try:
            response = requests.get(shopify_url, headers=headers)
            response.raise_for_status()  # Raise exception if request failed
            order_data = response.json().get("order", {})

            cancel_reason = order_data.get("cancel_reason")
            financial_status = order_data.get("financial_status", "").lower()
            if cancel_reason is not None:
                frappe.throw("Error from Reason Order is cancelled, please contact support.")
            # Condition 2: Refund detected
            if "refund" in financial_status:
                frappe.throw("Error from financial_status Order is refunded, please contact support.")

        except requests.RequestException as e:
            frappe.throw(f"Error connecting to Shopify API: {e}")

            
    def fetching_tracking_details(self):
        if self.is_return or self.courier_service != "CriticaLog":
            return
        try:
            payload = {
                "Auth": " MTMzMzQzNzMwMzIz",  
                "DocketNo": self.name
            }
            url = "https://testing.ecritica.co/eFreightLive/api/tracking.php"
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, headers=headers, json=payload)

            if response.status_code == 200:
                data = response.json()

                # Check for invalid response
                if data.get("code") == 5 and "Invalid Con Number" in str(data.get("data", {}).get("docketDetails", "")):
                    frappe.msgprint(f"The sales order number '{self.name}' is not recognized as a valid tracking number.")
                    return

                # Extract and save remark
                remark = (
                    data.get("data", {})
                    .get("docketDetails", {})
                    .get("Booking_Status", {})
                    .get("Remark")
                )
                if remark:
                    self.remark_status = remark
                    self.db_update()
                else:
                    print("No remark found in the response")
            else:
                frappe.msgprint(f"API returned status code: {response.status_code}")

        except Exception as e:
            frappe.msgprint(f"Failed to send data to Criticalog API. Error: {str(e)}")


    def rto_charges_update(self):
        if not self.is_return:
            return
        valid_causes = ["RTO Customer", "RTO Delivery Partner"]
        if not self.cause_of_return or self.cause_of_return not in valid_causes:
            return

        # Fetch RTO Charges from NJ Settings
        rto_cost = frappe.db.get_value("NJ Settings", {"parameter": "RTO Charges"}, "value")
        # If value exists, sum with cost_amount
        if rto_cost and self.cost_of_delivery:
            try:
                updated_cost = float(self.cost_of_delivery) + float(rto_cost)
                self.cost_of_delivery = updated_cost
                self.db_update()
            except Exception as e:
                frappe.log_error(f"RTO Cost update failed: {e}", "RTO Charges Update")

    def update_details_to_delivery_charege_doc(self):
        if self.is_return:
            return
        # Check if a Delivery Charges document with the same AWB number exists
        existing_delivery_charge = frappe.get_all(
            "Delivery Charges",
            filters={"awb_number": self.tracking_id},
            limit=1
        )

        serial_nos = set()
        sales_orders = set()

        for row in self.get("items"):
            if row.get("serial_no"):
                serial_text = row.get("serial_no")
                for line in serial_text.split("\n"):
                    for serial in line.split(","):
                        serial = serial.strip()  
                        if serial:  
                            serial_nos.add(serial)
            if row.get("against_sales_order"):
                for order in row.get("against_sales_order").split(","):
                    order = order.strip()
                    if order:
                        sales_orders.add(order)

        for row in self.get("packed_items"):
            if row.get("serial_no"):
                serial_text = row.get("serial_no")
                for line in serial_text.split("\n"):
                    for serial in line.split(","):
                        serial = serial.strip() 
                        if serial:  
                            serial_nos.add(serial)

        # Convert sets to sorted, comma-separated strings
        serial_nos_str = ",".join(sorted(serial_nos))
        sales_orders_str = ",".join(sorted(sales_orders))

        if existing_delivery_charge:
            delivery_charge = frappe.get_doc("Delivery Charges", existing_delivery_charge[0].name)

            existing_serials = set()
            if delivery_charge.serial_no:
                for serial in delivery_charge.serial_no.split(","):
                    serial = serial.strip()
                    if serial:
                        existing_serials.add(serial)
            
            all_serials = existing_serials.union(serial_nos)
            delivery_charge.serial_no = ",".join(sorted(all_serials))

            # Update sales_order
            existing_orders = set()
            if delivery_charge.sales_order:
                for order in delivery_charge.sales_order.split(","):
                    order = order.strip()
                    if order:
                        existing_orders.add(order)
            
            all_orders = existing_orders.union(sales_orders)
            delivery_charge.sales_order = ",".join(sorted(all_orders))
        else:
            # Create a new document
            delivery_charge = frappe.new_doc("Delivery Charges")
            delivery_charge.awb_number = self.tracking_id
            delivery_charge.serial_no = serial_nos_str
            delivery_charge.sales_order = sales_orders_str
            delivery_charge.delivery_note = self.name
            delivery_charge.shiprocket_order_id = self.shiprocket_order_id
            delivery_charge.shiprocket_shipment_id = self.shiprocket_shipment_id
            delivery_charge.courier_service = self.courier_service
            delivery_charge.remark_status = self.remark_status
            delivery_charge.cit_image = self.cit_image
            delivery_charge.shiprocket_manifests = self.shiprocket_manifests
            delivery_charge.shiprocket_image = self.shiprocket_image
            delivery_charge.shiprocket_invoice = self.shiprocket_invoice
            delivery_charge.pickup_scheduled_date = self.pickup_scheduled_date
            delivery_charge.weight = self.weight

            delivery_charge.height = self.height
            delivery_charge.length = self.length
            delivery_charge.breadth = self.breadth
            delivery_charge.item_group_qty = self.item_group_qty
            delivery_charge.etd = self.etd
            delivery_charge.etd_hours = self.etd_hours
            delivery_charge.charge_weight = self.charge_weight
            delivery_charge.cod_charges = self.cod_charges
            delivery_charge.coverage_charges = self.coverage_charges
            delivery_charge.other_charges = self.other_charges
            delivery_charge.freight_charge = self.freight_charge
            delivery_charge.ship_rocket_rto_charges = self.rto_charges


        # Set common fields
        delivery_charge.rto_charges = self.cost_of_delivery
        delivery_charge.cit_image = self.cit_image

        if getattr(self, 'is_return', False):
            delivery_charge.cause_of_return = self.cause_of_return

        # Save or insert the document
        try:
            if delivery_charge.is_new():
                delivery_charge.insert(ignore_permissions=True)
            else:
                delivery_charge.save(ignore_permissions=True)

                delivery_charge.submit()
        except Exception as e:
            frappe.log_error(f"Error updating Delivery Charges doc: {e}", "Delivery Charges Sync Error")

    def qc_nj_of_days_checking(self):
        is_active = frappe.db.get_value('NJ Settings', {'parameter': 'dn_qc_active_status'}, 'value')
        if is_active != "Active":
            return 
        
        allowed_inspection_types = frappe.db.get_value('NJ Settings', {'parameter': 'inspection_type'}, 'value')
        inspection_days = frappe.db.get_value('NJ Settings', {'parameter': 'no_of_days'}, 'value')
        
        allowed_inspection_types_list = [t.strip() for t in allowed_inspection_types.split(",")]
        
        serial_nos_raw = frappe.get_all(
            'Delivery Note Item',
            filters={'parent': self.name},
            fields=['serial_no', 'name', 'item_code']  # Added more fields for debugging
        )
        
        serial_nos = set()
        for row in serial_nos_raw:
            if row.serial_no:
                for s in row.serial_no.split('\n'):
                    if s.strip():  
                        serial_nos.add(s.strip())
        
        error_messages = []
        
        for serial_no in serial_nos:       
            # 5. Fetch all QI for this serial no (barcode)
            qi_records = frappe.db.sql("""
                SELECT name, creation, inspection_type
                FROM `tabNJ Quality Inspection`
                WHERE barcode = %s AND docstatus = 1
                ORDER BY creation DESC
            """, serial_no, as_dict=True)
            
            
            if not qi_records:
                continue
            
            latest_qi = qi_records[0]
            qi_type = latest_qi.inspection_type.strip()
            
            if qi_type not in allowed_inspection_types_list:
                continue 
            
            # 7. Check if QI creation is within the allowed number of days
            creation_date = get_datetime(latest_qi.creation)
            current_date = now_datetime()
            days_difference = (current_date - creation_date).days
            
            if int(days_difference) > int(inspection_days):
                error_msg = f"More than {inspection_days} days have passed for Serial No {serial_no}. Please perform re-QC."
                error_messages.append(error_msg)
        
        # 8. Throw all error messages at once
        if error_messages:
            unique_errors = list(set(error_messages))

            frappe.throw("<br>".join(unique_errors))

@frappe.whitelist()
def reset_part_grades_to_unknown_on_return(serial_no, dn_name, warehouse, expense_account):
    import json
    from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
    from nj_p1_features.nj_p1_features.doctype.machine_part_changes.machine_part_changes import get_part_ledger_entry

    parent_item = frappe.db.get_value("Serial No", serial_no, "item_code")
    if not parent_item:
        frappe.log_error(
            f"Parent item not found for serial no {serial_no}",
            "Return DN Grade Reset"
        )
        return

    if not warehouse:
        frappe.log_error(
            f"Warehouse not found for serial no {serial_no}",
            "Return DN Grade Reset"
        )
        return

    # ----------------------------------------------------------
    # Split into serialized vs non-serialized components
    # ----------------------------------------------------------
    serialized_components = frappe.db.sql("""
        SELECT item, component_serial_no, item_group, item_group_idx
        FROM `tabSerial No Component`
        WHERE parent = %s
          AND is_available = 1
          AND component_serial_no IS NOT NULL
          AND component_serial_no != ''
    """, (serial_no,), as_dict=True)

    non_serialized_components = frappe.db.sql("""
        SELECT item, component_serial_no, item_group, item_group_idx
        FROM `tabSerial No Component`
        WHERE parent = %s
          AND is_available = 1
          AND (component_serial_no IS NULL OR component_serial_no = '')
    """, (serial_no,), as_dict=True)

    if not serialized_components and not non_serialized_components:
        return

    # ==========================================================
    # STEP 1 — UNPACK ONLY SERIALIZED COMPONENTS
    # Parent laptop IN → serialized child parts OUT + parent base back IN
    # ==========================================================
    grade_changed_components = []

    if serialized_components:
        unpack_items = []

        parent_val = get_part_ledger_entry(parent_item, serial_no) or 0
        total_component_value = 0

        # consume full parent laptop
        unpack_items.append({
            "repack_item_code": parent_item,
            "repack_serial_no": serial_no,
            "repack_item_source_warehouse": warehouse,
            "repack_item_base_price": parent_val,
        })

        # create child serialized parts back into stock
        for comp in serialized_components:
            part_serial = comp.component_serial_no
            current_item = comp.item

            if not part_serial or not current_item:
                continue

            comp_wh = frappe.db.get_value("Serial No", part_serial, "warehouse") or warehouse
            comp_val = get_part_ledger_entry(current_item, part_serial) or 0
            total_component_value += comp_val

            unpack_items.append({
                "unpack_item_code": current_item,
                "unpack_serial_no": part_serial,
                "unpack_item_target_warehouse": comp_wh,
                "unpack_item_base_price": comp_val,
            })

        # create stripped/base parent item back into stock
        parent_base_value = parent_val - total_component_value
        if parent_base_value < 0:
            parent_base_value = 0

        unpack_items.append({
            "unpack_item_code": parent_item,
            "unpack_serial_no": serial_no,
            "unpack_item_target_warehouse": warehouse,
            "unpack_item_base_price": parent_base_value,
        })

        if len(unpack_items) > 2:
            stock_entry_using_nj_lib(json.dumps({
                "name": dn_name,
                "doctype": "Delivery Note",
                "stock_entry_type": "Repack",
                "expense_account": expense_account,
                "repack_items": unpack_items,
            }))

        # ==========================================================
        # STEP 2 — CHANGE SERIALIZED PART ITEMS TO UNKNOWN
        # ==========================================================
        grade_change_items = []

        for comp in serialized_components:
            part_serial = comp.component_serial_no
            current_item = comp.item

            if not part_serial or not current_item:
                continue

            parts = current_item.rsplit("-", 1)
            if len(parts) == 2:
                unknown_item = parts[0] + "-UNKNOWN"
            else:
                unknown_item = current_item

            if not frappe.db.exists("Item", unknown_item):
                frappe.log_error(
                    f"UNKNOWN item not found: {unknown_item}",
                    "Return DN"
                )
                grade_changed_components.append({
                    "comp": comp,
                    "grade_changed": False,
                    "final_item": current_item,
                })
                continue

            comp_warehouse = frappe.db.get_value("Serial No", part_serial, "warehouse")
            if not comp_warehouse:
                sle = frappe.db.sql("""
                    SELECT warehouse
                    FROM `tabStock Ledger Entry`
                    WHERE item_code = %s
                      AND serial_no = %s
                      AND is_cancelled = 0
                      AND qty_after_transaction > 0
                    ORDER BY posting_date DESC, posting_time DESC
                    LIMIT 1
                """, (current_item, part_serial), as_list=True)
                comp_warehouse = sle[0][0] if sle else warehouse

            valuation_rate = get_part_ledger_entry(current_item, part_serial) or 0

            grade_change_items.append({
                "repack_item_code": current_item,
                "repack_serial_no": part_serial,
                "repack_item_source_warehouse": comp_warehouse,
                "repack_item_base_price": valuation_rate,
                "unpack_item_code": unknown_item,
                "unpack_serial_no": part_serial,
                "unpack_item_target_warehouse": comp_warehouse,
                "unpack_item_base_price": valuation_rate,
            })

            grade_changed_components.append({
                "comp": comp,
                "grade_changed": True,
                "final_item": unknown_item,
                "comp_warehouse": comp_warehouse,
                "valuation_rate": valuation_rate,
            })

        if grade_change_items:
            stock_entry_using_nj_lib(json.dumps({
                "name": dn_name,
                "doctype": "Delivery Note",
                "stock_entry_type": "Repack",
                "expense_account": expense_account,
                "repack_items": grade_change_items,
            }))

        # ==========================================================
        # STEP 3 — FINAL REPACK ONLY SERIALIZED COMPONENTS
        # Parent laptop IN + UNKNOWN serialized parts IN -> laptop OUT
        # ==========================================================
        final_repack_items = []

        total_comp_valuation = 0
        for gc in grade_changed_components:
            part_serial = gc["comp"].component_serial_no
            if not part_serial:
                continue

            if gc.get("grade_changed"):
                val = gc.get("valuation_rate", 0)
            else:
                val = get_part_ledger_entry(gc["final_item"], part_serial) or 0

            total_comp_valuation += val

        parent_valuation_final = get_part_ledger_entry(parent_item, serial_no) or 0
        final_repack_items.append({
            "repack_item_code": parent_item,
            "repack_serial_no": serial_no,
            "repack_item_source_warehouse": warehouse,
            "repack_item_base_price": parent_valuation_final,
        })

        for gc in grade_changed_components:
            part_serial = gc["comp"].component_serial_no
            final_item = gc["final_item"]

            if not part_serial or not final_item:
                continue

            comp_warehouse = frappe.db.get_value("Serial No", part_serial, "warehouse")
            if not comp_warehouse:
                sle = frappe.db.sql("""
                    SELECT warehouse
                    FROM `tabStock Ledger Entry`
                    WHERE item_code = %s
                      AND serial_no = %s
                      AND is_cancelled = 0
                      AND qty_after_transaction > 0
                    ORDER BY posting_date DESC, posting_time DESC
                    LIMIT 1
                """, (final_item, part_serial), as_list=True)
                comp_warehouse = sle[0][0] if sle else warehouse

            val = gc.get("valuation_rate", 0)

            final_repack_items.append({
                "repack_item_code": final_item,
                "repack_serial_no": part_serial,
                "repack_item_source_warehouse": comp_warehouse,
                "repack_item_base_price": val,
            })

        final_repack_items.append({
            "unpack_item_code": parent_item,
            "unpack_serial_no": serial_no,
            "unpack_item_target_warehouse": warehouse,
            "unpack_item_base_price": parent_valuation_final + total_comp_valuation,
        })

        if final_repack_items:
            stock_entry_using_nj_lib(json.dumps({
                "name": dn_name,
                "doctype": "Delivery Note",
                "stock_entry_type": "Repack",
                "expense_account": expense_account,
                "repack_items": final_repack_items,
            }))

        # ==========================================================
        # STEP 4 — UPDATE SERIALIZED COMPONENT DB / CHILD SERIALS
        # ==========================================================
        for gc in grade_changed_components:
            part_serial = gc["comp"].component_serial_no
            if not part_serial:
                continue

            frappe.db.set_value(
                "Serial No",
                part_serial,
                {
                    "item_code": gc["final_item"],
                    "parent_serial_no": serial_no,
                    "status": "Delivered",
                    "warehouse": None,
                    "delivery_document_no": dn_name
                },
                update_modified=False
            )

            frappe.db.sql("""
                UPDATE `tabSerial No Component`
                SET grade = 'UNKNOWN',
                    item = %s,
                    reference_doctype = 'Delivery Note',
                    reference_doctype_no = %s
                WHERE parent = %s
                  AND component_serial_no = %s
            """, (gc["final_item"], dn_name, serial_no, part_serial))

    # ==========================================================
    # STEP 5 — UPDATE NON-SERIALIZED COMPONENTS DIRECTLY
    # No unpack / repack, only UNKNOWN conversion
    # ==========================================================
    for comp in non_serialized_components:
        current_item = comp.get("item")
        if not current_item:
            continue

        parts = current_item.rsplit("-", 1)
        if len(parts) == 2:
            unknown_item = parts[0] + "-UNKNOWN"
        else:
            unknown_item = current_item

        if not frappe.db.exists("Item", unknown_item):
            frappe.log_error(
                f"UNKNOWN item not found for non-serialized component: {unknown_item}",
                "Return DN Non-Serialized Grade Reset"
            )
            continue

        frappe.db.sql("""
            UPDATE `tabSerial No Component`
            SET grade = 'UNKNOWN',
                item = %s,
                reference_doctype = 'Delivery Note',
                reference_doctype_no = %s
            WHERE parent = %s
              AND item_group = %s
              AND item_group_idx = %s
              AND (component_serial_no IS NULL OR component_serial_no = '')
        """, (
            unknown_item,
            dn_name,
            serial_no,
            comp.get("item_group"),
            comp.get("item_group_idx")
        ))

@frappe.whitelist()
def reset_only_motherboard_grade_to_d_on_return(serial_no, dn_name, warehouse, expense_account):
    import json
    from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
    from nj_p1_features.nj_p1_features.doctype.machine_part_changes.machine_part_changes import get_part_ledger_entry

    motherboard_groups = ["MOTHERBOARD", "MOTHER BOARD"]

    parent_item = frappe.db.get_value("Serial No", serial_no, "item_code")
    if not parent_item:
        frappe.log_error(
            f"Parent item not found for serial no {serial_no}",
            "Return DN Grade D Reset"
        )
        return

    motherboard_components = frappe.db.sql("""
        SELECT name, item, component_serial_no, item_group, item_group_idx
        FROM `tabSerial No Component`
        WHERE parent = %s
          AND is_available = 1
          AND UPPER(TRIM(item_group)) IN ('MOTHERBOARD', 'MOTHER BOARD')
    """, (serial_no,), as_dict=True)

    if not motherboard_components:
        frappe.logger().info(
            f"No motherboard row found to mark Grade D for serial {serial_no} in Return DN {dn_name}"
        )
        return

    for comp in motherboard_components:
        current_item = comp.get("item")
        if not current_item:
            continue

        parts = current_item.rsplit("-", 1)
        if len(parts) == 2:
            grade_d_item = parts[0] + "-GRADE D"
        else:
            grade_d_item = current_item

        if not frappe.db.exists("Item", grade_d_item):
            frappe.log_error(
                f"Grade D item not found: {grade_d_item}",
                "Return DN Grade D Reset"
            )
            continue

        # ----------------------------------------------------------
        # SERIALIZED motherboard: unpack -> grade change -> repack
        # ----------------------------------------------------------
        if comp.get("component_serial_no"):
            mb_serial = comp.get("component_serial_no")

            parent_val = get_part_ledger_entry(parent_item, serial_no) or 0
            mb_val = get_part_ledger_entry(current_item, mb_serial) or 0

            # STEP 1: unpack motherboard from laptop
            unpack_items = [
                {
                    "repack_item_code": parent_item,
                    "repack_serial_no": serial_no,
                    "repack_item_source_warehouse": warehouse,
                    "repack_item_base_price": parent_val,
                },
                {
                    "unpack_item_code": current_item,
                    "unpack_serial_no": mb_serial,
                    "unpack_item_target_warehouse": warehouse,
                    "unpack_item_base_price": mb_val,
                },
                {
                    "unpack_item_code": parent_item,
                    "unpack_serial_no": serial_no,
                    "unpack_item_target_warehouse": warehouse,
                    "unpack_item_base_price": max(parent_val - mb_val, 0),
                },
            ]

            stock_entry_using_nj_lib(json.dumps({
                "name": dn_name,
                "doctype": "Delivery Note",
                "stock_entry_type": "Repack",
                "expense_account": expense_account,
                "repack_items": unpack_items,
            }))

            # STEP 2: convert motherboard item to Grade D
            grade_change_items = [{
                "repack_item_code": current_item,
                "repack_serial_no": mb_serial,
                "repack_item_source_warehouse": warehouse,
                "repack_item_base_price": mb_val,
                "unpack_item_code": grade_d_item,
                "unpack_serial_no": mb_serial,
                "unpack_item_target_warehouse": warehouse,
                "unpack_item_base_price": mb_val,
            }]

            stock_entry_using_nj_lib(json.dumps({
                "name": dn_name,
                "doctype": "Delivery Note",
                "stock_entry_type": "Repack",
                "expense_account": expense_account,
                "repack_items": grade_change_items,
            }))

            # STEP 3: repack Grade D motherboard back into laptop
            repack_items = [
                {
                    "repack_item_code": parent_item,
                    "repack_serial_no": serial_no,
                    "repack_item_source_warehouse": warehouse,
                    "repack_item_base_price": max(parent_val - mb_val, 0),
                },
                {
                    "repack_item_code": grade_d_item,
                    "repack_serial_no": mb_serial,
                    "repack_item_source_warehouse": warehouse,
                    "repack_item_base_price": mb_val,
                },
                {
                    "unpack_item_code": parent_item,
                    "unpack_serial_no": serial_no,
                    "unpack_item_target_warehouse": warehouse,
                    "unpack_item_base_price": parent_val,
                },
            ]

            stock_entry_using_nj_lib(json.dumps({
                "name": dn_name,
                "doctype": "Delivery Note",
                "stock_entry_type": "Repack",
                "expense_account": expense_account,
                "repack_items": repack_items,
            }))

            # STEP 4: update serialized child Serial No
            frappe.db.set_value(
                "Serial No",
                mb_serial,
                {
                    "item_code": grade_d_item,
                    "parent_serial_no": serial_no,
                    "status": "Delivered",
                    "warehouse": None,
                    "delivery_document_no": dn_name
                },
                update_modified=False
            )

        # ----------------------------------------------------------
        # NON-SERIALIZED motherboard: direct item/grade update
        # ----------------------------------------------------------
        frappe.db.sql("""
            UPDATE `tabSerial No Component`
            SET grade = 'Grade D',
                item = %s,
                reference_doctype = 'Delivery Note',
                reference_doctype_no = %s
            WHERE name = %s
        """, (grade_d_item, dn_name, comp.get("name")))

@frappe.whitelist()
def custome_limits_crossed_error(self, args, item, qty_or_amount):

    # ---------------------------------------------------------
    # 1. Fetch against sales order (Delivery Note Item → Sales Order)
    # ---------------------------------------------------------
    against_sales_order = frappe.get_value(
        "Delivery Note Item",
        {"parent": self.name},
        "against_sales_order"
    )

    # print("Against SO =", against_sales_order)

    sale_type = None
    if against_sales_order:
        sale_type = frappe.get_value(
            "Sales Order",
            {"name": against_sales_order},
            "sale_type"
        )

    # print("SALE TYPE =", sale_type)
    nj_setting_value = frappe.db.get_value("NJ Settings", {"parameter": "sale_type_name"}, "value")

    # ---------------------------------------------------------
    # 2. SKIP FUNCTION COMPLETELY IF NJ Seeting Value is Matches
    # ---------------------------------------------------------
    if sale_type == nj_setting_value:
        # print("Skipping limits_crossed_error — Amazon order")
        customer = frappe.db.get_value("Delivery Note", {"name": self.name}, "customer")
        customer_data = frappe.db.get_value(
            "Customer",
            {"name": customer},
            ["allow_over_dn", "qty"],
            as_dict=True
        )

        if customer_data.allow_over_dn != 1:
            frappe.throw("Allow Over DN is desabled for this Customer.")
        if customer_data.qty == 0:
            frappe.throw("Qty is 0 for this Customer. Please update the Qty.")

        total_qty = frappe.db.get_value("Sales Order", against_sales_order, "total_qty")

        percentage = frappe.db.get_value("Customer", customer, "qty")

        customer_qty_raw = (percentage / 100) * total_qty

        customer_qty = math.ceil(customer_qty_raw)
        total_sum_qty = total_qty + customer_qty

        submitted_dn = frappe.db.sql(f"""
            SELECT DISTINCT dn.name, dn.total_qty
            FROM `tabDelivery Note` dn
            INNER JOIN `tabDelivery Note Item` dni
                ON dni.parent = dn.name
            WHERE dn.docstatus = 1
            AND dn.name != '{self.name}'
            AND dni.against_sales_order = '{against_sales_order}'
        """, as_dict=True)



        submitted_dn_qty = sum((d.total_qty or 0) for d in submitted_dn)

        # Fetch current DN qty
        current_dn_qty = frappe.db.get_value("Delivery Note", self.name, "total_qty") 

        # Total delivered including current
        total_delivered = submitted_dn_qty + current_dn_qty
        if self.is_replacement !=1:
            frappe.throw("Is replacement is not checked and its Mandatory.")
        # Compare
        if total_sum_qty < total_delivered:
            frappe.throw("Over Delivery Note is not allowed. Please update the Qty.")
        return 

    # ---------------------------------------------------------
    # 3. Continue normal custom error logic
    # ---------------------------------------------------------
    if qty_or_amount == "qty":
        action_msg = _(
            'To allow over receipt / delivery, update "Over Receipt/Delivery Allowance" in Stock Settings or the Item.'
        )
    else:
        action_msg = _(
            'To allow over billing, update "Over Billing Allowance" in Accounts Settings or the Item.'
        )

    # Throw custom error
    frappe.throw(
        _(
            "Custom ERROR: This document is over limit by {0} {1} for item {4}. "
            "Are you making another {3} against the same {2}?"
        ).format(
            frappe.bold(_(item["target_ref_field"].title())),
            frappe.bold(item["reduce_by"]),
            frappe.bold(_(args.get("target_dt"))),
            frappe.bold(_(self.doctype)),
            frappe.bold(item.get("item_code")),
        )
        + "<br><br>" + action_msg,
        OverAllowanceError,
        title=_("Limit Crossed"),
    )


@frappe.whitelist()
def get_link_1(name):
    nj_setting_value = frappe.db.get_value("NJ Settings", {"parameter": "NJpulse_url"}, "value")
    
    link = frappe.db.get_list("Doc Attachment", {"doctypename": name, "file_type": "Video", "docstatus": 1}, ["linked_data"])
    for item in link:
        item["linked_data"] = nj_setting_value + item["linked_data"]
    return link

@frappe.whitelist()
def validate_delivery_bios(doc):

    if isinstance(doc, str):
        doc = json.loads(doc)
    
    if doc.get("is_return"):
        return

    error_message = []

    bios_settings = frappe.db.get_value("NJ Settings", {"parameter": "bios_settings"}, "value")

    if not bios_settings:
        return {"error": "NJ Settings for Delivery Note, <b>bios_settings</b> is not defined"}
    
    if int(bios_settings):

            item_group_list = frappe.db.get_value('NJ Settings', {'parameter': 'bios_item_group'}, ['value'])

            if item_group_list:
                item_group_list = json.loads(item_group_list)

            for item in doc.get('items'):
                serial_no = item.get('serial_no', None)
                item_group = item.get("item_group")
                idx = item.get("idx", "N/A")

                if serial_no:
                    serial_no = serial_no.strip()
                    serial_list = serial_no.split('\n')

                    for serial in serial_list:
                        bios_serial_no = frappe.db.get_value('Serial No', serial, 'bios_serial_no')
                        if (bios_serial_no is None or bios_serial_no.strip() == '') and item_group in item_group_list:
                            error_message.append(
                                f"<b>Row {idx}</b>: Serial No <b>{serial}</b> for item group <b>{item_group}</b> has no Bios Serial No"
                            )

    return error_message if error_message else True

@frappe.whitelist()
def send_sales_invoice_email_on_delivery_note(doc, method=None):
    """Sends a single email with order readiness details and Sales Invoice PDF when a Delivery Note is submitted."""
    try:
        order_id = None

        sales_invoice = frappe.get_value("Delivery Note Item", {"parent": doc.name}, "against_sales_invoice")
        if not sales_invoice:
            frappe.msgprint(f"⚠️ No Sales Invoice found for Delivery Note {doc.name}. Email not sent.")
            return

        sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice)

        customer_email = frappe.db.get_value("Customer", sales_invoice_doc.customer, "email_id")
        if not customer_email:
            customer_email = frappe.db.get_value(
                "Dynamic Link",
                {"link_doctype": "Customer", "link_name": doc.customer, "parenttype": "Address"},
                "parent"
            )
            if customer_email:
                customer_email = frappe.db.get_value("Address", customer_email, "email_id")

        # if not customer_email:
        #     frappe.msgprint(f"⚠️ No email found for customer {sales_invoice_doc.customer}. Email not sent.")
        #     return

        pdf_data = frappe.attach_print("Sales Invoice", sales_invoice, print_format="Standard")

        tracking_id = doc.get("tracking_id")
        tracking_courier = doc.get("courier_service")
        billing_address = doc.get("address_display")
        against_sales_order = frappe.get_value("Delivery Note Item", {"parent": doc.name}, "against_sales_order")
        
        order_values = frappe.db.get_value(
            "Sales Order", 
            {"name": against_sales_order}, 
            ["order_id", "amazon_order_id", "shopify_order_id"]
        )

        if order_values:
            order_id = next((value for value in order_values if value), None)

        sender_email = frappe.db.get_value('NJ Settings', {'parameter': 'sender_mail'}, ['value'])

        courier_tracking_data = {
            'CriticaLog': 'https://criticalog.com/tracking/',
            'Tirupati Courier Tracking': 'http://www.shreetirupaticourier.net/',
            'Shiprocket Manifest': 'https://www.shiprocket.in/shipment-tracking/'
        }

        tracking_link = courier_tracking_data.get(tracking_courier, None)
        tracking_info = ""
        if tracking_link and tracking_id:
            tracking_info = f"<p><b>Courier Partner:</b> {tracking_courier}</p><p><b>Tracking Number:</b> {tracking_id}</p><p><b>Track your order here:</b> <a href='{tracking_link}'>{tracking_link}</a></p>"

        subject = f"Your Order {order_id} is Ready – with Tacking Id {tracking_id} "

        message = f"""
         <p>Dear {sales_invoice_doc.customer_name},</p>
        <p>We are pleased to inform you that your order <b>{order_id}</b> is now ready for pickup and will be delivered to:</p>
        <p><b>Shipping Address:</b><br>{billing_address}</p>
        {tracking_info}
        <br>
        <p>Thank you for choosing <b>NewJaisa Technologies</b>.</p>
        <p>Best regards,</p>
        <p><b>NewJaisa Technologies</b></p>
        """

        frappe.sendmail(
            recipients=[customer_email],
            subject=subject,
            message=message,
            reference_doctype=sales_invoice_doc.doctype,
            reference_name=sales_invoice_doc.name,
            # attachments=[pdf_data],
            sender=sender_email,
            now=True
        )

        frappe.msgprint(f"📧 Email sent successfully to {customer_email} with Sales Invoice {sales_invoice_doc.name}.")

    except Exception as e:
        frappe.log_error(message=str(e), title="Sales Invoice Email Failed")

@frappe.whitelist()
def get_cod_amount(so_name):
    try:
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": TOKEN
        }

        filters = {"name": so_name, "docstatus": 1,'order_type':"Sales"}

        raw_order_id = frappe.get_value("Sales Order", filters, "shopify_order_id")

        if raw_order_id and len(raw_order_id.lstrip('#')) < 7:
            order_id = raw_order_id.lstrip('#')
        else:
            raw_order_id = frappe.get_value("Sales Order", filters, "order_id")
            order_id = raw_order_id.lstrip('#') if raw_order_id else None

            if not order_id:
                raw_order_id = frappe.get_value("Sales Order", filters, "shopify_order_number")
                order_id = raw_order_id.lstrip('#') if raw_order_id else None

        if not order_id:
            return {"order_id": None, "cod_amount": 0}

        url = f"{SHOPIFY_URL}{order_id}"
        response = requests.get(url, headers=headers)
        data = response.json()

        if "orders" in data and data["orders"]:
            order = data["orders"][0]
            cod_amount = order.get("total_outstanding", 0)
            return {"order_id": order_id, "cod_amount": cod_amount}

        return {"order_id": order_id, "cod_amount": 0}

    except Exception as e:
        frappe.log_error(f"Error in get_cod_amount: {str(e)}", "Shopify COD Fetch Error")
        return {"order_id": None, "cod_amount": 0}


# ---- GLOBAL SHOPIFY RATE-LIMIT HANDLER ----
def shopify_request(session, method, url, headers=None, json=None):
    while True:
        response = session.request(method, url, headers=headers, json=json)

        # --- SAFE RETRY-AFTER PARSING ---
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                retry_after = float(retry_after)  # works for "2" or "2.0"
            except ValueError:
                retry_after = 1  # fallback to 1 second
        else:
            retry_after = 0

        # Shopify throttling (status 429)
        if response.status_code == 429:
            time.sleep(max(retry_after, 1))
            continue

        # Shopify API call limit logic
        call_limit = response.headers.get("X-Shopify-Shop-Api-Call-Limit")
        if call_limit:
            try:
                used, max_allowed = map(int, call_limit.split('/'))
                if used >= max_allowed - 2:
                    time.sleep(1)
            except:
                pass

        return response


# ---- FULFILLMENT FUNCTION ----
@frappe.whitelist(allow_guest=True)
def trigger_fulfillment(order_id, original_order_id=None, shopify_order_no=None, dn_name=None):

    doc = frappe.get_doc("Delivery Note", dn_name)

    if doc.is_return:
        return

    # Prevent duplicate fulfillment for same sales order
    against_sales_order = frappe.get_value("Delivery Note Item", {"parent": dn_name}, "against_sales_order")
    if against_sales_order:
        exists = frappe.db.exists(
            "Delivery Note",
            {"is_return": 1, "against_sales_order": against_sales_order}
        )
        if exists:
            return

    # ---------------- SAFE SHOPIFY SESSION ----------------
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=False)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": TOKEN
    }

    # ---------------- GET ORDER DETAILS ----------------
    order_url = f"{SHOPIFY_URL}{order_id}"
    r = shopify_request(session, "GET", order_url, headers=headers)

    if r.status_code != 200:
        frappe.throw(f"Shopify Order Error: {r.text}")

    order_data = r.json().get("orders", [])
    if not order_data:
        frappe.throw("Order not found in Shopify")

    order = order_data[0]
    shopify_order_id = order.get("id")
    if not shopify_order_id:
        frappe.throw("Missing Shopify Order ID")

    fulfillment_status = order.get("fulfillment_status")

    # ---------------- TRACKING DETAILS ----------------
    tracking_number, courier_service = frappe.db.get_value(
        "Delivery Note", dn_name, ["tracking_id", "courier_service"]
    ) or (None, None)

    if not tracking_number:
        frappe.throw("Tracking ID not found")

    tracking_link = None
    try:
        courier_doc = frappe.get_doc("Courier Service", courier_service)
        base_url = getattr(courier_doc, "tracking_url", None)
        if base_url:
            tracking_link = f"{base_url.rstrip('/')}/{tracking_number}"
        courier_company = getattr(courier_doc, "courier_name", courier_service)
    except:
        courier_company = courier_service

    # ===========================================================
    # CASE 1: Already fulfilled → Update tracking only
    # ===========================================================
    if fulfillment_status == "fulfilled":
        url_f = f"{SHOPIFY_URL}{shopify_order_id}/fulfillments.json"
        r2 = shopify_request(session, "GET", url_f, headers=headers)

        # Better error handling for API response
        if r2.status_code != 200:
            frappe.log_error(
                title="Shopify Fulfillment Fetch Error",
                message=f"Order ID: {shopify_order_id}\nStatus Code: {r2.status_code}\nResponse: {r2.text}"
            )
            # frappe.msgprint(
            #     "Order is already fulfilled in Shopify but tracking cannot be updated. "
            #     "Please update tracking manually in Shopify admin.",
            #     indicator="orange"
            # )
            return

        f_json = r2.json()
        fulfillments = f_json.get("fulfillments", [])
        
        # Filter for non-cancelled fulfillments
        active_fulfillments = [f for f in fulfillments if f.get("status") != "cancelled"]
        
        if not active_fulfillments:
            # Order is marked as fulfilled but no active fulfillments found
            # This can happen with legacy orders or manual fulfillments
            frappe.log_error(
                title="No Active Fulfillment Found",
                message=f"Order ID: {shopify_order_id}\nFulfillment Status: {fulfillment_status}\nFulfillments Response: {f_json}"
            )
            # frappe.msgprint(
            #     "Order is already fulfilled in Shopify but no fulfillment record found to update. "
            #     "Tracking information must be updated manually in Shopify admin.",
            #     indicator="orange"
            # )
            return

        # Get the first active fulfillment
        f_id = active_fulfillments[0]["id"]

        update_url = f"{SHOPIFY_URL}fulfillments/{f_id}/update_tracking.json"
        payload = {
            "fulfillment": {
                "tracking_info": {
                    "number": tracking_number,
                    "company": courier_company,
                    "url": tracking_link
                },
                "notify_customer": True
            }
        }

        r3 = shopify_request(session, "POST", update_url, headers=headers, json=payload)
        if r3.status_code != 200:
            frappe.log_error(
                title="Shopify Tracking Update Failed",
                message=f"Fulfillment ID: {f_id}\nStatus Code: {r3.status_code}\nResponse: {r3.text}"
            )
            frappe.throw(f"Tracking update failed: {r3.text}")

        # frappe.msgprint("Tracking information updated successfully in Shopify", indicator="green")
        return

    # ===========================================================
    # CASE 2: Create NEW fulfillment
    # ===========================================================
    fulfillment_order_url = FULLFILMENT_ORDER_ID.format(shopify_order_id=shopify_order_id)
    r4 = shopify_request(session, "GET", fulfillment_order_url, headers=headers)
    
    if r4.status_code != 200:
        frappe.log_error(
            title="Shopify Fulfillment Order Fetch Error",
            message=f"Order ID: {shopify_order_id}\nStatus Code: {r4.status_code}\nResponse: {r4.text}"
        )
        frappe.throw(f"Failed to fetch fulfillment order: {r4.text}")
    
    fulfillment_data = r4.json().get("fulfillment_orders", [])

    if not fulfillment_data:
        frappe.throw("Fulfillment Order not found")

    fulfillment_order_id = fulfillment_data[0]["id"]

    # Create fulfillment payload
    fulfillment_payload = {
        "fulfillment": {
            "line_items_by_fulfillment_order": [
                {"fulfillment_order_id": fulfillment_order_id}
            ],
            "tracking_info": {
                "number": tracking_number,
                "company": courier_company,
                "url": tracking_link
            }
        }
    }

    r5 = shopify_request(session, "POST", MAKE_FULLFILMENT, headers=headers, json=fulfillment_payload)
    if r5.status_code not in [200, 201]:
        frappe.log_error(
            title="Shopify Fulfillment Creation Error",
            message=f"Order ID: {shopify_order_id}\nStatus Code: {r5.status_code}\nResponse: {r5.text}"
        )
        frappe.throw(f"Fulfillment creation error: {r5.text}")
    
    # frappe.msgprint("Fulfillment created successfully in Shopify", indicator="green")



def qi_mandatory_checks_on_dn_submit(doc, method=None):

    if doc.is_return:
        return

    for item in doc.items:

        if not item.serial_no:
            continue

        serial_nos = [s.strip() for s in item.serial_no.split("\n") if s.strip()]

        for serial_no in serial_nos:

            item_code = frappe.db.get_value("Serial No", serial_no, "item_code")
            item_group = frappe.db.get_value("Item", item_code, "item_group")

            if item_group != "Laptops":
                continue

            mandatory_checks = frappe.db.sql("""
                SELECT name
                FROM `tabNJ QC Check List`
                WHERE mandatory = 1
                AND docstatus = 1
                AND name IN (
                    SELECT quality_check
                    FROM `tabNJ Quality Checks` njqc
                    JOIN `tabNj QC Options` njqco ON njqco.parent = njqc.name
                    JOIN `tabInspection Type` it ON it.name = njqc.inspection_type
                    WHERE it.active = 1
                    AND njqc.item_group IN (
                        SELECT component_type
                        FROM `tabComponent`
                        WHERE parent = (
                            SELECT item_wizard
                            FROM `tabSerial No`
                            WHERE name = %s
                        )
                    )
                )
            """, (serial_no,), as_dict=True)

            if not mandatory_checks:
                continue

            # -------- CUT OFF CALCULATION --------
            cutoff = frappe.db.sql("""
                SELECT GREATEST(
                    IFNULL((SELECT MAX(creation)
                        FROM `tabDelivery Note Item`
                        WHERE docstatus = 1
                        AND parent != %s
                        AND serial_no LIKE CONCAT('%%', %s, '%%')
                    ), '1000-01-01 00:00:00'),

                    IFNULL((SELECT MAX(creation)
                        FROM `tabPacked Item`
                        WHERE docstatus = 1
                        AND serial_no LIKE CONCAT('%%', %s, '%%')
                    ), '1000-01-01 00:00:00'),

                    IFNULL((SELECT creation
                        FROM `tabSerial No`
                        WHERE name = %s
                    ), '1000-01-01 00:00:00')
                )
            """, (doc.name, serial_no, serial_no, serial_no), as_list=True)[0][0]

            logger.info(f"QC cutoff for serial {serial_no}: {cutoff}")

            # -------- FINAL QC FETCH --------
            qi_names = frappe.db.sql("""
                SELECT name
                FROM `tabNJ Quality Inspection`
                WHERE barcode = %s
                AND inspection_type = 'Final QC'
                AND docstatus = 1
                AND creation >= %s
                ORDER BY creation DESC
                LIMIT 1
            """, (serial_no, cutoff), as_list=True)

            if not qi_names:
                frappe.throw(
                    f"No submitted NJ Quality Inspection found for Serial No: {serial_no}"
                )

            mandatory_check_names = {check["name"] for check in mandatory_checks}
            passed_checks = set()
            failed_checks = {}
            missing_checks = mandatory_check_names.copy()

            for qi_name in qi_names:

                nj_checks = frappe.db.sql("""
                    SELECT check_name, score
                    FROM `tabNJ Checks`
                    WHERE parent = %s
                """, (qi_name[0],), as_dict=True)

                nj_check_names = {check.check_name for check in nj_checks}

                missing_checks -= nj_check_names

                for check in nj_checks:

                    if check.check_name not in mandatory_check_names:
                        continue

                    if check.score <= 1:
                        passed_checks.add(check.check_name)
                    else:
                        failed_checks[check.check_name] = qi_name[0]

                if passed_checks == mandatory_check_names:
                    break

            if failed_checks:
                msg = ", ".join(
                    [f"{check} (QI: {qi})" for check, qi in failed_checks.items()]
                )
                frappe.throw(
                    f"Mandatory checks failed for Serial No: {serial_no}: {msg}"
                )

            if missing_checks:
                frappe.throw(
                    f"Mandatory checks missing for Serial No: {serial_no}: {', '.join(missing_checks)}"
                )
@frappe.whitelist()
def update_item_details(self):
    if isinstance(self, str):
        self = json.loads(self)
    # If weight/dimensions are already filled, assume user has set them — do not override
    if self.get("weight") or self.get("height") or self.get("length") or self.get("breadth"):
        return None
    total_weight = 0
    height = length = breadth = None
    # Step 1: Get allowed item groups from NJ Settings
    item_group_value = frappe.db.get_value(
        "NJ Settings", {"parameter": "Item Group Validation"}, "value"
    )
    allowed_item_groups = []
    if item_group_value:
        allowed_item_groups = [group.strip() for group in item_group_value.split(",")]
    # Step 2: Filter matching items
    matching_rows = []
    for row in self.get("items", []):
        item_code = row.get("item_code")
        if not item_code:
            continue
        item_group = frappe.db.get_value("Item", item_code, "item_group")
        if item_group in allowed_item_groups:
            matching_rows.append(row)
    # Step 3: If not exactly 1 matching item, skip
    if len(matching_rows) != 1:
        print("Skipping: multiple matching items.")
        return None
    item = matching_rows[0]
    if item.get("qty") != 1:
        print("Skipping: qty is not 1.")
        return None
    # Step 4: Fetch from Item Group
    item_code = item.get("item_code")
    item_group = frappe.db.get_value("Item", item_code, "item_group")
    try:
        group_doc = frappe.get_doc("Item Group", item_group)

        if group_doc.get("weight"):
            try:
                total_weight += float(group_doc.weight)
            except ValueError:
                frappe.log_error(f"Invalid weight in Item Group: {group_doc.name}", "Weight Error")

        for dim in group_doc.get("dimensions", []):
            param = dim.parameter.strip().lower()
            value = dim.value
            if "height" in param and not height:
                height = value
            elif "length" in param and not length:
                length = value
            elif "breadth" in param and not breadth:
                breadth = value

    except Exception as e:
        print(f"Error reading item group {item_group}: {str(e)}")

    return {
        'weight': total_weight,
        'height': height,
        'length': length,
        'breadth': breadth
    }
           
@frappe.whitelist()
def fetch_cod_amount(doc_name):
    against_sales_order = frappe.get_value("Delivery Note Item", {"parent": doc_name}, "against_sales_order")
    print("against_sales_order=======================", against_sales_order)
    
    if against_sales_order:
        sales_order = frappe.get_doc("Sales Order", against_sales_order)
        print("sales_order=======================", sales_order )
        
        cod_amt = sales_order.total_outstanding
        print("cod_amt=======================", cod_amt)
        is_cod = sales_order.is_cod
        print("is_cod=======================", is_cod)
        payment_received = sales_order.payment_received  
        print("payment_received=======================", payment_received)  
        
        return {
            'cod_amount': cod_amt,
            'is_cod': is_cod,
            'payment_received': payment_received
        }
    
    return {
        'cod_amount': 0,
        'is_cod': 0,
        'payment_received': 0
    }

@frappe.whitelist()
def set_cod_details_critical(doc, method=None):
    print("345678------------------")
    """
    Automatically fetch COD amount and set mode_of_transfer
    when Delivery Note is saved.
    """

    against_sales_order = frappe.get_value(
        "Delivery Note Item",
        {"parent": doc.name},
        "against_sales_order"
    )
    frappe.logger().info(f"against_sales_order = {against_sales_order}")

    if not against_sales_order:
        doc.cod_amount = 0
        doc.mode_of_transfer = "Surface"
        return

    sales_order = frappe.get_doc("Sales Order", against_sales_order)

    cod_amt = sales_order.total_outstanding or 0
    is_cod = sales_order.is_cod
    payment_received = sales_order.payment_received

    frappe.logger().info(
        f"COD Amount: {cod_amt}, Is COD: {is_cod}, Payment Received: {payment_received}"
    )

    # ✅ Set COD Amount
    doc.cod_amount = cod_amt

    # ✅ Mode of Transfer logic
    if is_cod and payment_received:
        doc.mode_of_transfer = "Surface"
    elif is_cod and not payment_received:
        doc.mode_of_transfer = "COD Surface"
    else:
        doc.mode_of_transfer = "Surface"
    # doc.save(ignore_permissions=True)
    frappe.db.set_value("Delivery Note", doc.name, "mode_of_transfer", doc.mode_of_transfer,update_modified=False)

@frappe.whitelist()
def send_consignement_data(doc):
    # start_time = time.time()
    try:
        # Convert string to Frappe dict
        doc = frappe._dict(json.loads(doc))
        # sales_order_doc = frappe.get_doc("Sales Order", doc.name)
        delivery_note = frappe.get_doc("Delivery Note", doc.name)
        against_sales_order = frappe.get_value(
            "Delivery Note Item", {"parent": delivery_note.name}, "against_sales_order"
        )

        total_qty = 0
        for item in delivery_note.items:
            is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")
            
            if is_stock_item == 1:
                total_qty += item.qty
        frappe.db.set_value("Delivery Note", doc.name, "item_group_qty", total_qty,update_modified=False)              
        if not doc.shipping_address_name:
            frappe.throw("Shipping address is not set.")
        total_item_charges = 0
        for item in doc.get("items", []):
            if not item.get("item_code"):
                continue
            item_group = frappe.db.get_value("Item", item.get("item_code"), "item_group") 
            group_doc = frappe.get_doc("Item Group", item_group)
            item_charges = group_doc.get("item_charges")
            if item_charges and item.get("qty"):
                item_total_charge = float(item_charges) * float(item.get("qty"))
                total_item_charges += item_total_charge
            else:
                print("Missing item_charges or quantity for item:", item.get("item_code"))
        pincode = frappe.db.get_value("Address", doc.shipping_address_name, "pincode")
        if not pincode:
            frappe.throw("Pincode not found in the shipping address.")
        
        pincode_doc = frappe.db.get_value("Pincode", {"pincode_no": pincode}, ["rate", "cod"], as_dict=True)
        if not pincode_doc:
            frappe.throw(f"Pincode {pincode} not found in Pincode master.")
        
        if not doc.weight:
            frappe.throw("Weight is not set in Delivery Note.")
        total_item_charges = 0
        for item in doc.get("items", []):
            if not item.get("item_code"):
                continue
            item_group = frappe.db.get_value("Item", item.get("item_code"), "item_group") 
            group_doc = frappe.get_doc("Item Group", item_group)
            item_charges = group_doc.get("item_charges")
            if item_charges and item.get("qty"):
                item_total_charge = float(item_charges) * float(item.get("qty"))
                total_item_charges += item_total_charge
            else:
                print("Missing item_charges or quantity for item:", item.get("item_code"))
        rate = float(pincode_doc.rate or 0)
        cod_charge = float(pincode_doc.cod or 0)
        weight = float(doc.weight or 0)
        is_cod = False
        payment_received = False
        if against_sales_order:
            # Method 1: Fetch only is_cod field
            is_cod = frappe.db.get_value("Sales Order", against_sales_order, "is_cod")
            payment_received = frappe.db.get_value("Sales Order", against_sales_order, "payment_received")
        if payment_received == 1 and is_cod == 1:
            cost_of_delivery = rate * weight
            
            if cost_of_delivery > total_item_charges:
                frappe.throw(f"Cannot generate AWB number because courier total cost ({cost_of_delivery}) is more than item charges total ({total_item_charges})")
        # Calculate cost of delivery and run COD validation only for COD orders
        elif is_cod == 1:
            cost_of_delivery = (rate * weight) + cod_charge
            # COD validation - only run for COD orders
            ship_rocket_settings = frappe.get_doc("Ship Rocket Settings")
            cod_charges_table = ship_rocket_settings.get("cod_charges", [])
            charges_value = None
            for cod_charge_row in cod_charges_table:
                charges_value = cod_charge_row.charges_value  
                if charges_value:
                    break      
            if charges_value:
                numeric_charges_value = float(charges_value.replace('%', '').strip())
                # Calculate percentage of grand_total
                grand_total = float(doc.get("grand_total", 0) or 0)
                cod_percentage_amount = round((numeric_charges_value / 100) * grand_total, 2)
                cod_and_item_charges_total = total_item_charges + cod_percentage_amount
                if cod_and_item_charges_total < cost_of_delivery:
                    frappe.throw(f"COD validation failed: COD charges courier total cost ({cost_of_delivery:.2f}) is greater than ({numeric_charges_value:.2f}% of grand total = {cod_percentage_amount:.2f})")
            
        else:
            # For prepaid orders, no COD charges
            cost_of_delivery = rate * weight
            
            if cost_of_delivery > total_item_charges:
                frappe.throw(f"Cannot generate AWB number because courier total cost ({cost_of_delivery}) is more than item charges total ({total_item_charges})")
        company_address = frappe.get_doc("Address", doc.company_address) if doc.company_address else None
        shipping_address = frappe.get_doc("Address", doc.shipping_address_name) if doc.shipping_address_name else None
        # formatted_date = doc.delivery_date.strftime("%Y-%m-%d") if hasattr(doc.delivery_date, 'strftime') else str(doc.delivery_date)
        formatted_date = datetime.today().strftime("%Y-%m-%d")
        
        against_sales_order = frappe.get_value(
            "Delivery Note Item", {"parent": delivery_note.name}, "against_sales_order"
        )
        if against_sales_order:
            sales_order_doc = frappe.get_doc("Sales Order", against_sales_order)
            # COD checked but also payment received
            if sales_order_doc.is_cod == 1 and sales_order_doc.payment_received == 1:
                    PaymentType = "Prepaid"

                    if sales_order_doc.grand_total:
                        consignmentValue = float(sales_order_doc.grand_total)
                    else:
                        total_default_charge = 0
                        found_charges = False
                        
                        for item in sales_order_doc.items:
                            if item.item_code:
                                item_doc = frappe.get_doc("Item", item.item_code)
                                if item_doc.item_group:
                                    try:
                                        item_group_doc = frappe.get_doc("Item Group", item_doc.item_group)
                                        if hasattr(item_group_doc, 'default_charge') and item_group_doc.default_charge:
                                            total_default_charge += float(item_group_doc.default_charge)
                                            found_charges = True
                                    except:
                                        continue
                        
                        if found_charges and total_default_charge > 0:
                            consignmentValue = total_default_charge
                        else:
                            consignmentValue = 300.0
            # COD checked 
            elif sales_order_doc.is_cod == 1:
                PaymentType = "COD"
                consignmentValue = float(sales_order_doc.total_outstanding or 0)
            # normat Prepaid   
            else:
                PaymentType = "Prepaid"
                if sales_order_doc.grand_total:
                    consignmentValue = float(sales_order_doc.grand_total)
                else:
                    total_default_charge = 0
                    found_charges = False
                    
                    for item in sales_order_doc.items:
                        if item.item_code:
                            item_doc = frappe.get_doc("Item", item.item_code)
                            if item_doc.item_group:
                                try:
                                    item_group_doc = frappe.get_doc("Item Group", item_doc.item_group)
                                    if hasattr(item_group_doc, 'default_charge') and item_group_doc.default_charge:
                                        total_default_charge += float(item_group_doc.default_charge)
                                        found_charges = True
                                except:
                                    continue
                    
                    if found_charges and total_default_charge > 0:
                        consignmentValue = total_default_charge
                    else:
                        consignmentValue = 300.0
        else:
            frappe.throw("Sales Order not linked to this Delivery Note.")      
        # Fetch item groups
        item_group_value = frappe.db.get_value(
            "NJ Settings", {"parameter": "Item Group Validation"}, "value"
        )
        allowed_item_groups = []
        if item_group_value:
            allowed_item_groups = [group.strip() for group in item_group_value.split(",")]
        
        total_quantity = 0
        items = []
        for row in doc.get('items', []):
            item_group = frappe.db.get_value("Item", row.get("item_code"), "item_group")
            
            if not allowed_item_groups or item_group in allowed_item_groups:
                qty = float(row.get('qty', 1))
                total_quantity += qty  
                items.append({
                    "Length": f"{float(doc.length):.2f}",
                    "Breadth": f"{float(doc.breadth):.2f}",
                    "Height": f"{float(doc.height):.2f}",
                    "ProductCode": "AUTO",
                    "ProductDescription": row.get("item_name"),
                    "SplitPcs": f"{qty:.4f}",  
                    "IsPackaging": "0"
                })
            else:
                print(f"Skipping item {row.get('item_name')} - item group {item_group} not in allowed list")
        
        if not items:
            frappe.throw("No items found with allowed item groups for shipping.")
        transport = doc.mode_of_transfer
        if against_sales_order:
            sales_order_doc = frappe.get_doc("Sales Order", against_sales_order)
        # Function to determine ClientCode based on the fetched transport mode
        def get_client_code(transport_mode):
            if transport_mode == "Air":
                return frappe.db.get_single_value("Logistics Settings", "air")
            elif transport_mode == "Surface":
                return frappe.db.get_single_value("Logistics Settings", "surface")
            elif transport_mode == "COD Air":
                return frappe.db.get_single_value("Logistics Settings", "cod_air")
            elif transport_mode == "COD Surface":
                return frappe.db.get_single_value("Logistics Settings", "cod_surface")
        client_code = get_client_code(transport)
        print("ClientCode:========================", client_code)
        # Prepare header with correct total quantity
        header = {
            "ClientCode": client_code,
            "OrderNo/InvoiceNo": doc.name,
            "Order/InvoiceDate": formatted_date,
            "SenderName": doc.company,
            "SenderAdd1": company_address.address_line1 or " ",
            "SenderAdd2": company_address.address_line2 or "",
            "SenderCity": company_address.city or "",
            "SenderState": company_address.state or "",
            "SenderCountry": company_address.country or "India",
            "SenderPin": company_address.pincode or "",
            "SenderMobile": sanitize_phone(company_address.phone),
            "SenderEmail": company_address.email_id or "",
            "ReceiverName": doc.customer_name or "",
            "ReceiverAdd1": shipping_address.address_line1 or "",
            "ReceiverAdd2": shipping_address.address_line2 or " ",
            "ReceiverCity": shipping_address.city or "",
            "ReceiverState": shipping_address.state or "",
            "ReceiverCountry": shipping_address.country or "India",
            "ReceiverPin": shipping_address.pincode or "",
            "ReceiverMobile": sanitize_phone(shipping_address.phone),
            "ConsignmentValue": str(doc.grand_total),
            "NoQuantity": int(total_quantity),  
            "consignmentValue": str(doc.grand_total),
            "Weight": f"{weight:.2f}",  
            "TransitMode": doc.mode_of_transfer,
            "ProductMode": "Normal",
            "PaymentType": PaymentType,
            "Amount": consignmentValue,
            "Need_CitImage": "1"
        }
        # print("header=======================",header)
        # Add validation to ensure quantities match
        calculated_total = sum(float(item["SplitPcs"]) for item in items)
        if abs(calculated_total - total_quantity) > 0.001: 
            frappe.throw(f"Quantity mismatch: Total quantity ({total_quantity}) doesn't match sum of split quantities ({calculated_total})")
        
        data = {
            "ResponseHeader": "yes",
            "Header": [header],
            "ItemsDetails": items
        }
        url = frappe.db.get_single_value("Logistics Settings", "url")
        # url = "https://testing.ecritica.co/eFreightLive/api/con_generation.php"
        # url = "https://www.ecritica.co/eFreightLive/api/con_generation.php"
        headers = {"Content-Type": "application/json"}
        # print("headers=======================",headers)
        response = requests.post(url, headers=headers, json=data)
        # print("response=======================",response)
        resp_json = response.json()
        # print("resp_json=======================",resp_json)
        if resp_json.get('code') == 1 and resp_json.get('status') == 200:
            tracking_id = resp_json.get('data', {}).get('AWB Number') or resp_json.get('data', {}).get('AWBNumber')
            cit_data = resp_json.get('data', {}).get('CitImage') or resp_json.get('CitImage')          
            # Update the Sales Order document with AWB number, CIT image, cost of delivery, and courier service
            delivery_note = frappe.get_doc("Delivery Note", doc.name)
            delivery_note.tracking_id = tracking_id
            delivery_note.cit_image = cit_data
            delivery_note.cost_of_delivery = cost_of_delivery
            delivery_note.courier_service = "CriticaLog"  # Set courier service
            delivery_note.item_group_qty = total_quantity
            delivery_note.save()           
            # Use db_set to update without triggering validations or changing docstatus
            # delivery_note.db_set('tracking_id', tracking_id)
            # delivery_note.db_set('cit_image', cit_data)
            # delivery_note.db_set('cost_of_delivery', cost_of_delivery)
            # delivery_note.db_set('courier_service', 'CriticaLog')
            # delivery_note.db_set('item_group_qty', total_quantity)            
            frappe.msgprint(f"AWB Number generated successfully: {tracking_id}") 
            return {"awb_number": tracking_id, "cit_image": cit_data, "cost_of_delivery": cost_of_delivery}           
        else:
            frappe.throw(f"API returned error: {response.text}")
         
    except Exception as e:
        frappe.throw(f"Failed to send data to Criticalog API. Error: {str(e)}")   
@frappe.whitelist()
def shiprocket_awb_number(doc):
    """Create a ShipRocket consignment, assign an AWB, and generate a manifest and invoice."""
    try:
        frappe.log_error(f"Starting shiprocket_awb_number for doc: {doc}", "Debug")
        doc = frappe._dict(json.loads(doc))
        frappe.log_error(f"Parsed doc: {doc.name}", "Debug")
        auth_token = get_auth_token().get("token")

        if not auth_token:
            frappe.throw("Authentication token could not be retrieved from Shiprocket.")   
        try:
            delivery_note_doc = frappe.get_doc("Delivery Note", doc.name)
            total_qty = 0
            for item in delivery_note_doc.items:
                is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")
                
                # Only add qty if is_stock_item is 1 (i.e., checked/true)
                if is_stock_item == 1:
                    total_qty += item.qty

            # Update the item_group_qty field in the parent Delivery Note
            frappe.db.set_value("Delivery Note", doc.name, "item_group_qty", total_qty)
            against_sales_order = frappe.get_value(
                "Delivery Note Item", {"parent": delivery_note_doc.name}, "against_sales_order"
            )       
            shipping_address = frappe.get_doc("Address", delivery_note_doc.shipping_address_name) if delivery_note_doc.shipping_address_name else None    
            if not shipping_address:
                frappe.throw("Shipping address is required")
            formatted_date = datetime.today().strftime("%Y-%m-%d")

            # Prepare order_items from child table - ShipRocket format
            order_items = []
            for row in delivery_note_doc.items:
                item_code = row.item_code or ""
                trimmed_code = item_code[-50:] if len(item_code) > 50 else item_code

                order_items.append({
                    "name": trimmed_code,
                    "sku": trimmed_code,
                    "units": int(row.qty),
                    "selling_price": str(row.rate * 1.18),
                    "discount": "",
                    "tax": 18.0,
                    "hsn": ""
                })

            if against_sales_order:
                sales_order_doc = frappe.get_doc("Sales Order", against_sales_order)

                # Case 1: COD checked but also payment received → run normal prepaid flow
                if sales_order_doc.is_cod == 1 and sales_order_doc.payment_received == 1:
                    # print("Case 1: COD checked but also payment received → run normal prepaid flow")
                    payment_method = "Prepaid"

                    if delivery_note_doc.grand_total:
                        sub_total = float(delivery_note_doc.grand_total)
                    else:
                        # If grand_total not found, fetch from item groups
                        total_default_charge = 0
                        found_charges = False                

                        # Loop through items in Delivery Note
                        for item in delivery_note_doc.items:
                            if item.item_code:
                                try:
                                    item_doc = frappe.get_doc("Item", item.item_code)
                                    if item_doc.item_group:
                                        item_group_doc = frappe.get_doc("Item Group", item_doc.item_group)
                                        if getattr(item_group_doc, 'default_charge', None):
                                            total_default_charge += float(item_group_doc.default_charge)
                                            found_charges = True
                                except:
                                    continue

                        if found_charges and total_default_charge > 0:
                            sub_total = total_default_charge
                        else:
                            sub_total = 300.0

                # Case 2: Only COD checked → COD flow
                elif sales_order_doc.is_cod == 1:
                    # print("Case 2: Only COD checked → COD flow")
                    payment_method = "COD"
                    sub_total = float(sales_order_doc.total_outstanding or 0)

                # Case 3: Normal Prepaid flow (non-COD orders)
                else:
                    payment_method = "Prepaid"
                    sales_order_doc = frappe.get_doc("Sales Order", against_sales_order)

                    # --- Check if sale_type is NJ_Website_B2C ---
                    if getattr(sales_order_doc, "order_type", None) == "Maintenance":
                        # print("sale_type = Maintenance", sales_order_doc.order_type)

                        dn_total = float(delivery_note_doc.grand_total or 0)
                        # print("Delivery Note grand_total:", dn_total)

                        # Compare grand_total with 4000, take the maximum
                        sub_total = max(dn_total, 4000)
                        # print("sub_total (max of grand_total or 4000):", sub_total)

                    else:
                        if delivery_note_doc.grand_total:
                            sub_total = float(delivery_note_doc.grand_total)

                        else:
                            total_default_charge = 0
                            found_charges = False                

                            for item in delivery_note_doc.items:
                                if item.item_code:
                                    try:
                                        item_doc = frappe.get_doc("Item", item.item_code)
                                        if item_doc.item_group:
                                            item_group_doc = frappe.get_doc("Item Group", item_doc.item_group)
                                            if getattr(item_group_doc, 'default_charge', None):
                                                total_default_charge += float(item_group_doc.default_charge)
                                                found_charges = True
                                    except:
                                        continue

                            if found_charges and total_default_charge > 0:
                                sub_total = total_default_charge
                            else:
                                sub_total = 300.0
            else:
                frappe.throw("Sales Order not linked to this Delivery Note.")

            data = {
                "order_id": delivery_note_doc.name,
                "order_date": formatted_date,
                "pickup_location": "Office",
                "comment": f"Order from {delivery_note_doc.customer_name}",
                "billing_customer_name": delivery_note_doc.customer_name or "",
                "billing_last_name": "",
                "billing_address": shipping_address.address_line1 if shipping_address.address_line1 else "",
                "billing_address_2": shipping_address.address_line2 if shipping_address.address_line2 else "",
                "billing_city": shipping_address.city if shipping_address.city else "",
                "billing_pincode": shipping_address.pincode if shipping_address.pincode else "",
                "billing_state": shipping_address.state if shipping_address.state else "",
                "billing_country": shipping_address.country if shipping_address.country else "India",
                "billing_email": shipping_address.email_id if shipping_address.email_id else "",
                "billing_phone":sanitize_phone(shipping_address.phone),
                "shipping_is_billing": True,
                "shipping_customer_name": "",
                "shipping_last_name": "", 
                "order_items": order_items,
                "payment_method": payment_method,
                "sub_total": sub_total,
                "length": str(delivery_note_doc.length),
                "breadth": str(delivery_note_doc.breadth), 
                "height": str(delivery_note_doc.height),
                "weight": str(delivery_note_doc.weight)
            }
            # url = "https://apiv2.shiprocket.in/v1/external/orders/create/adhoc"
            url = frappe.db.get_single_value("Logistics Settings", "adhoc_url")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {auth_token.strip()}"
            }
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                try:
                    resp_json = response.json()
                    # print("response:--------159", response.json())
                    if resp_json.get('order_id'):
                        # Update document with ShipRocket IDs

                        frappe.db.set_value("Delivery Note", doc.name, {
                            "shiprocket_order_id": resp_json.get("order_id"),
                            "shiprocket_shipment_id": resp_json.get("shipment_id")
                        }, update_modified=False)
                        
                        # Update local doc object for further processing
                        doc.shiprocket_order_id = resp_json.get('order_id')
                        doc.shiprocket_shipment_id = resp_json.get('shipment_id')
                        
                        frappe.db.commit()
                    else:
                        frappe.throw(f"Order creation failed: {response.text}")
                except ValueError as json_err:
                    frappe.throw(f"Could not parse API response: {response.text}")
            else:
                # Handle different error codes
                if response.status_code == 401:
                    frappe.throw("Authentication failed. Please check your ShipRocket credentials.")
                elif response.status_code == 422:
                    frappe.throw(f"Validation error: {response.text}")
                else:
                    frappe.throw(f"API request failed with status {response.status_code}: {response.text}")
                    
        except Exception as e:
            frappe.log_error(f"Consignment API Failed for {doc.name}: {str(e)}", frappe.get_traceback())
            frappe.throw(f"Failed to send data to ShipRocket API. Error: {str(e)}")

        if not doc.shiprocket_shipment_id:
            frappe.throw("Shipment ID not found on the document after consignment creation.")
        
        shipment_id = doc.shiprocket_shipment_id
        invoice_order_id = doc.shiprocket_order_id
        shipment_list = [int(shipment_id)]

        # 1. Service Availability
        service_url = frappe.db.get_single_value("Logistics Settings", "service_url")
        service_response = requests.get(service_url, headers=headers, json={"order_id": invoice_order_id})
        service_json = service_response.json()
        courier_data = service_json.get("data", {}).get("available_courier_companies", [])
        if not courier_data:
            frappe.throw("No courier companies found in serviceability response.")

        # Get  courier names from Logistics Settings child table
        logistics_settings = frappe.get_doc("Logistics Settings")
        skipping_courier_names = []
        logistics_settings = frappe.get_doc("Logistics Settings")
        allowed_courier_names = []
        if logistics_settings and logistics_settings.shiprocketcourier_name_block_list:
            allowed_courier_names = [row.courier_name.strip() for row in logistics_settings.shiprocketcourier_name_block_list if row.courier_name]
        if not allowed_courier_names:
            frappe.throw("Allowed Courier Names not found in the child table. Please configure the allowed courier list in Logistics Settings.")

        # Check if any of the allowed courier names exist in the response
        response_courier_names = [courier.get("courier_name", "") for courier in courier_data]
        matching_couriers = [name for name in allowed_courier_names if name in response_courier_names]

        if not matching_couriers:
            frappe.throw(f"None of the allowed courier names from Logistics settings were found in the service response. Allowed: {allowed_courier_names}, Available: {response_courier_names}")
        # Calculate total charges for each courier
        best_courier = None
        lowest_total = float('inf')
        log_rating = frappe.db.get_single_value("Logistics Settings", "rating")
        for courier in courier_data:
            try:
                courier_name = courier.get("courier_name", "")
                etd = courier.get("etd", "")
                etd_hours = courier.get("etd_hours", "")
                freight_charge = float(courier.get("freight_charge", 0) or 0)
                cod_charges = float(courier.get("cod_charges", 0) or 0)
                charge_weight = float(courier.get("charge_weight", 0) or 0)
                coverage_charges = float(courier.get("coverage_charges", 0) or 0)
                other_charges = float(courier.get("other_charges", 0) or 0)
                rto_charges = float(courier.get("rto_charges", 0) or 0)
                
                # Only consider couriers that are in the allowed list
                if courier_name and allowed_courier_names:
                    if courier_name not in allowed_courier_names:
                        continue 
                else:
                    # If no allowed list is configured, skip this courier
                    continue        
                # Check rating - skip if 4 or below
                log_rating = frappe.db.get_single_value("Logistics Settings", "rating")
                rating = float(courier.get("rating", 0) or 0)
                if rating < log_rating:
                    continue           
                freight_charge = float(courier.get("freight_charge", 0) or 0)
                cod_charges = float(courier.get("cod_charges", 0) or 0)
                total = freight_charge + cod_charges
                
                # Select courier with lowest total cost
                if total < lowest_total:
                    lowest_total = total
                    best_courier = {
                        "courier_name": courier_name,
                        "courier_company_id": courier.get("courier_company_id"),
                        "total_cost": total,
                        "rating": rating,
                        "freight_charge": freight_charge,
                        "cod_charges": cod_charges,
                        "charge_weight": courier.get("charge_weight", 0),
                        "coverage_charges": courier.get("coverage_charges", 0),
                        "other_charges": courier.get("other_charges", 0),
                        "rto_charges": courier.get("rto_charges", 0),
                        "etd": courier.get("etd", ""),
                        "etd_hours": courier.get("etd_hours", "")
                    }
            except (ValueError, TypeError) as e:
                continue

        if not best_courier:
            frappe.throw(f"No suitable courier found from the allowed courier list with rating above {log_rating}.")
        if best_courier:
            courier_service_name = best_courier.get("courier_name")     
            if courier_service_name:
                if not frappe.db.exists("Courier Service", courier_service_name):
                    courier_service_doc = frappe.get_doc({
                        "doctype": "Courier Service",
                        "courier_name": courier_service_name,
                        "tracking_url": "https://shiprocket.co/tracking/"
                    })
                    courier_service_doc.insert(ignore_permissions=True)
                else:
                    print(f"Courier Service '{courier_service_name}' already exists")
                
                # Set values on Delivery Note
                delivery_note_doc.db_set("courier_service", courier_service_name)
                
            else:
                frappe.throw("Courier name not found in best courier selection")    
        # Calculate total item charges
        total_item_charges = 0
        for item in doc.get("items", []):
            if not item.get("item_code"):
                continue
            # Get item group
            item_group = frappe.db.get_value("Item", item.get("item_code"), "item_group") 
            group_doc = frappe.get_doc("Item Group", item_group)
            item_charges = group_doc.get("item_charges")
            if item_charges and item.get("qty"):
                item_total_charge = float(item_charges) * float(item.get("qty"))
                total_item_charges += item_total_charge
            else:
                print("Missing item_charges or quantity for item:", item.get("item_code"))

        # Calculate total COD charges
        is_cod = False
        if against_sales_order:
            is_cod = frappe.db.get_value("Sales Order", against_sales_order, "is_cod") or 0
        # COD Validation - Check if is_cod is enabled
        if is_cod == 1:            
            if best_courier:
                # Calculate total cost with weight
                freight_charge = best_courier.get('freight_charge', 0)
                cod_charges = best_courier.get('cod_charges', 0)
                doc_weight = doc.get('weight', 0) or 0
                
                total_cost = (freight_charge ) + cod_charges
                # Fetch COD charges from Ship Rocket Settings
                ship_rocket_settings = frappe.get_doc("Ship Rocket Settings")
                cod_charges_table = ship_rocket_settings.get("cod_charges", [])
                charges_value = None
                for cod_charge_row in cod_charges_table:
                    charges_value = cod_charge_row.charges_value  
                    if charges_value:
                        break         
                if charges_value:              
                    # Extract numeric value from percentage string (e.g., "8%" -> 8)
                    numeric_charges_value = float(charges_value.replace('%', '').strip())
                    
                    # Calculate percentage of grand_total    
                    grand_total = float(doc.get("grand_total", 0) or 0)
                    cod_percentage_amount = round((numeric_charges_value / 100) * grand_total, 2)
                    cod_and_item_charges_total = cod_percentage_amount+total_item_charges

                    # Compare COD percentage amount with total_cost
                    if cod_and_item_charges_total< total_cost:
                        frappe.throw(f"COD validation failed: COD charges courier total cost ({total_cost:.2f}) is greater than ({numeric_charges_value:.2f}% of grand total = {cod_and_item_charges_total:.2f})")             
                else:
                    frappe.throw("No COD charges value found in Ship Rocket Settings")
        else:
            # print("COD is not enabled, skipping COD validation...")
            # Check if courier total cost exceeds item charges total for non-COD orders
            if best_courier and best_courier.get('total_cost', 0) > total_item_charges:
                frappe.throw(f"Cannot generate AWB number because courier '{best_courier.get('courier_name')}' total cost ({best_courier.get('total_cost')}) is more than item charges total ({total_item_charges})")

        # Update Delivery Note with courier details
        frappe.db.set_value("Delivery Note", doc.name, {
            "shiprocket_courier_name": best_courier.get("courier_name"),
            "etd": best_courier.get("etd"),
            "etd_hours": best_courier.get("etd_hours"),
            "cod_charges": best_courier.get("cod_charges"),
            "freight_charge": best_courier.get("freight_charge"),
            "charge_weight": best_courier.get("charge_weight"),
            "coverage_charges": best_courier.get("coverage_charges"),
            "other_charges": best_courier.get("other_charges"),
            "rto_charges": best_courier.get("rto_charges")
        }, update_modified=False)

        # 2. AWB Assignment
        # awb_url = "https://apiv2.shiprocket.in/v1/external/courier/assign/awb"
        awb_url = frappe.db.get_single_value("Logistics Settings", "awb_number_url")

        awb_response = requests.post(awb_url, headers=headers, json={
            "shipment_id": shipment_id,
            "courier_id": best_courier.get("courier_company_id")
        })
        awb_json = awb_response.json()
        if "message" in awb_json:
            frappe.throw(f"ShipRocket AWB Assignment Failed: {awb_json.get('message')}")

        response_data = awb_json.get("response", {})
        data = response_data.get("data", {})
        awb_code = None
        pickup_scheduled_date = None
        if isinstance(data, dict):
            awb_code = data.get("awb_code")
            invoice_no = data.get("invoice_no")
            transporter_id = data.get("transporter_id")
            transporter_name = data.get("transporter_name")
            pickup_scheduled_date = data.get("pickup_scheduled_date")  
        else:

            frappe.throw(f"ShipRocket AWB Assignment Failed: Invalid response format - {data}")
            # ✅ Save AWB Code and other details to Delivery Note
        frappe.db.set_value("Delivery Note", doc.name, {
            "tracking_id": awb_code,
            "lr_no": invoice_no,
            "gst_transporter_id": transporter_id,
            "transporter_name": transporter_name
        } ,update_modified=False)

        if pickup_scheduled_date:
            frappe.db.set_value("Delivery Note", doc.name, "pickup_scheduled_date", pickup_scheduled_date,update_modified=False)
            frappe.msgprint(f"AWB: {awb_code} assigned successfully. Pickup scheduled for: {pickup_scheduled_date}")
        else:
            # 3. Pickup Generation (when pickup date was not in AWB response)
            try:
                # pickup_url = "https://apiv2.shiprocket.in/v1/external/courier/generate/pickup"
                pickup_url = frappe.db.get_single_value("Logistics Settings", "pickup_url")
                pickup_response = requests.post(pickup_url, headers=headers, json={"shipment_id": shipment_list})
                pickup_json = pickup_response.json()

                if "message" in pickup_json and pickup_json.get("message") != "Pickup scheduled successfully":
                    frappe.msgprint(f"Pickup scheduling message: {pickup_json.get('message')}")
                
                pickup_date = None
                response_data = pickup_json.get("response", {})
                
                if isinstance(response_data, dict):
                    pickup_date = response_data.get("pickup_scheduled_date")
                    if not pickup_date:
                        pickup_date = response_data.get("pickup_date")
                
                if pickup_date:
                    frappe.db.set_value("Delivery Note", doc.name, "pickup_scheduled_date", pickup_date,update_modified=False)
                    frappe.msgprint(f"AWB: {awb_code} assigned successfully. Pickup scheduled for: {pickup_date}")
                else:
                    frappe.msgprint(f"AWB: {awb_code} assigned successfully. Pickup may have been scheduled - please check ShipRocket dashboard.")
                    
            except Exception as e:
                frappe.msgprint(f"AWB: {awb_code} assigned successfully, but pickup scheduling encountered an issue: {str(e)}")
        # 5. Invoice Generation
        invoice_order_id = doc.shiprocket_order_id
        # invoice_url = "https://apiv2.shiprocket.in/v1/external/orders/print/invoice"
        invoice_url = frappe.db.get_single_value("Logistics Settings", "invoice_url")
        invoice_response = requests.post(invoice_url, headers=headers, json={"ids": [invoice_order_id]})
        invoice_json = invoice_response.json()
        invoice_pdf_url = invoice_json.get("invoice_url")
        if not invoice_pdf_url:
            frappe.throw("Invoice URL not found in response.")
        invoice_file_response = requests.get(invoice_pdf_url)
        if invoice_file_response.status_code != 200:
            frappe.throw(f"Could not fetch invoice PDF: {invoice_file_response.status_code}")
        invoice_pdf_b64 = base64.b64encode(invoice_file_response.content).decode()
        frappe.db.set_value("Delivery Note", doc.name, "shiprocket_invoice", invoice_pdf_b64,update_modified=False)

        # 6. Label Generation
        # label_url = "https://apiv2.shiprocket.in/v1/external/courier/generate/label"
        label_url = frappe.db.get_single_value("Logistics Settings", "label_url")
        label_response = requests.post(label_url, headers=headers, json={"shipment_id": shipment_list})
        label_json = label_response.json()
        label_link = label_json.get("label_url")
        if not label_link:
            frappe.throw("Label URL not found in response.")
        label_file_response = requests.get(label_link)
        if label_file_response.status_code != 200:
            frappe.throw(f"Could not fetch label PDF: {label_file_response.status_code}")
        label_pdf_b64 = base64.b64encode(label_file_response.content).decode()
        frappe.db.set_value("Delivery Note", doc.name, "shiprocket_image", label_pdf_b64,update_modified=False) 
        
        # 4. Manifest Generation
        # manifest_url = "https://apiv2.shiprocket.in/v1/external/manifests/generate"
        manifest_url = frappe.db.get_single_value("Logistics Settings", "manifest_url")
        manifest_response = requests.post(manifest_url, headers=headers, json={"shipment_id": shipment_list})
        manifest_json = manifest_response.json()

        # Check if there's an error message in the response
        if "message" in manifest_json:
            frappe.throw(f"Manifest Generation Error: {manifest_json.get('message')}")
        # Get manifest URL
        manifest_pdf_url = manifest_json.get("manifest_url")
        if not manifest_pdf_url:
            frappe.throw(f"Manifest URL not found. Full response: {manifest_json}")
          # Fetch and save manifest PDF
        manifest_file_response = requests.get(manifest_pdf_url)
        if manifest_file_response.status_code != 200:
            frappe.throw(f"Could not fetch manifest PDF: {manifest_file_response.status_code}")

        manifest_pdf_b64 = base64.b64encode(manifest_file_response.content).decode()
        frappe.db.set_value("Delivery Note", doc.name, "shiprocket_manifests", manifest_pdf_b64,update_modified=False)
        frappe.db.commit()

        return {
            "awb_code": awb_code,
            "pickup_scheduled_date": pickup_scheduled_date,
            "etd": best_courier.get("etd"),
            "charge_weight": best_courier.get("charge_weight"),
            "cod_charges": best_courier.get("cod_charges"),
            "coverage_charges": best_courier.get("coverage_charges"),
            "freight_charges": best_courier.get("freight_charge"),
            "other_charges": best_courier.get("other_charges"),
            "rto_charges": best_courier.get("rto_charges"),
            "etd_hours": best_courier.get("etd_hours"),
            "label_url": label_link,
            "manifest_url": manifest_pdf_url,
            "invoice_url": invoice_pdf_url,
            "shiprocket_courier_name": best_courier.get("courier_name"),
            "tranporter_name": transporter_name,
            "lr_no": invoice_no,
            "gst_transporter_id": transporter_id,
        }
    except Exception as e:
        frappe.log_error(f"Error in shiprocket_awb_number: {str(e)}", frappe.get_traceback())
        raise

@frappe.whitelist()
def fetch_shiprocket_details(doc):
    try:
        if isinstance(doc, str):
            doc = json.loads(doc)

        auth_token = get_auth_token().get("token")
        dn_name = doc.get("name")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token.strip()}"
        }

        # 1. Fetch Shiprocket order by channel_order_id
        # fetch_url = f"https://apiv2.shiprocket.in/v1/external/orders?filter_by=channel_order_id&filter=DN-257570"
        fetch_url = f"https://apiv2.shiprocket.in/v1/external/orders?filter_by=channel_order_id&filter={dn_name}"
        response = requests.get(fetch_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        frappe.logger().info(f"Shiprocket order fetch response: {data}")

        # 2. Extract order id and shipment id
        orders = data.get("data", [])    
        if not orders:
            frappe.throw("No orders found in Shiprocket for this Delivery Note")

        order_data = orders[0]
        invoice_order_id = order_data.get("id")
        shipment_lists = [invoice_order_id]
        shipments = order_data.get("shipments", [])

        if not invoice_order_id:
            frappe.throw("Order ID not found in Shiprocket response")
        if not shipments:
            frappe.throw("No shipments found for this order in Shiprocket")

        shipment_data = shipments[0]
        shipment_id = shipment_data.get("id")  # first shipment id
        shipment_list = [shipment_id]

        # Extract required fields for mapping
        courier_name = shipment_data.get("courier")
        pickup_scheduled_date = shipment_data.get("pickup_scheduled_date")
        awb = shipment_data.get("awb")
        # Save values in Delivery Note
        frappe.db.set_value("Delivery Note", dn_name, {
            "shiprocket_order_id": invoice_order_id,
            "shiprocket_shipment_id": shipment_id,
            "shiprocket_courier_name": courier_name,
            "courier_name": courier_name,
            "pickup_scheduled_date": pickup_scheduled_date,
            "tracking_id": awb,
            # "freight_charges": freight_charges
        }, update_modified=False)
        # order_data = orders[0]
        # invoice_order_id = order_data.get("id")
        shipments = order_data.get("shipments", [])
        if not invoice_order_id:
            frappe.throw("Order ID not found in Shiprocket response")
        if not shipments:
            frappe.throw("No shipments found for this order in Shiprocket")

        shipment_id = shipments[0].get("id") 
        shipment_list = [shipment_id]

        # 3. Generate Invoice
        invoice_url = "https://apiv2.shiprocket.in/v1/external/orders/print/invoice"
        invoice_response = requests.post(invoice_url, headers=headers, json={"ids": [invoice_order_id]})
        invoice_response.raise_for_status()
        invoice_json = invoice_response.json()
        frappe.logger().info(f"Shiprocket invoice response: {invoice_json}")

        invoice_pdf_url = invoice_json.get("invoice_url")
        if not invoice_pdf_url:
            frappe.throw("Invoice URL not found in Shiprocket response")

        invoice_file_response = requests.get(invoice_pdf_url)
        if invoice_file_response.status_code != 200:
            frappe.throw(f"Could not fetch invoice PDF: {invoice_file_response.status_code}")

        invoice_pdf_b64 = base64.b64encode(invoice_file_response.content).decode()
        frappe.db.set_value("Delivery Note", dn_name, "shiprocket_invoice", invoice_pdf_b64, update_modified=False)

        # 4. Generate Label
        label_url = "https://apiv2.shiprocket.in/v1/external/courier/generate/label"
        label_response = requests.post(label_url, headers=headers, json={"shipment_id": shipment_list})
        label_response.raise_for_status()
        label_json = label_response.json()
        frappe.logger().info(f"Shiprocket label response: {label_json}")

        label_link = label_json.get("label_url")
        if not label_link:
            frappe.throw("Label URL not found in Shiprocket response")

        label_file_response = requests.get(label_link)
        if label_file_response.status_code != 200:
            frappe.throw(f"Could not fetch label PDF: {label_file_response.status_code}")

        label_pdf_b64 = base64.b64encode(label_file_response.content).decode()
        frappe.db.set_value("Delivery Note", dn_name, "shiprocket_image", label_pdf_b64, update_modified=False)
        # 5. Generate Manifest
        manifest_endpoints = [
            "https://apiv2.shiprocket.in/v1/external/manifests/generate",
            "https://apiv2.shiprocket.in/v1/external/manifests/print"
        ]

        manifest_pdf_url = None

        for url in manifest_endpoints:
            manifest_response = requests.post(url, headers=headers, json={"order_ids": shipment_lists})
            manifest_response.raise_for_status()
            manifest_json = manifest_response.json()
            frappe.logger().info(f"Shiprocket manifest response from {url}: {manifest_json}")

            # Check if API returned an error message
            if "message" in manifest_json:
                frappe.logger().warning(f"Manifest API message: {manifest_json.get('message')}")

            manifest_pdf_url = manifest_json.get("manifest_url")
            if manifest_pdf_url:
                break  # Found manifest, exit loop

        if not manifest_pdf_url:
            frappe.throw(f"Manifest URL not found from both APIs. Full response: {manifest_json}")

        # Fetch PDF
        manifest_file_response = requests.get(manifest_pdf_url)
        if manifest_file_response.status_code != 200:
            frappe.throw(f"Could not fetch manifest PDF: {manifest_file_response.status_code}")

        manifest_pdf_b64 = base64.b64encode(manifest_file_response.content).decode()
        frappe.db.set_value("Delivery Note", dn_name, "shiprocket_manifests", manifest_pdf_b64, update_modified=False)

        return {
            "status": "success",
            "order_id": invoice_order_id,
            "shipment_id": shipment_id,
            "invoice_url": invoice_pdf_url,
            "label_url": label_link,
            "manifest_url": manifest_pdf_url
        }

    except Exception as e:
        frappe.log_error(f"Error fetching Shiprocket invoice/label/manifest: {str(e)}", frappe.get_traceback())
        raise

def adapter_repacked_serial_no(nj_serial_no):
    try:
        # query="""
        #     SELECT tot_sed.serial_no as adapter_serial_no
        #     FROM `tabStock Entry Detail` AS sed
        #     INNER JOIN `tabStock Entry Detail` AS tot_sed ON tot_sed.parent = sed.parent
        #     INNER JOIN `tabStock Entry` AS stock_entry ON stock_entry.name = sed.parent
        #     WHERE
        #         (sed.serial_no = %(serial_no)s OR 
        #             sed.serial_no LIKE CONCAT(%(serial_no)s, '\\n%%') OR 
        #             sed.serial_no LIKE CONCAT('%%\\n', %(serial_no)s) OR 
        #             sed.serial_no LIKE CONCAT('%%\\n', %(serial_no)s, '\\n%%')) AND
        #         stock_entry.purpose = 'Repack' AND 
        #         stock_entry.docstatus = 1 AND
        #         tot_sed.s_warehouse IS NOT NULL AND 
        #         tot_sed.item_group = 'Laptop Adaptors'
        #     ORDER BY stock_entry.creation DESC
        #     LIMIT 1
        # """
        partlist_query="""
          Select component_serial_no as adapter_serial_no from `tabSerial No Component` where parent=%s and item_group="Laptop Adaptors" and component_serial_no <> "" order by item_group_idx desc limit 1;
        """
        if nj_serial_no is not None and nj_serial_no:

            data=frappe.db.sql(partlist_query, nj_serial_no, as_dict=1)
        
            if data is not None and data:  
                return data[0].get("adapter_serial_no","")
           
        return "Empty"
                
    except Exception as e:
        log_error(traceback.format_exc(),"Error while getting adapter repacked serial no in for serial no "+nj_serial_no)
        return str(e)
    
@frappe.whitelist()
def sanitize_phone(phone):
    digits = ''.join(filter(str.isdigit, phone or ""))
    # If phone has more than 10 digits, take the last 10
    if len(digits) > 10:
        digits = digits[-10:]
    # Return only if it's exactly 10 digits
    return digits if len(digits) == 10 else ""

@frappe.whitelist()
def allow_to_save(doc):
    try:
        if isinstance(doc,str):
            doc=json.loads(doc)
        is_return=frappe.db.get_value("Delivery Note",{"name":doc.get("name","")},"is_return")
        if is_return is not None and is_return==1:
            return "pass"
        execute=frappe.db.get_value("NJ Settings", {"parameter": "Adaptor_restriction_in_DN"}, "value")
        if execute is not None and execute=="0":
            return "pass"
        child_data=doc["packed_items"]
        dn_name=doc.get("name","")
        

        if not child_data:
            child_data=doc["items"]
        log_error(str(child_data),"child_data for dn name "+dn_name)
        for data in child_data:
            child_nj_serial_data=data.get("serial_no","")
            child_adapter_serial_no=data.get("adapter_serial_no","")
            nj_serial_nos=[]
            adapter_serial_nos=[]

            if  child_nj_serial_data:
                if '\n' in child_nj_serial_data:
                    nj_serial_nos=child_nj_serial_data.split('\n')
                else:
                    nj_serial_nos.append(child_nj_serial_data)
            else:
                continue

            if child_adapter_serial_no:
                if '\n' in child_adapter_serial_no:
                    adapter_serial_nos=child_adapter_serial_no.split('\n')
                else:
                    adapter_serial_nos.append(child_adapter_serial_no)

            serial_no_order=0
            log_error(str(adapter_serial_nos),"adapter_serial_nos for dn name "+dn_name)
            log_error(str(nj_serial_nos),"nj_serial_nos for dn name "+dn_name)
            
            for nj_serial_no in nj_serial_nos:
                item_group=frappe.db.get_value("Serial No",nj_serial_no,"item_group")
                if item_group and item_group=="Laptops" or item_group=="Chromebooks":
                    serial_no_order+=1
                    if not adapter_serial_nos:
                        return "Please enter Adapter Serial No"
                    else:
                        repacked_serial_no=adapter_repacked_serial_no(nj_serial_no)
                        try:
                          respective_adapter_serial_no=adapter_serial_nos[serial_no_order-1]
                          is_serial_no_encrypted=frappe.db.get_value("Serial No",respective_adapter_serial_no,"name")
                          if not is_serial_no_encrypted:
                              respective_adapter_serial_no=frappe.db.get_value("QR Code Mapping",{"doctype1":"Serial No","name":respective_adapter_serial_no},"serial_no")
                          if repacked_serial_no!=respective_adapter_serial_no:
                            return "Repacked Adapter Serial No for Serial No: " +nj_serial_no+ " does not match with the scanned Serial No:"+ str(adapter_serial_nos[serial_no_order-1])
                        except IndexError:
                          return "NO Adapter Serial No Found for Serial No:" + nj_serial_no
                else:
                    continue
        return "pass"
    
    except Exception as e:
        log_error(traceback.format_exc(),"Error while saving delivery note "+dn_name)
        return str(e)
    

@frappe.whitelist()
def setting_dispatch_address(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)

    bg_address = frappe.db.get_value("NJ Settings", {"parameter": "bg_dispatch_address"}, "value")
    nj_address = frappe.db.get_value("NJ Settings", {"parameter": "jn_dispatch_address"}, "value")

    dispatch_location = None

    for item in doc.get("items", []):
        warehouse = item.get("warehouse")
        if not warehouse:
            continue

        location = frappe.db.get_value("Warehouse", warehouse, "location")

        if location == "BG":
            dispatch_location = bg_address
            break
        elif location == "JN":
            dispatch_location = nj_address
            break
        elif location == "Vendor":
            # Get Address linked to this warehouse from Dynamic Link
            address_name = frappe.db.sql("""
                SELECT dl.parent 
                FROM `tabDynamic Link` dl
                WHERE dl.link_name = %s
                  AND dl.link_doctype = 'Warehouse'
                  AND dl.parenttype = 'Address'
                LIMIT 1
            """, warehouse, as_dict=True)
            if address_name:
                dispatch_location = address_name[0].parent
                break

    return dispatch_location

@frappe.whitelist()
def updating_new_address(sales_order_name=None): 
    """Fetch updated address from previously submitted Delivery Notes against the given Sales Order"""
    if not sales_order_name:
        return None

    # Fetch all submitted DN Items linked to SO
    delivery_notes = frappe.get_all(
        "Delivery Note Item",
        filters={"against_sales_order": sales_order_name, "docstatus": 1},
        fields=["parent"]
    )
    if not delivery_notes:
        return None

    # Loop through linked Delivery Notes and return the first updated address
    for dn in delivery_notes:
        dn_doc = frappe.get_doc("Delivery Note", dn.parent)
        if dn_doc.get("is_return") and dn_doc.get("updated_address"):
            return dn_doc.get("updated_address")

    return None

@frappe.whitelist()
def get_item_group_cost_centers(items):
    """
    Fetch cost centers for given item_groups in bulk.
    items comes as JSON string, so parse it first.
    """
    try:
        items = json.loads(items)
    except Exception:
        items = []

    result = {}
    for item in items:
        if item.get("item_group"):
            cost_center = frappe.db.get_value("Item Group", item["item_group"], "cost_center")
            if cost_center:
                result[item["idx"]] = cost_center
    return result




@frappe.whitelist()
def deviding_tax_chargese_dn(doc, method=None):
    if doc.is_return == 1:
        return

    # --------------------------------------------------
    # 1) Fetch Sales Invoices from DN
    # --------------------------------------------------
    sales_invoices = list(
        {
            item.against_sales_invoice
            for item in doc.items
            if item.against_sales_invoice
        }
    )
    print("sales_invoices========================", sales_invoices)

    if not sales_invoices:
        return

    # --------------------------------------------------
    # 2) Pick FIRST Sales Invoice only
    # --------------------------------------------------
    first_si = sales_invoices[0]
    sales_channel = frappe.db.get_value("Sales Invoice", first_si, "sales_channel")
    print("sale_type========================", sales_channel)

    # --------------------------------------------------
    # 3) Run validation ONLY for NJ-Website-B2C
    # --------------------------------------------------
    if sales_channel != "Amazon":
        return

    # --------------------------------------------------
    # 4) Fetch NJ Settings (Allowed tax accounts)
    # --------------------------------------------------
    nj_setting_value = frappe.db.get_value(
        "NJ Settings",
        {"parameter": "taxe_account_heads"},
        "value"
    )
    print("nj_setting_value=====================", nj_setting_value)
    if not nj_setting_value:
        return

    try:
        allowed_accounts = set(json.loads(nj_setting_value))
    except Exception:
        allowed_accounts = set(
            acc.strip() for acc in nj_setting_value.split(",") if acc.strip()
        )
    print("allowed_accounts=====================", allowed_accounts)

    # --------------------------------------------------
    # 5) Fetch SI TOTAL VALUE + CURRENT DN TOTAL
    # --------------------------------------------------
    si_total_value_rows = frappe.db.get_all(
        "Sales Invoice",
        filters={"name": ["in", sales_invoices], "docstatus": 1},
        fields=["name", "total"]
    )
    si_total_value_map = {row.name: flt(row.total) for row in si_total_value_rows}
    print("si_total_value_map=====================", si_total_value_map)

    current_dn_total = flt(doc.total)
    print("current_dn_total=====================", current_dn_total)

    if not current_dn_total:
        return

    # --------------------------------------------------
    # 6) Fetch UNMATCHED TAXES FROM Sales Invoice (per SI)
    # --------------------------------------------------
    si_unmatched_taxes = {}
    for si_name in sales_invoices:
        si_taxes = frappe.get_all(
            "Sales Taxes and Charges",
            filters={"parent": si_name, "parenttype": "Sales Invoice"},
            fields=["account_head", "charge_type", "tax_amount"]
        )
        print("si_taxes=====================", si_taxes)

        si_unmatched_taxes[si_name] = {}
        for tax in si_taxes:
            if tax.account_head not in allowed_accounts:
                si_unmatched_taxes[si_name][tax.account_head] = flt(tax.tax_amount)

    print("si_unmatched_taxes=====================", si_unmatched_taxes)
    if not any(si_unmatched_taxes.values()):
        return

    # --------------------------------------------------
    # 7) Allocate unmatched SI taxes by VALUE ratio
    # formula: (SI tax / SI total value) * current DN total
    # --------------------------------------------------
    allocated_tax_by_account = {}

    for si_name in sales_invoices:
        si_total_value = flt(si_total_value_map.get(si_name))
        current_dn_value = current_dn_total

        print("si_total_value=====================", si_total_value)
        print("current_dn_value=====================", current_dn_value)

        if not si_total_value or not current_dn_value:
            continue

        for account_head, si_tax_amount in (si_unmatched_taxes.get(si_name) or {}).items():
            divided_amount = round((flt(si_tax_amount) / si_total_value) * current_dn_value, 2)
            allocated_tax_by_account[account_head] = round(
                flt(allocated_tax_by_account.get(account_head)) + divided_amount, 2
            )
            print("divided_amount=====================", divided_amount)

    if not allocated_tax_by_account:
        return

    print("allocated_tax_by_account=====================", allocated_tax_by_account)

    # --------------------------------------------------
    # 8) Update SAME tax row in DN
    # --------------------------------------------------
    conversion_rate = flt(doc.conversion_rate) or 1
    for tax in doc.taxes:
        if tax.account_head in allocated_tax_by_account:
            tax_amount = flt(allocated_tax_by_account[tax.account_head])
            tax.tax_amount = tax_amount
            tax.base_tax_amount = round(tax_amount * conversion_rate, 2)


@frappe.whitelist()
def deviding_tax_chargese_return_dn(doc, method=None):
    # Run ONLY for return DN
    if doc.is_return != 1:
        return

    # --------------------------------------------------
    # 1) Fetch original DN from return_against
    # --------------------------------------------------
    original_dn_name = doc.return_against
    print("original_dn_name========================", original_dn_name)
    if not original_dn_name:
        return

    # --------------------------------------------------
    # 2) Check sales channel from original DN's first linked SI
    # --------------------------------------------------
    original_dn_sales_invoices = list(
        {
            item.against_sales_invoice
            for item in frappe.get_all(
                "Delivery Note Item",
                filters={"parent": original_dn_name},
                fields=["against_sales_invoice"]
            )
            if item.against_sales_invoice
        }
    )
    print("original_dn_sales_invoices========================", original_dn_sales_invoices)
    if not original_dn_sales_invoices:
        return

    first_si = original_dn_sales_invoices[0]
    sales_channel = frappe.db.get_value("Sales Invoice", first_si, "sales_channel")
    print("sales_channel========================", sales_channel)

    # --------------------------------------------------
    # 3) Run validation ONLY for Amazon
    # --------------------------------------------------
    if sales_channel != "Amazon":
        return

    # --------------------------------------------------
    # 4) Fetch NJ Settings (Allowed tax accounts)
    # --------------------------------------------------
    nj_setting_value = frappe.db.get_value(
        "NJ Settings",
        {"parameter": "taxe_account_heads"},
        "value"
    )
    print("nj_setting_value=====================", nj_setting_value)
    if not nj_setting_value:
        return

    try:
        allowed_accounts = set(json.loads(nj_setting_value))
    except Exception:
        allowed_accounts = set(
            acc.strip() for acc in nj_setting_value.split(",") if acc.strip()
        )
    print("allowed_accounts=====================", allowed_accounts)

    # --------------------------------------------------
    # 5) Fetch original DN total + current return DN total
    # --------------------------------------------------
    original_dn_total = abs(flt(frappe.db.get_value("Delivery Note", original_dn_name, "total")))
    current_return_dn_total = abs(flt(doc.total))
    print("original_dn_total=====================", original_dn_total)
    print("current_return_dn_total=====================", current_return_dn_total)

    if not original_dn_total or not current_return_dn_total:
        return

    # --------------------------------------------------
    # 6) Fetch UNMATCHED TAXES FROM original DN
    # --------------------------------------------------
    original_dn_unmatched_taxes = {}
    original_dn_taxes = frappe.get_all(
        "Sales Taxes and Charges",
        filters={"parent": original_dn_name, "parenttype": "Delivery Note"},
        fields=["account_head", "charge_type", "tax_amount"]
    )
    print("original_dn_taxes=====================", original_dn_taxes)

    for tax in original_dn_taxes:
        if tax.account_head not in allowed_accounts:
            original_dn_unmatched_taxes[tax.account_head] = flt(tax.tax_amount)

    print("original_dn_unmatched_taxes=====================", original_dn_unmatched_taxes)
    if not original_dn_unmatched_taxes:
        return

    # --------------------------------------------------
    # 7) Allocate unmatched DN taxes by VALUE ratio
    # formula: (abs(DN tax) / abs(original DN total)) * abs(current return DN total)
    # final tax is stored as negative for return DN
    # --------------------------------------------------
    allocated_tax_by_account = {}
    for account_head, dn_tax_amount in original_dn_unmatched_taxes.items():
        divided_amount = round((abs(flt(dn_tax_amount)) / original_dn_total) * current_return_dn_total, 2)
        divided_amount = -abs(divided_amount)
        allocated_tax_by_account[account_head] = round(
            flt(allocated_tax_by_account.get(account_head)) + divided_amount, 2
        )
        print("divided_amount=====================", divided_amount)

    if not allocated_tax_by_account:
        return

    print("allocated_tax_by_account=====================", allocated_tax_by_account)

    # --------------------------------------------------
    # 8) Update SAME tax row in return DN
    # --------------------------------------------------
    conversion_rate = flt(doc.conversion_rate) or 1
    for tax in doc.taxes:
        if tax.account_head in allocated_tax_by_account:
            tax_amount = -abs(flt(allocated_tax_by_account[tax.account_head]))
            tax.tax_amount = tax_amount
            tax.base_tax_amount = round(tax_amount * conversion_rate, 2)
# @frappe.whitelist()
# def deviding_tax_chargese(doc, method=None):
#     print("sales_orders=================34343434=======")


@frappe.whitelist()
def deviding_tax_chargese_return_dn(doc, method=None):
    # Run ONLY for return DN
    if doc.is_return != 1:
        return

    # --------------------------------------------------
    # 1) Fetch original DN from return_against
    # --------------------------------------------------
    original_dn_name = doc.return_against
    print("original_dn_name========================", original_dn_name)
    if not original_dn_name:
        return

    # --------------------------------------------------
    # 2) Check sales channel from original DN's first linked SI
    # --------------------------------------------------
    original_dn_sales_invoices = list(
        {
            item.against_sales_invoice
            for item in frappe.get_all(
                "Delivery Note Item",
                filters={"parent": original_dn_name},
                fields=["against_sales_invoice"]
            )
            if item.against_sales_invoice
        }
    )
    print("original_dn_sales_invoices========================", original_dn_sales_invoices)
    if not original_dn_sales_invoices:
        return

    first_si = original_dn_sales_invoices[0]
    sales_channel = frappe.db.get_value("Sales Invoice", first_si, "sales_channel")
    print("sales_channel========================", sales_channel)

    # --------------------------------------------------
    # 3) Run validation ONLY for Amazon
    # --------------------------------------------------
    if sales_channel != "Amazon":
        return

    # --------------------------------------------------
    # 4) Fetch NJ Settings (Allowed tax accounts)
    # --------------------------------------------------
    nj_setting_value = frappe.db.get_value(
        "NJ Settings",
        {"parameter": "taxe_account_heads"},
        "value"
    )
    print("nj_setting_value=====================", nj_setting_value)
    if not nj_setting_value:
        return

    try:
        allowed_accounts = set(json.loads(nj_setting_value))
    except Exception:
        allowed_accounts = set(
            acc.strip() for acc in nj_setting_value.split(",") if acc.strip()
        )
    print("allowed_accounts=====================", allowed_accounts)

    # --------------------------------------------------
    # 5) Fetch original DN total + current return DN total
    # --------------------------------------------------
    original_dn_total = abs(flt(frappe.db.get_value("Delivery Note", original_dn_name, "total")))
    current_return_dn_total = abs(flt(doc.total))
    print("original_dn_total=====================", original_dn_total)
    print("current_return_dn_total=====================", current_return_dn_total)

    if not original_dn_total or not current_return_dn_total:
        return

    # --------------------------------------------------
    # 6) Fetch UNMATCHED TAXES FROM original DN
    # --------------------------------------------------
    original_dn_unmatched_taxes = {}
    original_dn_taxes = frappe.get_all(
        "Sales Taxes and Charges",
        filters={"parent": original_dn_name, "parenttype": "Delivery Note"},
        fields=["account_head", "charge_type", "tax_amount"]
    )
    print("original_dn_taxes=====================", original_dn_taxes)

    for tax in original_dn_taxes:
        if tax.account_head not in allowed_accounts:
            original_dn_unmatched_taxes[tax.account_head] = flt(tax.tax_amount)

    print("original_dn_unmatched_taxes=====================", original_dn_unmatched_taxes)
    if not original_dn_unmatched_taxes:
        return

    # --------------------------------------------------
    # 7) Allocate unmatched DN taxes by VALUE ratio
    # formula: (abs(DN tax) / abs(original DN total)) * abs(current return DN total)
    # final tax is stored as negative for return DN
    # --------------------------------------------------
    allocated_tax_by_account = {}
    for account_head, dn_tax_amount in original_dn_unmatched_taxes.items():
        divided_amount = round((abs(flt(dn_tax_amount)) / original_dn_total) * current_return_dn_total, 2)
        divided_amount = -abs(divided_amount)
        allocated_tax_by_account[account_head] = round(
            flt(allocated_tax_by_account.get(account_head)) + divided_amount, 2
        )
        print("divided_amount=====================", divided_amount)

    if not allocated_tax_by_account:
        return

    print("allocated_tax_by_account=====================", allocated_tax_by_account)

    # --------------------------------------------------
    # 8) Update SAME tax row in return DN
    # --------------------------------------------------
    conversion_rate = flt(doc.conversion_rate) or 1
    for tax in doc.taxes:
        if tax.account_head in allocated_tax_by_account:
            tax_amount = -abs(flt(allocated_tax_by_account[tax.account_head]))
            tax.tax_amount = tax_amount
            tax.base_tax_amount = round(tax_amount * conversion_rate, 2)

