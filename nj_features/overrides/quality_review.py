# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class QualityReview(Document):
	pass

@frappe.whitelist()
def get_quality_procedure_details(quality_procedure_name,review_type,severity_level):
	print('get_quality_procedure_data-----------',quality_procedure_name,review_type,severity_level)
	if review_type == 'Severity' and severity_level:
		query = """Select * from `tabQuality Processes` where parent = '{0}' and severity = '{1}'""".format(quality_procedure_name,severity_level)
		data = frappe.db.sql(query,as_dict=1)
	if review_type == 'Full Review':
		query = """Select * from `tabQuality Processes` where parent = '{0}'""".format(quality_procedure_name)
		data = frappe.db.sql(query,as_dict=1)
	return data