# Copyright (c) 2026, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, flt, getdate, nowdate
from frappe.model.document import Document

class AutoRFQCreation(Document):
	pass


def auto_rfq_creation():
	departments = _get_setting_values("auto_rfq_creation_departments")
	item_groups = _get_setting_values("auto_rfq_creation_item_groups")

	if not departments or not item_groups:
		frappe.log_error(
			message=(
				"Auto RFQ Creation was skipped because one or both NJ Settings "
				"values are empty: auto_rfq_creation_departments, "
				"auto_rfq_creation_item_groups."
			),
			title="Auto RFQ Creation Settings Missing",
		)
		return

	serial_nos = frappe.db.sql(
		"""
		SELECT
			sn.name AS serial_no,
			sn.department
		FROM `tabSerial No` sn
		INNER JOIN `tabItem` item ON item.name = sn.item_code
		WHERE sn.status = 'Active'
			AND sn.department IN %(departments)s
			AND item.item_group IN %(item_groups)s
		ORDER BY sn.name
		""",
		{
			"departments": tuple(departments),
			"item_groups": tuple(item_groups),
		},
		as_dict=True,
	)

	doc = frappe.new_doc("Auto RFQ Creation")
	doc.rfq_creation = nowdate()
	open_mr_data = _get_open_mr_data(serial_nos)

	for serial_no in serial_nos:
		doc.append(
			"auto_rfq_serial_no",
			{
				"serial_no": serial_no.serial_no,
				"department": serial_no.department,
			},
		)

	for mr_item in open_mr_data:
		if not mr_item.item_exists:
			print(
				"[Auto RFQ Creation] Skipping missing Item Code "
				f"'{mr_item.item_code}' for Serial No '{mr_item.serial_no}' "
				f"in Material Request '{mr_item.material_request}'."
			)
			continue

		doc.append(
			"auto_rfq_open_mr_data",
			{
				"material_request": mr_item.material_request,
				"serial_no": mr_item.serial_no,
				"item_code": mr_item.item_code,
				"quantity": mr_item.quantity,
			},
		)

	calculation_details = _print_inventory_comparison(open_mr_data) or []
	for calculation in calculation_details:
		doc.append("auto_rfq_calculation_details", calculation)
	eligible_suppliers = _set_rfq_inclusion_details(doc)

	doc.insert(ignore_permissions=True)
	_create_global_rfq(doc, eligible_suppliers)
	return doc.name


def _get_setting_values(parameter):
	value = frappe.db.get_value(
		"NJ Settings",
		{
			"module": "NJ Features",
			"doc_type": "Auto RFQ Creation",
			"parameter": parameter,
		},
		"value",
	)

	return list(dict.fromkeys(part.strip() for part in (value or "").split(",") if part.strip()))


def _get_open_mr_data(serial_nos):
	serial_no_names = tuple(row.serial_no for row in serial_nos)
	if not serial_no_names:
		return []

	return frappe.db.sql(
		"""
		SELECT
			mr.name AS material_request,
			mri.serial_no,
			mri.item_code,
			mri.qty AS quantity,
			IF(item.name IS NULL, 0, 1) AS item_exists
		FROM `tabMaterial Request Item` mri
		INNER JOIN `tabMaterial Request` mr ON mr.name = mri.parent
		LEFT JOIN `tabItem` item ON item.name = mri.item_code
		WHERE mri.serial_no IN %(serial_nos)s
			AND mr.docstatus = 1
			AND COALESCE(TRIM(mr.post_order_status), '') = ''
			AND COALESCE(TRIM(mri.post_order_status), '') != 'Completed'
			AND IFNULL(mr.status, '') NOT IN (
				'Stopped', 'Cancelled', 'Ordered', 'Issued',
				'Transferred', 'Received', 'Completed'
			)
		ORDER BY mri.serial_no, mr.name, mri.idx
		""",
		{"serial_nos": serial_no_names},
		as_dict=True,
	)


