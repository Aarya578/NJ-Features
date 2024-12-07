# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe,json
from frappe.model.document import Document
from nj_lib.utils.common_utils import get_active_emp,get_active_item_code
from erpnext.controllers.item_variant import get_variant
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib





class RepackForNonSerialised(Document):
    def on_submit(self):
        accounting_cost_account = frappe.db.get_single_value('NewJaisa Configuration', 'default_operational_cost_account')
        stock_data = {
            "name": self.name,
            "doctype": self.doctype,
            "series": "NJ-STE-NS-REP-",
            "stock_entry_type": "Repack",
            "repack_items": get_repack_items(self),
            "expense_account": accounting_cost_account
        }
        stock_data_str = json.dumps(stock_data)
        stock_entry_using_nj_lib(stock_data_str)

def get_repack_items(self):
    get_repack_items_list = []

    get_repack_items_dict = {
		"repack_item_code": self.item_code,
        "repack_item_source_warehouse": self.warehouse,
        "qty": self.quantity
	}
    get_repack_items_list.append(get_repack_items_dict)

    get_unpack_items_dict = {
        "unpack_item_code": self.repack_item_code,
        "unpack_item_target_warehouse": self.warehouse,
        "qty": self.quantity
    }
    get_repack_items_list.append(get_unpack_items_dict)

    return get_repack_items_list

@frappe.whitelist()
def get_item_code_and_warehouse(item_code):
    emp_data = get_active_emp(frappe.session.user)
    if item_code:
        variant_value = frappe.db.get_value("Item", {"name": item_code}, "has_serial_no")
        if variant_value == 1:
            frappe.throw("Serialised Item is not allowed to be Repacked!")

    grade = frappe.db.get_value("Item Variant Attribute", {"parent": item_code, "attribute": "Grade"}, "attribute_value")
    if not grade:
        frappe.throw("No 'Grade' found for the given Item Code: <b>" + item_code + "</b>")
    return {
        "grade": grade,
        "warehouse": emp_data.get("work_warehouse")
    }

@frappe.whitelist()
def get_repack_item_code_with_new_grade(item_code,new_grade):
    if not item_code:
        frappe.throw("Item Code is not given.")

    get_grade_and_grade_a_data = frappe.db.sql("""
        SELECT parent, attribute_value
        FROM `tabItem Attribute Value`
        WHERE parent = 'grade' and attribute_value = %s
    """, (new_grade),as_dict=True)

    if not get_grade_and_grade_a_data:
        frappe.throw("No {new_grade} attribute found in Item Attribute Table!<br>Please contact <b>NPD Team</b>.")

    grade_attribute = get_grade_and_grade_a_data[0].get('parent')
    grade_a_attribute = get_grade_and_grade_a_data[0].get('attribute_value')

    item_data = get_active_item_code(item_code, fields=['variant_of'])
    item_template = item_data.get('variant_of')

    attribute_data = frappe.db.sql("""
        SELECT attribute, attribute_value
        FROM `tabItem Variant Attribute`
        WHERE parent = %s
    """, (item_code), as_dict=True)

    if not attribute_data:
        frappe.throw("No attributes found for the given Item Code: <b>" + item_code + "</b>!<br>Please contact <b>NPD Team</b>.")

    attribute_dict = {item['attribute']: item['attribute_value'] for item in attribute_data}

    if grade_attribute in attribute_dict:
        attribute_dict[grade_attribute] = grade_a_attribute
        final_item_code = get_variant(item_template, attribute_dict)
        
        if final_item_code:
            return final_item_code
        else:
            frappe.throw("No <b>'Grade'</b> attributes found for the given Item Code: <b>" + item_code + "</b>!<br>Please contact <b>NPD Team</b>.")
    
    return None


@frappe.whitelist()
def get_new_grade(doctype, txt, searchfield, start, page_len, filters):
    txt = ''

    grade = filters.get('grade')

    get_grade = """
                    SELECT name from `tabGrade` where name <> %s
                """

    parent = frappe.db.sql(get_grade, (grade), as_dict=1)

    filtered_data = [item['name'] for item in parent]

    filters_data = [
        ["name", "in", filtered_data],
    ]

    return frappe.get_all(
        "Grade",
        filters=filters_data,
        fields=["name"],
        as_list=1,
        or_filters=[
            ["name", "like", f"%{txt}%"]
        ]
    )