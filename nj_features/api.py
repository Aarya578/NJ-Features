import json
import frappe
from frappe import _

@frappe.whitelist()
def part_qi_check():
    try:
        result, current_data = {}, {}
        count = []
        item_code, activity, qi_name, part_name, submit_status = '', '', '', '', ''
        
        data_bytes = frappe.request.data
        data_str = data_bytes.decode('utf-8')
        data = json.loads(data_str)
        item_code = frappe.db.get_value('Serial No', {'name': data['serialNo']}, 'item_code')
        # print(f"item_code: {item_code}")

        if 'submitStatus' in data:
            submit_status = data['submitStatus']
            
        #save prevPart data
        if 'checkName' in data:
            if data['prevPart'] == "":
                data['prevPart'] = 1
            qi_name = save_qi_data(data)
        
        else: qi_name = save_qi_data(data)

        #submit qi_doc
        if (data['submitStatus'].lower() == 'accepted' or data['submitStatus'].lower() == 'rejected'):
            qi_doc = frappe.get_doc('Quality Inspection', data['qi_name'])
            if qi_doc.docstatus == 0:
                qi_doc.status = data['submitStatus']
                qi_doc.submit()

        if 'currentPart' in data:
            current_data = show_current_part_data(data, result, qi_name)
            # print(f"current_data: {current_data}")

        if "result" in current_data:
            result.update(current_data["result"])
        if "activity" in current_data:
            activity = current_data["activity"]
        if "part" in current_data:
            part_name = current_data["part"]
        if "count" in current_data:
            count = current_data["count"]

        nj_readings = []
        if data['submitStatus'].lower() == 'preview':
            nj_readings1 = get_prev_detail(data)
            nj_readings = nj_readings1["nj_readings"]

        output = {
            "item_code": item_code,
            "part_name": part_name,
            "is_available": "1",
            "activity": activity,
            "total_part": count,
            "qi_name": qi_name,
            "submit_status": submit_status,
            "check_name": result,
            "nj_readings": nj_readings
        }

        return output

    except Exception as e:
        print(f"An error occurred in part_qi_check: {e}")
        return {"success": False, "message": f"Error: {str(e)}"}


def show_current_part_data(data, result, qi_name):
    part_name, result = '', {}

    serial_no = data['serialNo']
    i = int(data['currentPart'])
    item_group_list = item_group_list_from_itw(serial_no, data)
    if item_group_list and 1 <= i <= len(item_group_list):
        part_name = item_group_list[i - 1][0]
        result= get_current_part_data(data, result, part_name, qi_name)
        result['part'] = part_name
        result['count'] = len(item_group_list)
    
    return result




def get_current_part_data(data, result, part_name, qi_name):
    activity = ''
    item_group = part_name

    serial_no = data['serialNo']
    i = int(data['currentPart'])
    item_group_list = item_group_list_from_itw(serial_no, data)
    if item_group_list and 1 <= i <= len(item_group_list):
        part_name = item_group_list[i - 1][0]

    parent_name_query = frappe.db.sql("""
        SELECT name, activity FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s
    """, (part_name, data['inspection_type']))

    if parent_name_query:
        parent_name = parent_name_query[0][0]
        activity = parent_name_query[0][1]

        second_query = frappe.db.sql("""SELECT quality_check, mandatory FROM `tabNj QC Options` WHERE parent = %s ORDER BY idx""", 
        (parent_name), as_dict=True)

        for row in second_query:
            quality_check = row.get('quality_check')
            mandatory = row.get('mandatory')

            nj_qc_check_list_query = frappe.db.sql("""
                SELECT name_of_check, type, diagnostic_type, description, name FROM `tabNJ QC Check List` WHERE name = %s
            """, (quality_check), as_dict=True)

            options_query = frappe.db.sql("""
                SELECT check_options, score, active FROM `tabQC Options` WHERE parent = %s AND active=1
            """, (quality_check), as_dict=True)

            if nj_qc_check_list_query:
                nj_qc_check_list = nj_qc_check_list_query[0]
            else:
                nj_qc_check_list = {}

            name = nj_qc_check_list.get('name', '')

            selected = frappe.db.get_value('NJ Checks', {
                'item_group': part_name,
                'check_name': name,
                'parent': data.get('qi_name')
            }, 'options', order_by='idx')
            
            combined_info = {
                "name_of_the_check": nj_qc_check_list.get('name_of_check', ''),
                "type": nj_qc_check_list.get('type', ''),
                "diagnostic_type": nj_qc_check_list.get('diagnostic_type', ''),
                "description": nj_qc_check_list.get('description', ''),
                "mandatory": mandatory,
                "selected": selected if selected else '',
                "options": options_query
            }

            result[quality_check] = combined_info

    return {"result": result, "activity": activity}



