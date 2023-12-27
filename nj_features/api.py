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
            SELECT name, activity FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s;
        """, (item_group, inspection_type))

        if parent_name:
            p1 = parent_name[0][0]
            activity = parent_name[0][1]

            second_query = frappe.db.sql("""
                SELECT quality_check FROM `tabNj QC Options` WHERE parent = %s order by idx;
            """, (p1), as_dict=True)
            
            for row in second_query:
                quality_check = row.get('quality_check')

                nj_qc_check_list = frappe.db.sql("""SELECT name_of_check, type, diagnostic_type, description FROM `tabNJ QC Check List` WHERE name = %s
                """, (quality_check), as_dict=True)
                
                if nj_qc_check_list:
                    combined_info = {
                        "name_of_the_check": nj_qc_check_list[0].get('name_of_check'),
                        "type": nj_qc_check_list[0].get('type'),
                        "diagnostic_type": nj_qc_check_list[0].get('diagnostic_type'),
                        "description": nj_qc_check_list[0].get('description'),
                        "options": frappe.db.sql("""
                            SELECT check_options, score FROM `tabQC Options` WHERE parent = %s AND active=1;
                        """, (quality_check), as_dict=True)
                    }
                else:
                    combined_info = {}
                result[quality_check] = combined_info

    output = {
            "part_name": item_group,
            "activity": activity,
            "check_name": result
        }
    return output

@frappe.whitelist()
def get_kb_from_serial_no(serial_no):
    serial_no_doc = frappe.db.sql("""SELECT item_code FROM `tabSerial No` where name = %s""", (serial_no), as_dict=1)
    if not serial_no_doc:
        frappe.throw(_("Serial No '{0}' not found.").format(serial_no), title=_("Serial No Not Found"))
    item_doc = frappe.db.sql("""SELECT brand, item_model from `tabItem` WHERE name = %s""", serial_no_doc[0].item_code, as_dict=1)
    conditions = []
    params = []

    if item_doc and item_doc[0].get('brand'):
        conditions.append("brand = %s")
        params.append(item_doc[0].brand)

    if item_doc and item_doc[0].get('item_model'):
        conditions.append("model = %s")
        params.append(item_doc[0].item_model)

    if item_doc and item_doc[0].get('active'):
        conditions.append("active = 1")

    query = """
        SELECT attach, description 
        FROM `tabKnowledge Base` 
        WHERE {} 
    """.format(" OR ".join(conditions))

    kb_doc = frappe.db.sql(query, tuple(params), as_dict=True)
    return kb_doc