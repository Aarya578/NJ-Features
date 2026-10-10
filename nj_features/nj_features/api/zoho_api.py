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


def zoho_coql(select_query):
	"""Run a COQL query (CRM Object Query Language) and return the matched rows."""
	response = requests.post(
		f"{_api_base()}/coql", headers=_headers(), json={"select_query": select_query}, timeout=30
	)
	if response.status_code == 204:
		return []
	return _handle_response(response, "POST", "coql").get("data", [])


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


def _resolve_and_link_address_and_contact(customer_name, deal_data, account_id):
	"""Creates or links Address & Contact for the Customer using data from Zoho Account, Deal & Contact."""
	account_data = {}
	if account_id:
		try:
			acc_res = zoho_get(f"Accounts/{account_id}")
			account_data = (acc_res.get("data") or [{}])[0]
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Failed to fetch Zoho Account {account_id} for Address")

	contact_name = None
	contact_email = None
	contact_phone = None
	contact_obj = deal_data.get("Contact_Name")
	if contact_obj and isinstance(contact_obj, dict) and contact_obj.get("id"):
		try:
			cres = zoho_get(f"Contacts/{contact_obj['id']}")
			cdata = (cres.get("data") or [{}])[0]
			contact_name = cdata.get("Full_Name") or contact_obj.get("name")
			contact_email = cdata.get("Email")
			contact_phone = cdata.get("Phone") or cdata.get("Mobile")
		except Exception:
			contact_name = contact_obj.get("name")
	elif contact_obj and isinstance(contact_obj, dict):
		contact_name = contact_obj.get("name")

	# Extract address lines directly from Zoho Account or Deal
	street = (
		account_data.get("Billing_Street")
		or deal_data.get("Address_1_Street_Address")
		or deal_data.get("Address_1")
	)
	city = (
		account_data.get("Billing_City")
		or deal_data.get("Address_1_City")
	)
	state = (
		account_data.get("Billing_State")
		or deal_data.get("Address_1_State_Province")
	)
	pincode = (
		account_data.get("Billing_Code")
		or deal_data.get("Address_1_Zip_Postal_Code")
	)
	country = account_data.get("Billing_Country") or deal_data.get("Address_1_Country_Region") or "India"

	address_doc_name = None

	# Only create the Address if valid address details exist in Zoho
	# (ERPNext Address doctype requires street, city, state, pincode, and email)
	if street and city and state and pincode:
		addr_title = f"{customer_name}-Billing"
		existing_addr = frappe.db.get_value("Address", {"address_title": addr_title}, "name")
		if existing_addr:
			address_doc_name = existing_addr
		else:
			try:
				addr = frappe.new_doc("Address")
				addr.address_title = addr_title
				addr.address_type = "Billing"
				addr.address_line1 = str(street).strip()
				addr.city = str(city).strip()
				addr.state = str(state).strip()
				addr.gst_state = str(state).strip()
				addr.country = str(country).strip()
				addr.pincode = str(pincode).strip()
				if contact_email:
					addr.email_id = str(contact_email).strip()
				if contact_phone:
					addr.phone = str(contact_phone).strip()
				gstin = (account_data.get("GSTIN") or "").strip()
				if len(gstin) == 15:
					addr.gstin = gstin
				addr.append("links", {"link_doctype": "Customer", "link_name": customer_name})
				addr.insert(ignore_permissions=True)
				frappe.db.commit()
				address_doc_name = addr.name
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"Failed to create Address for Customer {customer_name}")

	# Create Contact if name available
	if contact_name:
		existing_contact = frappe.db.get_value("Contact", {"first_name": contact_name}, "name")
		if not existing_contact:
			try:
				con = frappe.new_doc("Contact")
				con.first_name = contact_name
				if contact_email:
					con.email_id = contact_email
					con.append("email_ids", {"email_id": contact_email, "is_primary": 1})
				if contact_phone:
					con.phone = str(contact_phone)
					con.append("phone_nos", {"phone": str(contact_phone), "is_primary_phone": 1})
				con.append("links", {"link_doctype": "Customer", "link_name": customer_name})
				con.insert(ignore_permissions=True)
				frappe.db.commit()
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"Failed to create Contact for Customer {customer_name}")

	return address_doc_name


