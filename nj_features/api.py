import frappe
import json
from frappe import _
from frappe.model.document import Document
from nj_p1_features.nj_p1_features.doctype.nj_quality_inspection.nj_quality_inspection import fetch_nj_qlty_readings, get_qc_check_details, get_qc_options, get_all_grade

@frappe.whitelist()
def eq(query):
    if not isinstance(query, str):
        return {"error": "Query must be a string."}

    try:
        result = frappe.db.sql(query, as_dict=1)
        return result
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}

@frappe.whitelist()
def part_qi_check():
    # init variables
    result, current_data, data_conv, nj_qi_doc = {}, {}, {}, {}
    count = []
    item_code, activity, qi_name, part_name, submit_status, automatic_count, qi_status, is_available = '', '', '', '', '', '', '', ''
    
    # data from NJPulse
    data = frappe.request.data # Byte
    data_str = data.decode('utf-8') # Str
    data_json = json.loads(data_str) # JSON
    # print(f"data_json: {data_json}")
    """
    1. Get latest draft based on serial_no & inspection type or create new doctype
    2. On Barcode: => nj_quality_inspection.js
        a. set bios_serial_number
        b. implement: (m)get_itm_code_on_barcode
        c. implement: (m)fill_nj_quality_reading_from_serial_or_itm_wizard
        d. implement: (m)add_item_group_and_Quality_check
    3. Save previous part data
    4. set grade
    5. Show current part data
    6. Show preview
    """
    
    # 1. Get latest draft based on serial_no & inspection type or create new doctype
    if 'qi_name' in data_json:
        draft_qi = frappe.db.sql("""SELECT name FROM `tabNJ Quality Inspection` WHERE barcode = %s and inspection_type = %s and docstatus = 0 ORDER BY creation desc""", (data['serialNo'], data['inspection_type']))
        if data_json['qi_name'] != '':
            existing_qi_doc = frappe.get_doc('NJ Quality Inspection', data_json['qi_name'])
            # print(f"existing_qi_doc: {existing_qi_doc}")
            if existing_qi_doc.name != '':
                data_json['serialNo'] = existing_qi_doc.bios_serial_number
                data_json['inspection_type'] = existing_qi_doc.inspection_type
                data_json['qi_name'] = existing_qi_doc.name
                nj_qi_doc = existing_qi_doc
        
        elif draft_qi:
                nj_qi_doc = frappe.get_doc('NJ Quality Inspection', draft_qi[0][0])
                
        else:
            nj_qi_doc = frappe.new_doc('NJ Quality Inspection')
            nj_qi_doc.barcode = data_json.get('serialNo', '')
                # a. set bios_serial_number
            nj_qi_doc.bios_serial_number = data_json.get('serialNo', '')
            nj_qi_doc.inspection_type = data_json.get('inspection_type', '')
            nj_qi_doc.inspected_by = data_json.get('user_email', '')
            
                # b. implement: (m)get_itm_code_on_barcode
            nj_qi_doc = get_itm_code_on_barcode(nj_qi_doc) # Done
            
                # c. implement: (m)fill_nj_quality_reading_from_serial_or_itm_wizard
            nj_readings = fetch_nj_qlty_readings(json.dumps(nj_qi_doc.as_dict())) # Done
            nj_qi_doc = fill_data_nj_readings_table(nj_qi_doc, nj_readings) # Done
            nj_qi_doc.save()
            print(f"\n439). \nnew nj_qi_doc: {nj_qi_doc.as_dict()}\n")
            
    if data_json['prevPart']:
        # 3. Save previous part data 
        nj_qi_doc = save_previous_part_data(nj_qi_doc, data_json)
        print(f"442 if prevPart\n{nj_qi_doc}\n")
    
    # 4. Show current part data
    result = show_current_part_data(nj_qi_doc, data_json)
    
    # return nj_qi_doc
    return result