def _print_inventory_comparison(open_mr_data):
	item_requirements = {}
	for row in open_mr_data:
		if row.item_exists:
			item_requirements[row.item_code] = (
				item_requirements.get(row.item_code, 0) + flt(row.quantity)
			)

	if not item_requirements:
		print("[Auto RFQ Inventory Comparison] No valid open MR items found.")
		return []

	inventory_departments = _get_setting_values("auto_rfq_inventory_departments")
	if not inventory_departments:
		print(
			"[Auto RFQ Inventory Comparison] Skipped because NJ Settings "
			"parameter 'auto_rfq_inventory_departments' is empty."
		)
		return []

	inventory_rows = frappe.db.sql(
		"""
		SELECT
			bin.item_code,
			COALESCE(SUM(bin.actual_qty), 0) AS inventory_qty
		FROM `tabBin` bin
		INNER JOIN `tabWarehouse` warehouse ON warehouse.name = bin.warehouse
		WHERE bin.item_code IN %(item_codes)s
			AND warehouse.department IN %(departments)s
			AND warehouse.disabled = 0
			AND warehouse.is_group = 0
		GROUP BY bin.item_code
		""",
		{
			"item_codes": tuple(item_requirements),
			"departments": tuple(inventory_departments),
		},
		as_dict=True,
	)
	inventory_by_item = {row.item_code: flt(row.inventory_qty) for row in inventory_rows}

	print("[Auto RFQ Inventory Comparison] Grouped MR requirement vs department inventory")
	print(f"Inventory Departments: {', '.join(inventory_departments)}")
	shortage_by_item = {}
	for item_code in sorted(item_requirements):
		required_qty = flt(item_requirements[item_code])
		inventory_qty = flt(inventory_by_item.get(item_code, 0))
		shortage_qty = max(required_qty - inventory_qty, 0)
		print(
			f"Item Code: {item_code} | MR Qty: {required_qty:g} | "
			f"Inventory Qty: {inventory_qty:g} | "
			f"Shortage Qty: {shortage_qty:g} | "
			f"Calculation: max({required_qty:g} - {inventory_qty:g}, 0) = {shortage_qty:g}"
		)
		if shortage_qty > 0:
			shortage_by_item[item_code] = {
				"mr_qty": required_qty,
				"inventory_qty": inventory_qty,
				"shortage_qty": shortage_qty,
			}

	if not shortage_by_item:
		print("[Auto RFQ WIP Part List Comparison] Skipped: inventory covers all MR quantities.")
		return []

	return _print_wip_part_list_comparison(shortage_by_item)


