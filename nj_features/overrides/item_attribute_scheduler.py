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


def check_item_attribute_price_validity():
    reminder_days = get_item_attribute_setting(
        "item_attribute_price_reminder_days"
    )

    validity_days = get_item_attribute_setting(
        "item_attribute_price_validity_days"
    )

    # Validate NJ Settings
    if not reminder_days or not validity_days:
        frappe.log_error(
            "Item Attribute reminder/validity settings are missing",
            "Item Attribute Price Validation"
        )
        return

    if reminder_days >= validity_days:
        frappe.log_error(
            "Reminder days must be less than validity days",
            "Item Attribute Price Validation"
        )
        return

    today = getdate(nowdate())

    # Blank updated_on rows are intentionally ignored
    rows = frappe.get_all(
        "Item Attribute Value",
        filters={
            "updated_on": ["is", "set"]
        },
        fields=[
            "parent",
            "updated_on",
        ],
    )

    reminder_item_attributes = set()
    invalid_item_attributes = set()

    for row in rows:
        days_old = date_diff(
            today,
            getdate(row.updated_on)
        )

        # More than reminder days -> send reminder
        if days_old > reminder_days:
            reminder_item_attributes.add(row.parent)

        # More than validity days -> untick Is Valid
        if days_old > validity_days:
            invalid_item_attributes.add(row.parent)

    # -----------------------------------------
    # 14-day validity check
    # -----------------------------------------
    for item_attribute in invalid_item_attributes:
        frappe.db.set_value(
            "Item Attribute",
            item_attribute,
            "is_valid",
            0,
            update_modified=False,
        )

    # -----------------------------------------
    # 7-day reminder through Notification
    # -----------------------------------------
    if reminder_item_attributes:
        notification = frappe.get_doc(
            "Notification",
            "Item Attribute Price Update Reminder"
        )

        for item_attribute in reminder_item_attributes:
            doc = frappe.get_doc(
                "Item Attribute",
                item_attribute
            )

            notification.send(doc)