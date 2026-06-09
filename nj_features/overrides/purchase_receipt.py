# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
import time
from frappe.utils import nowdate, add_days
from datetime import timedelta
from frappe.utils import getdate, nowdate, flt
from nj_lib.utils.common_utils import is_serialized
from nj_features.nj_features.api.qr_code import generate_and_save_qrcode
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt
from frappe import _
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

logger = frappe.logger("prtimelog", allow_site=True)


def log_pr_time(label, docname, start):
    logger.debug(f"[PR: {docname}] {label} took {time.perf_counter() - start:.4f} seconds")


class CustomPurchaseReceipt(PurchaseReceipt):

    # ─────────────────────────────────────────────────────────────────────
    # MANUAL CONVERSION OVERRIDE — re-assert after standard validate
    # ─────────────────────────────────────────────────────────────────────
    def validate(self):
        super().validate()
        # self._restore_manual_conversion_factors()

    def _restore_manual_conversion_factors(self):
        for item in self.items:
            if item.get("manual_conversion_override"):
                cf = flt(item.conversion_factor)
                if cf <= 0:
                    frappe.throw(
                        f"Row {item.idx} ({item.item_code}): Conversion Factor must be "
                        f"greater than 0 when Manual Conversion Override is enabled."
                    )
                item.stock_qty = flt(item.qty) * cf
    # ─────────────────────────────────────────────────────────────────────

    def before_save(self):
        generate_batch_no(self)

    def on_submit(self):
        total_start = time.perf_counter()
        try:
            start = time.perf_counter()
            super(CustomPurchaseReceipt, self).on_submit()
            log_pr_time("super().on_submit()", self.name, start)

            start = time.perf_counter()
            self.auto_closure_mr_via_pr()
            log_pr_time("auto_closure_mr_via_pr", self.name, start)

            start = time.perf_counter()
            self.set_registry_no_on_submit()
            log_pr_time("set_registry_no_on_submit", self.name, start)

            start = time.perf_counter()
            self.auto_create_debit_note()
            log_pr_time("auto_create_debit_note", self.name, start)

            get_batch(self)
        finally:
            log_pr_time("CustomPurchaseReceipt.on_submit total", self.name, total_start)
    
    def on_cancel(self):
        super(CustomPurchaseReceipt, self).on_cancel()
        self.set_registry_no_on_cancel()

    def set_registry_no_on_submit(self):
        total_qty = 0
        for item in self.items:
            total_qty += item.qty
            if item.sir_registry_no:
                sir_registry_no = item.sir_registry_no.split(',')
                sir_actual_qty = item.sir_actual_qty.split(',')

                sir_list = [{'sir_registry_no': sr.strip(), 'actual_qty': int(qty.strip())} for sr, qty in zip(sir_registry_no, sir_actual_qty)]
                item_qty = item.qty

                if len(sir_list) == 1:
                    frappe.db.sql("""
                            UPDATE `tabSecurity Inward Registry Child`
                            SET actual_qty = GREATEST(actual_qty - %s, 0)
                            WHERE parent = %s 
                            AND item_code = %s 
                            AND item_group = %s
                        """, (item.qty, sir_list[0].get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)
                elif len(sir_list) > 1:
                    for sir in sir_list:
                        if int(item.qty) > sum([int(row['actual_qty']) for row in sir_list]) and item_qty > 0:
                                frappe.db.sql("""
                                    UPDATE `tabSecurity Inward Registry Child`
                                    SET actual_qty = GREATEST(actual_qty - %s, 0)
                                    WHERE parent = %s 
                                    AND item_code = %s 
                                    AND item_group = %s
                                """, (item_qty, sir.get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)
                                item_qty -= sir.get('actual_qty')

                        elif int(item.qty) < sum([int(row['actual_qty']) for row in sir_list]) and item_qty > 0:
                            frappe.db.sql("""
                                UPDATE `tabSecurity Inward Registry Child`
                                SET actual_qty = GREATEST(actual_qty - %s, 0)
                                WHERE parent = %s 
                                AND item_code = %s 
                                AND item_group = %s
                            """, (item_qty, sir.get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)
                            item_qty -= sir.get('actual_qty')

                        elif int(item.qty) == sum([int(row['actual_qty']) for row in sir_list]) and item_qty > 0:
                            frappe.db.sql("""
                                UPDATE `tabSecurity Inward Registry Child`
                                SET actual_qty = GREATEST(actual_qty - %s, 0)
                                WHERE parent = %s 
                                AND item_code = %s 
                                AND item_group = %s
                            """, (item_qty, sir.get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)
                            item_qty -= sir.get('actual_qty')

    def auto_closure_mr_via_pr(self):
        allowed_references = get_pr_material_request_references()
        logger.info(
            "[PR MR Auto Closure] PR=%s allowed_references=%s",
            self.name,
            allowed_references,
        )
        if not allowed_references:
            logger.info("[PR MR Auto Closure] PR=%s skipped: no NJ Settings value", self.name)
            return

        for item in self.items:
            mr_names = get_pr_item_material_requests(item)
            reference_filters = []
            query_params = {
                "mr_names": tuple(mr_names),
                "item_code": item.item_code,
            }
            for idx, reference in enumerate(allowed_references):
                exact_key = f"reference_{idx}"
                like_key = f"reference_like_{idx}"
                reference_filters.append(
                    f"(mri.create_reference = %({exact_key})s OR mri.create_reference LIKE %({like_key})s)"
                )
                query_params[exact_key] = reference
                query_params[like_key] = f"%{reference}%"

            logger.info(
                "[PR MR Auto Closure] PR=%s row=%s item_code=%s qty=%s material_requests=%s material_request_item=%s create_reference_filter=%s",
                self.name,
                item.idx,
                item.item_code,
                item.qty,
                mr_names,
                item.get("material_request_item"),
                allowed_references,
            )
            if not mr_names or not item.item_code:
                logger.info(
                    "[PR MR Auto Closure] PR=%s row=%s skipped: missing material request or item_code",
                    self.name,
                    item.idx,
                )
                continue

            material_request_items = frappe.db.sql(
                """
                SELECT
                    mri.name,
                    mri.parent,
                    mri.qty,
                    IFNULL(mri.received_qty, 0) AS received_qty
                FROM `tabMaterial Request Item` mri
                INNER JOIN `tabMaterial Request` mr ON mr.name = mri.parent
                WHERE
                    mr.docstatus = 1
                    AND mri.parent IN %(mr_names)s
                    AND mri.item_code = %(item_code)s
                    AND ({reference_condition})
                    AND IFNULL(mri.post_order_status, 'Not Completed') != 'Completed'
                ORDER BY mr.transaction_date ASC, mr.creation ASC, mri.idx ASC
                """.format(reference_condition=" OR ".join(reference_filters)),
                query_params,
                as_dict=True,
            )
            logger.info(
                "[PR MR Auto Closure] PR=%s row=%s matching_mr_items=%s",
                self.name,
                item.idx,
                material_request_items,
            )

            linked_mr_item = item.get("material_request_item")
            standard_updated_linked_item = bool(
                linked_mr_item
                and any(mr_item.name == linked_mr_item for mr_item in material_request_items)
            )
            remaining_qty = 0 if standard_updated_linked_item else flt(item.qty)
            logger.info(
                "[PR MR Auto Closure] PR=%s row=%s linked_mr_item=%s standard_updated_linked_item=%s remaining_qty=%s",
                self.name,
                item.idx,
                linked_mr_item,
                standard_updated_linked_item,
                remaining_qty,
            )

            for mr_item in material_request_items:
                if flt(mr_item.received_qty) >= flt(mr_item.qty):
                    frappe.db.set_value(
                        "Material Request Item",
                        mr_item.name,
                        "post_order_status",
                        "Completed",
                        update_modified=False,
                    )
                    logger.info(
                        "[PR MR Auto Closure] PR=%s row=%s MR=%s MRI=%s marked Completed: received_qty=%s qty=%s",
                        self.name,
                        item.idx,
                        mr_item.parent,
                        mr_item.name,
                        mr_item.received_qty,
                        mr_item.qty,
                    )

                if mr_item.name == linked_mr_item:
                    logger.info(
                        "[PR MR Auto Closure] PR=%s row=%s MRI=%s skipped qty update: standard PR updater already handled linked MR item",
                        self.name,
                        item.idx,
                        mr_item.name,
                    )
                    continue

                if remaining_qty <= 0:
                    logger.info(
                        "[PR MR Auto Closure] PR=%s row=%s stopped: remaining_qty=%s",
                        self.name,
                        item.idx,
                        remaining_qty,
                    )
                    break

                pending_qty = flt(mr_item.qty) - flt(mr_item.received_qty)
                if pending_qty <= 0:
                    logger.info(
                        "[PR MR Auto Closure] PR=%s row=%s MRI=%s skipped: pending_qty=%s",
                        self.name,
                        item.idx,
                        mr_item.name,
                        pending_qty,
                    )
                    continue

                qty_to_update = min(remaining_qty, pending_qty)
                new_received_qty = flt(mr_item.received_qty) + qty_to_update
                values = {"received_qty": new_received_qty}

                if new_received_qty >= flt(mr_item.qty):
                    values["post_order_status"] = "Completed"

                frappe.db.set_value(
                    "Material Request Item",
                    mr_item.name,
                    values,
                    update_modified=False,
                )
                logger.info(
                    "[PR MR Auto Closure] PR=%s row=%s MR=%s MRI=%s qty_to_update=%s old_received_qty=%s new_received_qty=%s status=%s remaining_before=%s",
                    self.name,
                    item.idx,
                    mr_item.parent,
                    mr_item.name,
                    qty_to_update,
                    mr_item.received_qty,
                    new_received_qty,
                    values.get("post_order_status", "unchanged"),
                    remaining_qty,
                )
                remaining_qty -= qty_to_update
            logger.info(
                "[PR MR Auto Closure] PR=%s row=%s completed with remaining_qty=%s",
                self.name,
                item.idx,
                remaining_qty,
            )
            
    def set_registry_no_on_cancel(self):
        for item in self.items:
            if item.sir_registry_no:
                sir_registry_no = item.sir_registry_no.split(',')
                sir_actual_qty = item.sir_actual_qty.split(',')
                sir_list = [{'sir_registry_no': sr.strip(), 'actual_qty': int(qty.strip())} 
                        for sr, qty in zip(sir_registry_no, sir_actual_qty)]
                
                if len(sir_list) == 1:
                    get_sir_data = frappe.db.sql("""
                                SELECT actual_qty, received_qty FROM `tabSecurity Inward Registry Child`
                                WHERE parent = %s 
                                AND item_code = %s 
                                AND item_group = %s
                            """, (sir_list[0].get('sir_registry_no'), item.item_code, item.item_group), as_dict=1)
                    
                    if get_sir_data:
                        if int(get_sir_data[0].get('actual_qty')) + int(sir_list[0].get('actual_qty')) == int(get_sir_data[0].get('received_qty')):
                            frappe.db.sql("""
                                UPDATE `tabSecurity Inward Registry Child`
                                SET actual_qty = actual_qty + %s
                                WHERE parent = %s
                                AND item_code = %s
                                AND item_group = %s
                            """, (sir_list[0].get('actual_qty'), sir_list[0].get('sir_registry_no'), 
                                item.item_code, item.item_group), debug=0, explain=0)
                        else:
                            updated_qty = int(item.qty) + int(get_sir_data[0].get('actual_qty'))
                            frappe.db.sql("""
                                UPDATE `tabSecurity Inward Registry Child`
                                SET actual_qty = %s
                                WHERE parent = %s
                                AND item_code = %s
                                AND item_group = %s
                            """, (updated_qty, sir_list[0].get('sir_registry_no'), 
                                item.item_code, item.item_group), debug=0, explain=0)
                        
                elif len(sir_list) > 1:
                    for sir in sir_list:
                        get_sir_data = frappe.db.sql("""
                                SELECT actual_qty, received_qty FROM `tabSecurity Inward Registry Child`
                                WHERE parent = %s 
                                AND item_code = %s 
                                AND item_group = %s
                            """, (sir.get('sir_registry_no'), item.item_code, item.item_group), as_dict=1)
                        
                        if get_sir_data:
                            if int(sir.get('actual_qty')) + int(get_sir_data[0].get('actual_qty')) == int(get_sir_data[0].get('received_qty')):
                                frappe.db.sql("""
                                    UPDATE `tabSecurity Inward Registry Child`
                                    SET actual_qty = actual_qty + %s
                                    WHERE parent = %s
                                    AND item_code = %s
                                    AND item_group = %s
                                """, (sir.get('actual_qty'), sir.get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)

                                if int(item.qty) == int(sir.get('actual_qty')):
                                    break

                            elif int(sir.get('actual_qty')) + int(get_sir_data[0].get('actual_qty')) != int(get_sir_data[0].get('received_qty')):
                                updated_qty = 0
                                for r in sir_list:
                                    if r.get('sir_registry_no') != sir.get('sir_registry_no'):
                                        updated_qty += r.get('actual_qty')
                                    else:
                                        break

                                resulting_val = abs(item.qty - updated_qty)

                                frappe.db.sql("""
                                    UPDATE `tabSecurity Inward Registry Child`
                                    SET actual_qty = actual_qty + %s
                                    WHERE parent = %s
                                    AND item_code = %s
                                    AND item_group = %s
                                    """, (resulting_val, sir.get('sir_registry_no'), item.item_code, item.item_group), debug=0, explain=0)
                                
                                if int(updated_qty) + int(resulting_val) == int(item.qty): 
                                    break

    def auto_create_debit_note(self):
        print("inside auto_create_debit_note==============")

        if not self.is_return:
            return

        existing = frappe.db.exists(
            "Purchase Invoice",
            {
                "is_return": 1,
                "return_against": self.name
            }
        )

        if existing:
            return

        try:
            pr_name = self.return_against

            pi_name = frappe.db.get_value(
                "Purchase Invoice Item",
                {
                    "purchase_receipt": pr_name,
                    "docstatus": 1
                },
                "parent"
            )

            if not pi_name:
                po_name = frappe.db.get_value(
                    "Purchase Receipt Item",
                    {"parent": pr_name},
                    "purchase_order"
                )

                if po_name:
                    pi_name = frappe.db.get_value(
                        "Purchase Invoice Item",
                        {
                            "purchase_order": po_name,
                            "docstatus": 1
                        },
                        "parent"
                    )

            if not pi_name:
                frappe.throw("Purchase Invoice not found for this PR")

            print("Using PI:", pi_name)

            source_pi = frappe.get_doc("Purchase Invoice", pi_name)
            supplier_gst_no = source_pi.get("supplier_gst_no")
            bill_no = source_pi.get("bill_no")

            print("GST:", supplier_gst_no, "| Bill No:", bill_no)

            debit_note = make_purchase_invoice(self.name)

            if not debit_note:
                frappe.throw("Debit Note creation failed")

            debit_note.supplier_gst_no = supplier_gst_no or "N/A"
            debit_note.bill_no = bill_no or "AUTO"

            print("Debit Note Created:", debit_note.name)

            debit_note.flags.ignore_permissions = True
            debit_note.submit()

            frappe.msgprint(
                _("Debit Note {0} created and submitted automatically.").format(debit_note.name),
                alert=True
            )

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                "Auto Debit Note Creation Failed"
            )
            raise

def get_pr_material_request_references():
    settings_value = frappe.db.get_value(
        "NJ Settings",
        {"parameter": "meterial_request_via_pr"},
        "value",
    )
    if not settings_value:
        settings_value = frappe.db.get_value(
            "NJ Settings",
            {"parameter": "material_request_via_pr"},
            "value",
        )

    return [
        reference.strip()
        for reference in (settings_value or "").replace("\n", ",").split(",")
        if reference.strip()
    ]

def get_pr_item_material_requests(item):
    mr_names = []

    if item.get("material_request"):
        mr_names.append(item.material_request)

    if item.get("material_request_item"):
        material_request = frappe.db.get_value(
            "Material Request Item",
            item.material_request_item,
            "parent",
        )
        if material_request:
            mr_names.append(material_request)

    return list(dict.fromkeys(mr_names))

def generate_batch_no(doc, method=None):
    start = time.perf_counter()
    try:
        for item in doc.items:
            set_registry_no(item)

            has_batch_no = frappe.db.get_value('Item', item.item_code, 'has_batch_no')

            if has_batch_no and item.idx:
                batch_id = f"{item.purchase_order}-{item.idx}"
                item.batch_no = batch_id

                if frappe.db.exists('Batch', batch_id):
                    batch_doc = frappe.get_doc('Batch', batch_id)
                else:
                    batch_doc = frappe.new_doc('Batch')
                    batch_doc.batch_id = batch_id
                    batch_doc.item = item.item_code
                    batch_doc.save()
    finally:
        log_pr_time("generate_batch_no", doc.name, start)
                                
def get_batch(doc, method=None):
    start = time.perf_counter()
    try:
        for item in doc.items:
            qr_code_mappings = []

            if item.item_code and item.qty and is_serialized(item.item_code) == 1:
                serial_nos = item.serial_no.split('\n') if item.serial_no else []
                for serial_no in serial_nos:
                    if serial_no.strip():
                        update_serial_no(serial_no.strip(), doc, item)

            if item.serial_no:
                for serial in item.serial_no.split('\n'):
                    serial = serial.strip()
                    if serial:
                        qr_code_mappings.append(generate_and_save_qrcode(serial))
            elif item.truncated_item_code:
                generate_and_save_qrcode(item.truncated_item_code)

            qr_code_mapping_str = '\n'.join(qr_code_mappings)
            frappe.db.sql("""
                UPDATE `tabPurchase Receipt Item` 
                SET qr_code_mapping = %s 
                WHERE name = %s
            """, (qr_code_mapping_str, item.name))
    finally:
        log_pr_time("get_batch", doc.name, start)

def before_save_purchase_receipt(doc, method):
    if doc.doctype == "Purchase Receipt":
        get_batch(doc, method)

def update_serial_no_on_pr_submit(doc, method=None):
    for item in doc.items:
        if item.item_code and item.qty and is_serialized(item.item_code) == 1:
            serial_nos = item.serial_no.split('\n') if item.serial_no else []
            for serial_no in serial_nos:
                update_serial_no(serial_no, doc, item)

def get_po_grade_for_purchase_receipt_item(item):
    """
    Fetch grade from Purchase Order Item.
    This function is intentionally PO-based because the requirement says:
    run this only when Grade is Grade A in Purchase Order.
    """
    if not item.get("purchase_order"):
        return None

    # Best match: direct PO Item link from PR Item
    if item.get("purchase_order_item"):
        po_grade = frappe.db.get_value(
            "Purchase Order Item",
            item.purchase_order_item,
            "grade"
        )
        if po_grade:
            return str(po_grade).strip()

    # Fallback match: same PO + same item_code
    if item.get("item_code"):
        po_grade = frappe.db.get_value(
            "Purchase Order Item",
            {
                "parent": item.purchase_order,
                "item_code": item.item_code
            },
            "grade"
        )
        if po_grade:
            return str(po_grade).strip()

    return None


def is_purchase_order_grade_a(item):
    po_grade = get_po_grade_for_purchase_receipt_item(item)
    return po_grade and po_grade.strip().upper() == "GRADE A"


def is_unknown_value(value):
    return not value or str(value).strip().upper() == "UNKNOWN"


def get_grade_a_item_value(value):
    if not value:
        return value

    value = str(value).strip()
    upper_value = value.upper()

    # If already Grade A, no need to change
    if upper_value.endswith("-GRADE A") or upper_value.endswith(" GRADE A"):
        return value

    # If item already ends with another grade, replace that grade with GRADE A
    grade_suffixes = [
        "-GRADE B", "-GRADE C", "-GRADE D",
        " GRADE B", " GRADE C", " GRADE D",
        "-UNKNOWN", " UNKNOWN"
    ]

    for suffix in grade_suffixes:
        if upper_value.endswith(suffix):
            return value[:len(value) - len(suffix)] + "-GRADE A"

    # If UNKNOWN appears anywhere inside item code, replace it
    if "UNKNOWN" in upper_value:
        value = value.replace("UNKNOWN", "GRADE A")
        value = value.replace("Unknown", "GRADE A")
        value = value.replace("unknown", "GRADE A")
        return value

    # If no grade exists, append Grade A
    return value + "-GRADE A"

def get_grade_a_item_for_part(serial_no_doc, part):
    item_group = part.get("item_group")

    if not item_group:
        return None

    parent_item_code = serial_no_doc.get("item_code") or ""
    parent_upper = parent_item_code.upper()

    # Try to identify model from parent item code
    model_keywords = []

    for keyword in ["T480", "T470", "L14", "5430", "5420", "5410", "5400"]:
        if keyword in parent_upper:
            model_keywords.append(keyword)

    candidates = frappe.get_all(
        "Item",
        filters={
            "item_group": item_group,
            "name": ["like", "%GRADE A%"]
        },
        fields=["name"],
        limit=100
    )

    if not candidates:
        return None

    candidate_names = [c.name for c in candidates]

    item_group_upper = item_group.upper()

    for model in model_keywords:
        matched = [
            name for name in candidate_names
            if model in name.upper()
            and item_group_upper in name.upper()
        ]

        if matched:
            matched = sorted(matched, key=len)
            return matched[0]

    # 2. Prefer generic S-<ITEM GROUP>-GRADE A item
    generic_name = f"S-{item_group}-GRADE A"

    for name in candidate_names:
        if name.upper() == generic_name.upper():
            return name

    # 3. Prefer any candidate that ends with GRADE A and contains the item group text
    matched = [
        name for name in candidate_names
        if item_group_upper in name.upper()
        and name.upper().endswith("GRADE A")
    ]

    if matched:
        matched = sorted(matched, key=len)
        return matched[0]

    # 4. Last fallback: only if exactly one candidate exists
    if len(candidate_names) == 1:
        return candidate_names[0]

    return None


def update_serial_no_part_list_grade_a_from_po(serial_no_doc, item):
    """
    Updates Serial No part list only when linked Purchase Order Item Grade = Grade A.

    What it changes:
    1. Part list grade UNKNOWN/blank -> Grade A
    2. Part list item/item_code -> matching Grade A Item

    If no valid Grade A Item exists in Item master, block the process.
    """
    if not is_purchase_order_grade_a(item):
        return

    part_rows = serial_no_doc.get("serial_no_component") or []

    if not part_rows:
        return

    missing_grade_a_items = {}

    for part in part_rows:
        # Update Grade column only if blank/UNKNOWN
        if part.meta.get_field("grade") and is_unknown_value(part.get("grade")):
            part.grade = "Grade A"

        # Update Item column to Grade A item
        for item_fieldname in ["item", "item_code"]:
            if not part.meta.get_field(item_fieldname):
                continue

            current_item_code = part.get(item_fieldname)

            if current_item_code:
                updated_item_code = get_grade_a_item_value(current_item_code)
            else:
                updated_item_code = get_grade_a_item_for_part(serial_no_doc, part)

            if not updated_item_code:
                item_group = part.get("item_group") or "Unknown Item Group"

                missing_grade_a_items[item_group] = (
                    "No valid existing Grade A Item Code found in Item master"
                )

                logger.warning(
                    "[PR Grade A Part List Update] Serial No=%s Row=%s skipped %s update. Could not find Grade A item for item_group=%s",
                    serial_no_doc.name,
                    part.name,
                    item_fieldname,
                    part.get("item_group")
                )
                continue

            if updated_item_code == part.get(item_fieldname):
                continue

            field_df = part.meta.get_field(item_fieldname)

            # If field is linked to Item, update only if that Item exists.
            # This prevents Purchase Receipt submit from breaking.
            if field_df and field_df.fieldtype == "Link" and field_df.options == "Item":
                if not frappe.db.exists("Item", updated_item_code):
                    item_group = part.get("item_group") or "Unknown Item Group"

                    missing_grade_a_items[item_group] = (
                        f"Missing Item Code: {updated_item_code}"
                    )

                    logger.warning(
                        "[PR Grade A Part List Update] Serial No=%s Row=%s skipped %s update. Item does not exist: %s",
                        serial_no_doc.name,
                        part.name,
                        item_fieldname,
                        updated_item_code
                    )
                    continue

            part.set(item_fieldname, updated_item_code)

    if missing_grade_a_items:
        message_rows = []

        for item_group, reason in missing_grade_a_items.items():
            message_rows.append(
                f"<b>{item_group}</b>: {reason}"
            )

        # Clear earlier ERPNext success messages like "Serial No XYZ Created"
        # because this validation is going to block the submit.
        frappe.local.message_log = []

        frappe.throw(
            msg=(
                f"Cannot continue because valid existing <b>Grade A Item Code</b> "
                f"is missing for some part rows in Serial No <b>{serial_no_doc.name}</b>."
                f"<br><br>"
                + "<br>".join(message_rows)
                + "<br><br>Please create/correct the Grade A Item Code in Item Master and try again."
            ),
            title="Grade A Item Code Missing"
        )

def update_serial_no(serial_no, doc, item):
    serial_no_doc = frappe.get_doc('Serial No', serial_no, for_update=True)
    supplier_name = frappe.db.get_value('Supplier', {'name': doc.supplier}, 'supplier_name')
    
    if serial_no_doc:
        get_purc_warranty_data = get_purchase_warranty_data(item, item.purchase_order)

        has_warrenty = frappe.db.get_value('Purchase Receipt', {'name': doc.name}, 'has_warranty')
        if has_warrenty:
           serial_no_doc.vendor_warranty_expiry_date = get_purc_warranty_data.get('vendor_warranty_expiry_date') if get_purc_warranty_data.get('vendor_warranty_expiry_date') else doc.warrenty_till_date
        else:
           serial_no_doc.vendor_warranty_expiry_date = None

        serial_no_doc.purchase_price = item.base_rate
        serial_no_doc.current_price = item.base_rate
        serial_no_doc.barcode = serial_no
        serial_no_doc.grade = item.grade
        update_serial_no_part_list_grade_a_from_po(serial_no_doc, item)
        serial_no_doc.supplier = doc.supplier
        serial_no_doc.purchase_warranty_days = get_purc_warranty_data.get('warranty_days') if get_purc_warranty_data.get('warranty_days') else doc.warranty_days
        serial_no_doc.purchase_order = item.purchase_order
        serial_no_doc.reference_doctype_no = doc.name
        serial_no_doc.supplier_name = supplier_name
        serial_no_doc.purchase_receipt = doc.name
        serial_no_doc.save()

def get_purchase_warranty_data(item, purchase_order):
    purc_doc = frappe.get_doc('Purchase Order', purchase_order)
    matching_warranty = {}

    if purc_doc:
        for row in purc_doc.get("purchase_order_warrenty_for_specific_parts"):
            if row.get("item_group") == item.item_group:
                matching_warranty["vendor_warranty_expiry_date"] = purc_doc.get("transaction_date") + timedelta(days=row.get("warranty_days"))
                matching_warranty["warranty_days"] = row.get("warranty_days")

    return matching_warranty

def set_registry_no(item):
    query = """
        SELECT name FROM `tabSecurity Inward Registry` 
        WHERE reference_po_number = %s AND docstatus = 1 AND total_qty > 0
    """
    
    get_sir_data = frappe.db.sql(query, (item.purchase_order,), as_dict=1)

    if get_sir_data:
        sir_names = []
        sir_actual_qty = []

        for data in get_sir_data:
            get_registry_doc = frappe.get_doc('Security Inward Registry', data.get('name'))

            if get_registry_doc.get('registry_type') == "Accept Registry":
                for row in get_registry_doc.get('purchase_inward_registry_child'):
                    if row.get('item_code') == item.item_code and row.get('item_group') == item.item_group and int(row.get('received_qty')) > 0:
                        sir_names.append(row.get('parent'))
                        sir_actual_qty.append(row.get('actual_qty'))

        if sir_names:
            item.sir_registry_no = ', '.join(sir_names)
            item.sir_actual_qty = ', '.join(sir_actual_qty)

@frappe.whitelist()
def check_for_warranty_validity(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)

    name = doc.get("name")
    vendor_warranty_expiry_date = doc.get("vendor_warranty_expiry_date")

    if not vendor_warranty_expiry_date or not name:
        return

    expiry_date = getdate(vendor_warranty_expiry_date)
    today = getdate(nowdate())

    is_warranty_valid = 1 if expiry_date >= today else 0

    frappe.db.set_value(doc.get("doctype"), name, "warranty_valid_check", is_warranty_valid)

    return {"warranty_valid_check": is_warranty_valid}


# ─────────────────────────────────────────────────────────────────────────────
# UOM Helpers — used by Purchase Receipt JS for item-wise UOM dropdown + CF
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_item_uoms(item_code):
    """Return all UOMs and conversion factors for an item."""
    return frappe.db.get_all(
        'UOM Conversion Detail',
        filters={'parent': item_code},
        fields=['uom', 'conversion_factor'],
        order_by='idx asc'
    )


@frappe.whitelist()
def get_item_uoms_for_query(doctype, txt, searchfield, start, page_len, filters):
    """Search query for UOM dropdown — returns all active UOMs."""
    if isinstance(filters, str):
        filters = json.loads(filters)
    return frappe.db.sql("""
        SELECT uom.name
        FROM `tabUOM` uom
        WHERE uom.enabled = 1
        AND uom.name LIKE %s
        ORDER BY
            CASE WHEN uom.name = %s THEN 0 ELSE 1 END,
            uom.name ASC
        LIMIT %s OFFSET %s
    """, ("%%%s%%" % txt, txt or "", page_len, start))


MR_SOURCE_DEPARTMENT = "Inward  - NJ"
MR_DEFAULT_SCHEDULE_DAYS = 3
MR_MIN_QTY = 0.000001


def _split_department_names(departments):
    if not departments:
        return []

    return [d.strip() for d in str(departments).split(",") if d.strip()]


def _get_consumable_departments(core_item_codes, consumable_item_codes):
    if not core_item_codes or not consumable_item_codes:
        return set()

    rows = frappe.db.sql("""
        SELECT DISTINCT
            c.departments
        FROM
            `tabItem` i
        INNER JOIN
            `tabItem Wizards` iw
            ON iw.item_template = i.variant_of
        INNER JOIN
            `tabConsumables` c
            ON c.parent = iw.name
        INNER JOIN
            `tabItem` item_doc
            ON item_doc.name = c.item_code
        WHERE
            i.item_code IN %(core_item_codes)s
            AND c.item_code IN %(consumable_item_codes)s
            AND item_doc.in_stock = 1
    """, {
        "core_item_codes": tuple(core_item_codes),
        "consumable_item_codes": tuple(consumable_item_codes),
    }, as_dict=1)

    departments = set()
    for row in rows:
        departments.update(_split_department_names(row.departments))

    return departments


def _get_schedule_days_for_department(source_department, target_department):
    source_sequence = frappe.db.get_value(
        "Department",
        source_department,
        "department_sequence",
    )
    print("source_sequence=======================", source_sequence)
    target_sequence = frappe.db.get_value(
        "Department",
        target_department,
        "department_sequence",
    )
    print("target_sequence=======================", target_sequence)

    if source_sequence is None or target_sequence is None:
        return None

    source_sequence = int(source_sequence)
    print("source_sequence=======================", source_sequence)
    target_sequence = int(target_sequence)
    print("target_sequence=======================", target_sequence)

    if target_sequence >= source_sequence:
        filters = {
            "from_sequence": source_sequence,
            "to_sequence": target_sequence,
        }
        print("filters=======================", filters)
        result = frappe.db.sql("""
            SELECT SUM(department_sla)
            FROM `tabDepartment`
            WHERE department_sequence >= %(from_sequence)s
                AND department_sequence < %(to_sequence)s
        """, filters)
        print("result=======================", result)
    else:
        filters = {
            "from_sequence": target_sequence,
            "to_sequence": source_sequence,
        }
        print("filters=======================", filters)
        result = frappe.db.sql("""
            SELECT SUM(department_sla)
            FROM `tabDepartment`
            WHERE department_sequence > %(from_sequence)s
                AND department_sequence <= %(to_sequence)s
        """, filters)
        print("result=======================", result)

    if not result or result[0][0] is None:
        return None

    return int(result[0][0] or 0)


def get_mr_schedule_date_from_pr(core_item_codes, shortage_item_codes):
    consumable_departments = _get_consumable_departments(
        core_item_codes,
        shortage_item_codes,
    )
    print("consumable_departments========11111111===============", consumable_departments)

    if not consumable_departments:
        return add_days(nowdate(), MR_DEFAULT_SCHEDULE_DAYS)

    schedule_days = []
    for department in consumable_departments:
        days = _get_schedule_days_for_department(MR_SOURCE_DEPARTMENT, department)
        if days is not None:
            schedule_days.append(days)

    if not schedule_days:
        return add_days(nowdate(), MR_DEFAULT_SCHEDULE_DAYS)

    return add_days(nowdate(), max(schedule_days))






# def mr_raise_from_pr(doc, method=None):
#     print("inside the function===================")
#     core_items = ["Laptops", "Chromeboxes", "Chromebooks", "Desktops", "Macbooks"]
#     print("core_items=======================", core_items)

#     # 🔹 Step 1: Get PR item codes
#     item_codes = list({d.item_code for d in doc.items if d.item_code})
#     print("item_codes=======================", item_codes)
#     if not item_codes:
#         return

#     # 🔹 Step 2: Filter core items
#     core_item_codes = frappe.get_all(
#         "Item",
#         filters={
#             "item_code": ["in", item_codes],
#             "item_group": ["in", core_items],
#         },
#         pluck="item_code",
#     )
#     print("core_item_codes=======================", core_item_codes)

#     if not core_item_codes:
#         return

#     # 🔹 Step 3: Fetch Consumables (SUM)
#     consumable_items = frappe.db.sql("""
#         SELECT 
#             c.item_code,
#             SUM(c.quantity) AS quantity
#         FROM 
#             `tabItem` i
#         INNER JOIN 
#             `tabItem Wizards` iw 
#             ON iw.item_template = i.variant_of
#         INNER JOIN 
#             `tabConsumables` c 
#             ON c.parent = iw.name
#         INNER JOIN 
#             `tabItem` item_doc
#             ON item_doc.name = c.item_code
#         WHERE 
#             i.item_code IN %(core_item_codes)s
#             AND item_doc.in_stock = 1
#         GROUP BY 
#             c.item_code
#     """, {"core_item_codes": tuple(core_item_codes)}, as_dict=1 , debug=1)
#     print("consumable_items=======================", consumable_items)

#     if not consumable_items:
#         return

#     # 🔹 Step 4: Extract item codes
#     consumable_item_codes = list({d["item_code"] for d in consumable_items})
#     print("consumable_item_codes=================", consumable_item_codes)
#     if not consumable_item_codes:
#         return

#     # 🔹 Step 5: Warehouse stock (SUM)
#     warehouse_qty = frappe.db.sql("""
#         SELECT  
#             b.item_code,
#             SUM(b.actual_qty) AS actual_qty
#         FROM 
#             `tabBin` b 
#         WHERE 
#             b.warehouse IN (
#                 SELECT name 
#                 FROM `tabWarehouse`
#                 WHERE department = 'Stores - NJ'
#             )
#             AND b.item_code IN %(consumable_item_codes)s
#         GROUP BY 
#             b.item_code
#     """, {
#         "consumable_item_codes": tuple(consumable_item_codes)
#     }, as_dict=1, debug=1)
#     print("warehouse_qty=======================", warehouse_qty)

#     # 🔹 Step 6: Convert to dict
#     bin_map = {d["item_code"]: d["actual_qty"] for d in warehouse_qty}
#     print("bin_map=======================", bin_map)

#     # 🔹 Step 7: Calculate shortage
#     shortage_items = []
#     for d in consumable_items:
#         item_code = d["item_code"]
#         print("item_code=======================", item_code)
#         required_qty = d["quantity"]
#         print("required_qty=======================", required_qty)
#         available_qty = bin_map.get(item_code, 0)
#         print("available_qty=======================", available_qty)

#         if available_qty < required_qty:
#             shortage_qty = required_qty - available_qty
#             print("shortage_qty=======================", shortage_qty)
#             shortage_items.append({
#                 "item_code": item_code,
#                 "qty": shortage_qty
#             })

#     # 🔹 Step 8: Stop if no shortage
#     if not shortage_items:
#         return

#     # 🔹 Step 9: Fetch FRU numbers in one go
#     item_fru_map = {
#         d["name"]: d["fru_number"]
#         for d in frappe.get_all(
#             "Item",
#             filters={"name": ["in", [i["item_code"] for i in shortage_items]]},
#             fields=["name", "fru_number"]
#         )
#     }
#     print("item_fru_map=======================", item_fru_map)

#     # 🔹 Step 10: Create MR
#     mr = frappe.new_doc("Material Request")
#     mr.material_request_type = "Manufacture"
#     mr.purpose = "Purchase"
#     mr.naming_series = 'MREQ-.YYYY.-.MM.-'
#     mr.company = doc.company
#     mr.schedule_date = add_days(nowdate(), 3)
#     mr.post_order_status = ''

#     # 🔹 Step 11: Append items
#     for d in shortage_items:
#         fru_number = item_fru_map.get(d["item_code"]) or "N/A"

#         mr.append("items", {
#             "item_code": d["item_code"],
#             "qty": d["qty"],
#             "schedule_date": mr.schedule_date,
#             "warehouse": "Stores - NJ",
#             "fru_number": fru_number
#         })

#     # 🔹 Step 12: Save & Submit
#     mr.insert(ignore_permissions=True)
#     mr.submit()

#     frappe.msgprint(f"Material Request Created: {mr.name}")

# def mr_raise_from_pr(doc, method=None):
#     return
#     print("inside the function===================")
#     core_items = ["Laptops", "Chromeboxes", "Chromebooks", "Desktops", "Macbooks"]
#     print("core_items=======================", core_items)

#     # 🔹 Step 1: Get PR item codes
#     item_codes = list({d.item_code for d in doc.items if d.item_code})
#     print("item_codes=======================", item_codes)
#     if not item_codes:
#         return

#     # 🔹 Step 2: Filter core items
#     core_item_codes = frappe.get_all(
#         "Item",
#         filters={
#             "item_code": ["in", item_codes],
#             "item_group": ["in", core_items],
#         },
#         pluck="item_code",
#     )
#     print("core_item_codes=======================", core_item_codes)

#     if not core_item_codes:
#         return

#     # 🔹 Step 3: Fetch Consumables (SUM)
#     consumable_items = frappe.db.sql("""
#         SELECT 
#             c.item_code,
#             SUM(c.quantity * pri.qty) AS quantity
#         FROM 
#             `tabPurchase Receipt Item` pri
#         INNER JOIN 
#             `tabItem` i
#             ON i.name = pri.item_code
#         INNER JOIN 
#             `tabItem Wizards` iw 
#             ON iw.item_template = i.variant_of
#         INNER JOIN 
#             `tabConsumables` c 
#             ON c.parent = iw.name
#         INNER JOIN 
#             `tabItem` item_doc
#             ON item_doc.name = c.item_code
#         WHERE 
#             pri.parent = %(purchase_receipt)s
#             AND i.item_code IN %(core_item_codes)s
#             AND item_doc.in_stock = 1
#         GROUP BY 
#             c.item_code
#     """, {
#         "purchase_receipt": doc.name,
#         "core_item_codes": tuple(core_item_codes),
#     }, as_dict=1 , debug=1)
#     print("consumable_items=======================", consumable_items)

#     if not consumable_items:
#         return

#     # 🔹 Step 4: Extract item codes
#     consumable_item_codes = list({d["item_code"] for d in consumable_items})
#     print("consumable_item_codes=================", consumable_item_codes)
#     print("PR MR consumable_item_codes count=================", len(consumable_item_codes))
#     if not consumable_item_codes:
#         return

#     # 🔹 Step 5: Warehouse stock (SUM)
#     warehouse_qty = frappe.db.sql("""
#         SELECT  
#             b.item_code,
#             SUM(b.actual_qty) AS actual_qty
#         FROM 
#             `tabBin` b 
#         WHERE 
#             b.warehouse IN (
#                 SELECT name 
#                 FROM `tabWarehouse`
#                 WHERE department = 'Stores - NJ'
#             )
#             AND b.item_code IN %(consumable_item_codes)s
#         GROUP BY 
#             b.item_code
#     """, {
#         "consumable_item_codes": tuple(consumable_item_codes)
#     }, as_dict=1, debug=1)
#     print("warehouse_qty=======================", warehouse_qty)
#     print("PR MR warehouse_qty rows count=======================", len(warehouse_qty))

#     # 🔹 Step 6: Convert to dict
#     bin_map = {d["item_code"]: d["actual_qty"] for d in warehouse_qty}
#     print("bin_map=======================", bin_map)

#     # 🔹 Step 7: Calculate shortage
#     shortage_items = []
#     for d in consumable_items:
#         item_code = d["item_code"]
#         print("item_code=======================", item_code)
#         required_qty = d["quantity"]
#         print("required_qty=======================", required_qty)
#         available_qty = bin_map.get(item_code, 0)
#         print("available_qty=======================", available_qty)

#         shortage_qty = required_qty - available_qty
#         if shortage_qty > MR_MIN_QTY:
#             print("shortage_qty=======================", shortage_qty)
#             shortage_items.append({
#                 "item_code": item_code,
#                 "qty": flt(shortage_qty, 6)
#             })

#     print("PR MR shortage_items before MR qty adjustment=======================", shortage_items)
#     print("PR MR shortage_items count before MR qty adjustment=======================", len(shortage_items))

#     # 🔹 Step 8: Stop if no shortage
#     if not shortage_items:
#         return

#     # 🔹 Step 9: Adjust shortage qty by already raised active Manufacture MR qty
#     existing_mr_items = frappe.db.sql("""
#         SELECT
#             mri.item_code,
#             SUM(mri.qty) AS existing_qty
#         FROM
#             `tabMaterial Request Item` mri
#         INNER JOIN
#             `tabMaterial Request` mr
#             ON mr.name = mri.parent
#         WHERE
#             mr.material_request_type = 'Manufacture'
#             AND mr.docstatus < 2
#             AND mri.item_code IN %(item_codes)s
#         GROUP BY
#             mri.item_code
#     """, {
#         "item_codes": tuple(d["item_code"] for d in shortage_items)
#     }, as_dict=1)
#     print("PR MR existing Manufacture MR qty rows=======================", existing_mr_items)
#     print("PR MR existing Manufacture MR qty rows count=======================", len(existing_mr_items))

#     if existing_mr_items:
#         existing_qty_by_item = {}
#         for row in existing_mr_items:
#             existing_qty_by_item[row.item_code] = flt(row.existing_qty)
#         print("PR MR existing_qty_by_item=======================", existing_qty_by_item)

#         adjusted_shortage_items = []
#         message_rows = []

#         for d in shortage_items:
#             existing_qty = existing_qty_by_item.get(d["item_code"], 0)
#             if existing_qty <= 0:
#                 adjusted_shortage_items.append(d)
#                 continue

#             required_qty = flt(d["qty"])
#             pending_qty = required_qty - existing_qty
#             print(
#                 "PR MR qty adjustment=======================",
#                 d["item_code"],
#                 "required:",
#                 required_qty,
#                 "existing_mr_qty:",
#                 existing_qty,
#                 "new_mr_qty:",
#                 max(pending_qty, 0),
#             )

#             if pending_qty > MR_MIN_QTY:
#                 adjusted_shortage_items.append({
#                     "item_code": d["item_code"],
#                     "qty": flt(pending_qty, 6),
#                 })

#             message_rows.append(
#                 _("Item Code: {0} | Required: {1} | Existing MR Qty: {2} | New MR Qty: {3}").format(
#                     frappe.bold(d["item_code"]),
#                     frappe.bold(required_qty),
#                     frappe.bold(existing_qty),
#                     frappe.bold(max(pending_qty, 0)),
#                 )
#             )

#         frappe.msgprint(
#             _("Existing Manufacture Material Request qty adjusted:<br>{0}").format(
#                 "<br>".join(message_rows)
#             ),
#             title=_("Material Request Qty Adjusted"),
#             indicator="orange",
#         )

#         shortage_items = adjusted_shortage_items

#     print("PR MR shortage_items after MR qty adjustment=======================", shortage_items)
#     print("PR MR shortage_items count after MR qty adjustment=======================", len(shortage_items))

#     if not shortage_items:
#         return

#     # 🔹 Step 10: Fetch FRU numbers in one go
#     item_fru_map = {
#         d["name"]: d["fru_number"]
#         for d in frappe.get_all(
#             "Item",
#             filters={"name": ["in", [i["item_code"] for i in shortage_items]]},
#             fields=["name", "fru_number"]
#         )
#     }
#     print("item_fru_map=======================", item_fru_map)

#     # 🔹 Step 11: Create MR
#     mr = frappe.new_doc("Material Request")
#     mr.material_request_type = "Manufacture"
#     mr.purpose = "Purchase"
#     mr.naming_series = 'MREQ-.YYYY.-.MM.-'
#     mr.company = doc.company
#     mr.schedule_date = get_mr_schedule_date_from_pr(
#         core_item_codes,
#         [d["item_code"] for d in shortage_items],
#     )
#     print("PR MR schedule_date=======================", mr.schedule_date)
#     mr.post_order_status = ''

#     # 🔹 Step 12: Append items
#     for d in shortage_items:
#         fru_number = item_fru_map.get(d["item_code"]) or "N/A"
#         print("PR MR append item=======================", d["item_code"], "qty:", d["qty"], "fru:", fru_number)

#         mr.append("items", {
#             "item_code": d["item_code"],
#             "qty": d["qty"],
#             "schedule_date": mr.schedule_date,
#             "warehouse": "Stores - NJ",
#             "fru_number": fru_number
#         })

#     # 🔹 Step 13: Save & Submit
#     mr.insert(ignore_permissions=True)
#     mr.submit()
#     print("PR MR created=======================", mr.name, "items:", len(shortage_items))

#     frappe.msgprint(f"Material Request Created: {mr.name}")
