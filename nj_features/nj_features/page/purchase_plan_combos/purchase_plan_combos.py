# Copyright (c) 2026, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import re
from collections import Counter

import frappe


CORE_ITEM_GROUPS = (
	"Laptops", "Chromebooks", "Macbooks", "Desktops",
	"Chromeboxes", "Full Set Desktops", "AIO",
)


def _text(value):
	return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def _is_any(value):
	return _text(value) in {"", "ANY", "ALL"}


def _number(value):
	match = re.search(r"\d+(?:\.\d+)?", _text(value))
	return float(match.group()) if match else None


def _price_distance(price_rule, price):
	rule = _text(price_rule).replace("₹", "").replace("K", "")
	if _is_any(rule) or price is None:
		return 0
	values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", rule)]
	if not values:
		return 0
	price_k = price / 1000
	if "+" in rule:
		return max(values[0] - price_k, 0)
	if len(values) > 1:
		low, high = min(values[:2]), max(values[:2])
		if low <= price_k <= high:
			return 0
		return min(abs(price_k - low), abs(price_k - high))
	return abs(price_k - values[0])


def _cpu_details(value):
	value = _text(value).replace("CORE ", "")
	family_match = re.search(r"\b(I[3579]|RYZEN\s*[3579]|M[1-9])\b", value)
	gen_match = re.search(r"(\d+)(?:ST|ND|RD|TH)?\s+GEN", value)
	if not gen_match:
		gen_match = re.search(r"\bI[3579]\s*[- ]\s*(\d+)(?:ST|ND|RD|TH)?\b", value)
	return (
		re.sub(r"\s+", " ", family_match.group(1)).strip() if family_match else "",
		int(gen_match.group(1)) if gen_match else None,
	)


def _processor_matches(rule, processor):
	if _is_any(rule):
		return True
	rule = _text(rule).replace("CORE ", "").replace(" GEN", "")
	family, generation = _cpu_details(processor)
	if not family:
		return False
	if family.startswith("M"):
		cpu_number = int(family[1:])
		rule_number = _number(rule)
		if not rule_number or not rule.startswith("M"):
			return False
		if "+" in rule:
			return cpu_number >= rule_number
		if "LESS" in rule or "BELOW" in rule:
			return cpu_number <= rule_number
		return cpu_number == rule_number

	rule_families = set(re.findall(r"\bI[3579]\b|\bRYZEN\s*[3579]\b", rule))
	if rule_families and family not in rule_families:
		return False
	if generation is None:
		return False
	numbers = [int(value) for value in re.findall(r"\d+", re.sub(r"\bI[3579]\b|\bRYZEN\s*[3579]\b", "", rule))]
	if not numbers:
		return True
	if "BELOW" in rule or "LESS" in rule:
		return generation <= numbers[0]
	if "ABOVE" in rule or "+" in rule:
		return generation >= numbers[0]
	if " TO " in rule and len(numbers) > 1:
		return min(numbers[:2]) <= generation <= max(numbers[:2])
	return generation in numbers


def _simple_match(rule, value, contains=False):
	if _is_any(rule):
		return True
	rule, value = _text(rule), _text(value)
	return rule in value if contains else rule == value


def _size_matches(rule, value):
	if _is_any(rule):
		return True
	rule_number, value_number = _number(rule), _number(value)
	if rule_number is None or value_number is None:
		return False
	rule_text = _text(rule)
	if "BELOW" in rule_text or "LESS" in rule_text:
		return value_number <= rule_number
	if "ABOVE" in rule_text or "+" in rule_text:
		return value_number >= rule_number
	return abs(value_number - rule_number) < 0.11


def _infer_touch(model):
	model = _text(model)
	keywords = ("TOUCH", "X360", "YOGA", "2 IN 1", "2-IN-1", "SPECTRE", "FLIP")
	return "TOUCH" if any(keyword in model for keyword in keywords) else "NON TOUCH"


def _infer_usage(model):
	model = _text(model)
	if any(keyword in model for keyword in ("GAMING", "VICTUS", "LEGION", "LOQ", "TUF", "PREDATOR")):
		return "GAMING"
	if any(keyword in model for keyword in ("WORKSTATION", "ZBOOK", "PRECISION", "THINKSTATION")):
		return "WORKSTATION"
	return "GENERAL"


