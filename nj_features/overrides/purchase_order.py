# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
import json
import traceback
from frappe.utils import flt
from frappe.model.mapper import get_mapped_doc

def create_batch(doc, method=None):
    for item in doc.items:
        item_doc = frappe.get_doc("Item", item.item_code)
        if item_doc.has_batch_no:
            batch_doc = frappe.new_doc('Batch')
            batch_doc.batch_id = doc.name +'-'+ str(item.idx)
            batch_doc.item = item.item_code
            batch_doc.save()


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL CONVERSION OVERRIDE — server-side guard
# ─────────────────────────────────────────────────────────────────────────────
def restore_manual_conversion_on_po(doc, method=None):
    for item in doc.items:
        if item.get("manual_conversion_override"):
            cf = flt(item.conversion_factor)
            if cf <= 0:
                frappe.throw(
                    f"Row {item.idx} ({item.item_code}): Conversion Factor must be "
                    f"greater than 0 when Manual Conversion Override is enabled."
                )
            item.stock_qty = flt(item.qty) * cf


@frappe.whitelist()
def check_billed_and_closed_amount(purchase_order, po_grand_total):
    po_grand_total = float(po_grand_total)
    
    total_billed_amount_query = """SELECT SUM(net_amount) AS total_billed_amount FROM `tabPurchase Receipt Item`
                                WHERE purchase_order = %s AND docstatus = 1"""
    total_billed_amount = frappe.db.sql(total_billed_amount_query, (purchase_order), as_dict=1)
    
    total_closed_amount_query = """SELECT SUM(net_amount) AS total_closed_amount FROM `tabPurchase Invoice Item` 
                                WHERE purchase_order = %s AND docstatus = 1"""
    total_closed_amount = frappe.db.sql(total_closed_amount_query, (purchase_order), as_dict=1)
    
    parameters_dict = {}
    po_nj_settings = frappe.db.get_all('NJ Settings', {'module': 'NJ Features', 'doc_type': 'Purchase Order'}, ['parameter', 'value'])
    
    for param in po_nj_settings:
        if param.parameter == 'purchase_receipt_value':
            parameters_dict[param.parameter] = float(param.value)
        else:
            parameters_dict[param.parameter] = param.value
            
    tolerance_amount = parameters_dict.get('purchase_receipt_value', 0)
    if parameters_dict.get('purchase_receipt_type').lower() == 'percentage':
        tolerance_amount = po_grand_total * (parameters_dict.get('purchase_receipt_value', 0) / 100)
    
    return {'po_grand_total':po_grand_total, 'tolerance_amount': tolerance_amount,
        'total_billed_amount': total_billed_amount[0].total_billed_amount, 'total_closed_amount': total_closed_amount[0].total_closed_amount}

@frappe.whitelist()
def make_purchase_receipt(source_name, target_doc=None, sir_name=None):
    try:
        def update_item(obj, target, source_parent):
            if sir_name:
                sir_doc = frappe.get_doc('Security Inward Registry', sir_name)
                for sir_item in sir_doc.get('transfer_registry', []):
                    if sir_item.get('item_code') == obj.item_code:
                        target.qty = sir_item.get('actual_qty')

            if obj.get("manual_conversion_override"):
                target.manual_conversion_override = 1
                target.conversion_factor = flt(obj.conversion_factor)

            target.stock_qty = (flt(obj.qty) - flt(obj.received_qty)) * flt(obj.conversion_factor)
            target.amount = (flt(obj.qty) - flt(obj.received_qty)) * flt(obj.rate)
            target.base_amount = (
                (flt(obj.qty) - flt(obj.received_qty)) * flt(obj.rate) * flt(source_parent.conversion_rate)
            )

        doc = get_mapped_doc(
            "Purchase Order",
            source_name,
            {
                "Purchase Order": {
                    "doctype": "Purchase Receipt",
                    "field_map": {"supplier_warehouse": "supplier_warehouse"},
                    "validation": {
                        "docstatus": ["=", 1],
                    },
                },
                "Purchase Order Item": {
                    "doctype": "Purchase Receipt Item",
                    "field_map": {
                        "name": "purchase_order_item",
                        "parent": "purchase_order",
                        "bom": "bom",
                        "material_request": "material_request",
                        "material_request_item": "material_request_item",
                    },
                    "postprocess": update_item,
                    "condition": lambda doc: abs(doc.received_qty) < abs(doc.qty)
                    and doc.delivered_by_supplier != 1,
                },
                "Purchase Taxes and Charges": {"doctype": "Purchase Taxes and Charges", "add_if_empty": True},
            },
            target_doc,
            set_missing_values,
        )

        doc.set_onload("ignore_price_list", True)

        return doc

    except Exception as e:
        traceback_info = traceback.format_exc()
        return {'error': str(e), 'traceback': traceback_info}
    

