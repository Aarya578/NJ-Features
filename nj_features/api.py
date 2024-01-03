import json
import frappe
from frappe import _

@frappe.whitelist()
def part_qi_check():
    try:
        result = {}
        item_code = ''
        item_group = ''
        activity = ''
        total_part = ''
        qi_name = ''
        
        data_bytes = frappe.request.data
        data_str = data_bytes.decode('utf-8')
        data = json.loads(data_str)
        serial_no = data['serialNo']
        print(f"data: {data}")
        item_code_query = frappe.db.sql(""" SELECT item_code FROM `tabSerial No` WHERE name = %s """, (serial_no), as_dict=True)

        # Serial number and qi_name is empty, but QI data for the serial number is in draft (docstatus = 0) then return the current data with a message saying retrieve existing data
        # check for checkname[0] hsa to have data then do a save qi data
        
        if data['submitStatus'].lower() == 'preview': return get_prev_detail(data)

        #save prevPart data
        if 'checkName' in data:
            if data['prevPart'] == "":
                data['prevPart'] = 1
            qi_name = save_qi_data(data)

        #submit qi_doc
        # if (data['submitStatus'].lower() == 'accepted' or 'rejected'):
        #     qi_doc = frappe.get_doc('Quality Inspection', qi_name)
        #     if qi_doc.docstatus == 0:
        #         qi_doc.submit()
        #         return f"{data['inspection_type']} has been {data['submitStatus']} for the serial no: {data['serialNo']}"

        if item_code_query and data['currentPart'] or data['submitStatus'].lower() == 'inprogress':
            print(f"inprogress")
            item_code = item_code_query[0].get('item_code')

            item_group_query = frappe.db.sql("""
                SELECT item_group FROM `tabSerial No Component` WHERE parent = %s AND idx = %s
            """, (serial_no, data['currentPart']))

            if item_group_query:
                item_group = item_group_query[0][0]

                parent_name_query = frappe.db.sql("""
                    SELECT name, activity, count(*) as total_part FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s
                """, (item_group, data['inspection_type']))
                print(f"parent_name_query: {parent_name_query}")
                if parent_name_query:
                    parent_name = parent_name_query[0][0]
                    activity = parent_name_query[0][1]
                    item_group_list = frappe.db.sql("""SELECT item_group FROM `tabSerial No Component` WHERE parent = %s order by idx""", (serial_no)) 
                    if item_group_list:
                        item_group = item_group_list[0][0]

                        total_part = frappe.db.sql("""
                            SELECT name, count(*) as total_part 
                            FROM `tabNJ Quality Checks` 
                            WHERE item_group = %s AND inspection_type = %s
                        """, (item_group, data['inspection_type']))
                    else:
                        total_part = []

                    print(f"total_part: {total_part}")
                    
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
            "total_part": total_part[0][1],
            "qi_name": qi_name,
            "check_name": result
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
    qi_name = data['qi_name']
    print(f"qi_name: {qi_name} for prev detail")
    if not qi_name:
        frappe.throw(_("Quality Inspection with barcode '{0}' not found.").format(data['serial_no']), title=_("Quality Inspection Not Found"))

    nj_readings = frappe.db.sql("""
        SELECT item_group, check_name, options, checks, score, weightage 
        FROM `tabNJ Checks` 
        WHERE parent = %s order by idx
    """, qi_name, as_dict=True)
    status = frappe.db.get_value('Quality Inspection', qi_name, 'qi_status')
    formatted_result = {
        "serial_no": data['serial_no'],
        "qi_name": qi_name,
        "status": status,
        "nj_readings": [
            {
                "part_name": part_name,
                "checks": [
                    {
                        "check_name": reading["check_name"],
                        "result": reading["options"],
                        "score": reading["score"],
                        "weightage": reading["weightage"]
                    } for reading in nj_readings if reading["item_group"] == part_name
                ]
            } for part_name in set(reading["item_group"] for reading in nj_readings)
        ]
    }

    return formatted_result


def save_qi_data(data):
    # qi_name as a primary key - Done
    print(f"data from save_qi_data: {data}")
    qi_doc = ''
    # Check if 'qi_name' exists in data
    if 'qi_name' in data:
        qi_doc = frappe.get_doc('Quality Inspection', data['qi_name'])

    print(f"qi_doc: {qi_doc} from qi_name")

    # not available -> insert - Done
    if not 'qi_name' in data:
        item_code = frappe.db.sql(""" SELECT item_code FROM `tabSerial No` WHERE name = %s""", (data['serialNo']))
        print(item_code[0][0])
        qi_doc = frappe.new_doc('Quality Inspection')
        qi_doc.barcode = data['serialNo']
        qi_doc.bios_serial_number = data['serialNo']
        qi_doc.inspection_type = data['inspection_type']
        qi_doc.machine_made_by = 'itsupport@newjaisa.com'
        qi_doc.inspected_by = 'itsupport@newjaisa.com'
        qi_doc.reference_name = 'MAT-PRE-2023-00001'
        if item_code:
            qi_doc.item_code = item_code[0][0]
        print(f"new qi_doc: {qi_doc}")

    # update checks and their values
    item_group = frappe.db.sql(""" SELECT item_group FROM `tabSerial No Component` WHERE parent = %s AND idx = %s
    """, (data['serialNo'], data['prevPart']))
    print(f"item_group: {item_group}")
    for i in range(len(data["checkName"])):
        check_name = data["checkName"][i]
        check_option = data["checkOption"][i]

        existing_entry = next(
            (entry for entry in qi_doc.nj_quality_checks if entry.item_group == item_group[0][0] and entry.check_name == check_name), None)
        print(f"existing_entry: {existing_entry}")
        if existing_entry:
            # If the combination exists, update the check_option
            existing_entry.options = check_option
        else:
            # If the combination does not exist, append a new record
            qi_doc.append("nj_quality_checks", {'item_group': item_group[0][0], 'check_name': check_name, 'options': check_option})
        if qi_doc.docstatus == 0:
            qi_doc.save()
        else: return f"Not able to save {qi_doc.name}"

    return qi_doc.name
