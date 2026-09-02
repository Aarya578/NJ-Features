import json
import frappe

from frappe.desk.reportview import get_sidebar_stats as original_get_sidebar_stats


@frappe.whitelist()
@frappe.read_only()
def get_sidebar_stats(stats, doctype, filters=None):
    """
    Globally disable _user_tags sidebar stats calculation across all DocTypes.

    Frappe frontend automatically requests stats=['_user_tags'] for every list view.
    On large tables (tabVersion, tabStock Entry, tabStock Ledger Entry, tabSerial No,
    tabNJQCA, tabSales Order, etc.), calculating _user_tags causes unindexed full-table
    scans and generates hundreds of gigabytes of temporary Aria disk files (/tmp/#sql_*.MAD),
    filling the disk to 100% and locking up MariaDB.
    """
    try:
        stats_list = json.loads(stats) if isinstance(stats, str) else stats
    except Exception:
        stats_list = []

    if not isinstance(stats_list, list):
        return original_get_sidebar_stats(stats, doctype, filters)

    # Strip _user_tags from requested stats
    stats_list = [s for s in stats_list if s != "_user_tags"]

    # If frontend requested only _user_tags (standard Frappe list view behavior), return empty stats immediately
    if not stats_list:
        return {"stats": {}}

    # Continue normal sidebar stats for any other valid fields
    return original_get_sidebar_stats(json.dumps(stats_list), doctype, filters)