def _print_wip_part_list_comparison(shortage_by_item):
	wip_department = "WIP  - NJ"
	eligible_wip_serials = frappe.db.sql(
		"""
		SELECT
			serial_no.name AS serial_no,
			serial_no.item_code,
			serial_no.item_group,
			serial_no.department,
			serial_no.status
		FROM `tabSerial No` serial_no
		WHERE serial_no.status = 'Active'
			AND serial_no.department = %(department)s
			AND serial_no.item_group IN ('Laptops', 'Chromebooks')
		ORDER BY serial_no.name
		""",
		{"department": wip_department},
		as_dict=True,
	)
	print("[Auto RFQ WIP Part List Comparison] Eligible WIP serial numbers")
	for serial_no in eligible_wip_serials:
		print(
			f"WIP Serial No: {serial_no.serial_no} | Parent Item Code: {serial_no.item_code} | "
			f"Item Group: {serial_no.item_group} | Department: {serial_no.department} | "
			f"Status: {serial_no.status}"
		)

	part_list_rows = frappe.db.sql(
		"""
		SELECT
			serial_no.name AS serial_no,
			part.item AS item_code,
			SUM(part.quantity) AS part_list_qty
		FROM `tabSerial No Component` part
		INNER JOIN `tabSerial No` serial_no ON serial_no.name = part.parent
		INNER JOIN `tabItem` serial_item ON serial_item.name = serial_no.item_code
		WHERE part.parenttype = 'Serial No'
			AND part.parentfield = 'serial_no_component'
			AND part.item IN %(item_codes)s
			AND part.is_available = 1
			AND part.quantity > 0
			AND serial_no.status = 'Active'
			AND serial_no.department = %(department)s
			AND serial_item.item_group IN ('Laptops', 'Chromebooks')
		GROUP BY serial_no.name, part.item
		ORDER BY part.item, serial_no.name
		""",
		{
			"item_codes": tuple(shortage_by_item),
			"department": wip_department,
		},
		as_dict=True,
	)
	print("[Auto RFQ WIP Part List Comparison] Serial-level matching available parts")
	if not part_list_rows:
		print("No eligible WIP Part List items match the current shortage Item Codes.")
	part_list_by_item = {}
	serial_nos_by_item = {}
	for row in part_list_rows:
		part_list_by_item[row.item_code] = (
			part_list_by_item.get(row.item_code, 0) + flt(row.part_list_qty)
		)
		serial_nos_by_item.setdefault(row.item_code, []).append(row.serial_no)
		print(
			f"WIP Serial No: {row.serial_no} | Item Code: {row.item_code} | "
			f"Available Part Qty: {flt(row.part_list_qty):g}"
		)

	print("[Auto RFQ WIP Part List Comparison] Item-level final shortage")
	print(f"WIP Department: {wip_department} | Serial Item Groups: Laptops, Chromebooks")
	shortage_after_wip = {}
	for item_code in sorted(shortage_by_item):
		quantities = shortage_by_item[item_code]
		part_list_qty = flt(part_list_by_item.get(item_code, 0))
		wip_serial_nos = ", ".join(serial_nos_by_item.get(item_code, [])) or "None"
		final_shortage_qty = max(quantities["shortage_qty"] - part_list_qty, 0)
		print(
			f"Item Code: {item_code} | MR Qty: {quantities['mr_qty']:g} | "
			f"Inventory Qty: {quantities['inventory_qty']:g} | "
			f"Initial Shortage Qty: {quantities['shortage_qty']:g} | "
			f"WIP Serial Nos: {wip_serial_nos} | "
			f"WIP Part List Qty: {part_list_qty:g} | "
			f"Final Shortage Qty: {final_shortage_qty:g} | "
			f"Calculation: max({quantities['shortage_qty']:g} - {part_list_qty:g}, 0) "
			f"= {final_shortage_qty:g}"
		)
		if final_shortage_qty > 0:
			shortage_after_wip[item_code] = {
				**quantities,
				"wip_serial_nos": wip_serial_nos if wip_serial_nos != "None" else "",
				"wip_part_list_qty": part_list_qty,
				"shortage_after_wip": final_shortage_qty,
			}

	if not shortage_after_wip:
		print("[Auto RFQ Grade Inventory Comparison] Skipped: WIP parts cover all shortages.")
		return []

	return _print_grade_inventory_comparison(shortage_after_wip)


