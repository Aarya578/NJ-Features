import frappe
from frappe import auth

@frappe.whitelist( allow_guest=True )
def login(usr, pwd):
    print(f"user 6 in login api : {usr}, pwd: {pwd}")
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
  
    sql="""SELECT department from `tabEmployee` where prefered_email =%s """
    department=frappe.db.sql(sql,(usr),as_dict=True)
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


@frappe.whitelist()
def generate_keys(user):
    api_key = ''
    user_details = frappe.get_doc('User', user)
    print("user_details====38 user details")
    api_secret = frappe.generate_hash(length=15)

    if not user_details.api_key:
        api_key = frappe.generate_hash(length=15)
        user_details.api_key = api_key

    user_details.api_secret = api_secret
    user_details.save()

    return f"{api_secret}"