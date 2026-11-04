# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
import re
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate


EMPLOYEE_PERSONAL_WAREHOUSE_TYPE = "Employee Personal Warehouse"
ASSET_ACTIONS = ("Outward", "Inward")

class DispatchSecurityCheckpoints(Document):
    def validate(self):
        if self.dispatch_type == "Asset":
            self.validate_asset_security_entries()
        elif self.dispatch_type == "Transfer":
            self.validate_transfer_security_entries()

    def before_submit(self):
        if self.dispatch_type == "Asset":
            self.validate_asset_security_entries(lock_serials=True)
        elif self.dispatch_type == "Transfer":
            if not self.dc_entry:
                frappe.throw(_("Select the DC Type before submitting."))
            self.validate_transfer_security_entries()
        elif self.dispatch_type == "Purchase Return":
            unscanned = [
                row.serial_no.strip()
                for row in self.get("dsc_purchase_return_details") or []
                if row.serial_no and row.serial_no.strip() and not row.is_sn_scanned
            ]
            if unscanned:
                frappe.throw(
                    _("Please scan these serial numbers before submitting: {0}").format(
                        ", ".join(frappe.utils.escape_html(serial_no) for serial_no in unscanned)
                    )
                )

    def validate_transfer_security_entries(self):
        entries = self.get("dispatch_security_stock_entry_table") or []
        if not entries:
            frappe.throw(_("Scan a Material Transfer Stock Entry before saving."))

        stock_entry_names = {row.stock_entry_name for row in entries if row.stock_entry_name}
        if len(stock_entry_names) != 1 or any(not row.stock_entry_name for row in entries):
            frappe.throw(_("All Transfer rows must belong to one scanned Stock Entry."))
        stock_entry_name = next(iter(stock_entry_names))
        stock_entry = frappe.db.get_value(
            "Stock Entry", stock_entry_name, ["stock_entry_type", "docstatus"], as_dict=True
        )
        if not stock_entry or stock_entry.stock_entry_type != "Material Transfer" or stock_entry.docstatus != 1:
            frappe.throw(
                _("Stock Entry {0} must be a submitted Material Transfer.").format(
                    frappe.bold(stock_entry_name)
                )
            )

        scanned_serials = set()
        non_serialized_quantities = {}
        for row in entries:
            serials = split_transfer_serials(row.serial_no)
            target_warehouse_type = frappe.db.get_value(
                "Warehouse", row.target_warehouse, "warehouse_type"
            ) if row.target_warehouse else None
            if not serials:
                if not row.item_code or not row.target_warehouse:
                    frappe.throw(_("Item Code and Target Warehouse are required in Transfer row {0}.").format(row.idx))
                if frappe.db.get_value("Item", row.item_code, "has_serial_no"):
                    frappe.throw(_("Serial No is required for serialized Item {0} in Transfer row {1}.").format(
                        frappe.bold(row.item_code), row.idx
                    ))
                if self.dc_entry and target_warehouse_type != self.dc_entry:
                    frappe.throw(
                        _("Item {0} is in a {1} warehouse ({2}). You cannot select DC Type {3} for this item.").format(
                            frappe.bold(row.item_code),
                            frappe.bold(target_warehouse_type or _("unspecified type")),
                            frappe.bold(row.target_warehouse),
                            frappe.bold(self.dc_entry),
                        )
                    )
                quantity = flt(row.serial_no_quantity)
                if quantity <= 0:
                    frappe.throw(_("Quantity must be greater than zero for Item {0} in Transfer row {1}.").format(
                        frappe.bold(row.item_code), row.idx
                    ))
                key = (row.item_code, row.target_warehouse)
                non_serialized_quantities[key] = non_serialized_quantities.get(key, 0) + quantity
                continue
            for serial_no in serials:
                if serial_no in scanned_serials:
                    frappe.throw(_("Serial No {0} appears more than once in the Transfer table.").format(frappe.bold(serial_no)))
                scanned_serials.add(serial_no)
                warehouse = frappe.db.get_value("Serial No", serial_no, "warehouse")
                if warehouse != row.target_warehouse:
                    frappe.throw(
                        _("Serial No {0} is in warehouse {1}, but Transfer row {2} has target warehouse {3}.").format(
                            frappe.bold(serial_no),
                            frappe.bold(warehouse or _("None")),
                            row.idx,
                            frappe.bold(row.target_warehouse or _("None")),
                        )
                    )
                if self.dc_entry and target_warehouse_type != self.dc_entry:
                    frappe.throw(
                        _("Serial No {0} is in a {1} warehouse ({2}). You cannot select DC Type {3} for this serial number.").format(
                            frappe.bold(serial_no),
                            frappe.bold(target_warehouse_type or _("unspecified type")),
                            frappe.bold(row.target_warehouse),
                            frappe.bold(self.dc_entry),
                        )
                    )

        for (item_code, target_warehouse), required_qty in non_serialized_quantities.items():
            available_qty = flt(frappe.db.get_value(
                "Bin", {"item_code": item_code, "warehouse": target_warehouse}, "actual_qty"
            ))
            if available_qty < required_qty:
                frappe.throw(
                    _("Insufficient stock for Item {0} in Warehouse {1}. Required: {2}; available: {3}.").format(
                        frappe.bold(item_code),
                        frappe.bold(target_warehouse),
                        required_qty,
                        available_qty,
                    )
                )
            latest_entry = frappe.db.sql(
                """
                SELECT entry.name
                FROM `tabStock Entry` entry
                INNER JOIN `tabStock Entry Detail` detail ON detail.parent = entry.name
                WHERE entry.docstatus = 1
                    AND entry.stock_entry_type = 'Material Transfer'
                    AND detail.item_code = %s
                    AND detail.t_warehouse = %s
                ORDER BY entry.posting_date DESC, entry.posting_time DESC,
                    entry.creation DESC, entry.name DESC
                LIMIT 1
                """,
                (item_code, target_warehouse),
                as_dict=True,
            )
            if not latest_entry or latest_entry[0].name != stock_entry_name:
                frappe.throw(
                    _("Please scan the latest Material Transfer Stock Entry for Item {0} in Warehouse {1}. Latest: {2}; scanned: {3}.").format(
                        frappe.bold(item_code),
                        frappe.bold(target_warehouse),
                        frappe.bold(latest_entry[0].name if latest_entry else _("Not found")),
                        frappe.bold(stock_entry_name),
                    )
                )

        latest_entries = get_latest_material_transfers(scanned_serials)
        for serial_no in sorted(scanned_serials):
            latest_entry = latest_entries.get(serial_no)
            if latest_entry != stock_entry_name:
                frappe.throw(
                    _("Please scan the latest Material Transfer Stock Entry for Serial No {0}. Latest: {1}; scanned: {2}.").format(
                        frappe.bold(serial_no),
                        frappe.bold(latest_entry or _("Not found")),
                        frappe.bold(stock_entry_name),
                    )
                )

    def on_submit(self):
        self.update_send_email_DN()
        self.update_payment_recived()
        # self.update_send_email_SI()

    def validate_asset_security_entries(self, lock_serials=False):
        entries = self.get("asset_security_entries") or []
        if not entries:
            frappe.throw(_("Scan at least one Serial No before saving an Asset security checkpoint."))

        serial_nos = list(dict.fromkeys(row.serial_no for row in entries if row.serial_no))
        if lock_serials and serial_nos:
            frappe.db.sql(
                "SELECT name FROM `tabSerial No` WHERE name IN %(serial_nos)s FOR UPDATE",
                {"serial_nos": tuple(serial_nos)},
            )

        latest_states = {
            serial_no: get_latest_asset_gate_action(serial_no, exclude_document=self.name)
            for serial_no in serial_nos
        }

        for row in entries:
            if not row.serial_no:
                frappe.throw(_("Serial No is required in Asset Security Entry row {0}.").format(row.idx))

            serial_details = get_employee_asset_serial_details(row.serial_no)
            previous = latest_states.get(row.serial_no)
            expected_action = get_next_asset_action(previous.get("asset_action") if previous else None)

            if row.asset_action not in ASSET_ACTIONS:
                frappe.throw(
                    _("Asset Action must be Outward or Inward for Serial No {0}.").format(
                        frappe.bold(row.serial_no)
                    )
                )

            if row.asset_action != expected_action:
                throw_invalid_asset_action(row.serial_no, row.asset_action, previous, expected_action)

            snapshot_fields = (
                ("item_code", "Item Code"),
                ("employee", "Employee"),
                ("warehouse", "Warehouse"),
                ("warehouse_type", "Warehouse Type"),
            )
            for fieldname, label in snapshot_fields:
                if (row.get(fieldname) or "") != (serial_details.get(fieldname) or ""):
                    frappe.throw(
                        _("{0} mismatch for Serial No {1}. Expected {2}, but the scanned row contains {3}.").format(
                            label,
                            frappe.bold(row.serial_no),
                            frappe.bold(serial_details.get(fieldname) or _("Not Available")),
                            frappe.bold(row.get(fieldname) or _("Not Available")),
                        )
                    )

            if row.is_new():
                row.scanned_by = frappe.session.user
                row.scan_time = row.scan_time or now_datetime()

            row.previous_action = previous.get("asset_action") if previous else ""
            row.previous_action_time = previous.get("scan_time") if previous else None
            latest_states[row.serial_no] = {
                "asset_action": row.asset_action,
                "scan_time": row.scan_time,
                "scanned_by": row.scanned_by,
                "parent": self.name,
            }

    def update_send_email_DN(self):
        try:
            for row in self.dispatch_security_child_table:
                if row.delivery_note:
                    dn_doc = frappe.get_doc("Delivery Note", row.delivery_note)
                    dn_doc.send_email = 1
                    dn_doc.save(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Error in update_send_email_DN")
            frappe.throw(f"Error while updating Delivery Note send_email: {e}")

    def update_send_email_SI(self):
        try:
            for row in self.dispatch_security_child_table:
                if row.sales_invoice:
                    # Fetch the Delivery Note
                    si_doc = frappe.get_doc("Sales Invoice", row.sales_invoice)
                    si_doc.send_email = 1
                    si_doc.save(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Error in update_send_email_SI")
            frappe.throw(f"Error while updating Sales Invoice send_email: {e}")

    def update_payment_recived(self):
        try:
            for row in self.dispatch_security_child_table:
                if row.sales_order:
                    so_doc = frappe.get_doc("Sales Order", row.sales_order)

                    if so_doc.get("is_cod") and not so_doc.get("payment_received"):
                        so_doc.payment_received = 1
                        so_doc.save(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Error in update_payment_recived")
            frappe.throw(f"Error while updating Sales Order payment_received: {e}")


def get_next_asset_action(previous_action):
    return "Inward" if previous_action == "Outward" else "Outward"


def split_transfer_serials(value):
    return [serial.strip() for serial in re.split(r"[\r\n,]+", value or "") if serial.strip()]


def get_latest_material_transfers(serial_nos):
    if not serial_nos:
        return {}
    conditions = " OR ".join("detail.serial_no LIKE %s" for _ in serial_nos)
    candidates = frappe.db.sql(
        f"""
        SELECT entry.name, detail.serial_no
        FROM `tabStock Entry` entry
        INNER JOIN `tabStock Entry Detail` detail ON detail.parent = entry.name
        WHERE entry.docstatus = 1
            AND entry.stock_entry_type = 'Material Transfer'
            AND ({conditions})
        ORDER BY entry.posting_date DESC, entry.posting_time DESC,
            entry.creation DESC, entry.name DESC
        """,
        tuple(f"%{serial_no}%" for serial_no in serial_nos),
        as_dict=True,
    )
    latest = {}
    for candidate in candidates:
        for serial_no in split_transfer_serials(candidate.serial_no):
            if serial_no in serial_nos and serial_no not in latest:
                latest[serial_no] = candidate.name
    return latest


def get_employee_asset_serial_details(serial_no):
    serial_no = (serial_no or "").strip()
    if not serial_no or not frappe.db.exists("Serial No", serial_no):
        frappe.throw(_("Serial No {0} does not exist.").format(frappe.bold(serial_no or _("Not provided"))))

    serial_details = frappe.db.get_value(
        "Serial No",
        serial_no,
        ["name", "item_code", "warehouse", "employee"],
        as_dict=True,
    )

    if not serial_details.warehouse:
        frappe.throw(
            _("Serial No {0} is not available in any warehouse and cannot be used for an Asset gate entry.").format(
                frappe.bold(serial_no)
            )
        )

    warehouse_details = frappe.db.get_value(
        "Warehouse",
        serial_details.warehouse,
        ["warehouse_type", "warehouse_owner"],
        as_dict=True,
    ) or frappe._dict()
    warehouse_type = warehouse_details.warehouse_type
    if warehouse_type != EMPLOYEE_PERSONAL_WAREHOUSE_TYPE:
        frappe.throw(
            _(
                "Serial No {0} is currently in warehouse {1}. Asset gate movement is allowed only when the warehouse type is {2}."
            ).format(
                frappe.bold(serial_no),
                frappe.bold(serial_details.warehouse),
                frappe.bold(EMPLOYEE_PERSONAL_WAREHOUSE_TYPE),
            ),
            title=_("Asset Movement Not Allowed"),
        )

    employee = serial_details.employee
    if not employee and warehouse_details.warehouse_owner:
        employee = frappe.db.get_value(
            "Employee",
            {"user_id": warehouse_details.warehouse_owner, "status": "Active"},
            "name",
        )
        if not employee:
            employee = frappe.db.get_value(
                "Employee",
                {"prefered_email": warehouse_details.warehouse_owner, "status": "Active"},
                "name",
            )

    if not employee:
        frappe.throw(
            _("No active Employee found linked to Warehouse {0} or Serial No {1}.").format(
                frappe.bold(serial_details.warehouse),
                frappe.bold(serial_no),
            ),
            title=_("Employee Not Found"),
        )

    employee_details = frappe.db.get_value(
        "Employee",
        employee,
        ["name", "employee_name", "serial_no"],
        as_dict=True,
    ) or frappe._dict()

    employee_name = employee_details.employee_name
    employee_serial_no = (employee_details.serial_no or "").strip()

    if not employee_serial_no:
        frappe.throw(
            _("No Serial No is assigned to Employee {0}.").format(
                frappe.bold(employee),
            ),
            title=_("Serial No Not Assigned"),
        )

    if employee_serial_no != serial_no:
        frappe.throw(
            _(
                "This Serial No {0} does not belong to Employee {1}. The available Serial No is {2}."
            ).format(
                frappe.bold(serial_no),
                frappe.bold(employee),
                frappe.bold(employee_serial_no),
            ),
            title=_("Serial No Mismatch"),
        )

    return frappe._dict(
        serial_no=serial_details.name,
        item_code=serial_details.item_code,
        employee=employee,
        employee_name=employee_name,
        warehouse=serial_details.warehouse,
        warehouse_type=warehouse_type,
    )


def get_latest_asset_gate_action(serial_no, exclude_document=None):
    conditions = ["parent.docstatus = 1", "entry.serial_no = %(serial_no)s"]
    values = {"serial_no": serial_no}
    if exclude_document:
        conditions.append("parent.name != %(exclude_document)s")
        values["exclude_document"] = exclude_document

    result = frappe.db.sql(
        f"""
        SELECT
            entry.asset_action,
            entry.scan_time,
            entry.scanned_by,
            parent.name AS parent
        FROM `tabDispatch Security Asset Entry` entry
        INNER JOIN `tabDispatch Security Checkpoints` parent
            ON parent.name = entry.parent
            AND entry.parenttype = 'Dispatch Security Checkpoints'
            AND entry.parentfield = 'asset_security_entries'
        WHERE {' AND '.join(conditions)}
        ORDER BY entry.scan_time DESC, parent.creation DESC, entry.idx DESC
        LIMIT 1
        """,
        values,
        as_dict=True,
    )
    return result[0] if result else None


def throw_invalid_asset_action(serial_no, requested_action, previous, expected_action):
    if not previous and requested_action == "Inward":
        frappe.throw(
            _("Serial No {0} has no previous Outward gate entry. Record Outward before Inward.").format(
                frappe.bold(serial_no)
            ),
            title=_("Inward Not Allowed"),
        )

    frappe.throw(
        _(
            "Serial No {0} is already {1}. The next permitted action is {2}. "
            "Last recorded by {3} at {4} in {5}."
        ).format(
            frappe.bold(serial_no),
            frappe.bold(previous.get("asset_action") if previous else requested_action),
            frappe.bold(expected_action),
            frappe.bold(previous.get("scanned_by") or _("Unknown user")) if previous else _("Unknown user"),
            frappe.bold(previous.get("scan_time") or _("Unknown time")) if previous else _("Unknown time"),
            frappe.bold(previous.get("parent") or _("Unknown document")) if previous else _("Unknown document"),
        ),
        title=_("Asset Action Not Allowed"),
    )


@frappe.whitelist()
def get_asset_security_scan_details(serial_no):
    details = get_employee_asset_serial_details(serial_no)
    previous = get_latest_asset_gate_action(details.serial_no)
    details.update({
        "previous_action": previous.get("asset_action") if previous else None,
        "previous_action_time": previous.get("scan_time") if previous else None,
        "previous_scanned_by": previous.get("scanned_by") if previous else None,
        "previous_document": previous.get("parent") if previous else None,
        "next_allowed_action": get_next_asset_action(previous.get("asset_action") if previous else None),
    })
    return details

@frappe.whitelist()
def scan_serial_no_data_for_sales(serial_no):
    try:
        serial_no = serial_no.strip()
        serial_no_exists = frappe.db.exists('Serial No', serial_no)
        if not serial_no_exists:
            frappe.throw(f"Serial No: {serial_no} doesn't exist")
            return None

        delivery_note = None
        dn_status = None
        sales_invoice = None
        sales_order = None
        item_code = None
        si_status = None
        approved = None
        sales_channel = None
        is_cod = None
        serial_no_from_dn_query = """
            SELECT
                dn.name AS delivery_note,
                dn.status AS dn_status,
                COALESCE(dni.against_sales_invoice, info_dni.against_sales_invoice) AS sales_invoice,
                COALESCE(dni.against_sales_order, info_dni.against_sales_order) AS sales_order,
                so.is_cod AS so_is_cod,
                COALESCE(dni.item_code, pi.item_code, info_dni.item_code) AS item_code,
                si.status AS si_status,
                si.approved,
                si.sales_channel
            FROM `tabDelivery Note` dn
            LEFT JOIN `tabDelivery Note Item` dni
                ON dni.parent = dn.name
                AND CONCAT('\n', REPLACE(IFNULL(dni.serial_no, ''), ',', '\n'), '\n')
                    LIKE %(serial_no_pattern)s
            LEFT JOIN `tabPacked Item` pi
                ON pi.parent = dn.name
                AND CONCAT('\n', REPLACE(IFNULL(pi.serial_no, ''), ',', '\n'), '\n')
                    LIKE %(serial_no_pattern)s
            LEFT JOIN `tabDelivery Note Item` info_dni
                ON info_dni.parent = dn.name
                AND info_dni.idx = 1
            LEFT JOIN `tabSales Invoice` si
                ON si.name = COALESCE(dni.against_sales_invoice, info_dni.against_sales_invoice)
            LEFT JOIN `tabSales Order` so
                ON so.name = COALESCE(dni.against_sales_order, info_dni.against_sales_order)
            WHERE dn.docstatus = 1
                AND (dni.name IS NOT NULL OR pi.name IS NOT NULL)
            ORDER BY dn.creation DESC, dn.modified DESC
            LIMIT 1
        """

        result = frappe.db.sql(
            serial_no_from_dn_query,
            {"serial_no_pattern": "%\n{}\n%".format(serial_no)},
            as_dict=True
        )
        if not result:
            serial_no_from_dn_query = """
                SELECT 
                    si.name AS sales_invoice,
                    si.status AS si_status,
                    sii.delivery_note AS delivery_note,
                    dn.status AS dn_status,
                    sii.sales_order AS sales_order,
                    so.is_cod AS so_is_cod,
                    sii.item_code,
                    si.approved,
                    si.sales_channel
                FROM `tabSales Invoice Item` sii
                INNER JOIN `tabSales Invoice` si 
                    ON si.name = sii.parent
                LEFT JOIN `tabDelivery Note` dn
                    ON dn.name = sii.delivery_note
                LEFT JOIN `tabSales Order` so
                    ON so.name = sii.sales_order    
                LEFT JOIN `tabPacked Item` pi ON si.name = pi.parent    
                WHERE (
                    sii.serial_no = {0}
                    or sii.serial_no like {1}
                    or sii.serial_no like {2}
                    or sii.serial_no like {3}
                    or pi.serial_no = {0}
                    or pi.serial_no like {1}
                    or pi.serial_no like {2}
                    or pi.serial_no like {3}
                )
                AND si.docstatus = 1
                ORDER BY si.creation DESC, si.modified DESC;
            """.format(
                frappe.db.escape(serial_no),
                frappe.db.escape("{}\n%".format(serial_no)),
                frappe.db.escape("%\n{}".format(serial_no)),
                frappe.db.escape("%\n{}\n%".format(serial_no)),
            )

            result = frappe.db.sql(serial_no_from_dn_query, as_dict=True)

        if result:
            data = result[0]
            delivery_note = data.get('delivery_note')
            dn_status = data.get('dn_status')
            sales_invoice = data.get('sales_invoice')
            sales_order = data.get('sales_order')
            item_code = data.get('item_code')
            si_status = data.get('si_status')
            approved = data.get('approved')
            sales_channel = data.get('sales_channel')
            is_cod = data.get('so_is_cod')

            if delivery_note and not sales_invoice:
                invoice_data = frappe.db.sql("""
                    SELECT
                        si.name AS sales_invoice,
                        si.status AS si_status,
                        sii.sales_order AS sales_order,
                        so.is_cod AS so_is_cod,
                        sii.item_code,
                        si.approved,
                        si.sales_channel
                    FROM `tabSales Invoice Item` sii
                    INNER JOIN `tabSales Invoice` si
                        ON si.name = sii.parent
                    LEFT JOIN `tabSales Order` so
                        ON so.name = sii.sales_order
                    WHERE sii.delivery_note = %s
                        AND si.docstatus = 1
                    ORDER BY si.creation DESC, si.modified DESC
                    LIMIT 1
                """, delivery_note, as_dict=True)

                if invoice_data:
                    invoice_data = invoice_data[0]
                    sales_invoice = invoice_data.get('sales_invoice')
                    sales_order = invoice_data.get('sales_order') or sales_order
                    item_code = invoice_data.get('item_code') or item_code
                    si_status = invoice_data.get('si_status')
                    approved = invoice_data.get('approved')
                    sales_channel = invoice_data.get('sales_channel')
                    is_cod = invoice_data.get('so_is_cod')

            if sales_order and not sales_invoice:
                invoice_data = frappe.db.sql("""
                    SELECT
                        si.name AS sales_invoice,
                        si.status AS si_status,
                        sii.sales_order AS sales_order,
                        so.is_cod AS so_is_cod,
                        sii.item_code,
                        si.approved,
                        si.sales_channel
                    FROM `tabSales Invoice Item` sii
                    INNER JOIN `tabSales Invoice` si
                        ON si.name = sii.parent
                    LEFT JOIN `tabSales Order` so
                        ON so.name = sii.sales_order
                    WHERE sii.sales_order = %s
                        AND si.docstatus = 1
                    ORDER BY
                        CASE WHEN sii.item_code = %s THEN 0 ELSE 1 END,
                        si.creation DESC,
                        si.modified DESC
                    LIMIT 1
                """, (sales_order, item_code), as_dict=True)

                if invoice_data:
                    invoice_data = invoice_data[0]
                    sales_invoice = invoice_data.get('sales_invoice')
                    item_code = invoice_data.get('item_code') or item_code
                    si_status = invoice_data.get('si_status')
                    approved = invoice_data.get('approved')
                    sales_channel = invoice_data.get('sales_channel')
                    is_cod = invoice_data.get('so_is_cod')

            if sales_invoice:
                if sales_channel == 'Amazon' and (not sales_invoice or not delivery_note):
                    frappe.msgprint(_("For Amazon orders, both Sales Invoice and Delivery Note must be submitted and available."))
                    return None
                elif sales_channel != 'Amazon' and si_status != 'Paid' and approved == 0:
                    frappe.msgprint(_("Sales Invoice '{}' must have a 'Paid' status to proceed and it is approved.").format(sales_invoice))
                    return None
                elif sales_channel != 'Amazon' and si_status == 'Paid' and approved == 0:
                    frappe.msgprint(_("Sales Invoice '{}' must be approved to proceed.").format(sales_invoice))
                    return None
            else:
                frappe.throw(_("No matching sales invoice found for serial number <b>{}</b>").format(serial_no))
                return None

        if delivery_note:
            delivery_note_creation = frappe.db.get_value('Delivery Note', delivery_note, 'creation')
            if delivery_note_creation:
                creation_date = getdate(delivery_note_creation)
                four_days_ago = add_days(nowdate(), -10)  # actually checks 10 days back
                if creation_date < getdate(four_days_ago):
                    frappe.throw("The latest Delivery Note was not created within the last 10 days.")

            customer_name = ""
            courier_name = ""
            tracking_id = ""
            email_id = ""
            dn_doc = frappe.get_doc("Delivery Note", delivery_note)
            customer_name = dn_doc.customer 
            courier_name = dn_doc.get("courier_service", "")
            tracking_id = dn_doc.get("tracking_id", "")
            if dn_doc.shipping_address_name:
                try:
                    address = frappe.get_doc("Address", dn_doc.shipping_address_name)
                    email_id = address.get("email_id", "")
                except frappe.DoesNotExistError:
                    pass

            return {
                'serial_no': serial_no,
                'item_code': item_code,
                'delivery_note': delivery_note,
                'sales_invoice': sales_invoice,
                'sales_order': sales_order,
                'si_status': si_status,
                'dn_status': dn_status,
                'sales_channel': sales_channel,
                'approved': approved,
                'customer_name': customer_name,
                'courier_name': courier_name,
                'tracking_id': tracking_id,
                'email_id': email_id,
                'is_cod': is_cod
            }

        return None

    except Exception as e:
        frappe.throw(e)

@frappe.whitelist()
def scan_serial_no_data_for_return(pr_name):
    try:
        pr_name = pr_name.strip()
        if not frappe.db.exists('Purchase Receipt', pr_name):
            frappe.throw(f"Serial No or Purchase Receipt: {pr_name} doesn't exist")
            return None
        if pr_name:
            return_data = frappe.db.sql("""select Pr.name as PR, Pr.status as PR_Status , Pr.total as PR_Total, Pi.total as PI_Total,
                    Pi.name as PI, Pi.status as PI_Status from `tabPurchase Receipt` Pr
                    inner join `tabPurchase Invoice Item` PII 
                    inner join `tabPurchase Invoice` Pi
                    on PII.purchase_receipt = Pr.name and 
                    Pi.name = PII.parent
                    where Pr.name = %s and Pr.is_return = 1 and Pr.docstatus = 1
                """, pr_name, as_dict=True)
        if not return_data:
            frappe.msgprint(_("No PR or PI data found for <b>{}</b>").format(pr_name))
            return None
        if not return_data[0].get('PR') and not return_data[0].get('PI'):
            frappe.msgprint(_("No PR or PI data found for <b>{}</b>").format(pr_name))
            return None

        if not return_data[0].get('PR_Status') and not return_data[0].get('PI_Status'):
            frappe.msgprint(_("Please check the status of PR or PI for <b>{}</b>").format(pr_name))
            return None
        
        if not return_data[0].get('PR_Total') or return_data[0].get('PR_Total') >= 0 and return_data[0].get('PI_Total') != return_data[0].get('PR_Total'):
            frappe.msgprint(_("Please check the total amount of PR or PI found for<b>{}</b>").format(pr_name))
            return None

        purchase_return_details = []
        receipt_items = frappe.get_all(
            "Purchase Receipt Item",
            filters={"parent": pr_name},
            fields=["item_code", "item_group", "purchase_order", "qty", "serial_no"],
            order_by="idx asc",
        )
        for item in receipt_items:
            serial_nos = split_transfer_serials(item.serial_no)
            if serial_nos:
                for serial_no in serial_nos:
                    purchase_return_details.append({
                        "serial_no": serial_no,
                        "item_code": item.item_code,
                        "qty": 1,
                        "item_group": item.item_group,
                        "purchase_order": item.purchase_order,
                    })
            else:
                purchase_return_details.append({
                    "serial_no": "",
                    "item_code": item.item_code,
                    "qty": abs(item.qty or 0),
                    "item_group": item.item_group,
                    "purchase_order": item.purchase_order,
                })
        
        return {
            'purchase_receipt': return_data[0].get('PR'),
            'purchase_invoice': return_data[0].get('PI'),
            'pr_status': return_data[0].get('PR_Status'),
            'pi_status': return_data[0].get('PI_Status'),
            'purchase_return_details': purchase_return_details,
        }
    
    except Exception as e:
        frappe.throw(e)

@frappe.whitelist()
def get_item_code_details_for_transfer(ste_number):
    ste_number = (ste_number or "").strip()
    if not frappe.db.exists('Stock Entry', ste_number):
        frappe.throw(f"Stock Entry : {ste_number} doesn't exist")

    stock_entry = frappe.db.get_value(
        "Stock Entry", ste_number, ["stock_entry_type", "docstatus"], as_dict=True
    )
    if stock_entry.stock_entry_type != "Material Transfer" or stock_entry.docstatus != 1:
        frappe.throw(
            _("Only a submitted Material Transfer Stock Entry can be scanned. {0} is not one.").format(
                frappe.bold(ste_number)
            )
        )

    material_transfer_details = frappe.db.get_all("Stock Entry Detail",
        filters={'parent': ste_number},
        fields=['t_warehouse', 'qty', 'item_code', 's_warehouse', 'idx', 'serial_no','parent']
    )

    result = []

    for row in material_transfer_details:
        s_warehouse_lc = frappe.db.get_value("Warehouse", {'name': row['s_warehouse']}, ['location'])
        t_warehouse_lc = frappe.db.get_value("Warehouse", {'name': row['t_warehouse']}, ['location'])

        if s_warehouse_lc == t_warehouse_lc:
            result.append({
                'error': f'The source warehouse and target warehouse cannot have the same location at  row <br><b>{row["idx"]}  .{row["item_code"]} at {ste_number}</b>'
            })
        else:
            result.append(row)

    return result