def _print_grade_inventory_comparison(shortage_after_wip):
	grade_departments = _get_setting_values("auto_rfq_grade_restriction_department")
	if not grade_departments:
		print(
			"[Auto RFQ Grade Inventory Comparison] Skipped because NJ Settings "
			"parameter 'auto_rfq_grade_restriction_department' is empty."
		)
		return []

	grade_suffixes = ("-grade a", "-grade b", "-grade d")
	variants_by_item = {}
	all_variants = set()
	for item_code in shortage_after_wip:
		lower_item_code = item_code.lower()
		matched_suffix = next(
			(suffix for suffix in grade_suffixes if lower_item_code.endswith(suffix)),
			None,
		)
		if not matched_suffix:
			print(
				f"[Auto RFQ Grade Inventory Comparison] Skipping Item Code '{item_code}': "
				"it does not end with GRADE A, GRADE B, or GRADE D."
			)
			continue

		base_item_code = lower_item_code[:-len(matched_suffix)]
		variants = {
			"GRADE A": f"{base_item_code}-grade a",
			"GRADE B": f"{base_item_code}-grade b",
			"GRADE D": f"{base_item_code}-grade d",
		}
		variants_by_item[item_code] = variants
		all_variants.update(variants.values())

	if not variants_by_item:
		print("[Auto RFQ Grade Inventory Comparison] No grade-based Item Codes to compare.")
		return []

	grade_inventory_rows = frappe.db.sql(
		"""
		SELECT
			LOWER(bin.item_code) AS normalized_item_code,
			bin.item_code,
			COALESCE(SUM(bin.actual_qty), 0) AS inventory_qty
		FROM `tabBin` bin
		INNER JOIN `tabWarehouse` warehouse ON warehouse.name = bin.warehouse
		WHERE LOWER(bin.item_code) IN %(item_codes)s
			AND warehouse.department IN %(departments)s
			AND warehouse.disabled = 0
			AND warehouse.is_group = 0
		GROUP BY LOWER(bin.item_code), bin.item_code
		ORDER BY bin.item_code
		""",
		{
			"item_codes": tuple(all_variants),
			"departments": tuple(grade_departments),
		},
		as_dict=True,
	)
	grade_inventory = {}
	actual_item_codes = {}
	for row in grade_inventory_rows:
		grade_inventory[row.normalized_item_code] = (
			grade_inventory.get(row.normalized_item_code, 0) + flt(row.inventory_qty)
		)
		actual_item_codes.setdefault(row.normalized_item_code, []).append(row.item_code)

	print("[Auto RFQ Grade Inventory Comparison] Shortage after WIP vs grade inventory")
	print(f"Grade Restriction Departments: {', '.join(grade_departments)}")
	shortage_after_grade_inventory = {}
	for item_code in sorted(variants_by_item):
		quantities = shortage_after_wip[item_code]
		variant_details = []
		total_grade_inventory = 0
		for grade, normalized_variant in variants_by_item[item_code].items():
			variant_qty = flt(grade_inventory.get(normalized_variant, 0))
			total_grade_inventory += variant_qty
			display_code = ", ".join(actual_item_codes.get(normalized_variant, [])) or normalized_variant
			variant_details.append(f"{grade} Item: {display_code} | Qty: {variant_qty:g}")

		final_shortage_qty = max(
			quantities["shortage_after_wip"] - total_grade_inventory,
			0,
		)
		print(
			f"Item Code: {item_code} | Shortage After WIP: {quantities['shortage_after_wip']:g} | "
			f"{' | '.join(variant_details)} | Total Grade Inventory Qty: {total_grade_inventory:g} | "
			f"Final Shortage Qty: {final_shortage_qty:g} | "
			f"Calculation: max({quantities['shortage_after_wip']:g} - "
			f"{total_grade_inventory:g}, 0) = {final_shortage_qty:g}"
		)
		if final_shortage_qty > 0:
			grade_items = {
				grade: frappe.db.get_value("Item", {"name": normalized_variant}, "name")
				for grade, normalized_variant in variants_by_item[item_code].items()
			}
			shortage_after_grade_inventory[item_code] = {
				**quantities,
				"grade_a_item": grade_items["GRADE A"],
				"grade_a_qty": flt(grade_inventory.get(variants_by_item[item_code]["GRADE A"], 0)),
				"grade_b_item": grade_items["GRADE B"],
				"grade_b_qty": flt(grade_inventory.get(variants_by_item[item_code]["GRADE B"], 0)),
				"grade_d_item": grade_items["GRADE D"],
				"grade_d_qty": flt(grade_inventory.get(variants_by_item[item_code]["GRADE D"], 0)),
				"grade_inventory_qty": total_grade_inventory,
				"shortage_after_grade_inventory": final_shortage_qty,
			}

	if not shortage_after_grade_inventory:
		print("[Auto RFQ Open PO Comparison] Skipped: grade inventory covers all shortages.")
		return []

	return _print_open_po_comparison(shortage_after_grade_inventory)


