import json
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

import frappe
import requests
from frappe import _
from frappe.utils.file_manager import save_file
from frappe.utils.password import get_decrypted_password


DEFAULT_SERVICEABILITY_URL = (
	"https://track.delhivery.com/api/dc/fetch/serviceability/pincode"
)
DEFAULT_PRODUCT_TYPE = "Heavy"
DEFAULT_ORDER_URL = "https://staging-express.delhivery.com/api/cmu/create.json"
DEFAULT_LABEL_URL = "https://track.delhivery.com/api/p/packing_slip"
PICKUP_LOCATION_NAME = "NewJaisa Technologies Limited"
REQUEST_TIMEOUT_SECONDS = 30


def _get_delhivery_settings():
	settings = frappe.get_single("Logistics Settings")
	api_token = get_decrypted_password(
		"Logistics Settings",
		"Logistics Settings",
		"delhivery_api_token",
		raise_exception=False,
	)

	if not api_token:
		frappe.throw(_("Please configure the Delhivery API Token in Logistics Settings."))

	return {
		"api_token": api_token,
		"serviceability_url": (
			settings.delhivery_serviceability_url or DEFAULT_SERVICEABILITY_URL
		).strip(),
		"order_url": (settings.delhivery_order_url or DEFAULT_ORDER_URL).strip(),
		"label_url": (settings.delhivery_label_url or DEFAULT_LABEL_URL).strip(),
		"product_type": (
			settings.delhivery_product_type or DEFAULT_PRODUCT_TYPE
		).strip(),
	}


def _validate_pincode(pincode):
	pincode = str(pincode or "").strip()
	if not pincode:
		frappe.throw(_("Pincode not found in the shipping address."))
	if not re.fullmatch(r"\d{6}", pincode):
		frappe.throw(_("Shipping address pincode must contain exactly 6 digits."))
	return pincode


def check_pincode_serviceability(pincode):
	"""Return Delhivery's postal-code details or throw when the pincode is unavailable."""
	pincode = _validate_pincode(pincode)
	settings = _get_delhivery_settings()
	params = {
		"product_type": settings["product_type"],
		"pincode": pincode,
	}
	headers = {
		"Authorization": f'Token {settings["api_token"]}',
		"Accept": "application/json",
	}
	print(
		"Delhivery serviceability request:",
		{
			"url": settings["serviceability_url"],
			"params": params,
		},
	)

	try:
		response = requests.get(
			settings["serviceability_url"],
			headers=headers,
			params=params,
			timeout=REQUEST_TIMEOUT_SECONDS,
		)
		print("Delhivery serviceability response status:", response.status_code)
		print("Delhivery serviceability response body:", response.text)
		response.raise_for_status()
		response_data = response.json()
	except requests.RequestException:
		frappe.log_error(frappe.get_traceback(), "Delhivery Serviceability API")
		frappe.throw(_("Unable to check Delhivery pincode serviceability. Please try again."))
	except ValueError:
		frappe.log_error(
			f"Pincode: {pincode}\nResponse: {response.text}",
			"Invalid Delhivery Serviceability Response",
		)
		frappe.throw(_("Delhivery returned an invalid serviceability response."))

	# Delhivery currently returns serviceability in ``data``. Keep support for
	# the older ``delivery_codes`` response format as well.
	serviceability_data = response_data.get("data") or []
	delivery_codes = response_data.get("delivery_codes") or []
	print("Delhivery serviceability data count:", len(serviceability_data))
	print("Delhivery delivery_codes count:", len(delivery_codes))

	if serviceability_data:
		postal_code = serviceability_data[0]
	elif delivery_codes:
		postal_code = delivery_codes[0].get("postal_code") or {}
	else:
		print(f"Delhivery pincode {pincode} is not serviceable")
		return {
			"serviceable": False,
			"pincode": pincode,
			"product_type": settings["product_type"],
			"message": response_data.get("error") or _("Pincode service is not available."),
			"response": response_data,
		}

	print(
		"Delhivery pincode is serviceable:",
		{
			"pincode": pincode,
			"city": postal_code.get("city"),
			"district": postal_code.get("district"),
			"state": postal_code.get("state") or postal_code.get("state_code"),
			"cod": postal_code.get("cod"),
			"pickup": postal_code.get("pickup"),
			"pre_paid": postal_code.get("pre_paid"),
			"payment_type": postal_code.get("payment_type"),
			"is_oda": postal_code.get("is_oda"),
		},
	)
	return {
		"serviceable": True,
		"pincode": pincode,
		"product_type": settings["product_type"],
		"postal_code": postal_code,
	}


