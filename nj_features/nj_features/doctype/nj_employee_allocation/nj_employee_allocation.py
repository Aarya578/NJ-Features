# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

from frappe import _
import frappe
from frappe.model.document import Document

class NJEmployeeAllocation(Document):
	user = frappe.get_doc('User', frappe.session.user)