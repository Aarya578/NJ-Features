# Copyright (c) 2026, NewJaisa
# For license information, please see license.txt

import json
import re
import requests
import frappe
from frappe.model.document import Document

OPENAI_API_KEY = "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"
OPENAI_MODEL = "gpt-5.2"


# ---------------------------------------------------------
# Hardcoded source URLs for FRU + image fetching
# Add model-specific URLs here.
# Model matching is case-insensitive and partial.
# ---------------------------------------------------------

PART_SOURCE_URLS = {
	"dell": {
		"default": "https://www.parts-people.com/",
	},
	"lenovo": {
		"default": "https://pcsupport.lenovo.com/in/en/",
	},
}


try:
	from nj_p1_features.nj_p1_features.doctype.item_wizards.iw_component import fetch_parts as fetch_dell_parts
except Exception:
	fetch_dell_parts = None

try:
	from nj_p1_features.nj_p1_features.doctype.item_wizards.lenovo_iw_component import get_lenovo_parts as fetch_lenovo_parts
except Exception:
	fetch_lenovo_parts = None

try:
	from nj_p1_features.nj_p1_features.doctype.item_wizards import hp_parts_scraper
	fetch_hp_parts = hp_parts_scraper.fetch_hp_parts_json
except Exception:
	hp_parts_scraper = None
	fetch_hp_parts = None


class NJSparePartAutomation(Document):
	pass


def get_existing_item_field(possible_fields):
	meta = frappe.get_meta("Item")

	for fieldname in possible_fields:
		if meta.has_field(fieldname):
			return fieldname

	return None


def get_item_context(item_code):
	model_field = get_existing_item_field([
		"model",
		"model_no",
		"model_number",
		"item_model",
		"laptop_model",
		"custom_model",
		"custom_model_no",
		"custom_model_number",
	])

	fru_field = get_existing_item_field([
		"fru_number",
		"fru_no",
		"part_item_code_fru",
		"part_no",
		"part_number",
		"custom_fru_number",
		"custom_fru_no",
		"custom_part_item_code_fru",
	])

	fields = ["name", "item_name", "item_group", "brand"]

	if model_field:
		fields.append(model_field)

	if fru_field:
		fields.append(fru_field)

	item = frappe.db.get_value("Item", item_code, fields, as_dict=True)

	if not item:
		frappe.throw(f"Item not found: {item_code}")

	erp_item_group = item.item_group
	generic_item_group = get_generic_item_group_name(
		erp_item_group,
		item.item_name
	)

	return {
		"item_code": item.name,
		"item_name": item.item_name,
		"item_group": erp_item_group,              # keep ERP group for matching/scraping
		"erp_item_group": erp_item_group,
		"generic_item_group": generic_item_group,  # use this for display/description
		"brand": item.brand,
		"model": item.get(model_field) if model_field else "",
		"fru_number": item.get(fru_field) if fru_field else "",
	}


def extract_response_text(response_json):
	if response_json.get("output_text"):
		return response_json.get("output_text")

	output = response_json.get("output") or []

	for output_item in output:
		if output_item.get("type") == "message":
			for content in output_item.get("content") or []:
				if content.get("type") in ["output_text", "text"]:
					return content.get("text")

	return ""


def call_openai_for_spare_part(context):
	api_key = OPENAI_API_KEY
	model = OPENAI_MODEL

	if not api_key:
		frappe.throw("OpenAI API key missing in Python file.")

	prompt = f"""
You are generating product information for a new laptop spare part.

Use the given item data as context. Do not invent exact OEM compatibility if it is not clear.

Input Data:
Item Name: {context.get("item_name") or ""}
Brand: {context.get("brand") or ""}
Model: {context.get("model") or ""}
Part Name: {context.get("generic_item_group") or context.get("item_group") or ""}
FRU Number: {context.get("fru_number") or ""}

Return only valid JSON in this exact structure:
{{
  "description": "A clean product description. Include Key Features inside this description.",
  "specifications": [
    "Specification 1",
    "Specification 2",
    "Specification 3"
  ]
}}

Rules:
- Description should be 120 to 180 words.
- Include a Key Features section inside the description.
- Specifications should be short and practical.
- If Model is blank, do not mention unknown model.
- If FRU Number is blank, do not mention unknown FRU.
- Do not use the words refurbished, used, second-hand, pre-owned, repaired, reused, or harvested.
- Do not directly use ERP-specific item group names. Convert them into normal customer-friendly spare part terms.
- Do not mention warranty, price, stock quantity, delivery, or discount.
- Do not claim the part is original/OEM unless the input clearly supports it.
- Use the Part Name as the normal spare part name. Do not mention ERP item group names like BODY A, BODY B, BODY C, BODY D, LAPTOP STORAGE, or BODY B FRONT BEZEL.
"""

	headers = {
		"Authorization": f"Bearer {api_key}",
		"Content-Type": "application/json",
	}

	payload = {
		"model": model,
		"input": prompt,
		"text": {
			"format": {
				"type": "json_object"
			}
		}
	}

	response = requests.post(
		"https://api.openai.com/v1/responses",
		headers=headers,
		json=payload,
		timeout=60,
	)

	if response.status_code >= 400:
		frappe.throw(f"OpenAI API Error: {response.status_code} - {response.text}")

	response_json = response.json()
	text = extract_response_text(response_json)

	if not text:
		frappe.throw("OpenAI returned empty response.")

	try:
		parsed = json.loads(text)
	except Exception:
		frappe.throw(f"OpenAI response was not valid JSON: {text}")

	return parsed, response_json