@frappe.whitelist()
def check_delivery_note_serviceability(doc):
	"""Check the pincode on a Delivery Note's linked shipping Address."""
	if isinstance(doc, str):
		doc = frappe.parse_json(doc)

	shipping_address_name = doc.get("shipping_address_name")
	print("Delhivery Delivery Note shipping address:", shipping_address_name)
	if not shipping_address_name:
		frappe.throw(_("Please select a Shipping Address before checking Delhivery."))

	pincode = frappe.db.get_value("Address", shipping_address_name, "pincode")
	print("Delhivery shipping address pincode:", pincode)
	return check_pincode_serviceability(pincode)


def _join_address(address):
	return ", ".join(
		part.strip()
		for part in (address.address_line1, address.address_line2)
		if part and part.strip()
	)


def _get_sales_order(delivery_note):
	sales_orders = {
		row.against_sales_order
		for row in delivery_note.items
		if row.against_sales_order
	}
	if not sales_orders:
		frappe.throw(_("Sales Order not linked to this Delivery Note."))
	if len(sales_orders) > 1:
		frappe.throw(_("Delhivery order creation supports only one Sales Order per Delivery Note."))
	return frappe.get_doc("Sales Order", sales_orders.pop())


def _get_delhivery_item_details(delivery_note):
	item_group_value = frappe.db.get_value(
		"NJ Settings",
		{"parameter": "delhivery_order_creation_item_groups"},
		"value",
	)
	allowed_item_groups = {
		group.strip() for group in (item_group_value or "").split(",") if group.strip()
	}
	if not allowed_item_groups:
		frappe.throw(
			_("Please configure delhivery_order_creation_item_groups in NJ Settings.")
		)

	item_codes = [row.item_code for row in delivery_note.items if row.item_code]
	item_groups = {}
	if item_codes:
		item_groups = dict(
			frappe.get_all(
				"Item",
				filters={"name": ["in", item_codes]},
				fields=["name", "item_group"],
				as_list=True,
			)
		)

	quantity = 0
	product_descriptions = []
	hsn_codes = []
	for row in delivery_note.items:
		item_group = item_groups.get(row.item_code)
		if item_group not in allowed_item_groups:
			print(
				"Skipping Delhivery item:",
				{"item_code": row.item_code, "item_group": item_group},
			)
			continue

		quantity += float(row.qty or 0)
		if row.item_name and row.item_name not in product_descriptions:
			product_descriptions.append(row.item_name)
		if row.get("gst_hsn_code") and row.gst_hsn_code not in hsn_codes:
			hsn_codes.append(row.gst_hsn_code)

	if quantity <= 0:
		frappe.throw(_("No Delivery Note items match the configured Delhivery item groups."))

	return {
		"quantity": int(quantity) if quantity.is_integer() else quantity,
		"products_desc": ", ".join(product_descriptions),
		"hsn_code": ", ".join(hsn_codes),
	}


