import frappe
from frappe import _

@frappe.whitelist()
def part_qi_check():
    result = {}

    first_query = """
        SELECT * FROM `tabNj QC Options` WHERE parent = 'core IQC-laptop Body C' ORDER BY idx;
    """

    first_result = frappe.db.sql(first_query, as_dict=True)

    for row in first_result:
        quality_check = row.get('quality_check')

        second_query = """
            SELECT check_options, active, score FROM `tabQC Options` WHERE parent = %s;
        """
        
        second_result = frappe.db.sql(second_query, quality_check, as_dict=True)
        
        result[quality_check] = second_result

    return {"result": result}