def clean_text(value):
	return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()

def get_generic_item_group_name(item_group, item_name=""):
	"""
	Convert ERP Item Group names into normal technician/customer-friendly names.
	ERP item group is still used internally for matching.
	Generic name is used for display and OpenAI description.
	"""

	text = normalize_match_text(f"{item_group or ''} {item_name or ''}")

	mapping = [
		(["body b", "front bezel", "lcd bezel", "display bezel", "bezel"], "Front Bezel"),
		(["body a", "lcd cover", "display cover", "back cover"], "Display Back Cover"),
		(["body c", "palmrest", "top cover"], "Palmrest"),
		(["body d", "base cover", "bottom cover", "lower case"], "Base Cover"),
		(["keyboard"], "Keyboard"),
		(["battery"], "Battery"),
		(["laptop ram", "ram", "memory"], "RAM"),
		(["laptop storage", "ssd", "hdd", "storage"], "Storage"),
		(["display", "lcd", "screen"], "Display"),
		(["touchpad", "trackpad"], "Touchpad"),
		(["speaker"], "Speaker"),
		(["fan"], "Fan"),
		(["hinge"], "Hinges"),
		(["camera", "webcam"], "Camera"),
		(["wifi", "wireless", "wlan"], "WiFi Card"),
		(["motherboard", "system board"], "Motherboard"),
		(["adapter", "adaptor", "charger"], "Adapter"),
		(["power cord"], "Power Cord"),
		(["cable"], "Cable"),
	]

	for keywords, generic_name in mapping:
		for keyword in keywords:
			if normalize_match_text(keyword) in text:
				return generic_name

	return clean_text(item_group)


def normalize_match_text(value):
	return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def split_tokens(value):
	text = normalize_match_text(value)
	return set(t for t in text.split() if len(t) >= 3)

def get_existing_serial_no_field(possible_fields):
	meta = frappe.get_meta("Serial No")

	for fieldname in possible_fields:
		if meta.has_field(fieldname):
			return fieldname

	return None


def get_bios_serial_no_from_erp(context):
	"""
	Find BIOS Serial No from ERP Serial No using Brand + Model.
	Example:
	Brand = Lenovo, Model = T470
	Returns BIOS Serial No like PF1FRWXA.
	"""

	brand = clean_text(context.get("brand"))
	model = clean_text(context.get("model"))

	if not brand or not model:
		frappe.throw("Brand and Model are required to fetch BIOS Serial No.")

	bios_field = get_existing_serial_no_field([
		"bios_serial_no",
		"bios_serialno",
		"bios_serial_number",
		"bios_no",
		"bios_number",
		"custom_bios_serial_no",
		"custom_bios_serialno",
		"custom_bios_serial_number",
		"custom_bios_no",
		"custom_bios_number",
	])

	if not bios_field:
		frappe.throw("BIOS Serial No field not found in Serial No doctype.")

	serial_meta = frappe.get_meta("Serial No")
	item_meta = frappe.get_meta("Item")

	brand_conditions = []
	model_conditions = []

	if serial_meta.has_field("brand"):
		brand_conditions.append("LOWER(IFNULL(sn.`brand`, '')) LIKE %(brand)s")

	if serial_meta.has_field("custom_brand"):
		brand_conditions.append("LOWER(IFNULL(sn.`custom_brand`, '')) LIKE %(brand)s")

	if item_meta.has_field("brand"):
		brand_conditions.append("LOWER(IFNULL(it.`brand`, '')) LIKE %(brand)s")

	for fieldname in [
		"model",
		"model_no",
		"model_number",
		"item_model",
		"laptop_model",
		"custom_model",
		"custom_model_no",
		"custom_model_number",
	]:
		if serial_meta.has_field(fieldname):
			model_conditions.append(f"LOWER(IFNULL(sn.`{fieldname}`, '')) LIKE %(model)s")

		if item_meta.has_field(fieldname):
			model_conditions.append(f"LOWER(IFNULL(it.`{fieldname}`, '')) LIKE %(model)s")

	# fallback matching from Serial No item_code / item_name
	if serial_meta.has_field("item_code"):
		model_conditions.append("LOWER(IFNULL(sn.`item_code`, '')) LIKE %(model)s")

	if serial_meta.has_field("item_name"):
		model_conditions.append("LOWER(IFNULL(sn.`item_name`, '')) LIKE %(model)s")

	if item_meta.has_field("item_name"):
		model_conditions.append("LOWER(IFNULL(it.`item_name`, '')) LIKE %(model)s")

	conditions = [
		f"IFNULL(sn.`{bios_field}`, '') != ''"
	]

	if brand_conditions:
		conditions.append("(" + " OR ".join(brand_conditions) + ")")

	if model_conditions:
		conditions.append("(" + " OR ".join(model_conditions) + ")")

	rows = frappe.db.sql(
		f"""
		SELECT
			sn.name,
			sn.`{bios_field}` AS bios_serial_no,
			sn.item_code
		FROM `tabSerial No` sn
		LEFT JOIN `tabItem` it
			ON it.name = sn.item_code
		WHERE {" AND ".join(conditions)}
		ORDER BY sn.modified DESC
		LIMIT 1
		""",
		{
			"brand": f"%{brand.lower()}%",
			"model": f"%{model.lower()}%",
		},
		as_dict=True,
	)

	if not rows:
		frappe.throw(
			f"No Serial No found with BIOS Serial No for Brand: {brand}, Model: {model}"
		)

	return clean_text(rows[0].get("bios_serial_no"))