def get_itm_code_on_barcode(nj_qi_doc):
    serial_no_doc = frappe.db.get_value('Serial No', {'name': nj_qi_doc.barcode}, ['item_code', 'item_group', 'item_name', 'status'], as_dict=1)
    if serial_no_doc:
        if serial_no_doc['status'] == 'Active':
            nj_qi_doc.item_code = serial_no_doc['item_code']
            nj_qi_doc.item_group = serial_no_doc['item_group']
            nj_qi_doc.item_name = serial_no_doc['item_name']
        else:
            frappe.msgprint(f"The Serial No is <b>{serial_no_doc['status']}</b>. You can't select this Serial No. Please select the <b>Active</b> <i>Serial No</i>")
    else:
        nj_qi_doc.item_group = None
    return nj_qi_doc


def fill_data_nj_readings_table(nj_qi_doc, nj_readings):
    existing_item_groups = []
    
    for entry in nj_readings:
        if entry.get('quality_check'):
            nj_qi_doc.append('nj_quality_readings', {
                'item_group': entry.get('item_group', ''),
                'quality_check': entry.get('quality_check', ''),
                'item': entry.get('item_code', ''),
                'part_serial_no': entry.get('serial_no', '')
            })

    if nj_qi_doc.get('item_group') and nj_qi_doc.get('inspection_type'):
        if not nj_qi_doc.get('nj_quality_readings'):
            nj_qi_doc['nj_quality_readings'] = []

        for nqr in nj_qi_doc.get('nj_quality_readings', []):
            existing_item_groups.append(nqr.get('item_group'))

        if nj_qi_doc.get('item_group') not in existing_item_groups:
            quality_check_name = frappe.db.get_value('NJ Quality Checks', f"{nj_qi_doc.get('inspection_type')}-{nj_qi_doc.get('item_group')}", 'name')

            if quality_check_name:
                child_table = nj_qi_doc.append('nj_quality_readings', {})
                child_table.item_group = nj_qi_doc.get('item_group')
                child_table.quality_check = quality_check_name
                child_table.is_available = 1
    return nj_qi_doc

    
    
def show_current_part_data(nj_qi_doc, data_json):
    combined_info, njpulse_format, result = {}, {}, {}
    activity, part_name, total_part, automatic_count = '', '', 0, 0
    
    idx = data_json["currentPart"]
    print(f"505). show_current_part_data - idx: {idx}")
    nj_quality_checks = nj_qi_doc.nj_quality_checks
    nj_quality_readings = nj_qi_doc.nj_quality_readings
    print(f"508 -- nj_quality_readings: {nj_quality_readings}")
    # if nj_quality_checks != []:
    part_name = nj_quality_readings[idx-1].item_group    
    nj_readings = nj_qi_doc.nj_quality_readings
    total_part = len(nj_readings)

    
    parent_name_query = frappe.db.sql("""
        SELECT name, activity FROM `tabNJ Quality Checks` WHERE item_group = %s AND inspection_type = %s
    """, (part_name, data_json['inspection_type']))
    if parent_name_query:
        parent_name = parent_name_query[0][0]
        activity = parent_name_query[0][1]
        print(f"parent_name_query: {parent_name_query}, {parent_name}")

        second_query = frappe.db.sql("""SELECT quality_check, mandatory FROM `tabNj QC Options` WHERE parent = %s ORDER BY idx""", 
        (parent_name), as_dict=True)

        for row in second_query:
            quality_check = row.get('quality_check')
            mandatory = row.get('mandatory')

            nj_qc_check_list_query = frappe.db.sql("""
                SELECT name_of_check, type, diagnostic_type, description, name, image, image_mandatory, video, video_mandatory,
                screenshot, screenshot_mandatory, input_type, input_type_data FROM `tabNJ QC Check List` WHERE name = %s
            """, (quality_check), as_dict=True)
            # print(f"\nquality_check: {quality_check} \n\nnj_qc_check_list_query: {nj_qc_check_list_query[0]}\n")
            options_query = frappe.db.sql("""
                SELECT check_options, score, active FROM `tabQC Options` WHERE parent = %s AND active=1
            """, (quality_check), as_dict=True)

            if nj_qc_check_list_query:
                nj_qc_check_list = nj_qc_check_list_query[0]
            else:
                nj_qc_check_list = {}

            name = nj_qc_check_list.get('name_of_check', '')

            selected = get_selected_value(nj_qi_doc.nj_quality_checks, part_name, name)
            # child = frappe.db.get_value('')
            combined_info = {
                "name_of_the_check": name,
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
                # "child": child,
                "options": options_query
            }
            result[quality_check] = combined_info
    
    # For automatic count
    check_name = frappe.db.get_value('Nj Quality Readings', {'parent': nj_qi_doc.name, 'item_group':part_name},'quality_check')
    no_of_checks = frappe.db.get_all('Nj QC Options', {'parent': check_name}, 'quality_check')
    for i in no_of_checks:
        automatic_list = frappe.db.sql("""
            SELECT count(diagnostic_type) as count FROM `tabNJ QC Check List`
            WHERE name = %s AND diagnostic_type = 'Automatic'
        """, (i.get('quality_check')), as_dict=True)

        if automatic_list[0].get('count') is not None:
            automatic_count += automatic_list[0].get('count')
    result['automatic_count'] = automatic_count
        
    # njpulse format
    njpulse_format = {
        "item_code": nj_qi_doc.item_code,
        "part_name": part_name,
        "is_available": 1, # nj_qi_doc.nj_quality_readings[idx-1].is_available
        "activity": activity,
        "total_part": total_part,
        "qi_name": nj_qi_doc.name if nj_qi_doc.name else "",
        "serial_no": nj_qi_doc.barcode,
        "bios_serial_number": nj_qi_doc.bios_serial_number, #
        "inspection_type": data_json['inspection_type'],
        "qi_status": "data_json.qi_status",
        "submit_status": nj_qi_doc.status,
        "automatic_count": automatic_count,
        "check_name": result,
        "nj_readings": show_preview(nj_qi_doc) if data_json.get('submit_status') == 'preview' else None
    }
    
    return njpulse_format
    
