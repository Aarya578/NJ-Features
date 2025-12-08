import frappe
from frappe import _
from erpnext.controllers.status_updater import OverAllowanceError


# 🔥 STEP 1 — Your custom override function
def custome_limits_crossed_error(self, args, item, qty_or_amount):
    print("\n\n=== CUSTOM limits_crossed_error CALLED ===\n")

    # Custom logic
    if qty_or_amount == "qty":
        action_msg = _(
            'To allow over receipt / delivery, update "Over Receipt/Delivery Allowance" in Stock Settings or the Item.'
        )
    else:
        action_msg = _(
            'To allow over billing, update "Over Billing Allowance" in Accounts Settings or the Item.'
        )

    frappe.throw(
        _(
            "Custom ERROR: This document is over limit by {0} {1} for item {4}. "
            "Are you making another {3} against the same {2}?"
        ).format(
            frappe.bold(_(item["target_ref_field"].title())),
            frappe.bold(item["reduce_by"]),
            frappe.bold(_(args.get("target_dt"))),
            frappe.bold(_(self.doctype)),
            frappe.bold(item.get("item_code")),
        )
        + "<br><br>"
        + action_msg,
        OverAllowanceError,
        title=_("Limit Crossed"),
    )


# 🔥 STEP 2 — Monkey patch function
def apply_patch():
    import erpnext.controllers.status_updater as status_updater

    # Override the class method directly
    status_updater.StatusUpdater.limits_crossed_error = custome_limits_crossed_error

    print("\n=== Monkey Patch Applied: limits_crossed_error overridden ===\n")
