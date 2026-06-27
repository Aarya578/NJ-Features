import frappe


def uncheck_item_attribute_is_valid():
    """
    Scheduler function:
    Unchecks Is Valid field in Item Attribute every 30 days.
    """

    if not frappe.get_meta("Item Attribute").has_field("is_valid"):
        frappe.log_error(
            title="Item Attribute Scheduler Error",
            message="Field 'is_valid' not found in Item Attribute"
        )
        return

    frappe.db.sql("""
        UPDATE `tabItem Attribute`
        SET is_valid = 0
        WHERE IFNULL(is_valid, 0) = 1
    """)

    frappe.db.commit()