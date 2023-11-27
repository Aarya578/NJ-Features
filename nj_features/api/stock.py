import frappe

@frappe.whitelist()
def jrp53p85u2rp9qc5(item_group=None, warehouse=None):
    if item_group is None and warehouse is None:
        frappe.throw("Please select 'item_group' or 'warehouse.")

    from erpnext.stock.report.stock_balance.stock_balance import execute
    from datetime import timedelta, datetime
    today = datetime.strptime(datetime.today().strftime('%Y-%m-%d'), '%Y-%m-%d')
    last_month = today - timedelta(30)

    if warehouse and item_group is None:
        frappe.throw("Please select 'item_group")
    if not frappe.local.form_dict.get("filters"):
        filters = {
            "from_date": str(last_month)[:10],
            "to_date": str(today)[:10],
            "item_group": str(item_group),
            "warehouse": str(warehouse)
        }
    else:
        filters = frappe.local.form_dict.get("filters")

    result = execute(filters)
    return result

@frappe.whitelist(allow_guest=True)
def test_stock_bal_1(item_group=None, warehouse=None, limit_start=None, limit_page_length=None):
    if item_group is None and warehouse is None:
        frappe.throw("Please select either 'item_group' or 'warehouse'.")

    from erpnext.stock.report.stock_balance.stock_balance import execute
    from datetime import timedelta, datetime

    today = datetime.strptime(datetime.today().strftime('%Y-%m-%d'), '%Y-%m-%d')
    last_month = today - timedelta(15)

    if item_group and warehouse is None:
        filters = {
            "from_date": str(last_month)[:10],
            "to_date": str(today)[:10],
            "item_group": str(item_group),
            "limit_start": limit_start if limit_start is not None else 0,
            "limit_page_length": limit_page_length if limit_page_length is not None else 500,
        }
    elif item_group and warehouse:
        filters = {
            "from_date": str(last_month)[:10],
            "to_date": str(today)[:10],
            "item_group": str(item_group),
            "warehouse": str(warehouse),
            "limit_start": limit_start if limit_start is not None else 0,
            "limit_page_length": limit_page_length if limit_page_length is not None else 500,
        }
    else:
        frappe.throw("Please select either 'item_group' or 'warehouse'.")

    result = execute(filters)
    return result