def _crop_delhivery_label_pdf(pdf_content):
	"""Remove Delhivery's blank A4 canvas while preserving vector label content."""
	ghostscript = shutil.which("gs")
	if not ghostscript:
		print("Ghostscript not available; saving the original Delhivery label PDF")
		return pdf_content

	try:
		with tempfile.TemporaryDirectory(prefix="delhivery-label-") as temp_dir:
			input_path = f"{temp_dir}/input.pdf"
			output_path = f"{temp_dir}/cropped.pdf"
			with open(input_path, "wb") as input_file:
				input_file.write(pdf_content)

			bbox_result = subprocess.run(
				[
					ghostscript,
					"-q",
					"-dNOPAUSE",
					"-dBATCH",
					"-sDEVICE=bbox",
					input_path,
				],
				capture_output=True,
				text=True,
				timeout=REQUEST_TIMEOUT_SECONDS,
				check=True,
			)
			bbox_match = re.search(
				r"%%HiResBoundingBox:\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)",
				bbox_result.stderr,
			)
			if not bbox_match:
				print("Delhivery label content bounds not found; saving original PDF")
				return pdf_content

			left, bottom, right, top = map(float, bbox_match.groups())
			padding = 6.0
			left = max(0.0, left - padding)
			bottom = max(0.0, bottom - padding)
			right += padding
			top += padding
			width = right - left
			height = top - bottom
			if width <= 0 or height <= 0:
				return pdf_content

			subprocess.run(
				[
					ghostscript,
					"-q",
					"-dNOPAUSE",
					"-dBATCH",
					"-sDEVICE=pdfwrite",
					"-dFIXEDMEDIA",
					f"-dDEVICEWIDTHPOINTS={width:.3f}",
					f"-dDEVICEHEIGHTPOINTS={height:.3f}",
					f"-sOutputFile={output_path}",
					"-c",
					f"<</PageOffset [{-left:.3f} {-bottom:.3f}]>> setpagedevice",
					"-f",
					input_path,
				],
				capture_output=True,
				timeout=REQUEST_TIMEOUT_SECONDS,
				check=True,
			)
			with open(output_path, "rb") as output_file:
				cropped_content = output_file.read()
			if not cropped_content.startswith(b"%PDF"):
				return pdf_content

			print(
				"Delhivery label PDF cropped:",
				{
					"width_points": round(width, 2),
					"height_points": round(height, 2),
					"original_size": len(pdf_content),
					"cropped_size": len(cropped_content),
				},
			)
			return cropped_content
	except (OSError, subprocess.SubprocessError) as error:
		print("Unable to crop Delhivery label PDF; saving original:", str(error))
		return pdf_content


def _generate_delhivery_label(delivery_note, waybill):
	settings = _get_delhivery_settings()
	headers = {
		"Authorization": f'Token {settings["api_token"]}',
		"Content-Type": "application/json",
	}
	params = {
		"wbns": waybill,
		"pdf": "true",
		"pdf_size": "4R",
	}
	print(
		"Delhivery label request:",
		{"url": settings["label_url"], "params": params},
	)
	response = requests.get(
		settings["label_url"],
		headers=headers,
		params=params,
		timeout=REQUEST_TIMEOUT_SECONDS,
	)
	content_type = (response.headers.get("Content-Type") or "").lower()
	print("Delhivery label response status:", response.status_code)
	print("Delhivery label response Content-Type:", content_type)
	print("Delhivery label response size:", len(response.content))
	response.raise_for_status()

	if "application/pdf" in content_type or response.content.startswith(b"%PDF"):
		pdf_content = response.content
	else:
		try:
			response_data = response.json()
		except ValueError as error:
			print("Delhivery label invalid response:", response.text[:1000])
			raise ValueError(_("Delhivery returned an invalid label response.")) from error

		packages = response_data.get("packages") or []
		pdf_download_link = packages[0].get("pdf_download_link") if packages else None
		if not pdf_download_link:
			print("Delhivery label JSON response has no PDF download link")
			raise ValueError(_("PDF download link not found in the Delhivery label response."))

		parsed_download_url = urlparse(pdf_download_link)
		if parsed_download_url.scheme != "https" or not parsed_download_url.netloc:
			raise ValueError(_("Delhivery returned an invalid PDF download link."))

		# The link contains temporary signed credentials, so do not print or store it.
		print("Downloading Delhivery label PDF from host:", parsed_download_url.netloc)
		download_response = requests.get(
			pdf_download_link,
			timeout=REQUEST_TIMEOUT_SECONDS,
		)
		download_content_type = (
			download_response.headers.get("Content-Type") or ""
		).lower()
		print("Delhivery PDF download status:", download_response.status_code)
		print("Delhivery PDF download Content-Type:", download_content_type)
		print("Delhivery PDF download size:", len(download_response.content))
		download_response.raise_for_status()
		if (
			"application/pdf" not in download_content_type
			and not download_response.content.startswith(b"%PDF")
		):
			raise ValueError(_("Delhivery PDF download did not return a valid PDF."))
		pdf_content = download_response.content

	pdf_content = _crop_delhivery_label_pdf(pdf_content)
	file_doc = save_file(
		f"{delivery_note.name}-Delhivery-{waybill}.pdf",
		pdf_content,
		"Delivery Note",
		delivery_note.name,
		is_private=1,
		df="delhivery_label",
	)
	delivery_note.db_set("delhivery_label", file_doc.file_url, update_modified=False)
	print(
		"Delhivery label saved:",
		{"delivery_note": delivery_note.name, "file_url": file_doc.file_url},
	)
	return file_doc.file_url