def get_part_search_keywords(context):
	"""
	Extra matching help because ERP item groups like BODY B FRONT BEZEL
	may appear in Lenovo as LCD Bezel / Display Bezel.
	"""

	item_name = normalize_match_text(context.get("item_name"))
	item_group = normalize_match_text(context.get("item_group"))
	text = f"{item_name} {item_group}"

	keywords = []

	if "bezel" in text:
		keywords.extend([
			"bezel",
			"lcd bezel",
			"display bezel",
			"screen bezel",
			"front bezel",
		])

	if "keyboard" in text:
		keywords.extend(["keyboard"])

	if "battery" in text:
		keywords.extend(["battery"])

	if "speaker" in text:
		keywords.extend(["speaker"])

	if "fan" in text:
		keywords.extend(["fan"])

	if "hinge" in text:
		keywords.extend(["hinge"])

	if "camera" in text or "webcam" in text:
		keywords.extend(["camera", "webcam"])

	if "touchpad" in text:
		keywords.extend(["touchpad", "trackpad"])

	if "wifi" in text or "wireless" in text or "wlan" in text:
		keywords.extend(["wifi", "wireless", "wlan"])

	if "body a" in text or "back cover" in text:
		keywords.extend(["lcd cover", "back cover", "display cover"])

	if "body d" in text or "base cover" in text or "bottom" in text:
		keywords.extend(["base cover", "lower case", "bottom cover"])

	cleaned = []
	for keyword in keywords:
		keyword = normalize_match_text(keyword)
		if keyword and keyword not in cleaned:
			cleaned.append(keyword)

	return cleaned


def set_doc_value_if_field_exists(doc, fieldname, value):
	if doc.meta.has_field(fieldname):
		doc.set(fieldname, value or "")


def get_source_url_for_brand_model(brand, model):
	brand_key = normalize_match_text(brand)
	model_key = normalize_match_text(model)

	if "dell" in brand_key:
		url_map = PART_SOURCE_URLS.get("dell") or {}
	elif "lenovo" in brand_key:
		url_map = PART_SOURCE_URLS.get("lenovo") or {}
	else:
		return ""

	# First try model-specific match
	for configured_model, url in url_map.items():
		configured_model_key = normalize_match_text(configured_model)

		if configured_model_key == "default":
			continue

		if configured_model_key and (
			configured_model_key in model_key or model_key in configured_model_key
		):
			return clean_text(url)

	# Fallback to default brand URL
	return clean_text(url_map.get("default"))


def get_part_images(part):
	images = []

	raw_images = part.get("images") or []

	if isinstance(raw_images, list):
		for img in raw_images:
			if isinstance(img, dict):
				url = img.get("url") or img.get("image") or ""
			else:
				url = img

			url = clean_text(url)
			if url and url not in images:
				images.append(url)

	for key in [
		"image",
		"image2",
		"image3",
		"image_1",
		"image_2",
		"image_3",
		"image_4",
		"image_5",
	]:
		url = clean_text(part.get(key))
		if url and url not in images:
			images.append(url)

	return images[:5]


def get_part_fru_values(part):
	values = []

	for key in ["FRU", "sku", "dell_pn", "FRU_all"]:
		value = clean_text(part.get(key))

		if not value:
			continue

		for piece in re.split(r"\s*\|\s*|,", value):
			piece = clean_text(piece).upper()

			if piece and piece not in values:
				values.append(piece)

	return values


