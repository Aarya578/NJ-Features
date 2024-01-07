import json
import frappe
from frappe import _

@frappe.whitelist()
def part_qi_check():
    try:
        result = {}
        count = []
        item_code = ''
        activity = ''
        qi_name = ''
        part_name = ''
        submit_status = ''

        
        data_bytes = frappe.request.data
        data_str = data_bytes.decode('utf-8')
        data = json.loads(data_str)
        item_code = frappe.db.get_value('Serial No', {'name': data['serialNo']}, 'item_code')
        print(f"item_code: {item_code}")

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
            qi_doc = frappe.get_doc('Quality Inspection', data['qi_name'])
            if qi_doc.docstatus == 0:
                qi_doc.submit()

        if 'currentPart' in data:
            result, part_name = show_current_part_data(data, item_code, result, count)
            print(f"part_name : {part_name}")

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
        print(f"An error occurred in part_qi_check: {e}")
        return {"success": False, "message": f"Error: {str(e)}"}


def show_current_part_data(data, item_code, result, count):
    global part_name, activity
    serial_no = data['serialNo']

    # Get Parts from Serial NO
    item_group_query = frappe.db.get_value('Serial No Component', {'parent': serial_no, 'idx': data['currentPart']}, 'item_group')

    # Get Parts from Item Wizard
    item_group_wizard = frappe.db.get_value('Item', {'name': item_code}, 'reference')
    part_frm_itw = frappe.db.get_value('Component', {'parent': item_group_wizard, 'idx': data['currentPart']}, 'component_type')

    if item_group_query:
        result = get_current_part_data(data, result, count, item_group_query)
        part_name = item_group_query
    elif part_frm_itw:
        result = get_current_part_data(data, result, count, part_frm_itw)
        part_name = part_frm_itw
    else:
        part_name = None
    print(f"part_name: {part_name}")
    return result, part_name



def get_current_part_data(data, result, count, part_name):
    item_group = part_name

    parent_name_query = frappe.db.sql("""
        SELECT name, activity FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s
    """, (item_group, data['inspection_type']))

    if parent_name_query:
        parent_name = parent_name_query[0][0]
        activity = parent_name_query[0][1]

        item_group_list = frappe.db.sql("""SELECT DISTINCT item_group FROM `tabSerial No Component` WHERE parent = %s""", (data['serialNo']), as_dict=1)
        print(f"item_group_list: {item_group_list}")
        for x in item_group_list:
            total_part_query = frappe.db.sql("""SELECT count(*) FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s""", 
            (x.item_group, data['inspection_type']))
            if total_part_query[0][0] == 1:
                count.append(total_part_query[0][0])

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
                (part_name, name, data['qi_name']), as_dict=True)

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

    return result



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
    item_group = ''
    # qi_name as a primary key, if check is null set '' - Done
    qi_doc = ''
    # Check if 'qi_name' exists in data
    if 'qi_name' in data:
        qi_name = data["qi_name"]
    if qi_name != '':
        qi_doc = frappe.get_doc('Quality Inspection', data['qi_name'])

    # not available -> insert - Done
    else:
        serial_no_doc = frappe.db.sql("""SELECT item_code, item_group, warehouse, item_name FROM `tabSerial No` WHERE name = %s""", (data['serialNo']))
        draft_qi = frappe.db.sql("""SELECT name FROM `tabQuality Inspection` WHERE barcode = %s and docstatus = 0 ORDER BY creation desc""", (data['serialNo']))
        if draft_qi:
            qi_doc = frappe.get_doc('Quality Inspection', draft_qi[0][0])
            qi_name = qi_doc.name

        else:    
            qi_doc = frappe.new_doc('Quality Inspection')
            qi_doc.barcode = data['serialNo']
            qi_doc.bios_serial_number = data['serialNo']
            qi_doc.inspection_type = data['inspection_type']
            qi_doc.machine_made_by = 'itsupport@newjaisa.com'
            qi_doc.inspected_by = 'itsupport@newjaisa.com'
            qi_doc.reference_name = 'PREC-06175'
            qi_name = qi_doc.name
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
        if check_option is not None:
            existing_child = frappe.db.sql(""" SELECT item_group, check_name, options, name FROM `tabNJ Checks` WHERE item_group = %s AND check_name = %s AND parent = %s ORDER BY idx""",
            (item_group, check_name, qi_doc.name))
            if existing_child:
                try:
                    demo = frappe.db.sql("""
                        UPDATE `tabNJ Checks` 
                        SET options = %s 
                        WHERE name = %s
                    """, (check_option, existing_child[0][3]))
                    frappe.db.commit()
                    print(f"Updated record: {existing_child[0][3]} - options: {check_option}, {demo}")
                except Exception as e:
                    frappe.db.rollback()
                    print(f"Error updating record: {existing_child[0][3]} - {e}")
            else:
                child_table = qi_doc.append("nj_quality_checks", {})
                child_table.item_group = item_group
                child_table.check_name = check_name
                child_table.options = check_option

    qi_doc.save()

    return qi_doc.name



@frappe.whitelist()
def get_kb_from_serial_no(serial_no, action_type=None, part_name=None):
    item_code = ''
    item_code = frappe.db.get_value('Serial No', {'name': serial_no}, 'item_code')
    if not item_code:
        frappe.throw(_("Serial No '{0}' not found.").format(serial_no), title=_("Serial No Not Found"))

    item_doc = frappe.db.get_value('Item', {'name': item_code}, ['brand','item_model'])
    
    item_group_list = item_group_list_from_itw(serial_no)
    part_list = []
    for item_group in item_group_list:
        part_list.append(item_group['item_group'])
   
    conditions = []
    params = []
    print(f"item_group_list: {item_group_list}")
    if item_doc and item_code:
        item_code = item_code

    if item_doc and item_doc[0]:
        conditions.append("brand = %s")
        params.append(item_doc[0])

    if item_doc and item_doc[1]:
        conditions.append("model = %s")
        params.append(item_doc[1])

    if action_type:
        conditions.append("action_type = %s")
        params.append(action_type)

    if part_name:
        conditions.append("part = %s")
        params.append(part_name)
    elif part_list:
        conditions.append("part IN %s")
        params.append(part_list)

    if conditions:
        query = f"""
            SELECT attach, description
            FROM `tabKnowledge Base` 
            WHERE {' AND '.join(conditions)} AND active = 1
        """
        print(f"query: {query}, {conditions}")
        kb_doc = frappe.db.sql(query, tuple(params), as_dict=True)
        return {"item_code":item_code, "kb_doc": kb_doc}
    else:
        frappe.throw(_("No valid conditions found for filtering Knowledge Base."), title=_("Invalid Query"))


@frappe.whitelist()
def item_group_list_from_itw(serial_no):
    ser_item_group = frappe.db.sql("""SELECT item_group FROM `tabSerial No Component` WHERE parent = %s ORDER BY idx""", (serial_no), as_dict=1)

    item_code = frappe.db.get_value('Serial No', {'serial_no':serial_no}, 'item_code')
    template_item_code = frappe.get_value('Item', filters={'item_code': item_code}, fieldname=['variant_of'])
    itw_item_group = frappe.db.sql("""SELECT component_type FROM `tabComponent` WHERE parent = %s ORDER BY idx""", (template_item_code), as_dict=1)
    item_group_list = ser_item_group if ser_item_group else itw_item_group
    
    return item_group_list