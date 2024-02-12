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
            qi_doc = frappe.get_doc('NJ Quality Inspection', data['qi_name'])
            if qi_doc.docstatus == 0:
                qi_doc.status = data['submitStatus']
                try:
                    qi_doc.submit()
                except frappe.exceptions.ValidationError as ve:
                    return {"success": False, "message": f"Validation Error: {str(ve)}"}
                except Exception as e:
                    return {"success": False, "message": f"Error: {str(e)}"}

        if 'currentPart' in data:
            current_data = show_current_part_data(data, result, qi_name)
            # print(f"current_data: {current_data}")

        if "result" in current_data:
            result.update(current_data["result"])
        if "activity" in current_data:
            activity = current_data["activity"]
        if "automatic_count" in current_data:
            automatic_count = current_data["automatic_count"]
        if "part" in current_data:
            part_name = current_data["part"]
        if "count" in current_data:
            count = current_data["count"]

        is_available = frappe.db.get_value('Nj Quality Readings', {'parent':qi_name}, 'is_available')

        nj_readings = []
        if data['submitStatus'].lower() == 'preview':
            nj_readings1 = get_prev_detail(data)
            nj_readings = nj_readings1["nj_readings"]

        output = {
            "item_code": item_code,
            "part_name": part_name,
            "is_available": is_available,
            "activity": activity,
            "total_part": count,
            "qi_name": qi_name,
            "submit_status": submit_status,
            "automatic_count": automatic_count,
            "check_name": result,
            "nj_readings": nj_readings
        }

        return output

    except Exception as e:
        print(f"An error occurred in part_qi_check: {e}")
        return {"success": False, "message": f"Error: {str(e)}"}


def show_current_part_data(data, result, qi_name):
    part_name, automatic_count, result, no_of_checks, automatic_list = '', 0, {}, [], []

    i = int(data['currentPart'])
    item_group_list = get_ig_list_nj(qi_name)['results']
    
    if item_group_list and 1 <= i <= len(item_group_list):
        part_name = item_group_list[i - 1].item_group
        # print(f"count: {len(item_group_list)}------{item_group_list}----------show_current")
        print(f"idx: {i}. part_name : {part_name}\n")
        result = get_current_part_data(data, result, part_name, qi_name)
        result['part'] = part_name
        result['count'] = len(item_group_list)
        check_name = frappe.db.get_value('Nj Quality Readings', {'parent': qi_name, 'item_group':part_name},'quality_check')
        no_of_checks = frappe.db.get_all('Nj QC Options', {'parent': check_name}, 'quality_check')
        # print(f"no_of_checks: {no_of_checks}")
        for i in no_of_checks:
            automatic_list = frappe.db.sql("""
                SELECT count(diagnostic_type) as count FROM `tabNJ QC Check List`
                WHERE name = %s AND diagnostic_type = 'Automatic'
            """, (i.get('quality_check')), as_dict=True)

            if automatic_list[0].get('count') is not None:
                automatic_count += automatic_list[0].get('count')
        result['automatic_count'] = automatic_count
    
    return result


def get_current_part_data(data, result, part_name, qi_name):
    activity, child = '', []

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
                SELECT name_of_check, type, diagnostic_type, description, name, image, image_mandatory, video, video_mandatory,
                screenshot, screenshot_mandatory, input_type, input_type_data FROM `tabNJ QC Check List` WHERE name = %s
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
                'parent': data.get('qi_name') or qi_name,
            }, 'options', order_by='idx')

            # child = frappe.db.get_value('Nj QC Options', {'parent': quality_check}, ['dependant', 'operator', 'options'])
            # print(f"child: {child}")
            # child = frappe.db.get_value('')
            
            combined_info = {
                "name_of_the_check": nj_qc_check_list.get('name_of_check', ''),
                "type": nj_qc_check_list.get('type', ''),
                "diagnostic_type": nj_qc_check_list.get('diagnostic_type', ''),
                "description": nj_qc_check_list.get('description', ''),
                "mandatory": mandatory,
                "input_type": nj_qc_check_list.get('input_type', ''),
                "input_type_data": nj_qc_check_list.get('input_type_data', ''),
                "image": nj_qc_check_list.get('image'),
                "image_mandatory": nj_qc_check_list.get('image_mandatory'),
                "video": nj_qc_check_list.get('video'),
                "video_mandatory": nj_qc_check_list.get('video_mandatory'),
                "screenshot": nj_qc_check_list.get('screenshot'),
                "screenshot_mandatory": nj_qc_check_list.get('screenshot_mandatory'),
                "selected": selected if selected else '',
                "child": child,
                "options": options_query
            }

            result[quality_check] = combined_info

    return {"result": result, "activity": activity}



