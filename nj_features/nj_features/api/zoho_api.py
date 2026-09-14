"""
Zoho CRM REST API client for the Zoho-ERPNext Quote Bridge integration.

Talks to Zoho's standard CRM REST API via OAuth2 (refresh token grant),
since the Zoho CRM edition in use here does not include Developer Hub
(Functions/Variables), so no logic runs inside Zoho itself. All sync
logic lives in ERPNext and calls out to Zoho instead.

Credentials live in the "Zoho Settings" single doctype, with client
secret and refresh token stored as Password fields (encrypted at rest).
"""

import requests
import frappe
from frappe.utils.password import get_decrypted_password

CACHE_KEY = "zoho_crm_access_token"
ACCOUNTS_DOMAIN = {
	"in": "https://accounts.zoho.in",
	"com": "https://accounts.zoho.com",
	"eu": "https://accounts.zoho.eu",
	"au": "https://accounts.zoho.com.au",
	"jp": "https://accounts.zoho.jp",
}


class ZohoAPIError(Exception):
	pass


def _get_settings():
	settings = frappe.get_single("Zoho Settings")
	if not settings.enabled:
		frappe.throw("Zoho Settings is disabled")
	if not settings.client_id or not settings.refresh_token:
		frappe.throw("Zoho Settings is missing client_id or refresh_token")
	return settings


def get_access_token():
	"""Return a valid access token, refreshing it if the cached one has expired."""
	cached = frappe.cache().get_value(CACHE_KEY)
	if cached:
		return cached

	settings = _get_settings()
	client_secret = get_decrypted_password("Zoho Settings", "Zoho Settings", "client_secret")
	refresh_token = get_decrypted_password("Zoho Settings", "Zoho Settings", "refresh_token")
	accounts_domain = ACCOUNTS_DOMAIN.get(settings.zoho_domain or "in", ACCOUNTS_DOMAIN["in"])

	response = requests.post(
		f"{accounts_domain}/oauth/v2/token",
		data={
			"grant_type": "refresh_token",
			"client_id": settings.client_id,
			"client_secret": client_secret,
			"refresh_token": refresh_token,
		},
		timeout=30,
	)

	if response.status_code != 200:
		frappe.log_error(response.text, "Zoho OAuth token refresh failed")
		frappe.throw(f"Zoho OAuth token refresh failed: {response.status_code}")

	data = response.json()
	access_token = data.get("access_token")
	api_domain = data.get("api_domain")
	expires_in = data.get("expires_in", 3600)

	if not access_token:
		frappe.log_error(str(data), "Zoho OAuth token refresh: no access_token")
		frappe.throw("Zoho OAuth token refresh did not return an access_token")

	if api_domain and api_domain != settings.api_domain:
		frappe.db.set_single_value("Zoho Settings", "api_domain", api_domain)
		frappe.db.commit()

	# Cache a little under the real TTL so we never serve a token past its expiry.
	frappe.cache().set_value(CACHE_KEY, access_token, expires_in_sec=max(expires_in - 120, 60))
	return access_token


def _api_base():
	settings = frappe.get_single("Zoho Settings")
	api_domain = settings.api_domain or {
		"in": "https://www.zohoapis.in",
		"com": "https://www.zohoapis.com",
		"eu": "https://www.zohoapis.eu",
		"au": "https://www.zohoapis.com.au",
		"jp": "https://www.zohoapis.jp",
	}.get(settings.zoho_domain or "in")
	return f"{api_domain}/crm/v3"


def _headers():
	return {
		"Authorization": f"Zoho-oauthtoken {get_access_token()}",
		"Content-Type": "application/json",
	}


def zoho_get(path, params=None):
	response = requests.get(f"{_api_base()}/{path}", headers=_headers(), params=params, timeout=30)
	return _handle_response(response, "GET", path)


def zoho_post(path, data):
	response = requests.post(f"{_api_base()}/{path}", headers=_headers(), json=data, timeout=30)
	return _handle_response(response, "POST", path)


def zoho_put(path, data):
	response = requests.put(f"{_api_base()}/{path}", headers=_headers(), json=data, timeout=30)
	return _handle_response(response, "PUT", path)


def _handle_response(response, method, path):
	if response.status_code >= 300:
		frappe.log_error(
			f"{method} {path}\nstatus={response.status_code}\n{response.text}",
			"Zoho CRM API error",
		)
		raise ZohoAPIError(f"{method} {path} failed: {response.status_code} {response.text}")
	if not response.content:
		return {}
	return response.json()
