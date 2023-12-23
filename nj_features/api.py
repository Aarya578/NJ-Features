import frappe
from frappe import _

@frappe.whitelist()
def part_qi_check(serial_no, idx, inspection_type):
    result = {}
    item_group_query = frappe.db.sql("""
        SELECT item_group FROM `tabSerial No Component` WHERE parent = %s AND idx = %s
    """, (serial_no, idx))
    
    if item_group_query:
        item_group = item_group_query[0][0]
        
        parent_name = frappe.db.sql("""
            SELECT name FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s;
        """, (item_group, inspection_type))

        if parent_name:
            p1 = parent_name[0][0]

            second_query = frappe.db.sql("""
                SELECT * FROM `tabNj QC Options` WHERE parent = %s;
            """, (p1), as_dict=True)

            for row in second_query:
                quality_check = row.get('quality_check')

                third_query = frappe.db.sql("""
                    SELECT check_options, active, score FROM `tabQC Options` WHERE parent = %s;
                """, (quality_check), as_dict=True)
                
                result[quality_check] = third_query

    return {item_group: result}