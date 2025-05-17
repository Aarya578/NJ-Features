# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from datetime import datetime, timedelta
from frappe.model.document import Document
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib

class AutoStockEntry(Document):
	pass

@frappe.whitelist()
def submit_ste(t_warehouse, serial_no):
	try:
		sn_data = frappe.db.get_value('Serial No', {'name': serial_no}, ['item_code', 'warehouse', 'status'], as_dict=1)
		if sn_data is None:
			frappe.throw(f"Serial No <b>{serial_no}</b> not found.")
		else:
			if sn_data.get('status') != 'Active':
				frappe.throw(f"Serial No <b>{serial_no}</b> is not Active.")
		
		check_validation_for_auto_stock_entry(t_warehouse, serial_no)

		material_transfer_items = []

		stock_entry_data = {
			"doctype": "Auto Stock Entry",
			"stock_entry_type": "Material Transfer",
			"material_transfer_items": material_transfer_items,
		}

		material_transfer_items.append({
			'qty': 1,
			'item_code': sn_data.get('item_code'),
			's_warehouse': sn_data.get('warehouse'),
			't_warehouse': t_warehouse,
			'serial_no': serial_no,
		})

		if material_transfer_items:
			return stock_entry_using_nj_lib(stock_entry_data)
		else:
			frappe.throw("None available in <b>Items</b> table.")

	except Exception as e:
		frappe.db.rollback()
		frappe.throw(f"Error while submitting Stock Entry: {e}")

@frappe.whitelist()
def get_work_warehouse():
	ase_data = frappe.db.get_value('Warehouse', {'ase_user': frappe.session.user, 'disabled': 0}, ['name'], as_dict=1)

	if ase_data is None:
		frappe.throw("No warehouse found for ASE user: {0}".format(frappe.session.user))
	if not ase_data.get('name'):
		frappe.throw(f"Warehouse is missing for <b>User: {frappe.session.user}</b>. Fill ASE User")

	return {"work_warehouse": ase_data.get('name')}

def check_validation_for_auto_stock_entry(t_warehouse, serial_no):
    try:
        serial_doc = frappe.get_doc('Serial No', serial_no)
        s_department = frappe.db.get_value('Warehouse', {'name': serial_doc.get('warehouse')}, 'department')
        s_warehouse = serial_doc.get('warehouse')
        department = frappe.db.get_value('Warehouse', {'name': t_warehouse}, 'department')
        department_doc = frappe.get_doc('Department', department)

        if department_doc.get('stock_movement_restriction_table'):
            validate_grade_restriction(serial_doc, department_doc)

        print("department_doc --------------------- ", department_doc)
        if department_doc.get('quality_inspection_status_for_stock_movement') and (department_doc.get('inspection_types') != [] or department_doc.get('inspection_types') is not None):
            check_qi_validation(serial_no, s_warehouse, s_department, department)

        frappe.throw("Validation successful.")

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Error in check_validation_for_auto_stock_entry")
        frappe.throw("An error occurred during validation. Please check logs.")


def validate_grade_restriction(serial_doc, department_doc):
    try:
        is_component = frappe.db.get_value('Item Group', serial_doc.get('item_group'), 'is_component')

        if not is_component:
            validate_non_component_grade(serial_doc, department_doc)
        else:
            validate_component_grade(serial_doc, department_doc)

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Error in validate_grade_restriction")
        frappe.throw("An error occurred while validating grade restriction.")


def validate_non_component_grade(serial_doc, department_doc):
    try:
        result = frappe.db.get_value('Serial No', {'name': serial_doc.get('name')}, ['grade', 'item_group'])

        if result is None:
            frappe.throw(f"Item <b>{serial_doc.get('item_code')}</b> not found. Cannot validate grade restrictions for serial <b>{serial_doc.name}</b>.")
            return

        lap_grade, lap_item_group = result

        for restriction in department_doc.get('stock_movement_restriction_table', []):
            restricted_grades = restriction.get('restricted_grade', "").split(", ")
            restricted_item_group = restriction.get('item_group')

            if lap_item_group == restricted_item_group and lap_grade in restricted_grades:
                frappe.throw(
                    f"Serial No <b>{serial_doc.name}</b> for item <b>{serial_doc.get('item_code')}</b> "
                    f"with item_group <b>{lap_item_group}</b> has a grade <b>{lap_grade}</b> that is not allowed "
                    f"for department <b>{department_doc.name}</b>."
                )

        for component in serial_doc.get('serial_no_component', []):
            for restriction in department_doc.get('stock_movement_restriction_table', []):
                restricted_grades = restriction.get('restricted_grade', "").split(", ")
                restricted_item_group = restriction.get('item_group')

                if (
                    component.get('item_group') == restricted_item_group and
                    component.get('grade') in restricted_grades and
                    component.get('quantity') == 1
                ):
                    frappe.throw(
                        f"Serial No <b>{serial_doc.name}</b> "
                        f"with item_group <b>{component.get('item_group')}</b> has a grade <b>{component.get('grade')}</b> that is not allowed "
                        f"for department <b>{department_doc.name}</b>."
                    )

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Error in validate_non_component_grade")
        frappe.throw("An error occurred while validating non-component grade restrictions.")


