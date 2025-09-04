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
        # Call the parent class's on_submity
        try:
            raise_nc_for_not_following_the_process(self)
        except Exception as e:
            frappe.throw(str(e))


@frappe.whitelist()
def get_quality_procedure_details(quality_procedure_name,review_type,severity_level=None):
    data = []
    if review_type == 'Severity' and severity_level:
        query = """Select * from `tabQuality Processes` where parent = '{0}' and severity = '{1}' order by idx DESC""".format(quality_procedure_name,severity_level)
        data = frappe.db.sql(query,as_dict=1)
    if review_type == 'Full Review':
        query = """Select * from `tabQuality Processes` where parent = '{0}' order by idx DESC""".format(quality_procedure_name)
        data = frappe.db.sql(query,as_dict=1)
    return data

@frappe.whitelist()
def get_kms_data(item_group, serial_no, department, part=None):
    model = frappe.db.get_value("Serial No", {"name": serial_no}, "model")
    brand = frappe.db.get_value("Serial No", {"name": serial_no}, "brand")

    html_content = None
    if model and brand:
        query = """
            SELECT 
                kn.html_content AS html_content
            FROM 
                `tabKnowledge Base` kn
            JOIN 
                `tabBrand Multiselect` Bn ON kn.name = Bn.parent
            JOIN 
                `tabKnowledge Base Models` Knb ON kn.name = Knb.parent
            JOIN 
                `tabPart Multiselect` Pm ON kn.name = Pm.parent
            JOIN
                `tabDepartment Multi Models` dp ON kn.name = dp.parent
            WHERE 
                Bn.brand = %s
                AND Knb.models = %s
                AND Pm.part = %s
                AND dp.department = %s
            LIMIT 1
        """
        html_content = frappe.db.sql(
            query, (brand, model,item_group,department), as_dict=True
        )

        if html_content:
            html_content = html_content[0]["html_content"]
            return html_content
    return ""
    