def _print_open_po_comparison(shortage_after_grade_inventory):
	po_item_rows = frappe.db.sql(
		"""
		SELECT
			po.name AS purchase_order,
			po.status,
			poi.item_code,
			poi.qty AS ordered_qty,
			poi.received_qty,
			GREATEST(poi.qty - poi.received_qty, 0) AS pending_qty
		FROM `tabPurchase Order Item` poi
		INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
		WHERE poi.item_code IN %(item_codes)s
			AND po.docstatus = 1
			AND po.status IN ('To Receive', 'To Receive and Bill', 'To Bill')
			AND GREATEST(poi.qty - poi.received_qty, 0) > 0
		ORDER BY poi.item_code, po.name, poi.idx
		""",
		{"item_codes": tuple(shortage_after_grade_inventory)},
		as_dict=True,
	)

	po_pending_by_item = {}
	po_names_by_item = {}
	print("[Auto RFQ Open PO Comparison] PO-level pending quantities")
	if not po_item_rows:
		print("No submitted open PO Items match the remaining shortage Item Codes.")
	for row in po_item_rows:
		pending_qty = flt(row.pending_qty)
		po_pending_by_item[row.item_code] = (
			po_pending_by_item.get(row.item_code, 0) + pending_qty
		)
		po_names_by_item.setdefault(row.item_code, [])
		if row.purchase_order not in po_names_by_item[row.item_code]:
			po_names_by_item[row.item_code].append(row.purchase_order)
		print(
			f"Purchase Order: {row.purchase_order} | Status: {row.status} | "
			f"Item Code: {row.item_code} | Ordered Qty: {flt(row.ordered_qty):g} | "
			f"Received Qty: {flt(row.received_qty):g} | Pending Qty: {pending_qty:g} | "
			f"Calculation: max({flt(row.ordered_qty):g} - {flt(row.received_qty):g}, 0) "
			f"= {pending_qty:g}"
		)

	print("[Auto RFQ Open PO Comparison] Item-level final RFQ quantity")
	calculation_details = []
	for item_code in sorted(shortage_after_grade_inventory):
		quantities = shortage_after_grade_inventory[item_code]
		total_po_pending_qty = flt(po_pending_by_item.get(item_code, 0))
		po_names = ", ".join(po_names_by_item.get(item_code, [])) or "None"
		final_rfq_qty = max(
			quantities["shortage_after_grade_inventory"] - total_po_pending_qty,
			0,
		)
		print(
			f"Item Code: {item_code} | "
			f"Shortage After Grade Inventory: "
			f"{quantities['shortage_after_grade_inventory']:g} | "
			f"Open PO Names: {po_names} | "
			f"Total Open PO Pending Qty: {total_po_pending_qty:g} | "
			f"Final RFQ Qty: {final_rfq_qty:g} | "
			f"Calculation: max({quantities['shortage_after_grade_inventory']:g} - "
			f"{total_po_pending_qty:g}, 0) = {final_rfq_qty:g}"
		)
		calculation_details.append(
			{
				"item_code": item_code,
				"mr_quantity": quantities["mr_qty"],
				"inventory_quantity": quantities["inventory_qty"],
				"inventory_shortage": quantities["shortage_qty"],
				"wip_serial_nos": quantities.get("wip_serial_nos"),
				"wip_part_list_quantity": quantities["wip_part_list_qty"],
				"shortage_after_wip": quantities["shortage_after_wip"],
				"grade_a_item": quantities.get("grade_a_item"),
				"grade_a_quantity": quantities["grade_a_qty"],
				"grade_b_item": quantities.get("grade_b_item"),
				"grade_b_quantity": quantities["grade_b_qty"],
				"grade_d_item": quantities.get("grade_d_item"),
				"grade_d_quantity": quantities["grade_d_qty"],
				"total_grade_inventory": quantities["grade_inventory_qty"],
				"shortage_after_grade": quantities["shortage_after_grade_inventory"],
				"open_purchase_orders": po_names if po_names != "None" else "",
				"open_po_pending_quantity": total_po_pending_qty,
				"final_rfq_quantity": final_rfq_qty,
			}
		)

	return calculation_details


