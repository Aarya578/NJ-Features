# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt
import frappe
from erpnext.quality_management.doctype.quality_review.quality_review import QualityReview
from nj_p1_features.nj_p1_features.doctype.nj_quality_inspection.nj_qi_non_compliance import raise_nc_for_not_following_the_process

logger = frappe.logger("PayULogger", allow_site=True, file_count=1)

class CustomQualityReview(QualityReview):
	def validate(self):
		# Call the parent class's validate
		super().validate()
	def on_submit(self):
		# Call the parent class's on_submit
		raise_nc_for_not_following_the_process(self)


@frappe.whitelist()
def get_quality_procedure_details(quality_procedure_name,review_type,severity_level=None):
	logger.info(f"quality_procedure_name: {quality_procedure_name}, review_type: {review_type}, severity_level: {severity_level}")
	data = []
	if review_type == 'Severity' and severity_level:
		logger.info(f"severity_level: {severity_level}")
		query = """Select * from `tabQuality Processes` where parent = '{0}' and severity = '{1}'""".format(quality_procedure_name,severity_level)
		data = frappe.db.sql(query,as_dict=1)
	if review_type == 'Full Review':
		logger.info(f"Full Review")
		query = """Select * from `tabQuality Processes` where parent = '{0}'""".format(quality_procedure_name)
		data = frappe.db.sql(query,as_dict=1)
	logger.info(f"data: {data}")
	return data