def get_prev_detail(data):
    if 'qi_name' in data:
        qi_name = data['qi_name']
        # check_name = frappe.db.get_value('Nj Quality Readings', {'parent': qi_name, 'item_group':part_name},'quality_check')
        nj_readings = frappe.get_all(
            'NJ Checks',
            filters={'parent': qi_name},
            fields=['item_group', 'check_name', 'options', 'score', 'weightage', 'idx', 'checks', 'description'],
            order_by='idx ASC'
        )

        formatted_result = {}
        for reading in nj_readings:
            part_name = reading['item_group']
            idx = frappe.db.get_value("Nj Quality Readings", {"item_group": part_name}, "idx")
            grade = frappe.db.get_value("Nj Quality Readings", {"item_group": part_name}, "grade")

            if part_name not in formatted_result:
                formatted_result[part_name] = {
                    'part_name': part_name,
                    'part_idx': idx,
                    'grade': grade if grade else None,
                    'checks': []
                }

            formatted_result[part_name]['checks'].append({
                'check_name': reading['check_name'],
                'result': reading['options'],
                'score': reading['score'],
                'weightage': reading['weightage']
            })

        final_result = list(formatted_result.values())

        return {'nj_readings': final_result}

    return None


# def save_qi_data(data):
#     qi_name, partIsAvailable, item_group, qi_doc = '', '', '', ''
#     if 'qi_name' in data:
#         qi_name = data["qi_name"]
#     if 'partIsAvailable' in data:   
#         partIsAvailable = data['partIsAvailable']
#     if qi_name != '':
#         qi_doc = frappe.get_doc('NJ Quality Inspection', data['qi_name'])

#     # not available -> insert - Done
#     else:
#         serial_no_doc = frappe.db.sql("""SELECT item_code, item_group, warehouse, item_name FROM `tabSerial No` WHERE name = %s""", (data['serialNo']))
#         draft_qi = frappe.db.sql("""SELECT name FROM `tabNJ Quality Inspection` WHERE barcode = %s and docstatus = 0 ORDER BY creation desc""", (data['serialNo']))
#         if draft_qi:
#             qi_doc = frappe.get_doc('NJ Quality Inspection', draft_qi[0][0])
#             qi_name = qi_doc.name

#         else:    
#             qi_doc = frappe.new_doc('NJ Quality Inspection')
#             qi_doc.barcode = data['serialNo']
#             qi_doc.bios_serial_number = data['serialNo']
#             qi_doc.inspection_type = data['inspection_type']
#             qi_doc.machine_made_by = 'itsupport@newjaisa.com'
#             qi_doc.inspected_by = 'itsupport@newjaisa.com'
#             qi_name = qi_doc.name
#             if serial_no_doc:
#                 qi_doc.item_code = serial_no_doc[0][0]
#                 qi_doc.item_group = serial_no_doc[0][1]
#                 qi_doc.current_warehouse = serial_no_doc[0][2]
#                 qi_doc.item_name = serial_no_doc[0][3]
#             result = fetch_nj_qlty_readings(qi_doc)
#             print(f"result: {result}, type: {type(result)}")

#             if result:
#                 for i in range(len(result)):
#                     child_table = qi_doc.append("nj_quality_readings", {})
#                     child_table.is_available = 1
#                     child_table.item_group = result[i]['item_group']
#                     child_table.quality_check = result[i]['quality_check']
#             qi_doc.save()