def _set_rfq_inclusion_details(auto_rfq_doc):
	item_codes = list(
		dict.fromkeys(
			row.item_code
			for row in auto_rfq_doc.auto_rfq_calculation_details
			if row.item_code
		)
	)
	item_details = {
		item.name: item
		for item in frappe.get_all(
			"Item",
			filters={"name": ["in", item_codes]},
			fields=["name", "item_group", "end_of_life", "disabled"],
		)
	} if item_codes else {}
	item_groups = {
		item_code: item.item_group for item_code, item in item_details.items()
	}
	requested_item_groups = tuple({group for group in item_groups.values() if group})
	supplier_rows = []
	if requested_item_groups:
		supplier_rows = frappe.db.sql(
			"""
			SELECT DISTINCT
				supplier.name AS supplier,
				supplier.supplier_name,
				supplier.supplier_primary_contact AS contact,
				supplier.email_id,
				mapping.item_group
			FROM `tabSupplier Item Group` mapping
			INNER JOIN `tabSupplier` supplier ON supplier.name = mapping.parent
			WHERE mapping.parenttype = 'Supplier'
				AND mapping.parentfield = 'supplier_item_group'
				AND mapping.item_group IN %(item_groups)s
				AND supplier.disabled = 0
			ORDER BY supplier.name, mapping.item_group
			""",
			{"item_groups": requested_item_groups},
			as_dict=True,
		)

	suppliers_by_group = {}
	for supplier in supplier_rows:
		suppliers_by_group.setdefault(supplier.item_group, set()).add(supplier.supplier)

	for row in auto_rfq_doc.auto_rfq_calculation_details:
		item = item_details.get(row.item_code)
		row.item_group = item_groups.get(row.item_code)
		row.end_of_life_item_code = ""
		if flt(row.final_rfq_quantity) <= 0:
			row.rfq_inclusion_status = "Skipped"
			row.skip_reason = "Final RFQ Quantity is zero after all deductions."
		elif (
			item
			and item.end_of_life
			and str(item.end_of_life) != "0000-00-00"
			and getdate(item.end_of_life) <= getdate(nowdate())
		):
			row.rfq_inclusion_status = "Skipped"
			row.end_of_life_item_code = row.item_code
			row.skip_reason = (
				f"Item reached its end of life on {item.end_of_life}."
			)
			print(
				f"[Auto RFQ Creation] Skipping Item Code: {row.item_code} | "
				f"End of Life Date: {item.end_of_life}"
			)
		elif item and item.disabled:
			row.rfq_inclusion_status = "Skipped"
			row.skip_reason = "Item is disabled."
		elif not row.item_group:
			row.rfq_inclusion_status = "Skipped"
			row.skip_reason = "Item Group is not configured in the Item master."
		elif not suppliers_by_group.get(row.item_group):
			row.rfq_inclusion_status = "Skipped"
			row.skip_reason = (
				f"No enabled Supplier is configured for Item Group {row.item_group}."
			)
		else:
			row.rfq_inclusion_status = "Included"
			row.skip_reason = ""

	return supplier_rows


def _create_global_rfq(auto_rfq_doc, eligible_suppliers):
	included_items = [
		row
		for row in auto_rfq_doc.auto_rfq_calculation_details
		if row.rfq_inclusion_status == "Included" and flt(row.final_rfq_quantity) > 0
	]
	if not included_items:
		print(
			f"[Auto RFQ Creation] Request for Quotation was not created for "
			f"{auto_rfq_doc.name}: no eligible Items remain."
		)
		return

	eligible_item_groups = {row.item_group for row in included_items}
	suppliers = {}
	for supplier in eligible_suppliers:
		if supplier.item_group in eligible_item_groups:
			suppliers[supplier.supplier] = supplier
	if not suppliers:
		print(
			f"[Auto RFQ Creation] Request for Quotation was not created for "
			f"{auto_rfq_doc.name}: no eligible Suppliers remain."
		)
		return

	required_date = add_days(nowdate(), 3)
	rfq = frappe.new_doc("Request for Quotation")
	rfq.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	rfq.transaction_date = nowdate()
	rfq.schedule_date = required_date
	rfq.message_for_supplier = "Please supply the specified items at the best possible rates"
	rfq.rfq_dashboard_link = auto_rfq_doc.name

	for supplier in sorted(suppliers.values(), key=lambda row: row.supplier):
		rfq.append(
			"suppliers",
			{
				"supplier": supplier.supplier,
				"supplier_name": supplier.supplier_name,
				"contact": supplier.contact,
				"email_id": supplier.email_id,
			},
		)

	for calculation in included_items:
		item = frappe.db.get_value(
			"Item",
			calculation.item_code,
			["item_name", "description", "item_group", "stock_uom"],
			as_dict=True,
		)
		rfq.append(
			"items",
			{
				"item_code": calculation.item_code,
				"item_name": item.item_name,
				"description": item.description,
				"item_group": item.item_group,
				"qty": calculation.final_rfq_quantity,
				"schedule_date": required_date,
				"uom": item.stock_uom,
				"stock_uom": item.stock_uom,
				"conversion_factor": 1,
			},
		)

	rfq.run_method("set_missing_values")
	rfq.insert(ignore_permissions=True)
	print(
		f"[Auto RFQ Creation] Created draft Request for Quotation {rfq.name} "
		f"for {auto_rfq_doc.name} with {len(rfq.suppliers)} Suppliers and "
		f"{len(rfq.items)} Items."
	)
	return rfq.name
