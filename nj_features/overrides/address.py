import frappe
import re
import requests, re, frappe
import frappe, requests, json, random, string
from frappe import _
import requests
from frappe.contacts.doctype.address.address import Address
import json


class CustomeAddress(Address):
	def validate(self):
		super().validate()
		self.picode_validations()
		# self.state_validetion()
		self.address_validations()
	

	def picode_validations(self):
		if self.pincode:
			# Validate format
			if not re.fullmatch(r"\d{6}", str(self.pincode)):
				frappe.throw(_("Please enter a valid 6-digit numeric Pin Code without spaces or special characters"))

			# Call API
			url = f"https://api.postalpincode.in/pincode/{self.pincode}"
			# print("url=====================", url)

			headers = {
				"User-Agent": "Mozilla/5.0",
				"Accept": "application/json"
			}

			try:
				response = requests.get(url, headers=headers, timeout=10)
				data = response.json()
				# print("data=====================", data)

				if data and data[0].get("Status") == "Success":
					post_offices = data[0].get("PostOffice", [])
					if post_offices:
						state_name = post_offices[0].get("State")
						# print("state_name=====================", state_name)
						if state_name:
							self.state = state_name
							
						else:
							frappe.throw(_("State information not found for this Pin Code"))
					else:
						frappe.throw(_("No Post Office data found for this Pin Code"))
				else:
					frappe.throw(_("Invalid Pin Code or data not found"))
				
			except requests.exceptions.RequestException as e:
				frappe.throw(_("Error fetching State from Pin Code API: {0}").format(str(e)))
	# def state_validetion(self):
	# 	if self.state!= self.gst_state:
	# 						frappe.throw(_("State Province state and GST state do not match Please corect it"))

	def address_validations(self):

		if self.address_line1 and len(self.address_line1) > 100:
			# print("address_line1=====================", len(self.address_line1),self.address_line1)
			frappe.throw(_("Address Line 1 should not exceed 100 characters"))

		if self.address_line2 and len(self.address_line2) > 100:
			# print("address_line2=====================", len(self.address_line2),self.address_line2)
			frappe.throw(_("Address Line 2 should not exceed 100 characters"))


@frappe.whitelist()
def hiding_gst_filed(links):
	if isinstance(links, str):
		links = json.loads(links)
		# print("links=======================",links)

	for link in links:
		if link.get("link_doctype") == "Customer":
			customer_name = link.get("link_name")
			# print("customer_name=======================",customer_name)
			gst_category = frappe.db.get_value("Customer", customer_name, "gst_category")
			# print("gst_category=======================",gst_category)
			return {"hide_gstin": gst_category == "Unregistered"}

	return {"hide_gstin": False}




import frappe, requests, json, random, string
from frappe import _

def generate_request_id(length=12):
	chars = string.ascii_uppercase + string.digits
	return ''.join(random.choice(chars) for _ in range(length))

@frappe.whitelist()
def fetch_gst_details(doc):
	if isinstance(doc, str):
		doc = json.loads(doc)

	try:
		# Step 1: Authenticate and fetch token
		token = frappe.db.get_single_value("Logistics Settings", "api_token")
		secret = frappe.db.get_single_value("Logistics Settings", "api_secret")
		auth_headers = {
			"gspappid": token,
			"gspappsecret": secret,
			"Content-Type": "application/x-www-form-urlencoded"
		}
		auth_res = requests.post(
			"https://gsp.adaequare.com/gsp/authenticate?action=GSP&grant_type=token",
			headers=auth_headers,
			data={"grant_type": "client_credentials"}
		)

		auth_json = auth_res.json()
		access_token = auth_json.get("access_token")
		print("access_token=======================", access_token)
		if not access_token:
			frappe.throw(_("Failed to fetch access token."))

		# Step 2: Generate requestid
		requestid = generate_request_id()

		# Step 3: Call GST API with bearer token
		url = f"https://gsp.adaequare.com/enriched/ei/api/master/gstin?gstin={doc.get('gstin')}"
		print("url=======================", url)
		headers = {
			"Content-Type": "application/json",
			"user_name": "API_NJ",
			"password": "Accounts@1234",
			"gstin": doc.get("gstin"),
			"requestid": requestid,
			"Authorization": f"Bearer {access_token}"
		}

		res = requests.get(url, headers=headers)
		data = res.json()

		if not data.get("success"):
			frappe.throw(_("Failed to fetch GST details: {0}").format(data.get("message")))

		result = data.get("result", {})
		print("result=======================", result)

		# Step 4: Map fields into doc
		doc["address_title"] = result.get("LegalName")
		doc["address_line1"] = " ".join(filter(None, [
			result.get("AddrBnm"),
			result.get("AddrBno"),
			result.get("AddrFlno"),
			# result.get("AddrSt"),
			result.get("AddrLoc")
		]))
		print("doc=====line 1==================", doc["address_line1"])
		doc["address_line2"] = result.get("AddrSt")
		print("doc=====line 2==================", doc["address_line2"])
		doc["city"] = result.get("AddrLoc")
		doc["pincode"] = result.get("AddrPncd")
		doc["gst_state_number"] = result.get("StateCode")

		# Save updated doc
		frappe.get_doc(doc).save(ignore_permissions=True)

		return {"status": "success", "data": result, "requestid": requestid}

	except Exception as e:
		frappe.throw(_("Error fetching GST details: {0}").format(str(e)))

