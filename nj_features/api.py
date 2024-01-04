import json
import frappe
from frappe import _

@frappe.whitelist()
def part_qi_check():
    try:
        result = {}
        count = []
        item_code = ''
        item_group = ''
        activity = ''
        total_part = ''
        qi_name = ''
        submit_status = ''

        
        data_bytes = frappe.request.data
        data_str = data_bytes.decode('utf-8')
        data = json.loads(data_str)
        serial_no = data['serialNo']
        item_code_query = frappe.db.sql(""" SELECT item_code FROM `tabSerial No` WHERE name = %s """, (serial_no), as_dict=True)

        if 'submitStatus' in data:
            submit_status = data['submitStatus']
        # Serial number and qi_name is empty, but QI data for the serial number is in draft (docstatus = 0) then return the current data with a message saying retrieve existing data
        # check for checkname[0] hsa to have data then do a save qi data
        #save prevPart data

        if 'checkName' in data:
            if data['prevPart'] == "":
                data['prevPart'] = 1
            qi_name = save_qi_data(data)

        #submit qi_doc
        if (data['submitStatus'].lower() == 'accepted' or data['submitStatus'].lower() == 'rejected'):
            qi_doc = frappe.get_doc('Quality Inspection', qi_name)
            if qi_doc.docstatus == 0:
                qi_doc.submit()
                return f"{data['inspection_type']} has been {data['submitStatus']} for the serial no: {data['serialNo']}"

        if 'currentPart' in data:
            item_code = item_code_query[0].get('item_code')

            item_group_query = frappe.db.sql("""
                SELECT item_group FROM `tabSerial No Component` WHERE parent = %s AND idx = %s
            """, (serial_no, data['currentPart']))
            
            if item_group_query:
                part_name = item_group_query[0][0]
                item_group = part_name

                parent_name_query = frappe.db.sql("""
                    SELECT name, activity FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s
                """, (item_group, data['inspection_type']))
                
                if parent_name_query:
                    parent_name = parent_name_query[0][0]
                    activity = parent_name_query[0][1]

                    item_group_list = frappe.db.sql("""SELECT DISTINCT item_group FROM `tabSerial No Component` WHERE parent = %s""", (serial_no))
                    for x in item_group_list:
                        total_part_query = frappe.db.sql("""SELECT count(*) FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s""", 
                        (x, data['inspection_type']))
                        count.append(total_part_query[0][0])
                    print(f"{count}")
                    
                    
                    second_query = frappe.db.sql("""SELECT quality_check, mandatory FROM `tabNj QC Options` WHERE parent = %s ORDER BY idx""", 
                    (parent_name), as_dict=True)

                    for row in second_query:
                        quality_check = row.get('quality_check')
                        mandatory = row.get('mandatory')

                        nj_qc_check_list_query = frappe.db.sql("""
                            SELECT name_of_check, type, diagnostic_type, description, name FROM `tabNJ QC Check List` WHERE name = %s
                        """, (quality_check), as_dict=True)

                        options_query = frappe.db.sql("""
                            SELECT check_options, score FROM `tabQC Options` WHERE parent = %s AND active=1
                        """, (quality_check), as_dict=True)

                        if nj_qc_check_list_query:
                            nj_qc_check_list = nj_qc_check_list_query[0]
                        else:
                            nj_qc_check_list = {}

                        name = nj_qc_check_list.get('name', '')
                        selected = frappe.db.sql(""" SELECT options FROM `tabNJ Checks` WHERE 
                            item_group = %s AND check_name = %s AND parent = %s ORDER BY idx""",
                            (part_name, name, qi_name), as_dict=True)

                        combined_info = {
                            "name_of_the_check": nj_qc_check_list.get('name_of_check', ''),
                            "type": nj_qc_check_list.get('type', ''),
                            "diagnostic_type": nj_qc_check_list.get('diagnostic_type', ''),
                            "description": nj_qc_check_list.get('description', ''),
                            "mandatory": mandatory,
                            "selected": selected[0]['options'] if selected else '',
                            "options": options_query
                        }

                        result[quality_check] = combined_info

        nj_readings = []
        if data['submitStatus'].lower() == 'preview':
            nj_readings1 = get_prev_detail(data)
            nj_readings = nj_readings1["nj_readings"]

        output = {
            "item_code": item_code,
            "part_name": part_name,
            "activity": activity,
            "total_part": len(count),
            "qi_name": qi_name,
            "submit_status": submit_status,
            "check_name": result,
            "nj_readings": nj_readings
        }

        return output

    except Exception as e:
        print(f"An error occurred: {e}")
        return {"success": False, "message": f"Error: {str(e)}"}

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