def score_external_part(part, context):
	score = 0

	item_name = context.get("item_name") or ""
	model = context.get("model") or ""
	brand = context.get("brand") or ""
	erp_item_group = context.get("item_group") or ""

	part_text = " ".join([
		str(part.get("title") or ""),
		str(part.get("part") or ""),
		str(part.get("description") or ""),
		str(part.get("full_description") or ""),
		str(part.get("part_category") or ""),
		str(part.get("hp_category") or ""),
		str(part.get("commodity") or ""),
		str(part.get("item_group") or ""),
		str(part.get("mapped_item_group") or ""),
		str(part.get("compatible_models") or ""),
		str(part.get("product_description") or ""),
		str(part.get("product_number") or ""),
	])

	part_text_norm = normalize_match_text(part_text)

	part_group = clean_text(part.get("item_group") or part.get("mapped_item_group"))

	if part_group and erp_item_group:
		if normalize_match_text(part_group) == normalize_match_text(erp_item_group):
			score += 250

	if model and normalize_match_text(model) in part_text_norm:
		score += 100

	if brand and normalize_match_text(brand) in part_text_norm:
		score += 30

	item_tokens = split_tokens(item_name)
	part_tokens = split_tokens(part_text)
	score += len(item_tokens.intersection(part_tokens)) * 10

	for keyword in get_part_search_keywords(context):
		if keyword in part_text_norm:
			score += 80

	return score


def pick_best_external_part(parts, context):
	if not parts or not isinstance(parts, list):
		return None

	scored = []

	for part in parts:
		if not isinstance(part, dict):
			continue

		score = score_external_part(part, context)
		scored.append((score, part))

	if not scored:
		return None

	scored.sort(key=lambda x: x[0], reverse=True)

	best_score, best_part = scored[0]

	if best_score < 30:
		return None

	return best_part

def pick_best_hp_product_number(product_options, context):
	"""
	When HP PartSurfer returns multiple Product Numbers for one serial,
	auto-pick the option that best matches ERP model/item name.
	Example:
	Model 840 G1 should pick K4G25UC - E840G1...
	not x360 11 G11.
	"""

	if not product_options:
		return ""

	model = normalize_match_text(context.get("model"))
	item_name = normalize_match_text(context.get("item_name"))
	item_group = normalize_match_text(context.get("item_group"))

	model_compact = model.replace(" ", "")
	item_name_compact = item_name.replace(" ", "")

	best_score = 0
	best_product_number = ""

	for opt in product_options:
		product_number = clean_text(opt.get("product_number"))
		description = clean_text(opt.get("description"))
		label = clean_text(opt.get("label"))

		option_text = normalize_match_text(
			f"{product_number} {description} {label}"
		)
		option_compact = option_text.replace(" ", "")

		score = 0

		if model and model in option_text:
			score += 200

		if model_compact and model_compact in option_compact:
			score += 250

		for token in split_tokens(model):
			if token in option_text:
				score += 40

		for token in split_tokens(item_name):
			if token in option_text:
				score += 10

		for token in split_tokens(item_group):
			if token in option_text:
				score += 5

		if score > best_score:
			best_score = score
			best_product_number = product_number

	if best_score >= 80:
		return best_product_number

	return ""


