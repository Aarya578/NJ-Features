# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt
import os
import pyqrcode
import frappe
from frappe.model.document import Document

class LaptopBox(Document):
	pass

@frappe.whitelist()
def get_item_attribute_laptop_value(parent, attribute_value):
	allowed_parents = {
		"Processor Type",
		"Processor Type1",
		"RAM",
		"RAM Capacity",
		"Storage Capacity",
		"Model",
	}

	if parent not in allowed_parents:
		frappe.throw("Invalid Item Attribute for Laptop MRP calculation.")

	return frappe.db.get_value(
		"Item Attribute Value",
		{
			"parent": parent,
			"attribute_value": attribute_value,
		},
		"laptop_value",
	)

@frappe.whitelist()
def printing_barcode(doc, method):
	encoded_data = doc.barcode
	format = 'png'

	url = pyqrcode.create(encoded_data)
	filename = f"{encoded_data}.{format}"

	base_directory = frappe.get_site_path("public", "files")
	file_path = os.path.join(base_directory, filename)

	print(f"Base directory path: {os.path.abspath(base_directory)}")

	absolute_path = os.path.abspath(file_path)

	if os.path.exists(file_path):
		print(f"File already exists at: {absolute_path}")
	else:
		url.png(file_path, scale=8)
		print(f"QR code saved at: {absolute_path}")
