import frappe
from frappe.model.document import Document


class NJRepack(Document):

    pass


def validate(doc, method):

    for row in doc.repack_attributes:

        if not row.current_item_code:
            continue

        # Check generated code exists
        if not row.repack_item_code:
            frappe.throw(
                "Please click Check and generate Repack Item Code"
            )

        # Check Item Master
        if not frappe.db.exists("Item", row.repack_item_code):
            frappe.throw(
                f"Repack Item Code {row.repack_item_code} does not exist in Item Master"
            )

        if not row.remark:
            frappe.throw(
                "Please enter Remark for repack change"
            )