def select_hp_product_number_from_automation(driver, product_number: str) -> bool:
	"""
	Runtime override for HP product number selection.

	We are keeping hp_parts_scraper.py unchanged because it is used by other tasks.
	This function is used only by NJ Spare Part Automation.
	"""

	if not hp_parts_scraper:
		return False

	product_number = clean_text(product_number).upper()

	if not product_number:
		return False

	print(f"\nSelecting HP Product Number from automation: {product_number}")

	By = hp_parts_scraper.By
	Select = hp_parts_scraper.Select
	normalize_text = hp_parts_scraper.normalize_text
	wait_for_page_ready = hp_parts_scraper.wait_for_page_ready
	time_module = hp_parts_scraper.time

	def is_parts_page_loaded():
		try:
			body_text = normalize_text(driver.find_element(By.TAG_NAME, "body").text)
		except Exception:
			body_text = ""

		text_l = body_text.lower()

		still_on_selection = (
			"multiple products associated" in text_l
			or "please select a product number" in text_l
		)

		has_parts_table = (
			"general(product family)" in text_l
			or "advanced(unique product s/n)" in text_l
			or "component bom" in text_l
			or "spare bom" in text_l
			or ("part number" in text_l and "part description" in text_l)
		)

		return has_parts_table and not still_on_selection

	try:
		selects = driver.find_elements(By.TAG_NAME, "select")
		selected = False

		for sel in selects:
			try:
				s = Select(sel)

				for opt in s.options:
					label = normalize_text(opt.text).upper()
					value = normalize_text(opt.get_attribute("value")).upper()

					if (
						label.startswith(product_number + " -")
						or label == product_number
						or value == product_number
						or product_number in value
					):
						option_value = opt.get_attribute("value")

						driver.execute_script(
							"""
							arguments[0].scrollIntoView({block: 'center'});
							arguments[0].value = arguments[1];

							const options = Array.from(arguments[0].options || []);
							const idx = options.findIndex(o => o.value === arguments[1]);

							if (idx >= 0) {
								arguments[0].selectedIndex = idx;
								options[idx].selected = true;
							}

							arguments[0].dispatchEvent(new Event('input', {bubbles: true}));
							arguments[0].dispatchEvent(new Event('change', {bubbles: true}));
							arguments[0].dispatchEvent(new Event('blur', {bubbles: true}));
							""",
							sel,
							option_value
						)

						try:
							s.select_by_value(option_value)
						except Exception:
							try:
								s.select_by_visible_text(opt.text)
							except Exception:
								pass

						selected = True
						print("DEBUG: HP product option selected from automation:", opt.text)
						break

				if selected:
					break

			except Exception as e:
				print("DEBUG: HP select loop skipped:", e)

		if not selected:
			print("DEBUG: HP product option not found from automation:", product_number)
			return False

		time_module.sleep(1)

		clicked = driver.execute_script(
			r"""
			function isVisible(el) {
				if (!el) return false;

				const rect = el.getBoundingClientRect();
				if (!rect || rect.width <= 0 || rect.height <= 0) return false;

				const style = window.getComputedStyle(el);
				if (style.display === 'none') return false;
				if (style.visibility === 'hidden') return false;

				return true;
			}

			function txt(el) {
				return (el.innerText || el.textContent || el.value || '')
					.replace(/\s+/g, ' ')
					.trim()
					.toLowerCase();
			}

			function clickEl(el) {
				if (!el) return false;

				try {
					el.scrollIntoView({block: 'center'});
				} catch (e) {}

				try {
					el.click();
					return true;
				} catch (e) {}

				try {
					el.dispatchEvent(new MouseEvent('mousedown', {view: window, bubbles: true, cancelable: true}));
					el.dispatchEvent(new MouseEvent('mouseup', {view: window, bubbles: true, cancelable: true}));
					el.dispatchEvent(new MouseEvent('click', {view: window, bubbles: true, cancelable: true}));
					return true;
				} catch (e) {}

				return false;
			}

			const forms = Array.from(document.querySelectorAll('form'));
			const roots = forms.length ? forms : [document];

			for (const root of roots) {
				const candidates = Array.from(root.querySelectorAll(
					'input[type="submit"], input[type="button"], button, a, span, div'
				)).filter(isVisible);

				for (const el of candidates) {
					const t = txt(el);
					const type = String(el.getAttribute('type') || '').toLowerCase();

					if (
						t === 'submit'
						|| t.includes('submit')
						|| t.includes('continue')
						|| t.includes('search')
						|| type === 'submit'
					) {
						const target = el.closest('button,input,a,[onclick],[role="button"]') || el;

						if (clickEl(target)) {
							return {
								clicked: true,
								text: t,
								type: type
							};
						}
					}
				}
			}

			// Last fallback: submit the form directly.
			const form = document.querySelector('form');

			if (form) {
				try {
					HTMLFormElement.prototype.submit.call(form);
					return {
						clicked: true,
						text: 'direct form submit',
						type: 'form'
					};
				} catch (e) {}
			}

			return {
				clicked: false,
				reason: 'submit button not found'
			};
			"""
		)

		print("DEBUG: HP submit click result from automation:", clicked)

		time_module.sleep(5)
		wait_for_page_ready(driver, timeout=20)

		for _ in range(10):
			if is_parts_page_loaded():
				print("DEBUG: HP parts page loaded after automation product selection.")
				return True

			time_module.sleep(2)

		try:
			body_text = normalize_text(driver.find_element(By.TAG_NAME, "body").text)
			print("DEBUG: HP still did not load parts page after automation product selection.")
			print("DEBUG BODY AFTER PRODUCT SELECTION:")
			print(body_text[:2500])
		except Exception:
			pass

	except Exception as e:
		print(f"HP product selection from automation failed: {e}")

	return False