# def show_preview(nj_qi_doc):
#     formatted_result, checks, part_name, part_idx = {}, {}, '', ''
#     # nj_checks = nj_qi_doc.nj_quality_checks
#     # print(f"\n\nnj_qi_doc: {nj_qi_doc.as_dict()}\n")
#     nj_qi_doc = nj_qi_doc.as_dict()
#     nj_readings = nj_qi_doc.nj_quality_readings
#     print(f"nj_readings: {nj_readings}")
#     for reading in nj_readings:
#         part_name = reading.item_group
#         part_idx = reading.idx
#     #     parent = reading.name
#     #     print(f"parent: {parent}")
#     #     # quality_check = reading.quality_check
#     #     check_name = frappe.db.get_value('Nj QC Options', {'parent': parent}, 'quality_check')

#     #     # Initialize an empty dictionary for each part_name if it doesn't exist
#     #     if part_name not in formatted_result:
#     #         formatted_result[part_name] = {
#     #             'part_name': part_name,
#     #             'checks': []
#     #         }

#     #     # Append check data to the checks list
#     #     print(f"check_name: {check_name}")
#     #     formatted_result[part_name]['checks'].append({
#     #         'check_name': check_name,
#     #         # 'result': reading.options if reading.options else "",
#     #         # 'is_available': reading.is_available,
#     #         # 'docstatus': reading.docstatus,
#     #         # Add other attributes as needed
#     #     })
    
#         stored_value = frappe.db.get_value("")
#         checks = {
#             "check_name": "",
#             "result": "",
#             "score": 0,
#             "weightage": 1
#         }
    
#         formatted_result = {
#             "part_name": part_name,
#             "part_idx": part_idx,
#             "check": checks
#         }

#     return formatted_result

