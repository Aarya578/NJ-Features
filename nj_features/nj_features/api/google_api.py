import time
import pytz
import frappe
from datetime import datetime

nj_long_query_logger = frappe.logger("nj_long_query", allow_site=True, file_count=2)
nj_sheet_query_logger = frappe.logger("nj_sheet_query", allow_site=True, file_count=1)
nj_query_for_stock_balance_logger = frappe.logger("nj_query_for_stock_balance", allow_site=True, file_count=1)

@frappe.whitelist(allow_guest=False)
def RGtH4w1n1ZeITPcY2qfhCyft1sNSih():
    start_time = time.time()
    ist = pytz.timezone('Asia/Kolkata')
    start_time_ist = datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')

    raw_query = frappe.local.form_dict.get("raw_query")
    raw_query = raw_query.replace("&gt;", ">").replace("&lt;", "<")

    if raw_query:
        try:
            raw_result = frappe.db.sql(raw_query, as_dict=1)

            end_time = time.time()
            end_time_ist = datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')
            execution_time = end_time - start_time

            if execution_time > 4:
                nj_long_query_logger.info(f"\n\nExecution started at {start_time_ist} IST\nraw_query: {raw_query}\nExecution ended at {end_time_ist} IST\nExecution time: {execution_time:.4f} seconds")
            else:
                nj_sheet_query_logger.info(f"\n\nExecution started at {start_time_ist} IST\nraw_query: {raw_query}\nExecution ended at {end_time_ist} IST\nExecution time: {execution_time:.4f} seconds")

            return raw_result

        except Exception as e:
            error_message = f"Error executing raw query: {str(e)}"
            nj_query_for_stock_balance_logger.error(f"\n\nExecution started at {start_time_ist} IST\nraw_query: {raw_query}\nError: {error_message}")
            return {"error": error_message}

    doctype = frappe.local.form_dict.get("doctype")
    fields = frappe.local.form_dict.get("fields")
    filters = frappe.local.form_dict.get("filters")
    limit = frappe.local.form_dict.get("limit")
    order_by = frappe.local.form_dict.get("order_by")
    where_string = ""
    if filters:
        where_string = " WHERE {0} ".format(filters)
    
    sql = """ SELECT {0} FROM `tab{1}` {2} ORDER BY {3} LIMIT {4} """.format(fields, doctype, where_string, order_by, limit)

    try:
        result = frappe.db.sql(sql, as_dict=1)

        end_time = time.time()
        end_time_ist = datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')
        execution_time = end_time - start_time

        if execution_time > 4:
            nj_long_query_logger.info(f"\n\nSQL Execution started at {start_time_ist} IST\nsql_query: {sql}\nExecution ended at {end_time_ist} IST\nExecution time: {execution_time:.4f} seconds")
        else:
            nj_sheet_query_logger.info(f"\n\nSQL Execution started at {start_time_ist} IST\nsql_query: {sql}\nExecution ended at {end_time_ist} IST\nExecution time: {execution_time:.4f} seconds")

        return result

    except Exception as e:
        error_message = f"Error executing standard SQL query: {str(e)}"
        nj_query_for_stock_balance_logger.error(f"\n\nExecution started at {start_time_ist} IST\nsql_query: {sql}\nError: {error_message}")
        return {"error": error_message}