def hp_select_product_number_and_submit_for_automation(driver, product_number):
	"""
	Select HP Product Number and click only the correct Product Number Submit button.
	This is used only in NJ Spare Part Automation.
	No change needed in hp_parts_scraper.py.
	"""

	if not hp_parts_scraper:
		return False

	product_number = clean_text(product_number).upper()

	if not product_number:
		return False

	By = hp_parts_scraper.By
	normalize_text = hp_parts_scraper.normalize_text
	wait_for_page_ready = hp_parts_scraper.wait_for_page_ready
	time_module = hp_parts_scraper.time

	def is_parts_page_loaded():
		try:
			body_text = normalize_text(driver.find_element(By.TAG_NAME, "body").text)
		except Exception:
			body_text = ""

		text_l = body_text.lower()

		still_on_selection = (
			"multiple products associated" in text_l
			or "please select a product number" in text_l
		)

		has_parts_table = (
			"general(product family)" in text_l
			or "advanced(unique product s/n)" in text_l
			or "component bom" in text_l
			or "spare bom" in text_l
			or ("part number" in text_l and "part description" in text_l)
		)

		return has_parts_table and not still_on_selection

	print(f"\nSelecting HP Product Number from NJ Spare Part Automation: {product_number}")

	try:
		result = driver.execute_script(
			r"""
			const productNumber = String(arguments[0] || '').trim().toUpperCase();

			function isVisible(el) {
				if (!el) return false;

				const rect = el.getBoundingClientRect();
				if (!rect || rect.width <= 0 || rect.height <= 0) return false;

				const style = window.getComputedStyle(el);
				if (style.display === 'none') return false;
				if (style.visibility === 'hidden') return false;
				if (parseFloat(style.opacity || '1') <= 0) return false;

				return true;
			}

			function txt(el) {
				return (el && (el.innerText || el.textContent || el.value || '') || '')
					.replace(/\s+/g, ' ')
					.trim()
					.toLowerCase();
			}

			function clickEl(el) {
				if (!el) return false;

				try {
					el.scrollIntoView({ block: 'center', inline: 'center' });
				} catch (e) {}

				try {
					el.click();
					return true;
				} catch (e) {}

				try {
					el.dispatchEvent(new MouseEvent('mousedown', {
						view: window,
						bubbles: true,
						cancelable: true
					}));
					el.dispatchEvent(new MouseEvent('mouseup', {
						view: window,
						bubbles: true,
						cancelable: true
					}));
					el.dispatchEvent(new MouseEvent('click', {
						view: window,
						bubbles: true,
						cancelable: true
					}));
					return true;
				} catch (e) {}

				return false;
			}

			let matchedSelect = null;
			let matchedValue = "";
			let matchedLabel = "";

			const selects = Array.from(document.querySelectorAll('select')).filter(isVisible);

			for (const sel of selects) {
				const opts = Array.from(sel.options || []);

				for (const opt of opts) {
					const label = (opt.textContent || '').replace(/\s+/g, ' ').trim().toUpperCase();
					const value = (opt.value || '').replace(/\s+/g, ' ').trim().toUpperCase();

					if (
						label.startsWith(productNumber + ' -')
						|| label === productNumber
						|| value === productNumber
						|| value.includes(productNumber)
					) {
						matchedSelect = sel;
						matchedValue = opt.value;
						matchedLabel = opt.textContent || '';
						break;
					}
				}

				if (matchedSelect) break;
			}

			if (!matchedSelect) {
				return {
					selected: false,
					clicked: false,
					reason: "Product Number option not found"
				};
			}

			matchedSelect.focus();
			matchedSelect.value = matchedValue;

			const options = Array.from(matchedSelect.options || []);
			const selectedIndex = options.findIndex(o => o.value === matchedValue);

			if (selectedIndex >= 0) {
				matchedSelect.selectedIndex = selectedIndex;
				options[selectedIndex].selected = true;
			}

			matchedSelect.dispatchEvent(new Event('input', { bubbles: true }));
			matchedSelect.dispatchEvent(new Event('change', { bubbles: true }));
			matchedSelect.dispatchEvent(new Event('blur', { bubbles: true }));

			// Important:
			// Search button and Generic Search button should NOT be clicked here.
			// Only Product Number Submit should be preferred.
			const roots = [];

			const form = matchedSelect.closest('form');
			if (form) roots.push(form);

			let parent = matchedSelect.parentElement;
			let depth = 0;

			while (parent && depth < 8) {
				roots.push(parent);
				parent = parent.parentElement;
				depth++;
			}

			roots.push(document);

			let best = null;
			let bestScore = -9999;

			for (const root of roots) {
				const candidates = Array.from(root.querySelectorAll(
					'input[type="submit"], input[type="button"], button, a, span, div'
				)).filter(isVisible);

				for (const el of candidates) {
					const t = txt(el);
					const value = String(el.value || '').replace(/\s+/g, ' ').trim().toLowerCase();
					const type = String(el.getAttribute('type') || '').toLowerCase();
					const combined = [t, value, type].join(' ');

					let score = 0;

					if (t === 'submit' || value === 'submit') score += 300;
					if (combined.includes('submit')) score += 200;
					if (type === 'submit') score += 150;

					// Avoid wrong buttons.
					if (combined.includes('generic search')) score -= 500;
					if (combined.includes('search')) score -= 200;
					if (combined.includes('feedback')) score -= 500;

					// Prefer button near selected dropdown.
					try {
						if (root !== document) score += 50;
					} catch (e) {}

					if (score > bestScore) {
						bestScore = score;
						best = el;
					}
				}
			}

			if (best && bestScore > 0) {
				const target = best.closest('button,input,a,[onclick],[role="button"]') || best;

				if (clickEl(target)) {
					return {
						selected: true,
						clicked: true,
						product_number: productNumber,
						button_text: txt(best),
						button_value: String(best.value || ''),
						score: bestScore
					};
				}
			}

			// Last fallback: submit only the form that contains the product dropdown.
			if (form) {
				try {
					HTMLFormElement.prototype.submit.call(form);

					return {
						selected: true,
						clicked: true,
						product_number: productNumber,
						button_text: "direct product form submit"
					};
				} catch (e) {}
			}

			return {
				selected: true,
				clicked: false,
				product_number: productNumber,
				reason: "Submit button not found"
			};
			""",
			product_number,
		)

		print("DEBUG: HP Product Number submit result:", result)

		time_module.sleep(5)
		wait_for_page_ready(driver, timeout=20)

		for _ in range(15):
			if is_parts_page_loaded():
				print("DEBUG: HP parts page loaded after Product Number selection.")
				return True

			time_module.sleep(2)

		try:
			body_text = normalize_text(driver.find_element(By.TAG_NAME, "body").text)
			print("DEBUG: HP parts page still not loaded after Product Number selection.")
			print("DEBUG BODY AFTER HP PRODUCT SELECTION:")
			print(body_text[:2500])
		except Exception:
			pass

	except Exception as e:
		print(f"HP Product Number selection failed in automation: {e}")

	return False

