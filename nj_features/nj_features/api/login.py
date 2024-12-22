import frappe
import traceback
import json
from frappe import auth
from frappe.utils import get_url
from nj_features.hooks import ENCRYPTION_KEY
from nj_lib.utils.common_utils import get_active_user
from nj_features.nj_features.api.encryption import decrypt
from werkzeug.utils import redirect
from werkzeug.wrappers import Response

@frappe.whitelist(allow_guest=True)
def login(usr, pwd, doctype_url=None):
    try:
        login_manager = frappe.auth.LoginManager()
        if " " in pwd:
            pwd = decrypt(pwd, ENCRYPTION_KEY)
        login_manager.authenticate(user=usr, pwd=pwd)
        login_manager.post_login()

    except frappe.AuthenticationError as e:
        error_message = f"Authentication failed for user: {usr}. Invalid login credentials."
        return {
            "success_key": 0,
            "message": error_message,
            "error_code": "AUTH_ERROR",
            "traceback": traceback.format_exc()
        }

    except Exception as e:
        error_message = f"Error while logging in user: {usr}. error: {str(e)}"
        return {
            "success_key": 0,
            "message": error_message,
            "error_code": "UNKNOWN_ERROR",
            "traceback": traceback.format_exc()
        }

    user_data = get_active_user(usr, fields=['api_key', 'username', 'email'])
    api_key, api_generate = '', ''

    try:
        if not user_data.get('api_key'):
            user_details = frappe.get_doc("User", usr)
            api_secret = frappe.generate_hash(length=15)
            if not user_details.api_key:
                api_key = frappe.generate_hash(length=15)
                user_details.api_key = api_key
            user_details.api_secret = api_secret
            user_details.save()
            api_generate = api_secret
            api_key = api_key
        else:
            api_generate = frappe.utils.password.get_decrypted_password(
                "User", frappe.session.user, fieldname="api_secret"
            )
            api_key = user_data.get('api_key')

        department = frappe.db.get_value('Employee', {'user_id': usr, 'status': 'Active'}, 'department')

        if department:
            frappe.response["message"] = {
                "success_key": 1,
                "message": "Authentication success",
                "sid": frappe.session.sid,
                "api_key": api_key,
                "api_secret": api_generate,
                "username": user_data.get('username'),
                "email": user_data.get('email'),
                "department": department
            }

            if doctype_url:
                base_url = get_url()
                redirect_url = f"{base_url}/app/{doctype_url}"
                # Create a custom JSON response
                response = Response()
                response.mimetype = 'application/json'
                response.charset = 'utf-8'
                payload = {
                    "message": "Login successful, redirecting...",
                    "redirect_url": redirect_url
                }
                response.data = json.dumps(payload)
                
                # Redirect to the new URL
                return redirect(redirect_url)

        else:
            error_message = (
                f"Department is not defined for your <b>'Mail ID: {usr}'</b>. "
                f"Please contact <b>IT Infra Team: <a href='mailto:itsupport@newjaisa.com'>itsupport@newjaisa.com</a></b>."
            )
            frappe.response["message"] = {
                "success_key": 2,
                "message": error_message,
                "error_code": "NO_DEPARTMENT"
            }

    except Exception as e:
        error_message = f"Error while logging in user: {usr}. error: {str(e)}"
        return {
            "success_key": 0,
            "message": error_message,
            "error_code": "UNKNOWN_ERROR",
            "traceback": traceback.format_exc()
        }

    return frappe.response["message"]