def validate_component_grade(serial_doc, department_doc):
    try:
        for restriction in department_doc.get('stock_movement_restriction_table', []):
            restricted_grades = [grade.upper() for grade in restriction.get('restricted_grade', "").split(", ")]

            if (
                serial_doc.get('item_group') == restriction.get('item_group') and
                get_item_code_and_warehouse(serial_doc.get('item_code')).upper() in restricted_grades
            ):
                frappe.throw(
                    f"Serial No <b>{serial_doc.name}</b> for item_group <b>{serial_doc.get('item_group')}</b> "
                    f"has a grade <b>{serial_doc.get('grade')}</b> that is not allowed for department <b>{department_doc.name}</b>."
                )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Error in validate_component_grade")
        frappe.throw("An error occurred while validating component grade restrictions.")

def get_item_code_and_warehouse(item_code):
    try:
        grade = frappe.db.get_value("Item Variant Attribute", {"parent": item_code, "attribute": "Grade"}, "attribute_value")
        if not grade:
            return

        return grade
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in get_item_code_and_warehouse")
        return

def check_qi_validation(serial_no, s_warehouse, s_department, t_department):
    try:
        print(
            "serial_no", serial_no,
            "s_warehouse", s_warehouse,
            "s_department", s_department,
            "t_department", t_department
        )

        s_department = frappe.db.get_value('Warehouse', {'name': s_warehouse}, 'department')
        s_inspection_type = frappe.get_doc('Department', s_department)
        inspection_types = [row.get('inspection_type') for row in s_inspection_type.get("inspection_types")]

        query = """
            SELECT se.creation, se.name
            FROM `tabStock Entry Detail` sed
            JOIN `tabStock Entry` se ON sed.parent = se.name
            WHERE se.stock_entry_type = "Material Transfer"
            AND sed.serial_no = %s
            AND se.docstatus = 1
            AND sed.target_department = %s
            ORDER BY se.creation DESC
            LIMIT 1
        """
        result = frappe.db.sql(query, (serial_no, s_department), explain=1, debug=1, as_dict=True)

        if result and inspection_types:
            creation_time = result[0]["creation"]
            formatted_time = creation_time.strftime("%Y-%m-%d %H:%M:%S")
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            print("formatted_time", formatted_time)
            print("current_time", current_time)

            qi_query = """
                SELECT name
                FROM `tabNJ Quality Inspection`
                WHERE inspection_type IN %s AND docstatus = 1
                AND modified BETWEEN %s AND %s
                AND barcode = %s
                ORDER BY creation DESC
                LIMIT 1
            """
            qi_result = frappe.db.sql(qi_query, (tuple(inspection_types), formatted_time, current_time, serial_no), explain=1, debug=1, as_dict=True)

            t_inspection_type = frappe.get_doc('Department', t_department)

            if qi_result:
                qi_doc = frappe.get_doc('NJ Quality Inspection', qi_result[0]["name"])

                if qi_doc:
                    allowed_statuses = t_inspection_type.get("quality_inspection_status_for_stock_movement").split(",")

                    if t_inspection_type.get("quality_inspection_status_for_stock_movement") and qi_doc.get("status") not in allowed_statuses:
                        expected_status = ", ".join(allowed_statuses)
                        actual_status = qi_doc.get("status")

                        frappe.throw(
                            f"NJ Quality Inspection <b>{qi_doc.name}</b> for serial no <b>{serial_no}</b> in department <b>{s_department}</b> "
                            f"has status <b>{actual_status}</b>, but target department <b>{t_department}</b> only allows quality inspection status: <b>{expected_status}</b>."
                        )
            else:
                frappe.throw(
                    f"NJ Quality Inspection not found for serial no <b>{serial_no}</b> in department <b>{s_department}</b>."
                )

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Error in check_qi_validation")
        frappe.throw("An error occurred during Quality Inspection validation. Please check logs.")