def hp_is_parts_page_loaded(driver):
	if not hp_parts_scraper:
		return False

	By = hp_parts_scraper.By
	normalize_text = hp_parts_scraper.normalize_text

	try:
		body_text = normalize_text(driver.find_element(By.TAG_NAME, "body").text)
	except Exception:
		body_text = ""

	text_l = body_text.lower()

	still_on_selection = (
		"multiple products associated" in text_l
		or "please select a product number" in text_l
	)

	has_parts_table = (
		"general(product family)" in text_l
		or "advanced(unique product s/n)" in text_l
		or "component bom" in text_l
		or "spare bom" in text_l
		or ("part number" in text_l and "part description" in text_l)
	)

	return has_parts_table and not still_on_selection


def fetch_hp_fru_image_parts_only(context):
	"""
	HP-only lightweight flow for NJ Spare Part Automation.

	Important:
	Do not call hp_parts_scraper.fetch_hp_parts_json(),
	because that function is used by another task.

	Flow:
	1. Open HP using BIOS / Serial No.
	2. If HP asks for Product Number, auto-pick Product Number.
	3. Instead of clicking HP's Product Number Submit button, directly open Product Number search.
	4. Parse only FRU and image links.
	"""

	if not hp_parts_scraper:
		frappe.throw("HP scraper module import failed. Check hp_parts_scraper.py path.")

	bios_number = get_bios_serial_no_from_erp(context)
	context["bios_number_used_for_scraping"] = bios_number

	driver = hp_parts_scraper.get_driver()

	try:
		# First open using BIOS / Serial No.
		hp_parts_scraper.open_hp_by_serial(driver, bios_number)

		product_options = hp_parts_scraper.extract_product_options(driver)

		if product_options:
			selected_product_number = clean_text(context.get("product_number") or "")

			if not selected_product_number:
				selected_product_number = pick_best_hp_product_number(product_options, context)

			if not selected_product_number:
				option_text = "\n".join([
					f"{idx}. {opt.get('product_number')} - {opt.get('description')}"
					for idx, opt in enumerate(product_options, start=1)
				])

				frappe.throw(
					"HP is asking to select Product Number, but automation could not confidently auto-select one.\n\n"
					+ option_text
				)

			context["hp_product_number_used_for_scraping"] = selected_product_number

			print(
				f"HP product selection auto-picked: {selected_product_number} "
				f"for model={context.get('model')}"
			)

			# Important fix:
			# Do NOT click the Product Number Submit button.
			# HP keeps staying on the same selection page.
			# Open the selected Product Number directly instead.
			print(f"Opening HP PartSurfer directly with Product Number: {selected_product_number}")
			hp_parts_scraper.open_hp_by_serial(driver, selected_product_number)

			if not hp_is_parts_page_loaded(driver):
				try:
					body_text = hp_parts_scraper.normalize_text(
						driver.find_element(hp_parts_scraper.By.TAG_NAME, "body").text
					)
					print("DEBUG: HP product number direct search did not load parts page.")
					print("DEBUG BODY AFTER PRODUCT NUMBER DIRECT SEARCH:")
					print(body_text[:2500])
				except Exception:
					pass

				frappe.throw(
					f"Could not load HP parts page using Product Number: {selected_product_number}"
				)

		parts = hp_parts_scraper.parse_hp_general_parts(driver) or []

		cleaned_parts = []

		for part in parts:
			if not isinstance(part, dict):
				continue

			fru_values = get_part_fru_values(part)
			fru = fru_values[0] if fru_values else clean_text(
				part.get("FRU") or part.get("hp_part_number")
			).upper()

			if not fru:
				continue

			images = get_part_images(part)

			if not images and hasattr(hp_parts_scraper, "get_hp_image_url_from_fru"):
				image_url = hp_parts_scraper.get_hp_image_url_from_fru(fru)
				if image_url:
					images = [image_url]

			row = dict(part)
			row["FRU"] = fru
			row["hp_part_number"] = fru
			row["images"] = images[:5]
			row["image"] = images[0] if len(images) > 0 else ""
			row["image2"] = images[1] if len(images) > 1 else ""
			row["image3"] = images[2] if len(images) > 2 else ""
			row["image_4"] = images[3] if len(images) > 3 else ""
			row["image_5"] = images[4] if len(images) > 4 else ""

			cleaned_parts.append(row)

		return cleaned_parts

	finally:
		try:
			driver.quit()
		except Exception:
			pass

