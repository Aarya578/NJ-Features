import json
import frappe
import traceback
from frappe.utils import get_url
from werkzeug.utils import redirect
from werkzeug.wrappers import Response
from frappe.sessions import delete_session
from nj_lib.utils.common_utils import get_active_user
from nj_features.nj_features.api.encryption import decrypt

@frappe.whitelist(allow_guest=True)
def login(usr, pwd, encrypted_pwd=False, doctype_url=None, api=False):
    try:
        if encrypted_pwd:
            pwd = decrypt(pwd)
        login_manager = frappe.auth.LoginManager()
        login_manager.authenticate(user=usr, pwd=pwd)
        login_manager.post_login()

    except frappe.AuthenticationError as e:
        error_message = f"Authentication failed for user: {usr}. {str(e)}"
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

        if api:
            return {
                "success_key": 1,
                "message": "Authentication success",
                "sid": frappe.session.sid,
                "api_key": api_key,
                "api_secret": api_generate,
                "username": user_data.get('username'),
                "email": user_data.get('email')
            }

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
                if "home" == doctype_url:
                    redirect_url = f"{base_url}/app"
                
                response = Response()
                response.mimetype = 'application/json'
                response.charset = 'utf-8'
                payload = {
                    "message": "Login successful, redirecting...",
                    "redirect_url": redirect_url
                }
                response.data = json.dumps(payload)
                
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

@frappe.whitelist()
def enforce_session_limit():
    
    try:
        user = frappe.session.user
        max_sessions = frappe.db.get_value("User", {"name": user}, "simultaneous_sessions")
        if not max_sessions:
            max_sessions = 1
        user_sessions_query = """SELECT sid, lastupdate FROM `tabSessions` WHERE user = %s ORDER BY lastupdate DESC"""
        user_sessions = frappe.db.sql(user_sessions_query, user, as_dict=1)

        if len(user_sessions) >= max_sessions:
            sessions_to_remove = len(user_sessions) - (max_sessions - 1)

            for session in user_sessions[:sessions_to_remove]:
                delete_session(session.sid, reason="Oldest session terminated due to session limit")

            frappe.db.commit()

        return True

    except Exception as e:
        frappe.db.rollback()
        traceback_info = traceback.format_exc()
        return {
            "success_key": 0,
            "message": f"Error while logging in user: {user}. error: {str(e)}",
            "error_code": "UNKNOWN_ERROR",
            "traceback": traceback_info
        }