@frappe.whitelist()
def generate_delhivery_label(delivery_note_name):
	delivery_note = frappe.get_doc("Delivery Note", delivery_note_name)
	waybill = delivery_note.tracking_id
	if not waybill:
		frappe.throw(_("Create the Delhivery order before generating its label."))
	if delivery_note.courier_service != "Delhivery":
		frappe.throw(_("This Delivery Note is not assigned to Delhivery."))

	try:
		file_url = _generate_delhivery_label(delivery_note, waybill)
	except requests.RequestException:
		frappe.log_error(frappe.get_traceback(), "Delhivery Label API")
		frappe.throw(_("Unable to generate the Delhivery label. Please try again."))
	except ValueError as error:
		frappe.log_error(frappe.get_traceback(), "Invalid Delhivery Label Response")
		frappe.throw(str(error))

	return {"success": True, "waybill": waybill, "file_url": file_url}


@frappe.whitelist()
def create_delhivery_order(doc, shipping_mode):
	if isinstance(doc, str):
		doc = frappe.parse_json(doc)

	delivery_note_name = doc.get("name")
	if not delivery_note_name:
		frappe.throw(_("Delivery Note is required."))
	if shipping_mode not in ("Surface", "Express"):
		frappe.throw(_("Shipping Mode must be Surface or Express."))

	delivery_note = frappe.get_doc("Delivery Note", delivery_note_name)
	if delivery_note.tracking_id:
		frappe.throw(
			_("Delivery Note {0} already has tracking ID {1}.").format(
				delivery_note.name, delivery_note.tracking_id
			)
		)
	if not delivery_note.shipping_address_name:
		frappe.throw(_("Please select a Shipping Address before creating a Delhivery order."))
	if not delivery_note.company_address:
		frappe.throw(_("Please select a Company Address before creating a Delhivery order."))

	shipping_address = frappe.get_doc("Address", delivery_note.shipping_address_name)
	company_address = frappe.get_doc("Address", delivery_note.company_address)
	serviceability = check_pincode_serviceability(shipping_address.pincode)
	if not serviceability.get("serviceable"):
		return serviceability

	sales_order = _get_sales_order(delivery_note)
	item_details = _get_delhivery_item_details(delivery_note)

	# Case 1: COD checked but payment already received → run normal prepaid flow
	if sales_order.is_cod == 1 and getattr(sales_order, "payment_received", 0) == 1:
		payment_mode = "Prepaid"
		cod_amount = 0

		if delivery_note.grand_total:
			total_amount = float(delivery_note.grand_total)
		else:
			# If grand_total not found, fetch from item groups
			total_default_charge = 0
			found_charges = False
			for item in delivery_note.items:
				if item.item_code:
					try:
						item_doc = frappe.get_doc("Item", item.item_code)
						if item_doc.item_group:
							item_group_doc = frappe.get_doc("Item Group", item_doc.item_group)
							if getattr(item_group_doc, "default_charge", None):
								total_default_charge += float(item_group_doc.default_charge)
								found_charges = True
					except Exception:
						continue

			if found_charges and total_default_charge > 0:
				total_amount = total_default_charge
			else:
				total_amount = 450.0

	# Case 2: Only COD checked → COD flow
	elif sales_order.is_cod == 1:
		payment_mode = "COD"
		cod_amount = float(sales_order.total_outstanding or 0)
		total_amount = float(delivery_note.grand_total or 0)

	# Case 3: Normal Prepaid flow (non-COD orders)
	else:
		payment_mode = "Prepaid"
		cod_amount = 0
		if delivery_note.grand_total:
			total_amount = float(delivery_note.grand_total)
		else:
			total_default_charge = 0
			found_charges = False
			for item in delivery_note.items:
				if item.item_code:
					try:
						item_doc = frappe.get_doc("Item", item.item_code)
						if item_doc.item_group:
							item_group_doc = frappe.get_doc("Item Group", item_doc.item_group)
							if getattr(item_group_doc, "default_charge", None):
								total_default_charge += float(item_group_doc.default_charge)
								found_charges = True
					except Exception:
						continue

			if found_charges and total_default_charge > 0:
				total_amount = total_default_charge
			else:
				total_amount = 300.0

	shipment = {
		"name": shipping_address.name,
		"add": _join_address(shipping_address),
		"pin": str(shipping_address.pincode or ""),
		"city": shipping_address.city or "",
		"state": shipping_address.state or "",
		"country": shipping_address.country or "India",
		"phone": shipping_address.phone or "",
		"order": delivery_note.name,
		"payment_mode": payment_mode,
		"return_pin": str(company_address.pincode or ""),
		"return_city": company_address.city or "",
		"return_phone": company_address.phone or "",
		"return_add": _join_address(company_address),
		"return_state": company_address.state or "",
		"return_country": company_address.country or "India",
		"cod_amount": cod_amount,
		"order_date": str(delivery_note.creation),
		"total_amount": total_amount,
		"quantity": item_details["quantity"],
		"waybill": "",
		"shipment_width": float(delivery_note.length or 0),
		"shipment_height": float(delivery_note.height or 0),
		"shipment_length": float(delivery_note.breadth or 0),
		# Delivery Note weight is maintained in kilograms; Delhivery expects grams.
		"weight": int(round(float(delivery_note.weight or 0) * 1000)),
		"shipping_mode": shipping_mode,
		"address_type": "",
	}
	if item_details["products_desc"]:
		shipment["products_desc"] = item_details["products_desc"]
	if item_details["hsn_code"]:
		shipment["hsn_code"] = item_details["hsn_code"]

	payload = {
		"shipments": [shipment],
		"pickup_location": {"name": PICKUP_LOCATION_NAME},
	}
	settings = _get_delhivery_settings()
	headers = {
		"Accept": "application/json",
		"Authorization": f'Token {settings["api_token"]}',
		"Content-Type": "application/json",
	}
	request_body = f"format=json&data={json.dumps(payload)}"
	print("Delhivery order request URL:", settings["order_url"])
	print("Delhivery order request payload:", json.dumps(payload, indent=2, default=str))

	try:
		response = requests.post(
			settings["order_url"],
			headers=headers,
			data=request_body,
			timeout=REQUEST_TIMEOUT_SECONDS,
		)
		print("Delhivery order response status:", response.status_code)
		print("Delhivery order response body:", response.text)
		response.raise_for_status()
		response_data = response.json()
	except requests.RequestException:
		frappe.log_error(frappe.get_traceback(), "Delhivery Order Creation API")
		frappe.throw(_("Unable to create the Delhivery order. Please try again."))
	except ValueError:
		frappe.log_error(
			f"Delivery Note: {delivery_note.name}\nResponse: {response.text}",
			"Invalid Delhivery Order Response",
		)
		frappe.throw(_("Delhivery returned an invalid order-creation response."))

	packages = response_data.get("packages") or []
	package = packages[0] if packages else {}
	waybill = package.get("waybill")
	if not response_data.get("success") or package.get("status") != "Success" or not waybill:
		remarks = package.get("remarks") or []
		error_message = ", ".join(filter(None, remarks)) or response_data.get("error")
		frappe.throw(error_message or _("Delhivery order creation failed."))

	delivery_note.db_set("tracking_id", waybill, update_modified=False)
	delivery_note.db_set("courier_service", "Delhivery", update_modified=False)
	label_url = None
	label_error = None
	try:
		label_url = _generate_delhivery_label(delivery_note, waybill)
	except Exception as error:
		label_error = str(error)
		frappe.log_error(frappe.get_traceback(), "Delhivery Label Generation After Order")
		print("Delhivery order created, but label generation failed:", label_error)
	print(
		"Delhivery order created successfully:",
		{"delivery_note": delivery_note.name, "waybill": waybill},
	)
	return {
		"success": True,
		"serviceable": True,
		"waybill": waybill,
		"label_url": label_url,
		"label_error": label_error,
		"shipping_mode": shipping_mode,
		"response": response_data,
	}
