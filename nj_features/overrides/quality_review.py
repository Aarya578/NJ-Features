# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt
import frappe
from erpnext.quality_management.doctype.quality_review.quality_review import QualityReview
from nj_p1_features.nj_p1_features.doctype.nj_quality_inspection.nj_qi_non_compliance import raise_nc_for_not_following_the_process

class CustomQualityReview(QualityReview):
	def validate(self):
		# Call the parent class's validate
		super().validate()
	def on_submit(self):
		# Call the parent class's on_submit
		raise_nc_for_not_following_the_process(self)


@frappe.whitelist()
def get_quality_procedure_details(quality_procedure_name,review_type,severity_level):
	if review_type == 'Severity' and severity_level:
		query = """Select * from `tabQuality Processes` where parent = '{0}' and severity = '{1}'""".format(quality_procedure_name,severity_level)
		data = frappe.db.sql(query,as_dict=1)
	if review_type == 'Full Review':
		query = """Select * from `tabQuality Processes` where parent = '{0}'""".format(quality_procedure_name)
		data = frappe.db.sql(query,as_dict=1)
	return data