import frappe
from frappe.model.document import Document


class NJRepack(Document):
    pass


def validate(doc, method):

    # Parent Serial No validation
    if not doc.serial_no:
        frappe.throw(
            "Serial No is mandatory"
        )

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