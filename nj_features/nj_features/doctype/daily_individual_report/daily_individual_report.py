import json
import frappe
from frappe.utils import nowdate, add_days
from frappe.model.document import Document

class DailyIndividualReport(Document):
    pass

@frappe.whitelist()
def fetch_data_imports():
    user = frappe.session.user
    yesterday = add_days(nowdate(), -1)
    today = nowdate()

    data_imports = frappe.get_all('Data Import',
        filters={
            'creation': ['between', [yesterday + " 00:00:00", today + " 23:59:59"]],
            'owner': user
        }, fields=['name', 'status']
    )

    sort_order = { 'error': 1, 'pending': 2, 'partial success': 3, 'success': 4 }

    data_imports.sort(key=lambda x: sort_order.get(x['status'].lower(), 4))
    return data_imports

@frappe.whitelist()
def get_serial_no_data():
    user = frappe.session.user

    get_work_warehouse_query = """
        SELECT DISTINCT name AS warehouse, warehouse_owner
        FROM `tabWarehouse` 
        WHERE warehouse_owner = %s AND disabled = 0 AND is_group = 0 
        AND warehouse_type IN ('Employee Personal Warehouse','Operation Warehouse')
    """

    work_warehouse = frappe.db.sql(get_work_warehouse_query, (user,), as_dict=True)
    
    word_warehouse = [row.get("warehouse") for row in work_warehouse]

    if not word_warehouse:
        frappe.msgprint("No warehouse found for user: {0}".format(frappe.session.user))
        return []

    placeholders = ', '.join(['%s'] * len(word_warehouse))
    query = f"""SELECT item_code, serial_no, warehouse
                FROM `tabSerial No` 
                WHERE warehouse is not null AND warehouse IN ({placeholders})"""

    serial_no_data = frappe.db.sql(query, tuple(word_warehouse), as_dict=True)

    return serial_no_data

@frappe.whitelist()
def mail_button_data_for_not_scan_serial_no_report(data):
    data = json.loads(data)
    if data[1]:
        table_html = "<table border='1' cellpadding='5' cellspacing='0'>"
        table_html += "<tr><th>Serial No</th><th>Warehouse</th><th>Audit Warehouse</th><th>Item Group</th><th>Item Code</th></tr>"
        for val in data[1]:
            table_html += f"<tr><td>{val['name']}</td><td>{val['warehouse']}</td><td>{val['audit_warehouse']}</td><td>{val['item_group']}</td><td>{val['item_code']}</td></tr>"
        table_html += "</table>"
        recipient_email = frappe.db.get_value("NJ Settings", {"parameter": "main_mail_for_inventory_update_daily"}, "value")
        nj_settings_cc_mails = frappe.db.get_value("NJ Settings", {"parameter": "cc_mails_for_inventory_report_daily"}, "value")
        cc_emails = nj_settings_cc_mails.split(",")
        subject = "Not Scanned Serial No. Report"
        message = f"<p>The following serial numbers are not scanned:</p>{table_html}"
        send_email_to_user(recipient_email, subject, message, cc_emails=cc_emails)

@frappe.whitelist()
def daily_report_to_send_personal_mail():
    all_warehouse_data = frappe.db.sql("""
        SELECT w.name, w.warehouse_owner 
        FROM `tabWarehouse` w JOIN `tabUser` u ON w.warehouse_owner = u.email 
        WHERE w.parent_warehouse LIKE '%work-warehouse%' 
        AND w.disabled = 0 AND u.enabled = 1;
    """, as_dict=1)
    
    submitted_warehouse_data = frappe.db.sql("""
        SELECT DISTINCT warehouse 
        FROM `tabDaily Individual Report` 
        WHERE docstatus = 1 AND DATE(creation) = CURRENT_DATE
    """, as_dict=1)
    
    submitted_warehouse_names = [d['warehouse'] for d in submitted_warehouse_data]
    
    missing_warehouse_emails = [mail['warehouse_owner'] for mail in all_warehouse_data if mail['name'] not in submitted_warehouse_names]
    
    https_link = "https://erp.newjaisa.com/app/serial-no/view/list"
    
    for email in missing_warehouse_emails:
        message = f"""
        <p>Please check that you have not submitted your Inventory report in Serial NO.</p>
        <p>For more details, visit the following link: <a href="{https_link}">Click here</a></p>
        <p>After visiting the page, please click on the "Update Inventory" button and submit your inventory.</p>
        <p>Thank you.</p>
        """
        send_email_to_user( email, 'Inventory Not Updated', message )

