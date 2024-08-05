import json
import frappe
from frappe import _
from frappe.model.document import Document


@frappe.whitelist()
def process_stock_movement_data():
    pass