def show_preview(nj_qi_doc):
    formatted_result = []
    nj_readings = nj_qi_doc.get('nj_quality_readings', [])

    for reading in nj_readings:
        part_name = reading.get('item_group')
        part_idx = reading.get('idx')
        inspection_type = nj_qi_doc.get('inspection_type')

        sql_query = f"""
            SELECT QCL.field_name, QC.idx 
            FROM `tabNj QC Options` AS QC
            INNER JOIN `tabNJ QC Check List` AS QCL ON QC.quality_check = QCL.name
            WHERE QC.parent = '{inspection_type}-{part_name}' ORDER BY QC.idx
        """
        checks_data = frappe.db.sql(sql_query, as_dict=True)

        checks = []
        for check_data in checks_data:
            check_name = check_data.get('field_name')
            idx = check_data.get('idx')
            result = get_check_result(nj_qi_doc, reading.get('quality_check'), check_name)
            checks.append({
                'check_name': check_name,
                'result': result.get('options', ''),
                # 'idx': idx,
                'score': result.get('score', 0.0),
                'weightage': result.get('weightage', 0.0)
            })

        formatted_result.append({
            'part_name': part_name,
            'part_idx': part_idx,
            'checks': checks
        })

    return formatted_result

def get_check_result(nj_qi_doc, parent, check_name):
    for check in nj_qi_doc.get('nj_quality_checks', []):
        if check.get('checks') == check_name:
            return check
    return {}



    # if 'qi_name' in data:
    #     qi_name = data['qi_name']
    #     # nj_readings = frappe.db.get_all('Nj Quality Readings', {'parent': qi_name}, ['quality_check', 'item_group', 'grade'], order_by='idx ASC')
    #     nj_readings = frappe.get_all(
    #         'NJ Checks',
    #         filters={'parent': qi_name},
    #         fields=['item_group', 'check_name', 'options', 'score', 'weightage', 'idx', 'checks', 'description'],
    #         order_by='idx ASC'
    #     )

    #     formatted_result = {}
    #     for reading in nj_readings:
    #         part_name = reading['item_group']
    #         idx = get_ig_list_nj(qi_name, part_name)['idx']
    #         # idx = frappe.db.get_value("Nj Quality Readings", {"item_group": part_name}, "idx")
    #         grade = frappe.db.get_value("Nj Quality Readings", {"item_group": part_name}, "grade")

    #         if part_name not in formatted_result:
    #             formatted_result[part_name] = {
    #                 'part_name': part_name,
    #                 'part_idx': idx,
    #                 'grade': grade if grade else None,
    #                 'checks': []
    #             }

    #         formatted_result[part_name]['checks'].append({
    #             'check_name': reading['check_name'],
    #             'result': reading['options'],
    #             'score': reading['score'],
    #             'weightage': reading['weightage']
    #         })

    #     final_result = list(formatted_result.values())

    #     return {'nj_readings': final_result}

    # return None
    
@frappe.whitelist()  
def save_previous_part_data(nj_qi_doc, data_json):
    data_obj, result, nj_quality_checks = {}, [], []
    if 'checkName' in data_json and data_json['partIsAvailable'] == '1':
        for check_name, check_option in zip(data_json["checkName"], data_json["checkOption"]):
            data_obj[check_name] = check_option
            
    data = json.dumps(data_obj)
    print(f"\n\nsave_previous_part_data 742 nj_qi_doc: {nj_qi_doc}\n")
    nj_quality_readings = nj_qi_doc.nj_quality_readings
    nj_quality_checks = json.dumps(nj_qi_doc.nj_quality_checks) #convert to str for passing data
    i = int(data_json["prevPart"])
    # print(f"\n\n 746 ------ {type(i)}")
    # Extracting item_group and quality_check from nj_quality_readings
    item_group = nj_quality_readings[i-1].item_group
    quality_check = nj_quality_readings[i-1].quality_check
    print(f"1.........{type(nj_quality_readings)}.... {nj_quality_readings}")
    
    if nj_quality_checks == []:
        print("if block executed")
        get_qc_options(quality_check, None, item_group)
        result = get_qc_check_details(data, None, item_group)
        
    else:
        print("else block executed")
        get_qc_options(quality_check, nj_quality_checks, item_group)
        result = get_qc_check_details(data, nj_quality_checks, item_group)
    
    if not isinstance(result, list):
        result = [result]
    print("8888888888888888888888888888888888")  
    print(f"\n\nresult: {result}")
    
    for entry in result:
        child_row = nj_qi_doc.append("nj_quality_checks", {})
        child_row.item_group = entry.get("item_group")
        child_row.checks = entry.get("checks")
        child_row.options = entry.get("options")
        child_row.check_name = entry.get("check_name")
        child_row.description = entry.get("description")
        child_row.score = entry.get("score", 0.0)
        child_row.weightage = entry.get("weightage", 1.0)
    nj_qi_doc.save()
    # 4. set grade
    set_total_score_value(nj_qi_doc)
    
    return nj_qi_doc