def fetch_dell_or_lenovo_parts_from_hardcoded_url(context):
	brand = normalize_match_text(context.get("brand"))

	if "dell" in brand:
		if not fetch_dell_parts:
			frappe.throw("Dell scraper import failed. Check iw_component.py path.")

		bios_number = get_bios_serial_no_from_erp(context)

		context["bios_number_used_for_scraping"] = bios_number

		return fetch_dell_parts(
			parts_url=None,
			model=None,
			service_tag=None,
			bios_number=bios_number,
		)

	if "lenovo" in brand:
		if not fetch_lenovo_parts:
			frappe.throw("Lenovo scraper import failed. Check lenovo_iw_component.py path.")

		bios_number = get_bios_serial_no_from_erp(context)

		context["bios_number_used_for_scraping"] = bios_number

		return fetch_lenovo_parts(
			parts_url=None,
			bios_number=bios_number,
		)

	if "hp" in brand:
		if not hp_parts_scraper:
			frappe.throw("HP scraper module import failed. Check hp_parts_scraper.py path.")

		return fetch_hp_fru_image_parts_only(context)

	return []


def fetch_fru_and_images_only(context):
	"""
	Dell, Lenovo and HP flow:

	Brand + Model -> ERP Serial No -> BIOS Serial No / Serial Number -> scraper.
	Then match only the required spare part and return its FRU + images.
	"""

	brand = normalize_match_text(context.get("brand"))


	parts = fetch_dell_or_lenovo_parts_from_hardcoded_url(context)

	if not parts:
		return {
			"scraped_fru_number": "",
			"images": [],
			"matched_part": None,
			"bios_number_used": context.get("bios_number_used_for_scraping") or "",
			"message": "No parts returned from scraper",
		}

	best_part = pick_best_external_part(parts, context)

	if not best_part:
		frappe.throw(
			"Could not confidently match ERP item with scraped Dell/Lenovo/HP parts. "
			"Please check Brand, Model, Item Name, Item Group, or BIOS Serial No."
		)

	fru_values = get_part_fru_values(best_part)
	images = get_part_images(best_part)

	return {
		"scraped_fru_number": fru_values[0] if fru_values else "",
		"images": images,
		"matched_part": best_part,
		"bios_number_used": context.get("bios_number_used_for_scraping") or "",
	}

@frappe.whitelist()
def generate_info(docname):
	doc = frappe.get_doc("NJ Spare Part Automation", docname)

	if not doc.item_code:
		frappe.throw("Please select Item Code first.")

	try:
		context = get_item_context(doc.item_code)

		doc.item_name = context.get("item_name")
		doc.item_group = context.get("item_group")
		set_doc_value_if_field_exists(
			doc,
			"generic_item_group",
			context.get("generic_item_group") or context.get("item_group")
		)
		doc.brand = context.get("brand")
		doc.model = context.get("model")
		doc.fru_number = context.get("fru_number")

		# 1. Generate description + specifications
		result, raw_response = call_openai_for_spare_part(context)

		description = result.get("description") or ""
		specifications = result.get("specifications") or []

		if isinstance(specifications, list):
			specifications_text = "\n".join([f"- {s}" for s in specifications])
		else:
			specifications_text = str(specifications or "")

		doc.generated_description = description
		doc.specifications = specifications_text

		# 2. Fetch FRU + images separately
		# Lenovo uses Brand + Model -> ERP Serial No BIOS -> existing Lenovo scraper
		fru_image_result = fetch_fru_and_images_only(context)

		set_doc_value_if_field_exists(
			doc,
			"scraped_fru_number",
			fru_image_result.get("scraped_fru_number")
		)

		for idx, image_url in enumerate(fru_image_result.get("images") or [], start=1):
			set_doc_value_if_field_exists(doc, f"image_{idx}", image_url)

		doc.raw_response = json.dumps({
			"openai_response": raw_response,
			"fru_image_result": fru_image_result,
		}, indent=2)

		doc.status = "Generated"
		doc.error_log = ""

		doc.save(ignore_permissions=True)
		frappe.db.commit()

		return {
			"status": "success",
			"description": description,
			"specifications": specifications_text,
			"scraped_fru_number": fru_image_result.get("scraped_fru_number"),
			"images": fru_image_result.get("images") or [],
			"bios_number_used": fru_image_result.get("bios_number_used") or "",
		}

	except Exception:
		doc.status = "Error"
		doc.error_log = frappe.get_traceback()
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.throw(doc.error_log)