def get_prev_detail(data):
    #use qi_name to get the qi information
    if 'qi_name' in data:
        qi_name = data['qi_name']

    nj_readings = frappe.db.sql("""
        SELECT item_group, check_name, options, checks, score, weightage, idx
        FROM `tabNJ Checks` 
        WHERE parent = %s ORDER BY idx asc
    """, qi_name, as_dict=True)

    formatted_result = {
        "nj_readings": [
            {
                "part_name": part_name,
                "part_idx": idx,
                "checks": [
                    {
                        "check_name": reading["check_name"],
                        "result": reading["options"],
                        "score": reading["score"],
                        "weightage": reading["weightage"]
                    } for reading in nj_readings if reading["item_group"] == part_name
                ]
            } for part_name, idx in set((reading["item_group"], reading["idx"]) for reading in nj_readings)
        ]
    }

    return formatted_result

def save_qi_data(data):
    qi_name = ''
    # qi_name as a primary key - Done
    qi_doc = ''
    # Check if 'qi_name' exists in data
    if 'qi_name' in data:
        qi_name = data["qi_name"]

    if qi_name != '':
        qi_doc = frappe.get_doc('Quality Inspection', data['qi_name'])

    # not available -> insert - Done
    else:
        serial_no_doc = frappe.db.sql(""" SELECT item_code, item_group, warehouse, item_name FROM `tabSerial No` WHERE name = %s""", (data['serialNo']))
        qi_doc = frappe.new_doc('Quality Inspection')
        qi_doc.barcode = data['serialNo']
        qi_doc.bios_serial_number = data['serialNo']
        qi_doc.inspection_type = data['inspection_type']
        qi_doc.machine_made_by = 'itsupport@newjaisa.com'
        qi_doc.inspected_by = 'itsupport@newjaisa.com'
        qi_doc.reference_name = 'PREC-06175'
        if serial_no_doc:
            qi_doc.item_code = serial_no_doc[0][0]
            qi_doc.item_group = serial_no_doc[0][1]
            qi_doc.current_warehouse = serial_no_doc[0][2]
            qi_doc.item_name = serial_no_doc[0][3]

    # update checks and their values
    item_group_query = frappe.db.sql(""" SELECT item_group FROM `tabSerial No Component` WHERE parent = %s AND idx = %s""", 
    (data['serialNo'], data['prevPart']))

    if item_group_query:
        item_group = item_group_query[0][0]

    for i in range(len(data["checkName"])):
        check_name = data["checkName"][i]
        check_option = data["checkOption"][i]

        existing_child = frappe.db.sql(""" SELECT item_group, check_name, options, name FROM `tabNJ Checks` WHERE item_group = %s AND check_name = %s AND options = %s AND parent = %s ORDER BY idx""",
        (item_group, check_name, check_option, qi_name))

        if existing_child:
            frappe.db.sql("""UPDATE `tabNJ Checks` SET options = %s WHERE name = %s """, 
            (check_option, existing_child[0][3]))
        else:
            child_table = qi_doc.append("nj_quality_checks", {})
            child_table.item_group = item_group
            child_table.check_name = check_name
            child_table.options = check_option

    qi_doc.save()

    return qi_doc.name
