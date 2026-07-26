import frappe


no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.title = "RFQ QC Dashboard"
    context.show_sidebar = False

    if frappe.session.user != "Guest":
        context.no_cache = 1

    return context