def get_selected_value(nj_quality_checks, part_name, check_name):
    for check in nj_quality_checks:
        if check.item_group == part_name and check.check_name == check_name:
            # print(f"\ncheck: {check.check_name}, {check_name}, {check.options}")
            return check.options 
    return None

@frappe.whitelist()
def set_total_score_value(doc):
    calc_type = frappe.db.get_single_value('NewJaisa Configuration', 'grade_calculation_criteria')
    print("Calculation type:", calc_type)
    if calc_type:
        for qr in doc.get("nj_quality_readings", []):
            mult_score_weightage = 0
            total_weightage = 0
            list_of_score_and_weightage = []
            matching_item_group = []
            is_eligible_for_calc = False
            
            for qc in doc.get("nj_quality_checks", []):
                if qc.get('item_group') == qr.get('item_group'):
                    if qc.get('weightage') is None or isinstance(qc.get('weightage'), str) and not qc.get('weightage').isdigit():
                        qc['weightage'] = 0.0
                    list_of_score_and_weightage.append([qc.get('score'), qc.get('weightage')])
                    matching_item_group.append(qr.get('item_group'))
                    is_eligible_for_calc = True
            
            if is_eligible_for_calc:
                qr['total_score'] = get_correct_total_score(list_of_score_and_weightage, calc_type)
                frappe.db.set_value("Nj Quality Readings", qr.get("name"), "total_score", qr['total_score'])
                print("Total score for", qr.get("name"), ":", qr['total_score'])
            
            if doc.get("nj_quality_checks") and len(doc.get("nj_quality_checks")) > 0 and qr.get('item_group') in matching_item_group:
                for check in doc.get("nj_quality_checks"):
                    if check.get('item_group'):
                        matchingItemgr = next((item for item in doc.get("nj_quality_readings") if item.get('item_group') == check.get('item_group')), None)
                        if matchingItemgr:
                            pass
                        else:
                            check['grade'] = None
                        if 'grade' in check:  # Ensure 'grade' key exists in check
                            frappe.db.set_value("NJ Quality Checks", check.get("name"), "grade", check['grade'])
                            print("Set grade for", check.get("name"), ":", check['grade'])
    
    set_grade_on_save(doc)

def get_correct_total_score(list_of_score_and_weightage, calc_type):
    total_score = 0
    score_list = []
    total_weightage = 0
    if list_of_score_and_weightage:
        for data in list_of_score_and_weightage:
            score_list.append(data[0] * data[1])
            total_weightage += data[1]
        if calc_type == 'Max':
            return max(score_list)
        elif calc_type == 'Min':
            return min(score_list)
        else:
            total_sum = sum(score_list)
            if total_weightage:
                return total_sum / total_weightage
            else:
                return 0
    else:
        return total_score
    
def set_grade_on_save(doc):
    str_doc = json.dumps(doc)
    linked_doc = get_all_grade(str_doc)
    if linked_doc:
        for row in doc.get("nj_quality_readings", []):
            for grade_details in linked_doc:
                if row["item_group"] == grade_details["parent"]:
                    if grade_details["min_total_score"] <= row.get("total_score", 0) <= grade_details["max_total_score"]:
                        if row.get("total_score") is not None and row.get("total_score") != "":
                            row["grade"] = grade_details["grade"]
                            print("Set grade for", row.get("name"), ":", row["grade"])
                            frappe.db.set_value("Nj Quality Readings", row.get("name"), "grade", row["grade"])
        frappe.db.commit()
        print("Grade updated in Nj Quality Readings")

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