# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
from frappe.utils import nowdate, add_days
from datetime import timedelta
from frappe.utils import getdate, nowdate, flt
from nj_lib.utils.common_utils import is_serialized
from nj_features.nj_features.api.qr_code import generate_and_save_qrcode
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt
from frappe import _
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

class CustomPurchaseReceipt(PurchaseReceipt):

    # ─────────────────────────────────────────────────────────────────────
    # MANUAL CONVERSION OVERRIDE — re-assert after standard validate
    # ─────────────────────────────────────────────────────────────────────
    def validate(self):
        super().validate()
        self._restore_manual_conversion_factors()

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

    def on_submit(self):
        super(CustomPurchaseReceipt, self).on_submit()
        self.set_registry_no_on_submit()
        self.auto_create_debit_note()
    
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

def generate_batch_no(doc, method=None):
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
                                
def get_batch(doc, method=None):
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

def before_save_purchase_receipt(doc, method):
    if doc.doctype == "Purchase Receipt":
        get_batch(doc, method)

def update_serial_no_on_pr_submit(doc, method=None):
    for item in doc.items:
        if item.item_code and item.qty and is_serialized(item.item_code) == 1:
            serial_nos = item.serial_no.split('\n') if item.serial_no else []
            for serial_no in serial_nos:
                update_serial_no(serial_no, doc, item)

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

