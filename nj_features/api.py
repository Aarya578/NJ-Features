import frappe
from frappe import _

@frappe.whitelist()
def part_qi_check(data):
    """
    --data format:
        {
            "checkName": [
                "Scratches Check",
                "Brand Check",
                "Dent Check"
            ],
            "checkOption": [
                "",
                "",
                ""
            ],
            "serialNo": "NJ861587",
            "inspection_type": "Core IQC",
            "prevPart": "3",
            "currentPart": "4",
            "submit_status": "preview"
        }
    """
    result = {}
    item_group = ''
    activity = ''

    item_code_query = frappe.db.sql("""
        SELECT item_code FROM `tabSerial No` WHERE name = %s
    """, (data['serialNo']), as_dict=True)

    if (data['submit_status']):
        get_prev_detail(data['serialNo'])

    if (data['checkName'] or data['checkOption']):
        save_qi_data(data)

    if item_code_query:
        item_code = item_code_query[0].get('item_code')

        item_group_query = frappe.db.sql("""
            SELECT item_group FROM `tabSerial No Component` WHERE parent = %s AND idx = %s
        """, (data['serialNo'], data['currentPart']))

        if item_group_query:
            item_group = item_group_query[0][0]

            parent_name_query = frappe.db.sql("""
                SELECT name, activity FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s
            """, (item_group, data['inspection_type']))

            if parent_name_query:
                parent_name = parent_name_query[0][0]
                activity = parent_name_query[0][1]

                second_query = frappe.db.sql("""
                    SELECT quality_check, mandatory FROM `tabNj QC Options` WHERE parent = %s ORDER BY idx
                """, (parent_name), as_dict=True)

                for row in second_query:
                    quality_check = row.get('quality_check')
                    mandatory = row.get('mandatory')

                    nj_qc_check_list_query = frappe.db.sql("""
                        SELECT name_of_check, type, diagnostic_type, description FROM `tabNJ QC Check List` WHERE name = %s
                    """, (quality_check), as_dict=True)

                    options_query = frappe.db.sql("""
                        SELECT check_options, score FROM `tabQC Options` WHERE parent = %s AND active=1
                    """, (quality_check), as_dict=True)

                    if nj_qc_check_list_query:
                        nj_qc_check_list = nj_qc_check_list_query[0]
                    else:
                        nj_qc_check_list = {}

                    combined_info = {
                        "name_of_the_check": nj_qc_check_list.get('name_of_check', ''),
                        "type": nj_qc_check_list.get('type', ''),
                        "diagnostic_type": nj_qc_check_list.get('diagnostic_type', ''),
                        "description": nj_qc_check_list.get('description', ''),
                        "mandatory": mandatory,
                        "options": options_query
                    }

                    result[quality_check] = combined_info

    output = {
        "item_code": item_code,
        "part_name": item_group,
        "activity": activity,
        "check_name": result
    }

    return output

@frappe.whitelist()
def get_kb_from_serial_no(serial_no):
    item_code = ''
    serial_no_doc = frappe.db.sql("""SELECT item_code FROM `tabSerial No` WHERE name = %s""", (serial_no), as_dict=1)
    if not serial_no_doc:
        frappe.throw(_("Serial No '{0}' not found.").format(serial_no), title=_("Serial No Not Found"))

    item_doc = frappe.db.sql("""SELECT brand, item_model, item_code FROM `tabItem` WHERE name = %s""", serial_no_doc[0].item_code, as_dict=1)

    conditions = []
    params = []

    if item_doc and item_doc[0].get('item_code'):
        item_code = item_doc[0].get('item_code')

    if item_doc and item_doc[0].get('brand'):
        conditions.append("brand = %s")
        params.append(item_doc[0].brand)

    if item_doc and item_doc[0].get('item_model'):
        conditions.append("model = %s")
        params.append(item_doc[0].item_model)

    if conditions:
        query = f"""
            SELECT attach, description
            FROM `tabKnowledge Base` 
            WHERE {' AND '.join(conditions)} AND active = 1
        """
        kb_doc = frappe.db.sql(query, tuple(params), as_dict=True)
        return {"item_code":item_code, "kb_doc": kb_doc}
    else:
        frappe.throw(_("No valid conditions found for filtering Knowledge Base."), title=_("Invalid Query"))


@frappe.whitelist()
def get_prev_detail(serial_no):
    quality_inspection = frappe.db.get_value('Quality Inspection', {'barcode': serial_no}, ['barcode', 'name', 'status'], as_dict=True)

    if not quality_inspection:
        frappe.throw(_("Quality Inspection with barcode '{0}' not found.").format(serial_no), title=_("Quality Inspection Not Found"))

    nj_readings = frappe.db.sql("""
        SELECT item_group, check_name, options, checks, score, weightage 
        FROM `tabNJ Checks` 
        WHERE parent = %s order by idx
    """, quality_inspection['name'], as_dict=True)

    formatted_result = {
        "quality_inspection": quality_inspection,
        "nj_readings": [
            {
                "part_name": part_name,
                "checks": [
                    {
                        "item_group": reading["item_group"],
                        "check_name": reading["check_name"],
                        "result": reading["options"],
                        "checks": reading["checks"],
                        "score": reading["score"],
                        "weightage": reading["weightage"]
                    } for reading in nj_readings if reading["item_group"] == part_name
                ]
            } for part_name in set(reading["item_group"] for reading in nj_readings)
        ]
    }

    return formatted_result

def save_qi_data(data):
    qi_doc = frappe.get_doc('Quality Inspection', {'barcode': data['serialNo']})

    if not qi_doc:
        qi_doc = frappe.new_doc('Quality Inspection')
        qi_doc.barcode = data['serialNo']
        qi_doc.item_group = data['partName']
        qi_doc.inspection_type = data['inspection_type']

    for i in range(len(data["checkName"])):
        child_table = qi_doc.append("nj_checks", {})
        child_table.item_group = data['partName']
        check_name = data["checkName"][i]
        check_option = data["checkOption"][i]
        child_table.check_name = check_name
        child_table.options = check_option

    qi_doc.save()
    return qi_doc.name



