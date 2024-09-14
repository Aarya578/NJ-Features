# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

class DispatchSecurityCheckpoints(Document):
	pass

@frappe.whitelist()
def scan_serial_no_data():