def mr_raise_from_pr(doc, method=None):
    print("inside the function===================")
    core_items = ["Laptops", "Chromeboxes", "Chromebooks", "Desktops", "Macbooks"]
    print("core_items=======================", core_items)

    # 🔹 Step 1: Get PR item codes
    item_codes = list({d.item_code for d in doc.items if d.item_code})
    print("item_codes=======================", item_codes)
    if not item_codes:
        return

    # 🔹 Step 2: Filter core items
    core_item_codes = frappe.get_all(
        "Item",
        filters={
            "item_code": ["in", item_codes],
            "item_group": ["in", core_items],
        },
        pluck="item_code",
    )
    print("core_item_codes=======================", core_item_codes)

    if not core_item_codes:
        return

    # 🔹 Step 3: Fetch Consumables (SUM)
    consumable_items = frappe.db.sql("""
        SELECT 
            c.item_code,
            SUM(c.quantity * pri.qty) AS quantity
        FROM 
            `tabPurchase Receipt Item` pri
        INNER JOIN 
            `tabItem` i
            ON i.name = pri.item_code
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
            pri.parent = %(purchase_receipt)s
            AND i.item_code IN %(core_item_codes)s
            AND item_doc.in_stock = 1
        GROUP BY 
            c.item_code
    """, {
        "purchase_receipt": doc.name,
        "core_item_codes": tuple(core_item_codes),
    }, as_dict=1 , debug=1)
    print("consumable_items=======================", consumable_items)

    if not consumable_items:
        return

    # 🔹 Step 4: Extract item codes
    consumable_item_codes = list({d["item_code"] for d in consumable_items})
    print("consumable_item_codes=================", consumable_item_codes)
    print("PR MR consumable_item_codes count=================", len(consumable_item_codes))
    if not consumable_item_codes:
        return

    # 🔹 Step 5: Warehouse stock (SUM)
    warehouse_qty = frappe.db.sql("""
        SELECT  
            b.item_code,
            SUM(b.actual_qty) AS actual_qty
        FROM 
            `tabBin` b 
        WHERE 
            b.warehouse IN (
                SELECT name 
                FROM `tabWarehouse`
                WHERE department = 'Stores - NJ'
            )
            AND b.item_code IN %(consumable_item_codes)s
        GROUP BY 
            b.item_code
    """, {
        "consumable_item_codes": tuple(consumable_item_codes)
    }, as_dict=1, debug=1)
    print("warehouse_qty=======================", warehouse_qty)
    print("PR MR warehouse_qty rows count=======================", len(warehouse_qty))

    # 🔹 Step 6: Convert to dict
    bin_map = {d["item_code"]: d["actual_qty"] for d in warehouse_qty}
    print("bin_map=======================", bin_map)

    # 🔹 Step 7: Calculate shortage
    shortage_items = []
    for d in consumable_items:
        item_code = d["item_code"]
        print("item_code=======================", item_code)
        required_qty = d["quantity"]
        print("required_qty=======================", required_qty)
        available_qty = bin_map.get(item_code, 0)
        print("available_qty=======================", available_qty)

        shortage_qty = required_qty - available_qty
        if shortage_qty > MR_MIN_QTY:
            print("shortage_qty=======================", shortage_qty)
            shortage_items.append({
                "item_code": item_code,
                "qty": flt(shortage_qty, 6)
            })

    print("PR MR shortage_items before MR qty adjustment=======================", shortage_items)
    print("PR MR shortage_items count before MR qty adjustment=======================", len(shortage_items))

    # 🔹 Step 8: Stop if no shortage
    if not shortage_items:
        return

    # 🔹 Step 9: Adjust shortage qty by already raised active Manufacture MR qty
    existing_mr_items = frappe.db.sql("""
        SELECT
            mri.item_code,
            SUM(mri.qty) AS existing_qty
        FROM
            `tabMaterial Request Item` mri
        INNER JOIN
            `tabMaterial Request` mr
            ON mr.name = mri.parent
        WHERE
            mr.material_request_type = 'Manufacture'
            AND mr.docstatus < 2
            AND mri.item_code IN %(item_codes)s
        GROUP BY
            mri.item_code
    """, {
        "item_codes": tuple(d["item_code"] for d in shortage_items)
    }, as_dict=1)
    print("PR MR existing Manufacture MR qty rows=======================", existing_mr_items)
    print("PR MR existing Manufacture MR qty rows count=======================", len(existing_mr_items))

    if existing_mr_items:
        existing_qty_by_item = {}
        for row in existing_mr_items:
            existing_qty_by_item[row.item_code] = flt(row.existing_qty)
        print("PR MR existing_qty_by_item=======================", existing_qty_by_item)

        adjusted_shortage_items = []
        message_rows = []

        for d in shortage_items:
            existing_qty = existing_qty_by_item.get(d["item_code"], 0)
            if existing_qty <= 0:
                adjusted_shortage_items.append(d)
                continue

            required_qty = flt(d["qty"])
            pending_qty = required_qty - existing_qty
            print(
                "PR MR qty adjustment=======================",
                d["item_code"],
                "required:",
                required_qty,
                "existing_mr_qty:",
                existing_qty,
                "new_mr_qty:",
                max(pending_qty, 0),
            )

            if pending_qty > MR_MIN_QTY:
                adjusted_shortage_items.append({
                    "item_code": d["item_code"],
                    "qty": flt(pending_qty, 6),
                })

            message_rows.append(
                _("Item Code: {0} | Required: {1} | Existing MR Qty: {2} | New MR Qty: {3}").format(
                    frappe.bold(d["item_code"]),
                    frappe.bold(required_qty),
                    frappe.bold(existing_qty),
                    frappe.bold(max(pending_qty, 0)),
                )
            )

        frappe.msgprint(
            _("Existing Manufacture Material Request qty adjusted:<br>{0}").format(
                "<br>".join(message_rows)
            ),
            title=_("Material Request Qty Adjusted"),
            indicator="orange",
        )

        shortage_items = adjusted_shortage_items

    print("PR MR shortage_items after MR qty adjustment=======================", shortage_items)
    print("PR MR shortage_items count after MR qty adjustment=======================", len(shortage_items))

    if not shortage_items:
        return

    # 🔹 Step 10: Fetch FRU numbers in one go
    item_fru_map = {
        d["name"]: d["fru_number"]
        for d in frappe.get_all(
            "Item",
            filters={"name": ["in", [i["item_code"] for i in shortage_items]]},
            fields=["name", "fru_number"]
        )
    }
    print("item_fru_map=======================", item_fru_map)

    # 🔹 Step 11: Create MR
    mr = frappe.new_doc("Material Request")
    mr.material_request_type = "Manufacture"
    mr.purpose = "Purchase"
    mr.naming_series = 'MREQ-.YYYY.-.MM.-'
    mr.company = doc.company
    mr.schedule_date = get_mr_schedule_date_from_pr(
        core_item_codes,
        [d["item_code"] for d in shortage_items],
    )
    print("PR MR schedule_date=======================", mr.schedule_date)
    mr.post_order_status = ''

    # 🔹 Step 12: Append items
    for d in shortage_items:
        fru_number = item_fru_map.get(d["item_code"]) or "N/A"
        print("PR MR append item=======================", d["item_code"], "qty:", d["qty"], "fru:", fru_number)

        mr.append("items", {
            "item_code": d["item_code"],
            "qty": d["qty"],
            "schedule_date": mr.schedule_date,
            "warehouse": "Stores - NJ",
            "fru_number": fru_number
        })

    # 🔹 Step 13: Save & Submit
    mr.insert(ignore_permissions=True)
    mr.submit()
    print("PR MR created=======================", mr.name, "items:", len(shortage_items))

    frappe.msgprint(f"Material Request Created: {mr.name}")
