import json
import frappe
from frappe import _
from frappe.model.document import Document
from nj_features.nj_features.doctype.njqca.njqca import get_info_from_serial_no, brand_model_validation, get_part_mapping, after_save_njqca, get_model, get_part_item_code_filtered_data, get_manual_repack_item_code_filtered_data
    
@frappe.whitelist()
def process_njqca_data():
    output = {}
    data = frappe.request.data
    data_json = data.decode('utf-8')
    data = json.loads(data_json)
    print('**14**data*****process_njqca_data****',data)
    njqca_doc = frappe.get_doc('NJQCA', data['njqca_name'])
    if 'email' in data and data['email'] is not None:
        work_warehouse = frappe.db.get_value('Employee', {'user_id': data['email']}, 'work_warehouse')
        print('***********work_warehouse************',work_warehouse)
        njqca_doc.warehouse = work_warehouse
        njqca_doc.save()
    if 'serial_no' in data and data['serial_no'] is not None:
        njqca_doc.serial_no = data['serial_no']
        njqca_doc_str = frappe.as_json(njqca_doc)
        Info_from_serial_no = get_info_from_serial_no(njqca_doc_str)
        print('************Info_from_serial_no**************',Info_from_serial_no)
        print('25')
        if Info_from_serial_no['warehouse'] != data['warehouse']:
            frappe.throw(
						_("Please Transfer This Serial No <b>{0}</b> To This Warehouse <b>{1}</b>.").format(
							data['serial_no'], data['warehouse']
						)
					)
            print('31')
        elif data['model'] is None or data['model'] == 'None':
            frappe.throw("Please Fill The Model. If Model is not there Please Contact NPD Team")
            print('34')
        elif (data['manual_repack_item_code'] is None or data['manual_repack_item_code'] == ''):
            frappe.throw("Please Fill The Manual Repack Item code")
            print('37')
        elif data['brand'] == Info_from_serial_no['brand']:
            frappe.throw("Please Check Brand is Not Matched")
            print('38')
        else:
            njqca_doc.item_code = Info_from_serial_no['item_code']
            print('****************after_save_njqca*********************',after_save_njqca(data['njqca_name']))
            njqca_doc.save()   
        print('45')  
    if 'model' in data and data['model'] is not None:
        njqca_doc.model = data['model']
        njqca_doc.save()
        print('45')
    if 'manual_repack_item_code' in data and data['manual_repack_item_code'] is not None:
        njqca_doc.manual_repack_item_code = data['manual_repack_item_code']
        njqca_doc.save()
        print('49')
    manual_item_codes = []
    if 'item_group' in data and 'brand' in data:
        manual_item_codes = get_manual_repack_item_code_filtered_data(data['item_group'],data['brand'],data['model'])
        # print('===========manual_item_codes================',manual_item_codes)
        print('54')
    part_item_codes = ()
    if 'part_item_group' in data:
        part_item_codes = get_part_item_code_filtered_data(data['part_item_group'])
        # print('*****************part_item_codes************************',part_item_codes)
    if 'njqca_name' in data and 'idx' in data and 'part_config_id' in data and 'part_item_code' in data:
        if data['idx'] is not None and data['part_config_id'] is not None and data['part_item_code'] is not None and data['njqca_name'] is not None:
            frappe.db.sql(
                """
                UPDATE `tabNJQCA Child`
                SET part_item_code = %s
                WHERE parent = %s AND idx = %s AND part_config_id = %s
                """,
                (data['part_item_code'], data['njqca_name'], data['idx'], data['part_config_id'])
            )

    model_list = get_model(njqca_doc.get('manufacturer_model'),njqca_doc.get('make'))
    # print('********modal_list*******',model_list)
    njqca_parent_data = {}
    njqca_child_data = []
    njqca_result_parameter = []
    # print('******njqca_data*********',njqca_doc.as_dict())
    njqca_parent_data['name'] = njqca_doc.get('name','')
    # njqca_parent_data['serial_no'] = njqca_doc.get('serial_no','')
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
            if key in ['idx','item_group','part_config_id','part_item_code','variant_1','variant_2','variant_3','variant_4','variant_8','variant_10']:
                child_data[key] = value
        njqca_child_data.append(child_data)
    njqca_result_parameter = njqca_doc.njqca_result_parameters
    # print('njqca_result_parameters===========',njqca_doc.njqca_result_parameters)
    part_item_codes = [item[0] for item in part_item_codes]
    output ={
        'njqca_parent_data':njqca_parent_data,
        'njqca_child_data' : njqca_child_data,
        'njqca_result_parameter' : njqca_result_parameter,
        'manual_item_codes' : manual_item_codes,
        'part_item_codes' : part_item_codes,
        'model_list' : model_list
    }
    print('*************************************',output)
    return output


