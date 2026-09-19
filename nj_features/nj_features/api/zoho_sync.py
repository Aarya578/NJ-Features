"""
ERP -> Zoho customer/item mirror for the Zoho-ERPNext Quote Bridge.

Runs on a schedule (see hooks.py). Pulls ERPNext Customers/Items changed
since the last run and upserts them into Zoho CRM's Accounts/Products
modules, matched on the ERP_Customer_ID / ERP_Item_Code custom fields.

Only Account_Name/Product_Name plus the ERP id field are mirrored right
now -- Zoho only has those custom fields today. Extend BOTH the field
list here and the corresponding Custom Field in Zoho if more of the
spec's mirror fields (Customer Group, Territory, GSTIN, ...) get added
on the Zoho side later.
"""

import frappe
from frappe.utils import now_datetime, get_datetime

from nj_features.nj_features.api.zoho_api import zoho_post

BATCH_SIZE = 100
FAR_PAST = "2000-01-01 00:00:00"

# Reps only quote whole units from Zoho, not spare parts -- narrowed from
# the full ~172k active-item catalog (which is genuinely that large: this
# is a refurb electronics business, and every grade/spec combination gets
# its own Item, e.g. "S-Laptop RAM-DDR4-8 GB-2666 GHZ-GRADE A").
ITEM_GROUPS_TO_MIRROR = ["Laptops", "Desktops", "Laptops(Bundle)", "Desktops(Bundle)"]


def _get_last_sync():
    settings = frappe.get_single("Zoho Settings")
    return settings.last_sync or FAR_PAST


def _set_last_sync(ts):
    frappe.db.set_single_value("Zoho Settings", "last_sync", ts)
    frappe.db.commit()


def _chunks(rows, size):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _upsert(module, records, duplicate_check_field, sync_label):
    if not records:
        return
    created = updated = failed = 0
    for batch in _chunks(records, BATCH_SIZE):
        result = zoho_post(
            f"{module}/upsert",
            {"data": batch, "duplicate_check_fields": [duplicate_check_field]},
        )
        for row in result.get("data", []):
            action = row.get("action")
            if action == "insert":
                created += 1
            elif action == "update":
                updated += 1
            else:
                failed += 1
                frappe.log_error(str(row), f"Zoho {sync_label} upsert row failed")
    frappe.logger("zoho_sync").info(
        f"{sync_label}: {created} created, {updated} updated, {failed} failed"
    )


def sync_customers_to_zoho():
    settings = frappe.get_single("Zoho Settings")
    if not settings.enabled:
        return

    since = _get_last_sync()
    run_started_at = now_datetime()

    customers = frappe.get_all(
        "Customer",
        filters=[["modified", ">", since]],
        fields=["name", "customer_name", "disabled"],
        order_by="modified asc",
    )

    records = [
        {
            "Account_Name": c.customer_name,
            "ERP_Customer_ID": c.name,
        }
        for c in customers
    ]
    _upsert("Accounts", records, "ERP_Customer_ID", "Customer mirror")

    candidate_items = frappe.get_all(
        "Item",
        filters=[
            ["modified", ">", since],
            ["is_sales_item", "=", 1],
            ["disabled", "=", 0],
            ["item_group", "in", ITEM_GROUPS_TO_MIRROR],
        ],
        fields=["name", "item_name", "disabled"],
        order_by="modified asc",
    )

    # Only mirror items a rep could actually quote right now: real stock and
    # a real Standard Selling price. Most of this catalog has neither (only
    # ~7% of the 4 item groups had a Standard Selling price when this was
    # added), so without this filter reps would see thousands of products
    # that produce a Rs 0 quote -- confirmed by testing, not a guess.
    if not candidate_items:
        items = []
    else:
        candidate_codes = [i.name for i in candidate_items]
        priced_codes = set(
            frappe.get_all(
                "Item Price",
                filters={"price_list": "Standard Selling", "selling": 1, "item_code": ["in", candidate_codes]},
                pluck="item_code",
            )
        )
        stocked_codes = {
            row.item_code
            for row in frappe.db.sql(
                """
                SELECT item_code, SUM(actual_qty) AS qty
                FROM `tabBin`
                WHERE item_code IN %(codes)s
                GROUP BY item_code
                HAVING qty > 0
                """,
                {"codes": candidate_codes},
                as_dict=True,
            )
        }
        items = [i for i in candidate_items if i.name in priced_codes and i.name in stocked_codes]

    records = [
        {
            "Product_Name": i.item_name,
            "ERP_Item_Code": i.name,
        }
        for i in items
    ]
    _upsert("Products", records, "ERP_Item_Code", "Item mirror")

    _set_last_sync(run_started_at)