#     # update checks and their values
#     i = int(data['prevPart'])
#     item_group_list = get_ig_list_nj(qi_name)['results']
#     if item_group_list and 1 <= i <= len(item_group_list):
#         item_group = item_group_list[i - 1][0]
#     if 'checkName' in data and partIsAvailable=='1':
#         for check_name, check_option in zip(data["checkName"], data["checkOption"]):
#             existing_child = frappe.db.sql(""" SELECT item_group, check_name, options, name, description, checks, score, weightage FROM `tabNJ Checks` WHERE item_group = %s AND check_name = %s AND parent = %s ORDER BY idx""",
#             (item_group, check_name, qi_doc.name))

#             grading = frappe.db.sql(""" SELECT check_options, active, score FROM `tabQC Options` WHERE check_options = %s AND parent = %s ORDER BY idx""",
#             (check_option, check_name))

#             data = frappe.db.get_value('QC Options', {'check_options': check_option, 'parent': check_name}, ['description', 'field_name'], order_by='idx')
#             print(f"data : {data}")
#             if existing_child:
#                 try:
#                     demo = frappe.db.sql("""
#                         UPDATE `tabNJ Checks` 
#                         SET options = %s, weightage = %s, score = %s, 
#                         WHERE name = %s
#                     """, (check_option, grading[0][1], grading[0][2], existing_child[0][3]))
#                     frappe.db.commit()
#                     print(f"Updated record: {existing_child[0][3]} - options: {check_option}, {demo}")
#                 except Exception as e:
#                     frappe.db.rollback()
#                     print(f"Error updating record: {existing_child[0][3]} - {e}")
#             else:
#                 child_table = qi_doc.append("nj_quality_checks", {})
#                 child_table.item_group = item_group
#                 child_table.options = check_option #Readings - fieldname
#                 child_table.check_name = check_name
#                 # child_table.description = 
#                 # child_table.checks = 
#                 child_table.score = grading[0][2]
#                 child_table.weightage = grading[0][1]
#                 qi_doc.save()

#     return qi_doc.name

def save_qi_data(data):
    qi_name, partIsAvailable, item_group, qi_doc = '', '', '', ''
    if 'qi_name' in data:
        qi_name = data["qi_name"]
    if 'partIsAvailable' in data:
        partIsAvailable = data['partIsAvailable']
    if qi_name != '':
        qi_doc = frappe.get_doc('NJ Quality Inspection', data['qi_name'])

    # not available -> insert - Done
    else:
        serial_no_doc = frappe.db.sql("""SELECT item_code, item_group, warehouse, item_name FROM `tabSerial No` WHERE name = %s""", (data['serialNo']))
        draft_qi = frappe.db.sql("""SELECT name FROM `tabNJ Quality Inspection` WHERE barcode = %s and docstatus = 0 ORDER BY creation desc""", (data['serialNo']))
        if draft_qi:
            qi_doc = frappe.get_doc('NJ Quality Inspection', draft_qi[0][0])
            qi_name = qi_doc.name

        else:    
            qi_doc = frappe.new_doc('NJ Quality Inspection')
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
            result = fetch_nj_qlty_readings(qi_doc)

            if result:
                for i in range(len(result)):
                    child_table = qi_doc.append("nj_quality_readings", {})
                    child_table.is_available = 1
                    child_table.item_group = result[i]['item_group']
                    child_table.quality_check = result[i]['quality_check']
            qi_doc.save()

    # update checks and their values
    serial_no = data['serialNo']
    i = int(data['prevPart'])
    item_group_list = item_group_list_from_itw(serial_no, data)
    if item_group_list and 1 <= i <= len(item_group_list):
        item_group = item_group_list[i - 1][0]
    if 'checkName' in data and partIsAvailable=='1':
        for check_name, check_option in zip(data["checkName"], data["checkOption"]):
            existing_child = frappe.db.sql(""" SELECT item_group, check_name, options, name, description, checks, score, weightage FROM `tabNJ Checks` WHERE item_group = %s AND check_name = %s AND parent = %s ORDER BY idx""",
            (item_group, check_name, qi_doc.name))
            grading = frappe.db.sql(""" SELECT check_options, active, score FROM `tabQC Options` WHERE check_options = %s AND parent = %s ORDER BY idx""",
            (check_option, check_name))
            if existing_child:
                try:
                    demo = frappe.db.sql("""
                        UPDATE `tabNJ Checks` 
                        SET options = %s, weightage = %s, score = %s
                        WHERE name = %s
                    """, (check_option, grading[0][1], grading[0][2], existing_child[0][3]))
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
                child_table.active = grading[0][1]
                child_table.score = grading[0][2]
                # set_grade_in_quality_readings(qi_doc, item_group)
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
def get_ig_list_nj(qi_name):
    qi_doc = frappe.get_doc('NJ Quality Inspection', qi_name, order_by="idx", as_dict=1)
    nj_readings = qi_doc.get('nj_quality_readings', [])
    
    results = [reading for reading in nj_readings if reading.get('quality_check')]
    return {'qi_doc_json': qi_doc, 'results': results}


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