@frappe.whitelist(allow_guest=True)
def create_quote_from_deal(deal_id=None, redirect=1):
	"""
	On-demand endpoint triggered when a Zoho CRM user clicks the 'Create ERP Quote' button.

	Parameters:
	- deal_id (str): The Zoho CRM Deal record ID.
	- redirect (int/bool): If 1 (default), performs a 302 redirect in browser to ERPNext Quotation desk view.
	                      If 0, returns a JSON response with quotation info.
	"""
	from frappe.utils import flt, cint
	from nj_features.nj_features.api.zoho_common import resolve_customer, zoho_now

	deal_id = deal_id or frappe.form_dict.get("deal_id")
	if not deal_id:
		frappe.throw("Parameter 'deal_id' is required", frappe.ValidationError)

	deal_id = str(deal_id).strip()
	should_redirect = cint(redirect if redirect is not None else frappe.form_dict.get("redirect", 1))

	# 1. Idempotency check: see if a Quotation already exists for this Deal
	existing_quote = frappe.db.get_value(
		"Quotation",
		{"zoho_deal_id": deal_id, "docstatus": ["<", 2]},
		["name", "docstatus"],
		as_dict=True,
	)
	if existing_quote:
		target_url = f"/app/quotation/{existing_quote.name}"
		if should_redirect:
			frappe.local.response["type"] = "redirect"
			frappe.local.response["location"] = target_url
			return
		return {
			"status": "success",
			"message": "Quotation already exists for this Zoho Deal",
			"quotation": existing_quote.name,
			"url": target_url,
			"is_new": False,
		}

	# 2. Fetch Deal record from Zoho CRM
	deal_res = zoho_get(
		f"Deals/{deal_id}",
		params={
			"fields": "Deal_Name,Account_Name,Products,ERP_Product,Quantity,Amount,ERP_Quotation_ID"
		},
	)
	deal_rows = deal_res.get("data") or []
	if not deal_rows:
		frappe.throw(f"Deal {deal_id} not found in Zoho CRM")
	deal_data = deal_rows[0]

	# If Zoho Deal already referenced an ERP Quotation that still exists
	erp_quotation_id = deal_data.get("ERP_Quotation_ID")
	if erp_quotation_id and frappe.db.exists("Quotation", erp_quotation_id):
		target_url = f"/app/quotation/{erp_quotation_id}"
		if should_redirect:
			frappe.local.response["type"] = "redirect"
			frappe.local.response["location"] = target_url
			return
		return {
			"status": "success",
			"message": "Quotation already exists for this Zoho Deal",
			"quotation": erp_quotation_id,
			"url": target_url,
			"is_new": False,
		}

	# 3. Resolve Customer from Account
	account = deal_data.get("Account_Name")
	if not account or not account.get("id"):
		frappe.throw(f"No Account linked to Deal {deal_id}. Please link an Account in Zoho CRM before creating a quotation.")

	account_id = account["id"]
	customer_name = resolve_customer(
		account_id,
		deal_id,
		zoho_get,
		zoho_put,
		skip_context="Zoho create_quote_from_deal",
	)
	if not customer_name:
		frappe.throw(f"Could not resolve or create ERPNext Customer for Zoho Account {account_id}")

	# Ensure zoho_account_id is updated
	if not frappe.db.get_value("Customer", customer_name, "zoho_account_id"):
		frappe.db.set_value("Customer", customer_name, "zoho_account_id", str(account_id))

	# 4. Resolve Address and Contact from Zoho (Account, Deal, and Contact)
	billing_addr = _resolve_and_link_address_and_contact(customer_name, deal_data, account_id)

	# 5. Resolve line item
	quantity = flt(deal_data.get("Quantity")) or 1.0
	amount = flt(deal_data.get("Amount")) or 0.0
	rate = amount / quantity if quantity > 0 and amount > 0 else 0.0

	# Gather rep's specs and description for context
	specs = (deal_data.get("Specs") or "").strip()
	deal_desc = (deal_data.get("Description") or "").strip()
	context_parts = [p for p in [specs, deal_desc] if p]
	context_str = " | ".join(context_parts)

	item_code = None
	item_description = f"Zoho Deal: {deal_data.get('Deal_Name') or deal_id}"
	if context_str:
		item_description = f"{item_description} ({context_str})"

	# Option A: Rep picked an exact ERP_Product lookup in Zoho
	product = deal_data.get("ERP_Product")
	if product and product.get("id"):
		try:
			prod_detail = zoho_get(f"Products/{product['id']}", params={"fields": "Product_Name,ERP_Item_Code"})
			pdata = (prod_detail.get("data") or [{}])[0]
			candidate_item = pdata.get("ERP_Item_Code")
			if candidate_item and frappe.db.exists("Item", candidate_item):
				item_code = candidate_item
				item_description = pdata.get("Product_Name") or item_description
				if context_str:
					item_description += f" -- Specs: {context_str}"
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Failed to fetch ERP_Product {product.get('id')} for Deal {deal_id}")

	# Option B: Category mapping (Laptops -> Generic Laptop 2024, etc.)
	if not item_code:
		category = (deal_data.get("Products") or "").strip()
		if "laptop" in category.lower():
			if frappe.db.exists("Item", "Generic Laptop 2024"):
				item_code = "Generic Laptop 2024"
				item_description = f"Laptops -- {context_str}" if context_str else "Generic Laptop"
		elif "desktop" in category.lower():
			candidate = frappe.db.get_value("Item", {"item_group": ["like", "%Desktop%"], "disabled": 0}, "name")
			if candidate:
				item_code = candidate
				item_description = f"Desktops -- {context_str}" if context_str else "Generic Desktop"

	# Option C: Fallback to Generic Laptop 2024 if available, or first active sales item
	if not item_code:
		if frappe.db.exists("Item", "Generic Laptop 2024"):
			item_code = "Generic Laptop 2024"
			item_description = f"Zoho Deal Item -- {context_str}" if context_str else f"Zoho Deal: {deal_data.get('Deal_Name') or deal_id}"
		else:
			fallback_item = frappe.db.get_value("Item", {"disabled": 0, "is_sales_item": 1}, "name")
			if not fallback_item:
				frappe.throw("No active sales item found in ERPNext to initialize quotation item.")
			item_code = fallback_item
			item_description = f"Placeholder for Zoho Deal {deal_data.get('Deal_Name') or deal_id} -- replace with actual item."

	# 6. Create Draft Quotation
	quotation = frappe.new_doc("Quotation")
	quotation.quotation_to = "Customer"
	quotation.party_name = customer_name
	quotation.company = "NewJaisa"
	quotation.currency = "INR"
	quotation.conversion_rate = 1.0
	quotation.selling_price_list = "Standard Selling"
	quotation.order_type = "Sales"
	quotation.sale_type = "NJ-Direct-B2B"
	quotation.zoho_deal_id = str(deal_id)

	if billing_addr:
		quotation.customer_address = billing_addr

	quotation.append(
		"items",
		{
			"item_code": item_code,
			"qty": quantity,
			"rate": rate,
			"description": item_description,
		},
	)

	quotation.insert(ignore_permissions=True)
	frappe.db.commit()

	# 6. Update Zoho Deal with ERP Quotation reference
	try:
		zoho_put(
			f"Deals/{deal_id}",
			{
				"data": [
					{
						"id": deal_id,
						"ERP_Quotation_ID": quotation.name,
						"ERP_Quotation_Status": "Draft",
						"Currency_1": quotation.grand_total,
						"ERP_Last_Sync": zoho_now(),
					}
				]
			},
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Failed to update Zoho Deal {deal_id} after creating Quotation {quotation.name}")

	# 7. Response / Redirect
	target_url = f"/app/quotation/{quotation.name}"
	if should_redirect:
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = target_url
		return

	return {
		"status": "success",
		"message": "Quotation created successfully",
		"quotation": quotation.name,
		"url": target_url,
		"is_new": True,
	}

