import frappe
from frappe import auth

@frappe.whitelist( allow_guest=True )
def login(usr, pwd):
    try:
        login_manager = frappe.auth.LoginManager()
        login_manager.authenticate(user=usr, pwd=pwd)
        login_manager.post_login()
    except frappe.exceptions.AuthenticationError:
        frappe.clear_messages()
        frappe.local.response["message"] = {
            "success_key":0,
            "message":"Authentication Error!"
        }
        return

    user = frappe.get_doc('User', frappe.session.user)
    generated_secret = frappe.utils.password.get_decrypted_password(
        "User", frappe.session.user, fieldname="api_secret"
    )
    api_generate = generated_secret
  
    get_dept_query = "SELECT department FROM `tabEmployee` WHERE user_id = %s"
    department=frappe.db.sql(get_dept_query,(usr), as_dict=True)
    
    if department:
        department = department[0]['department']
        frappe.response["message"] = {
            "success_key":1,
            "message":"Authentication success",
            "sid":frappe.session.sid,
            "api_key":user.api_key,
            "api_secret":api_generate,
            "username":user.username,
            "email":user.email,
            "department":department
        }
    else:
        error_message = f"Department is not defined for your <b>'Mail ID: {usr}'</b>. Please mail to <b>IT Infra Team: <a href='mailto:itsupport@newjaisa.com'>itsupport@newjaisa.com</a></b>."
        frappe.response["message"] = {
            "success_key":2,
            "message":error_message,
        }

@frappe.whitelist()
def generate_keys(user):
    api_key = ''
    user_details = frappe.get_doc('User', user)
    api_secret = frappe.generate_hash(length=15)

    if not user_details.api_key:
        api_key = frappe.generate_hash(length=15)
        user_details.api_key = api_key

    user_details.api_secret = api_secret
    user_details.save()

    return f"{api_secret}"