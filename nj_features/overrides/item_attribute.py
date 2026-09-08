import frappe
from frappe.utils import getdate, nowdate, date_diff, cint


def get_item_attribute_setting(parameter):
    value = frappe.db.get_value(
        "NJ Settings",
        {
            "module": "Stock",
            "doc_type": "Item Attribute",
            "parameter": parameter,
        },
        "value",
    )

    return cint(value)


def update_item_attribute_price_info(doc, method=None):
    today = getdate(nowdate())

    for row in doc.item_attribute_values:

        # New row
        if row.is_new():
            row.updated_on = today
            row.updated_by_ = frappe.session.user
            continue

        old_row = frappe.db.get_value(
            "Item Attribute Value",
            row.name,
            [
                "laptop_value",
                "desktop_value",
            ],
            as_dict=True,
        )

        if not old_row:
            continue

        laptop_changed = (
            float(row.laptop_value or 0)
            != float(old_row.laptop_value or 0)
        )

        desktop_changed = (
            float(row.desktop_value or 0)
            != float(old_row.desktop_value or 0)
        )

        if laptop_changed or desktop_changed:
            row.updated_on = today
            row.updated_by_ = frappe.session.user


def set_item_attribute_validity(doc, method=None):
    validity_days = get_item_attribute_setting(
        "item_attribute_price_validity_days"
    )

    if not validity_days:
        return

    today = getdate(nowdate())
    is_valid = 1

    for row in doc.item_attribute_values:

        if not row.updated_on:
            is_valid = 0
            break

        days_old = date_diff(
            today,
            getdate(row.updated_on)
        )

        if days_old > validity_days:
            is_valid = 0
            break

    doc.is_valid = is_valid