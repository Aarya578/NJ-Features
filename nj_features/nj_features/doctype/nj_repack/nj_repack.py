import frappe
from frappe.model.document import Document
from nj_features.nj_features.doctype.njqca.njqca import NJQCA


class NJRepack(Document):
    pass


def validate(doc, method=None):

    # Parent Serial No validation
    if not doc.serial_no:
        frappe.throw("Serial No is mandatory")

    for row in doc.repack_attributes:

        if not row.current_item_code:
            continue

        # Repack Item Code generated check
        if not row.repack_item_code:
            frappe.throw(
                "Please click Check and generate Repack Item Code"
            )

        # Item Master existence check
        if not frappe.db.exists("Item", row.repack_item_code):
            frappe.throw(
                f"Repack Item Code {row.repack_item_code} does not exist in Item Master"
            )

        # Remark validation
        if not row.remark:
            frappe.throw(
                "Please enter Remark for repack change"
            )


def before_submit(doc, method=None):

    if not doc.serial_no:
        frappe.throw(
            "Serial No is mandatory before submit"
        )

    if not doc.current_item_code:
        frappe.throw(
            "Current Item Code is mandatory before submit"
        )

    if not doc.repack_item_code:
        frappe.throw(
            "Repack Item Code is mandatory before submit"
        )

    if not frappe.db.exists("Item", doc.repack_item_code):
        frappe.throw(
            f"Repack Item Code {doc.repack_item_code} does not exist in Item Master"
        )

    for row in doc.repack_attributes:

        if not row.repack_item_code:
            frappe.throw(
                "Repack Item Code is mandatory before submit"
            )

        if not frappe.db.exists("Item", row.repack_item_code):
            frappe.throw(
                f"Repack Item Code {row.repack_item_code} does not exist in Item Master"
            )


def on_submit(doc, method=None):

    # Map NJ Repack fields to the field names expected by NJQCA
    doc.item_code = doc.current_item_code
    doc.manual_repack_item_code = doc.repack_item_code

    # NJQCA takes warehouse and base price from Serial No
    serial_data = frappe.db.get_value(
        "Serial No",
        doc.serial_no,
        ["warehouse", "purchase_rate"],
        as_dict=True
    )

    if not serial_data:
        frappe.throw(
            f"Serial No {doc.serial_no} not found"
        )

    if not serial_data.warehouse:
        frappe.throw(
            f"Warehouse not found for Serial No {doc.serial_no}"
        )

    doc.warehouse = serial_data.warehouse
    doc.base_price = serial_data.purchase_rate or 0

    # Reuse existing NJQCA Stock Entry logic
    NJQCA.make_stock_entry_using_nj_lib(doc)
    # Sync Serial No Part List with new repack item
    update_serial_no_part_list(doc)

def update_serial_no_part_list(doc):

    serial_no_doc = frappe.get_doc(
        "Serial No",
        doc.serial_no,
        for_update=True
    )

    # Get Grade from the NEW repack item
    new_grade = frappe.db.get_value(
        "Item Variant Attribute",
        {
            "parent": doc.repack_item_code,
            "attribute": "Grade"
        },
        "attribute_value"
    )

    updated = False

    for row in serial_no_doc.get("serial_no_component") or []:

        # Match the Part List row belonging to this serialized component
        if row.component_serial_no == doc.serial_no:
            row.item = doc.repack_item_code

            if new_grade:
                row.grade = new_grade

            row.reference_doctype = doc.doctype
            row.reference_doctype_no = doc.name

            updated = True
            break

    if updated:
        serial_no_doc.save(ignore_permissions=True)

@frappe.whitelist()
def get_repack_variant_options(item_template):

    template = frappe.get_doc("Item", item_template)

    from nj_features.nj_features.doctype.njqca.njqca import (
        get_variant_attribute_options,
    )

    result = {}

    for row in template.attributes:
        result[row.attribute] = get_variant_attribute_options(
            item_template=item_template,
            attribute=row.attribute
        ) or []

    return result