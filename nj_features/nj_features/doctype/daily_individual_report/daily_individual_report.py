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
        },
        fields=['name', 'status']
    )

    sort_order = {
        'error': 1,
        'pending': 2,
        'partial success': 3,
        'success': 4
    }

    data_imports.sort(key=lambda x: sort_order.get(x['status'].lower(), 4))
    return data_imports


@frappe.whitelist()
def get_serial_no_data():
    user = frappe.session.user
    today = nowdate()
    work_warehouse = frappe.db.get_value('Employee', {'user_id': frappe.session.user}, 'work_warehouse')
    serial_no_data = frappe.get_all('Serial No',
        filters={
            'warehouse': work_warehouse,
        },
        fields=['item_code', 'serial_no']
    )
    return serial_no_data


@frappe.whitelist()
def daily_report_not_submitted_warehouses_data():
    all_warehouse_data = frappe.db.sql("""select name from `tabWarehouse` where parent_warehouse like '%work-warehouse%' """, as_dict=1)
    submitted_warehouse_data = frappe.db.sql("""select warehouse from `tabDaily Individual Report` where docstatus = 1 and DATE(creation) = CURRENT_DATE """, as_dict=1)
    print('warehouse_data=================', all_warehouse_data)
    print('submitted_warehouse_data=================', submitted_warehouse_data)
@frappe.whitelist()
def all_no_selected_serial_no_data():
    # Fetch data from the database
    data = frappe.db.sql("""
        SELECT DATE(creation) AS creation_date ,serial_no, reason, owner 
        FROM `tabWork Warehouse Inventory` 
        WHERE DATE(creation) = CURRENT_DATE 
        AND docstatus = 1 
        AND no = 1
    """, as_dict=1)

    # Format the data as an HTML table
    if data:
        table_content = "<table border='1' cellpadding='5' cellspacing='0'>"
        table_content += "<tr><th>Date</th><th>Serial No</th><th>Reason</th><th>User</th></tr>"
        
        for row in data:
            table_content += f"<tr> <td>{row['creation_date']}</td><td>{row['serial_no']}</td><td>{row['reason']}</td><td>{row['owner']}</td></tr>"
        
        table_content += "</table>"
    else:
        table_content = "<p>No data found for today.</p>"

    # Send email with the table content
    # send_email_to_user(
    #     recipient_email="vishnudandu5366@gmail.com", 
    #     subject="Not Selected Serial No Data", 
    #     message=f"<p>The following data is not selected:</p>{table_content}"
    # )

    print('all_not_selected_serial_no_data================', data)


@frappe.whitelist()
def send_email_to_user(recipient_email, subject, message):
    try:
        # Define the email content
        email_args = {
            'recipients': recipient_email,
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