def _specificity(row):
	return sum(not _is_any(row.get(field)) for field in ("brand", "model", "processor", "touch", "usage", "size"))


def _matches(row, stock):
	return (
		_simple_match(row.get("brand"), stock.get("brand"))
		and _simple_match(row.get("model"), stock.get("model"), contains=True)
		and _processor_matches(row.get("processor"), stock.get("processor"))
		and _simple_match(row.get("touch"), stock.get("touch"))
		and _simple_match(row.get("usage"), stock.get("usage"))
		and _size_matches(row.get("size"), stock.get("display_size"))
	)


def _format_processor(value):
	return re.sub(r"\b(CORE|GEN)\b", "", _text(value)).replace("  ", " ").strip(" -")


def _format_counter(counter, formatter=lambda value: value):
	values = [(label, count) for label, count in counter.items() if count > 5]
	values.sort(key=lambda item: (-item[1], item[0]))
	return ", ".join(f"{formatter(label)} ({count})" for label, count in values)


def _get_active_stock():
	groups = ", ".join(["%s"] * len(CORE_ITEM_GROUPS))
	return frappe.db.sql(
		f"""
			SELECT sn.item_code, COUNT(sn.name) AS qty,
				iw.brand, iw.model,
				processor.attribute_value AS processor,
				(
					SELECT display.attribute_value
					FROM `tabItems Attribute` display
					WHERE display.parent = iw.name AND display.item_attribute = 'Display Size'
					ORDER BY display.idx
					LIMIT 1
				) AS display_size,
				(
					SELECT soi.base_rate
					FROM `tabSales Order Item` soi
					INNER JOIN `tabSales Order` so ON so.name = soi.parent
					WHERE so.docstatus = 1 AND soi.item_code = sn.item_code AND soi.base_rate > 0
					ORDER BY so.transaction_date DESC, so.creation DESC
					LIMIT 1
				) * 1.18 AS latest_price
			FROM `tabSerial No` sn
			INNER JOIN `tabItem` item ON item.name = sn.item_code
			INNER JOIN `tabItem Wizards` iw
				ON iw.name = (
					SELECT wizard.name
					FROM `tabItem Wizards` wizard
					WHERE wizard.item_template = item.variant_of AND wizard.docstatus = 1
					ORDER BY wizard.modified DESC
					LIMIT 1
				)
			LEFT JOIN `tabItem Variant Attribute` processor
				ON processor.parent = sn.item_code AND processor.attribute IN ('Processor Type', 'Processor Type1')
			WHERE sn.status = 'Active' AND sn.item_group IN ({groups})
			GROUP BY sn.item_code, iw.name, iw.brand, iw.model, processor.attribute_value
		""",
		CORE_ITEM_GROUPS,
		as_dict=True,
	)


def _add_sih_summaries(rows):
	processor_counts = [Counter() for _row in rows]
	model_counts = [Counter() for _row in rows]
	for stock in _get_active_stock():
		stock["touch"] = _infer_touch(stock.model)
		stock["usage"] = _infer_usage(stock.model)
		candidates = [(index, row) for index, row in enumerate(rows) if _matches(row, stock)]
		if not candidates:
			continue
		index, _row = min(
			candidates,
			key=lambda candidate: (
				-_specificity(candidate[1]),
				_price_distance(candidate[1].get("price"), stock.latest_price),
				candidate[0],
			),
		)
		qty = int(stock.qty or 0)
		processor_counts[index][_text(stock.processor)] += qty
		model_counts[index][_text(f"{stock.brand} {stock.model}")] += qty

	for index, row in enumerate(rows):
		row["processors_sih"] = _format_counter(processor_counts[index], _format_processor)
		row["models_sih"] = _format_counter(model_counts[index])


@frappe.whitelist()
def get_product_sufficiency_plan():
	"""Return configured plan rows with active-stock J/K summaries."""
	rows = frappe.get_all(
		"Product Sufficiency Plan",
		filters={
			"parent": "Logistics Settings",
			"parenttype": "Logistics Settings",
			"parentfield": "product_sufficiency_plan",
		},
		fields=["idx", "price", "brand", "model", "processor", "touch", "usage", "size", "example_models"],
		order_by="idx asc",
	)
	_add_sih_summaries(rows)
	return rows