#code from another module
def fetch_nj_qlty_readings(doc):
    Quality_reading, itm_wzrd, itm_wzrd_doc = [], '', ''
    if doc.barcode:
        item_code = frappe.db.get_value("Serial No", {'name': doc.get("barcode")}, 'item_code')
        itm_template = frappe.db.get_value("Item", {'name': item_code}, 'variant_of')
        #frappe.msgprint(f"{itm_template}")
        if itm_template:
            itm_wzrd = frappe.db.get_value("Item", {'name': itm_template}, 'reference')
            if itm_wzrd:
                itm_wzrd_doc = frappe.get_doc("Item Wizards", itm_wzrd)
    #quality_inspection = frappe.new_doc("Quality Inspection")
    serial_no_doc=frappe.get_doc('Serial No',doc.get("barcode"))
    serial_no=frappe.db.get_list('Serial No Component',
    filters={'parent':doc.get("barcode")},fields=['item_group'])
    # print(f"serial_no_doc: {serial_no_doc}")
    if serial_no:
        #quality_inspection.nj_quality_readings=[]
        for i in serial_no_doc.serial_no_component:
            nj_quality_checks=frappe.db.get_value('NJ Quality Checks',
            {'inspection_type':doc.get("inspection_type"),'item_group':i.item_group},['name'])
            Quality_reading.append({"item_group":i.item_group,"quality_check":nj_quality_checks})
        doc_ig_check = frappe.db.get_value('NJ Quality Checks',
        {'inspection_type':doc.get("inspection_type"),'item_group':doc.item_group},['name'])
        Quality_reading.append({"item_group":doc.item_group,"quality_check":doc_ig_check})
        return Quality_reading

    if not serial_no:
        for compo in itm_wzrd_doc.component:
            #frappe.msgprint(f"{compo.component_type}")
            nj_quality_checks=frappe.db.get_value('NJ Quality Checks',
            {'inspection_type':doc.get("inspection_type"),'item_group':compo.component_type},['name'])
            Quality_reading.append({"item_group":compo.component_type,"quality_check":nj_quality_checks})
        return Quality_reading
    
def set_grade_in_quality_readings(qi_doc, item_group):
    quality_checks = qi_doc.get("nj_quality_checks")
    if quality_checks:
        for check in quality_checks:
            if check.item_group == item_group:
                total_weightage = 0
                mult_score_weightage = 0
                for qc in quality_checks:
                    if qc.item_group == item_group:
                        mult_score_weightage += qc.score * qc.weightage
                        total_weightage += qc.weightage
                total_score = mult_score_weightage / total_weightage if total_weightage > 0 else 0

                quality_readings = qi_doc.get("nj_quality_readings")
                if quality_readings:
                    for reading in quality_readings:
                        if reading.item_group == item_group:
                            grade = get_grade(total_score, item_group)
                            if grade:
                                reading.grade = grade

def get_grade(total_score, item_group):
    if total_score is not None and item_group:
        grade_data = frappe.db.get_all("Item group Grades", {'parent': item_group},['min_total_score','max_total_score', 'grade'])
        for g in grade_data:
            if g.min_total_score <= total_score <= g.max_total_score:
                return g.grade
    return None