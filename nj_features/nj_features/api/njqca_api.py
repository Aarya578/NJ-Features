import json
import frappe
from frappe import _
from frappe.model.document import Document
from nj_features.nj_features.doctype.njqca.njqca import model_change_for_serial_no,get_info_from_serial_no, brand_model_validation, get_part_mapping, after_save_njqca, get_model, get_part_item_code_filtered_data, get_manual_repack_item_code_filtered_data
    
@frappe.whitelist()
def process_njqca_data():
    print('=======================================process_njqca_data===================================================')
    output = {}
    data = frappe.request.data
    data_json = data.decode('utf-8')
    data = json.loads(data_json)
    print('**14**data*****process_njqca_data****',data)
    njqca_doc = frappe.get_doc('NJQCA', data['njqca_name'])
    part_mapping_data = {}
    part_item_code_update_child_data = njqca_doc.as_dict().njqca_item_component

    if 'email' in data and data['email'] is not None:
        work_warehouse = frappe.db.get_value('Employee', {'user_id': data['email']}, 'work_warehouse')
        njqca_doc.warehouse = work_warehouse

    if 'serial_no' in data and data['serial_no'] is not None:
        njqca_doc.serial_no = data['serial_no']
        njqca_doc_str = frappe.as_json(njqca_doc)
        Info_from_serial_no = get_info_from_serial_no(njqca_doc_str)

        if Info_from_serial_no['warehouse'] != data['warehouse']:
            frappe.throw(
						("Please Transfer This Serial No <b>{0}</b> To This Warehouse <b>{1}</b>.").format(
							data['serial_no'], data['warehouse']
						)
					)
            
        elif data['model'] is None or data['model'] == 'None' or data['model'] == '':
            model_specific_query ="""select model_specific from `tabItem Group` where name = %s"""
            model_specific_value =frappe.db.sql(model_specific_query, data['item_group'], as_dict=True)
            if model_specific_value[0]['model_specific'] == 1 :
                frappe.throw("Please Fill The Model. If Model is not there Please Contact NPD Team")
        elif Info_from_serial_no['model'] is None:
            frappe.throw(
						("Model is not there for Serial No <b>{0}</b>. Please contact NPD Team").format(
							data['serial_no']
						)
					)
        # elif data['model'] != Info_from_serial_no['model'] :
        #     model_change_for_serial_no(data['model'],data['serial_no'])
        #     frappe.throw("serialno model and njqca model is different")


        elif data['brand'] != Info_from_serial_no['brand']:
            frappe.throw("Please Check the Brand is Not Matched")

        elif data['power_on'] == 'Yes':
            njqca_doc.item_code = Info_from_serial_no['item_code']
            part_mapping_data = get_part_mapping(data['item_group'],data['njqca_name'],data['model'])

            if 'repack_item_code' in part_mapping_data:
                njqca_doc.repack_item_code = part_mapping_data['repack_item_code']

                if njqca_doc.manual_repack_item_code == '' or njqca_doc.manual_repack_item_code is None:
                    njqca_doc.manual_repack_item_code = part_mapping_data['repack_item_code']

                if 'part_data' in part_mapping_data and part_mapping_data['part_data'] != ['error'] or part_mapping_data['part_data'] != []:
                    l=json.loads(part_mapping_data['part_data'])
                    for i in l:
                        name = i.get('name')
                        part_item_code_filter = i.get('part_item_code')
                        for j in njqca_doc.as_dict().njqca_item_component:
                            if j['name'] == name:
                                part_idx = j['idx']
                                child_data_for_part_item_code = njqca_doc.njqca_item_component[int(part_idx)-1]
                                child_data_for_part_item_code.update({
                                    "part_item_code": part_item_code_filter,
                                })
            after_save_njqca(data['njqca_name'])

        elif data['power_on'] == 'No':
            njqca_doc.power_on = data['power_on']

    if 'model' in data and data['model'] is not None:
        njqca_doc.model = data['model']

    if 'manual_repack_item_code' in data and data['manual_repack_item_code'] is not None:
        njqca_doc.manual_repack_item_code = data['manual_repack_item_code']

    manual_item_codes = []
    if 'item_group' in data and 'brand' in data:
        manual_item_codes = get_manual_repack_item_code_filtered_data(data['item_group'],data['brand'],data['model'])

    part_item_codes = ()
    if 'part_item_group' in data:
        part_item_codes = get_part_item_code_filtered_data(data['part_item_group'])
        part_item_codes = [item[0] for item in part_item_codes]

    if 'njqca_name' in data and 'idx' in data and 'part_config_id' in data and 'part_item_code' in data:
        if data['idx'] is not None and data['part_config_id'] is not None and data['part_item_code'] is not None and data['njqca_name'] is not None:
            child_data_idx = njqca_doc.njqca_item_component[int(data['idx'])-1]
            child_data_idx.update({
                "part_item_code": data['part_item_code'],
                
            })
            

    model_list = get_model(njqca_doc.get('manufacturer_model'))
    njqca_doc.save()
    njqca_parent_data = {}
    njqca_child_data = []
    njqca_result_parameter = []
    njqca_parent_data['name'] = njqca_doc.get('name','')
    njqca_parent_data['power_on'] = njqca_doc.get('power_on','')
    njqca_parent_data['serial_no'] = njqca_doc.get('serial_no') or ''
    njqca_parent_data['bios_serialno'] = njqca_doc.get('bios_serialno','')
    njqca_parent_data['docstatus'] = njqca_doc.get('docstatus','')
    njqca_parent_data['warehouse'] = njqca_doc.get('warehouse','')
    njqca_parent_data['brand'] = njqca_doc.get('brand','')
    njqca_parent_data['make'] = njqca_doc.get('make','')
    njqca_parent_data['manufacturer_model'] = njqca_doc.get('manufacturer_model','')
    njqca_parent_data['model'] = njqca_doc.get('model','')
    njqca_parent_data['item_group'] = njqca_doc.get('item_group','')
    njqca_parent_data['item_code'] = njqca_doc.get('item_code','')
    njqca_parent_data['repack_item_code'] = njqca_doc.get('repack_item_code','')
    njqca_parent_data['manual_repack_item_code'] = njqca_doc.get('manual_repack_item_code','')

    for item in njqca_doc.as_dict().njqca_item_component:
        child_data = {}
        for key,value in item.items():
            if key in ['idx','name','item_group','part_config_id','part_item_code','variant_1','variant_2','variant_6','variant_7','variant_8','variant_10']:
                child_data[key] = value
        njqca_child_data.append(child_data)

    njqca_result_parameter = njqca_doc.njqca_result_parameters

    if 'submit_status' in data and data['submit_status'] is not None:
        if data['manual_repack_item_code'] is not None and data['manual_repack_item_code'] != '':
            njqca_doc.docstatus = '1'
            njqca_doc.submit()
        else:
            frappe.throw('Please fill the Manual Repack Item Code. If there is no option to fill Please Contact NPD Team')
    
    output ={
        'njqca_parent_data':njqca_parent_data,
        'njqca_child_data' : njqca_child_data,
        'njqca_result_parameter' : njqca_result_parameter,
        'manual_item_codes' : manual_item_codes,
        'part_item_codes' : part_item_codes,
        'model_list' : model_list,
        'part_mapping_data' : part_mapping_data
    }

    return output