@frappe.whitelist()
def daily_report_not_submitted_warehouses_data():
    all_warehouse_data = frappe.db.sql("""select name, curdate(),warehouse_owner from `tabWarehouse` where parent_warehouse like '%work-warehouse%' and disabled = 0 """, as_dict=1)
    submitted_warehouse_data = frappe.db.sql("""select distinct warehouse from `tabDaily Individual Report` where docstatus = 1 and DATE(creation) = CURRENT_DATE """, as_dict=1)
    submitted_warehouse_names = [d['warehouse'] for d in submitted_warehouse_data]
    missing_warehouses = [warehouse for warehouse in all_warehouse_data if warehouse['name'] not in submitted_warehouse_names]
    if missing_warehouses:
        total_count = len(missing_warehouses)
        table_html = "<table border='1' cellpadding='5' cellspacing='0'>"
        table_html += "<tr><th>Date</th><th>Warehouse name</th><th>Owner</th></tr>"
        for warehouse in missing_warehouses:
            table_html += f"<tr><td>{warehouse['curdate()']}</td><td>{warehouse['name']}</td><td>{warehouse['warehouse_owner']}</td></tr>"
        table_html += "</table>"
        main_mail = frappe.db.get_value("NJ Settings", {"parameter": "main_mail_for_inventory_update_daily"}, "value")
        nj_settings_cc_mails = frappe.db.get_value("NJ Settings", {"parameter": "cc_mails_for_inventory_report_daily"}, "value")
        recipient_email = main_mail
        cc_emails = nj_settings_cc_mails.split(",")
        subject = "Inventory Not Updated"
        message = f"""
                <p>Total count of warehouses not submitted inventory: {total_count}</p>
                <p>The following warehouses have not submitted their Inventory:</p>
                {table_html}
                """
        send_email_to_user(recipient_email, subject, message, cc_emails=cc_emails)

@frappe.whitelist()
def all_no_selected_serial_no_data():
    data = frappe.db.sql("""
        SELECT DATE(creation) AS creation_date ,serial_no, reason, owner 
        FROM `tabWork Warehouse Inventory` 
        WHERE DATE(creation) = CURRENT_DATE 
        AND docstatus = 1 AND no = 1
    """, as_dict=1)

    if data:
        table_content = "<table border='1' cellpadding='5' cellspacing='0'>"
        table_content += "<tr><th>Date</th><th>Serial No</th><th>Reason</th><th>User</th></tr>"
        
        for row in data:
            table_content += f"<tr> <td>{row['creation_date']}</td><td>{row['serial_no']}</td><td>{row['reason']}</td><td>{row['owner']}</td></tr>"
        
        table_content += "</table>"
    else:
        table_content = "<p>No data found for today.</p>"

    main_mail = frappe.db.get_value("NJ Settings", {"parameter": "main_mail_for_inventory_update_daily"}, "value")
    nj_settings_cc_mails = frappe.db.get_value("NJ Settings", {"parameter": "cc_mails_for_inventory_report_daily"}, "value")
    cc_emails = nj_settings_cc_mails.split(",")
    send_email_to_user(
        recipient_email=main_mail, 
        subject="Not Found Serial No in Inventory", 
        message=f"<p>The following data is not found:</p>{table_content}",
        cc_emails=cc_emails
    )

@frappe.whitelist()
def send_email_to_user(recipient_email, subject, message,cc_emails=None):
    try:
        email_args = {
            'recipients': recipient_email,
            'cc': cc_emails,
            'subject': subject,
            'message': message,
            'reference_doctype': None,
            'reference_name': None,
            'attachments': None,
        }
        
        frappe.sendmail(**email_args)
        
        frappe.msgprint(f"Email sent successfully to {recipient_email}")
    except Exception as e:
        frappe.log_error(message=str(e), title="Email Sending Failed")
        frappe.throw(f"Failed to send email: {str(e)}")