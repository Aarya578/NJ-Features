import json
import frappe

from frappe.desk.reportview import get_sidebar_stats as original_get_sidebar_stats


DISABLE_USER_TAGS_FOR = {
    "Stock Movement",
}


@frappe.whitelist()
@frappe.read_only()
def get_sidebar_stats(stats, doctype, filters=None):
    """
    Disable _user_tags sidebar count only for Stock Movement.

    This stops queries like:
        select `_user_tags`, count(*)
        from `tabStock Movement`
        ...
    """

    # For all other doctypes, keep Frappe default behavior
    if doctype not in DISABLE_USER_TAGS_FOR:
        return original_get_sidebar_stats(stats, doctype, filters)

    try:
        stats_list = json.loads(stats) if isinstance(stats, str) else stats
    except Exception:
        stats_list = []

    if not isinstance(stats_list, list):
        return original_get_sidebar_stats(stats, doctype, filters)

    # Remove only _user_tags
    stats_list = [s for s in stats_list if s != "_user_tags"]

    # If frontend requested only _user_tags, return empty stats
    if not stats_list:
        return {"stats": {}}

    # Continue normal sidebar stats for other fields
    return original_get_sidebar_stats(json.dumps(stats_list), doctype, filters)
