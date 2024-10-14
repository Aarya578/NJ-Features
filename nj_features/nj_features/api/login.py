# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import auth
from nj_lib.utils.common_utils import get_active_user

@frappe.whitelist( allow_guest=True )
def login(usr, pwd):
    try:
        login_manager = frappe.auth.LoginManager()
        login_manager.authenticate(user=usr, pwd=pwd)
        login_manager.post_login()
        
    except frappe.exceptions.AuthenticationError:
        frappe.clear_messages()
        return {
            "success_key": 0,
            "message": "Authentication Error!"
        }

    api_key, api_generate = '', ''
    user_data = get_active_user(usr, fields=['api_key', 'username', 'email'])
    
    if not user_data.get('api_key'):
        api_generated_secret = frappe.get_attr("frappe.core.doctype.user.user.generate_keys")(usr)
        api_generate = api_generated_secret.get('api_secret')
        api_key_from_user_data = get_active_user(usr, fields=['api_key'])
        api_key = api_key_from_user_data.get('api_key')
    else:
        generated_secret = frappe.utils.password.get_decrypted_password(
            "User", frappe.session.user, fieldname="api_secret"
        )
        api_generate = generated_secret
        api_key = user_data.get('api_key')
        
    get_dept_query = "SELECT department FROM `tabEmployee` WHERE user_id = %s AND status = 'Active'"
    department=frappe.db.sql(get_dept_query,(usr), as_dict=True)
    
    if department:
        department = department[0]['department']
        frappe.response["message"] = {
            "success_key":1,
            "message":"Authentication success",
            "sid":frappe.session.sid,
            "api_key":api_key,
            "api_secret":api_generate,
            "username":user.get('username'),
            "email":user.get('email'),
            "department":department
        }
    else:
        error_message = f"Department is not defined for your <b>'Mail ID: {usr}'</b>. Please mail to <b>IT Infra Team: <a href='mailto:itsupport@newjaisa.com'>itsupport@newjaisa.com</a></b>."
        frappe.response["message"] = {
            "success_key":2,
            "message":error_message,
        }
        return

    user = frappe.get_doc('User', frappe.session.user)
    generated_secret = frappe.utils.password.get_decrypted_password(
        "User", frappe.session.user, fieldname="api_secret"
    )
    api_generate = generated_secret
  
    sql="""SELECT department from `tabEmployee` where user_id =%s AND status = 'Active'"""
    department=frappe.db.sql(sql,(usr),as_dict=True)
    if department:
        department = department[0]['department']
        frappe.response["message"] = {
        "success_key":1,
        "message":"Authentication success",
        "sid":frappe.session.sid,
        "api_key":user_data.get('api_key'),
        "api_secret":api_generate,
        "username":user_data.get('username'),
        "email":user_data.get('email'),
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