def get_prev_detail(data):
    if 'qi_name' in data:
        qi_name = data['qi_name']

        nj_readings = frappe.get_all(
            'NJ Checks',
            filters={'parent': qi_name},
            fields=['item_group', 'check_name', 'options', 'score', 'weightage', 'idx'],
            order_by='idx ASC'
        )

        formatted_result = {}
        for reading in nj_readings:
            part_name = reading['item_group']
            idx = reading['idx']

            # If part_name not in formatted_result, initialize it with an empty dictionary
            if part_name not in formatted_result:
                formatted_result[part_name] = {
                    'part_name': part_name,
                    'part_idx': idx,
                    'checks': []
                }

            # Append check details to the checks list
            formatted_result[part_name]['checks'].append({
                'check_name': reading['check_name'],
                'result': reading['options'],
                'score': reading['score'],
                'weightage': reading['weightage']
            })

        final_result = list(formatted_result.values())

        return {'nj_readings': final_result}

    return None


def save_qi_data(data):
    qi_name, partIsAvailable, item_group, qi_doc = '', '', '', ''
    if 'qi_name' in data:
        qi_name = data["qi_name"]
    if 'partIsAvailable' in data:
        partIsAvailable = data['partIsAvailable']
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
            qi_name = qi_doc.name
            if serial_no_doc:
                qi_doc.item_code = serial_no_doc[0][0]
                qi_doc.item_group = serial_no_doc[0][1]
                qi_doc.current_warehouse = serial_no_doc[0][2]
                qi_doc.item_name = serial_no_doc[0][3]
            qi_doc.save()

    # update checks and their values
    serial_no = data['serialNo']
    i = int(data['prevPart'])
    item_group_list = item_group_list_from_itw(serial_no, data)
    if item_group_list and 1 <= i <= len(item_group_list):
        item_group = item_group_list[i - 1][0]
    if 'checkName' in data and partIsAvailable=='1':
        for check_name, check_option in zip(data["checkName"], data["checkOption"]):
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
def get_kb_from_serial_no(serialNo, action_type=None, part_name=None):
    item_code = ''
    item_code = frappe.db.get_value('Serial No', {'name': serialNo}, 'item_code')
    if not item_code:
        frappe.throw(_("Serial No '{0}' not found.").format(serialNo), title=_("Serial No Not Found"))

    item_doc = frappe.db.get_value('Item', {'name': item_code}, ['brand','item_model'])
    
    item_group_list = item_group_list_from_itw(serialNo)
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
        kb_doc = frappe.db.sql(query, tuple(params), as_dict=True)
        return {"item_code":item_code, "kb_doc": kb_doc}
    else:
        frappe.throw(_("No valid conditions found for filtering Knowledge Base."), title=_("Invalid Query"))


@frappe.whitelist()
def item_group_list_from_itw(serial_no, data=None):
    # Get item groups from Serial No Component
    ser_item_group = frappe.db.sql("""
        SELECT item_group FROM `tabSerial No Component` WHERE parent = %s ORDER BY idx
    """, (serial_no), as_dict=1)

    # Get item code from Serial No
    item_code = frappe.db.get_value('Serial No', {'serial_no': serial_no}, 'item_code')

    # Get template item code from Item
    template_item_code = frappe.get_value('Item', filters={'item_code': item_code}, fieldname=['variant_of'])
    itw_name = frappe.get_value('Item', filters={'item_code': template_item_code}, fieldname=['reference'])

    # Get item groups from Item Wizard Component
    itw_item_group = frappe.db.sql("""
        SELECT component_type, idx FROM `tabComponent` WHERE parent = %s ORDER BY idx
    """, (itw_name), as_dict=1)

    # Combine item groups from both sources
    item_group_list = ser_item_group if ser_item_group else itw_item_group

    # If idx is provided, filter the item group based on idx
    if data is not None:
        filtered_item_group = []
        if ser_item_group:
            for x in ser_item_group:
                result = frappe.db.sql("""SELECT item_group FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s""", 
                (x.item_group, data['inspection_type']))
                filtered_item_group.extend(result)
            # filtered_item_group = [item_group for item_group in item_group_list if item_group.get('idx') == idx]
        elif itw_item_group:
            for x in itw_item_group:
                result = frappe.db.sql("""SELECT item_group FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s""", 
                (x.component_type, data['inspection_type']))
                filtered_item_group.extend(result)
            # filtered_item_group = [component_type for component_type in item_group_list if component_type.get('idx') == idx]
        return filtered_item_group
    else:
        return item_group_list
    

@frappe.whitelist()
def eq(query):
    if not isinstance(query, str):
        return {"error": "Query must be a string."}

    try:
        result = frappe.db.sql(query, as_dict=1)
        return result
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}