def validate_mandatory_links(doc, method=None):

    core_item_groups = ['Laptops', 'Chromeboxes', 'Chromebooks', 'Desktops']
    requires_links = False

     # Add email validation here
    email_id = (doc.get("contact_email") or "").strip()

    # fallback to Supplier master email, if needed
    if not email_id and doc.get("supplier"):
        email_id = (frappe.db.get_value("Supplier", doc.supplier, "email_id") or "").strip()

    if not email_id:
        frappe.throw("Email ID is mandatory for invoicing.")

    
    if doc.is_sample:
        return

    for item in doc.items:
        item_group = frappe.db.get_value('Item', item.item_code, 'item_group')
        if item_group in core_item_groups:
            requires_links = True
            break 
    
    if requires_links:
        if not doc.qc_link or not doc.pricing_link or not doc.npd_approval_:
            frappe.throw("QC Link,Pricing Link and NPD Approval is mandatory when core products are included in the Purchase Order.")


def validate_warranty_on_submit(doc, method=None):
    doc = frappe.get_doc(frappe.parse_json(doc))
    
    if not doc.get("part_warranty"):
        return {"status": "skipped", "message": "Part warranty not enabled"}

    for row in doc.get("purchase_order_warrenty_for_specific_parts"):
        if not row.item_group:
            continue

        standard_days = frappe.get_value("Item Group", row.item_group, "warranty_days") or 0
        user_days = row.warranty_days or 0

        if user_days < standard_days:
            frappe.throw(
                f"Cannot submit.<br>Warranty days for <b>{row.item_group}</b> are too low.<br>"
                f"Entered: <b>{user_days}</b>, Required Above: <b>{standard_days}</b>"
            )
      
def set_missing_values(source, target):
	target.run_method("set_missing_values")
	target.run_method("calculate_taxes_and_totals")


@frappe.whitelist()
def part_warrnty_days_after_save(docname):
    doc = frappe.get_doc("Purchase Order", docname)
    if not doc.get("part_warranty"):
        return {"status": "skipped", "message": "Part warranty not enabled"}
    
    current_item_groups = set()
    item_group_map = {}  
    
    for row in doc.get("items", []):
        item_code = row.get("item_code")
        if not item_code:
            continue
            
        item = frappe.get_doc("Item", item_code)
        item_group = item.item_group
        
        if item_group:
            current_item_groups.add(item_group)
            if item_group not in item_group_map:
                item_group_doc = frappe.get_doc("Item Group", item_group)
                item_group_map[item_group] = item_group_doc.warranty_days or 0
    
    existing_rows = {r.item_group: r for r in doc.get("purchase_order_warrenty_for_specific_parts", []) if r.item_group}
    new_warranty_entries = [] 
    added_count = 0
    removed_count = len(existing_rows) - len(current_item_groups & set(existing_rows.keys()))
    
    for item_group in current_item_groups:
        standard_days = item_group_map.get(item_group, 0)
        existing_row = existing_rows.get(item_group)
        
        if existing_row:
            user_days = existing_row.warranty_days or 0
            if user_days < standard_days:
                return {
                    "error": (
                        f"Warranty days entered for Item Group <b>{item_group}</b> is less than the standard.<br>"
                        f"Entered: <b>{user_days}</b> | Required Above: <b>{standard_days}</b>"
                    )
                }
            new_warranty_entries.append({
                "item_group": item_group,
                "warranty_days": existing_row.warranty_days
            })
        else:
            new_warranty_entries.append({
                "item_group": item_group,
                "warranty_days": standard_days
            })
            added_count += 1
    
    doc.set("purchase_order_warrenty_for_specific_parts", [])
    
    for entry in new_warranty_entries:
        doc.append("purchase_order_warrenty_for_specific_parts", entry)
    
    doc.flags.ignore_validate_update_after_submit = True
    doc.flags.ignore_permissions = True
    doc.flags.ignore_mandatory = True
    doc.save()
    
    return {
        "status": "updated",
        "message": f"Added {added_count}, removed {removed_count} warranty entries"
    }

@frappe.whitelist()
def get_tax_without_holding(supplier):
    tax_category = frappe.db.get_value("Supplier", supplier, "tax_withholding_category")
    frappe.logger().info(f"Fetched Tax Withholding Category for {supplier}: {tax_category}")
    return tax_category


@frappe.whitelist()
def get_item_group_cost_centers(items):
    print("get_item_group_cost_centers========+++++++")
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
def fetch_unique_records(doc):
    doc = json.loads(doc)

    items = doc.get("items", [])
    summary = {}  

    for row in items:
        item_code = row.get("item_code")
        if not item_code:
            continue

        qty = frappe.utils.flt(row.get("qty") or 0)
        rate = frappe.utils.flt(row.get("rate") or 0)
        amount = frappe.utils.flt(row.get("amount") or 0)

        if item_code not in summary:
            summary[item_code] = {
                "item_code": item_code,
                "qty": qty,
                "rate": rate,
                "amount": amount
            }
        else:
            summary[item_code]["qty"] += qty
            summary[item_code]["rate"] = rate
            summary[item_code]["amount"] += amount

    unique_rows = list(summary.values())
    return unique_rows


@frappe.whitelist()
def create_pr_on_submit(doc, method):
    return


# ─────────────────────────────────────────────────────────────────────────────
# UOM Helpers — used by Purchase Order JS for item-wise UOM dropdown + CF
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