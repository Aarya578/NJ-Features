"""
Shared helpers for the Zoho-ERPNext Quote Bridge, used by both the
Deals-based flow (zoho_quotation_sync.py) and the Quotes-based flow
(zoho_quote_sync.py).
"""

import frappe
from frappe.utils import now_datetime

NEW_CUSTOMER_GROUP = "All Customer Groups"
NEW_CUSTOMER_TERRITORY = "All Territories"


def zoho_now():
    return now_datetime().astimezone().isoformat(timespec="seconds")


def skip(record_id, reason, context="Zoho quotation sync"):
    """A validation problem -- leave the trigger checkbox on and log
    server-side.

    There's no error-visible-to-the-rep field in Zoho yet (would need an
    "ERP Sync Error" Custom Field), so this is only visible in ERPNext's
    Error Log for now. Leaving the flag checked means it keeps retrying
    every poll until someone fixes the underlying data and notices it
    stopped erroring -- better than silently dropping it, per the spec's
    own "silent no-op is the worst outcome" rule, but still not great.
    Worth adding that field later.
    """
    frappe.log_error(reason, f"{context} skipped {record_id}")


def resolve_customer(account_id, record_id, zoho_get, zoho_put, skip_context="Zoho quotation sync"):
    """Return an ERPNext Customer name for a Zoho Account, creating one on
    the fly if the Account was made directly in Zoho and never mirrored
    from ERP (no ERP_Customer_ID yet, or one that no longer resolves).
    The new Customer's name is written back onto the Zoho Account so this
    only happens once per Account.
    """
    account_detail = zoho_get(f"Accounts/{account_id}", params={"fields": "Account_Name,ERP_Customer_ID"})
    account_data = (account_detail.get("data") or [{}])[0]

    erp_customer_id = account_data.get("ERP_Customer_ID")
    if erp_customer_id and frappe.db.exists("Customer", erp_customer_id):
        return erp_customer_id

    account_name = account_data.get("Account_Name")
    if not account_name:
        skip(record_id, f"Account {account_id} has no Account_Name to create a Customer from.", skip_context)
        return None

    customer = frappe.new_doc("Customer")
    customer.customer_name = account_name
    customer.customer_type = "Company"
    customer.customer_group = NEW_CUSTOMER_GROUP
    customer.territory = NEW_CUSTOMER_TERRITORY
    customer.insert(ignore_permissions=True)
    frappe.db.commit()

    zoho_put(f"Accounts/{account_id}", {"data": [{"id": account_id, "ERP_Customer_ID": customer.name}]})

    return customer.name
