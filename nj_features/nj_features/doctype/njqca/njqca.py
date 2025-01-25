import re
import json
import frappe
import datetime
import traceback
from frappe import _
from frappe.utils import get_url
from frappe.model.document import Document
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
from nj_lib.utils.common_utils import get_active_emp, get_latest_item_wizard,check_item_code_vs_model_validation
from nj_p1_features.overrides.serial_no import update_component_in_serial_no
from nj_features.nj_features.doctype.inward.inward import get_item_template,has_item_wizards
from nj_p1_features.nj_p1_features.doctype.nj_quality_inspection.nj_quality_inspection import validation_for_nj_readings_in_nj_qi,update_total_preferred_grade_a

@frappe.whitelist()
def update_serial_no_componont_for_grade(self):
    try:
        serial_no_doc = frappe.get_doc("Serial No", self.serial_no)
        serial_no_doc.bios_serial_no = self.bios_serialno
        serial_no_doc.purchase_price = self.base_price
        serial_no_doc.current_price = self.base_price

        if not serial_no_doc.model:
            model = frappe.db.get_value('Item', {'name':serial_no_doc.item_code}, 'item_model')
            if model:
                serial_no_doc.model = model
        for reading in (self.njqca_item_component):
            if reading.part_item_code and reading.item_group:
                for sn in serial_no_doc.serial_no_component:
                    if reading.item_group == sn.item_group:
                        sn.item = reading.part_item_code
        
        item_template = frappe.db.get_value('Item', {'name':serial_no_doc.item_code}, 'variant_of')

        if item_template:
            item_wizard = get_latest_item_wizard(item_template, serial_no_doc.item_code)
            item_wizard_doc = frappe.get_doc("Item Wizards", {"name": item_wizard})
            update_component_in_serial_no(item_wizard_doc, serial_no_doc, serial_no_doc.model)
        serial_no_doc.save()

    except Exception as e:
        return {f'Error while updating the Serial No Component: {str(e)}'}

@frappe.whitelist()
def get_inspection_type():
    emp_dept = get_active_emp(frappe.session.user, fields=['department'])
    inspection_type= frappe.db.get_value('Department', {'name': emp_dept.get('department')}, 'inspection_type')
    if inspection_type:
        return inspection_type
    else:
        frappe.msgprint("<b>Inspection Type</b> is not updated in <b>Department: {0}</b>".format(emp_dept.get('department')))
        return None

def open_draft_qi(self):
    # try:
    #     inspection_type = get_inspection_type()
    #     if not inspection_type:
    #         inspection_type = self.inspection_type
    #     self.inspection_type = inspection_type

    #     if self.bios_serialno:
    #         serial_num = frappe.db.get_value('Serial No', {'bios_serial_no': self.bios_serialno}, 'name')

    #     existing_qi = frappe.get_list('NJ Quality Inspection', filters={'barcode': serial_num, 'inspection_type':inspection_type, 'docstatus': 0}, limit=1)
    #     if existing_qi:
    #         # Get the existing document
    #         new_qi = frappe.get_doc('NJ Quality Inspection', existing_qi[0].name)
    #     else:
    #         new_qi = frappe.new_doc('NJ Quality Inspection')
    #         new_qi.inspection_type = self.inspection_type 
    #         new_qi.barcode = serial_num
    #         new_qi.njqca_laptop_name = self.name
    #         new_qi.inspected_by = new_qi.owner
    #         if self.manual_repack_item_code :
    #             new_qi.item_code = self.manual_repack_item_code
    #             new_qi.item_name = self.manual_repack_item_code
        
    #     result = get_itm_code_on_barcode(new_qi)
    #     self.qi_name = new_qi.name

    #     fill_nj_quality_reading_from_serial_or_itm_wizard(new_qi, inspection_type, is_defective="0")
    try:
        inspection_type = self.inspection_type
        if not self.inspection_type:
            inspection_type = get_inspection_type()
            
        if self.bios_serialno:
            serial_num = frappe.db.get_value('Serial No', {'bios_serial_no': self.bios_serialno}, 'name')

        # Get all existing QIs for this barcode and inspection type
        existing_qis = frappe.get_list('NJ Quality Inspection',
            filters={
                'barcode': serial_num,
                'inspection_type': inspection_type
            },
            fields=['name', 'creation'],
            order_by='creation desc'
        )

        create_new_qi = True
        new_qi = None

        if existing_qis:
            latest_qi = existing_qis[0]
            time_diff = frappe.utils.time_diff_in_seconds(frappe.utils.now(), latest_qi.creation)
            
            if time_diff < 1200:  # 1200 seconds = 20 minutes
                # If the process is not 'njqca', reuse existing QI if less than 20 minutes old
                    new_qi = frappe.get_doc('NJ Quality Inspection', latest_qi.name)
                    create_new_qi = False
            else:
                # Create new QI if more than 20 minutes old
                create_new_qi = True 
        
        if create_new_qi:
            new_qi = frappe.new_doc('NJ Quality Inspection')
            new_qi.inspection_type = inspection_type
            new_qi.barcode = self.serial_no if self.serial_no else serial_num
            new_qi.njqca_laptop_name = self.name
            new_qi.inspected_by = new_qi.owner
            
            if self.manual_repack_item_code:
                new_qi.item_code = self.manual_repack_item_code
            
            result = get_itm_code_on_barcode(new_qi)
            self.qi_name = new_qi.name
            fill_nj_quality_reading_from_serial_or_itm_wizard(new_qi, inspection_type, is_defective="0")

        item_wizard_name = new_qi.get('item_wizard')
        item_group_data =''
        if item_wizard_name :
            component_type = """
            SELECT component_type from `tabComponent` where parent = %s"""
            component_type_data = frappe.db.sql(component_type,(item_wizard_name,),as_dict= True)
            item_group_data = [a['component_type'] for a in component_type_data]
        config_data_2_qi = frappe.db.get_value("NJ Settings",{"doc_type": "NJQCA","parameter":"config"},"value")

        if config_data_2_qi:
            try:
                config_data_2_qi = json.loads(config_data_2_qi)
            except json.JSONDecodeError as e:
                return f"Error in JSON parsing: {e}"
        else:
            config_data_2_qi = {}
        
        item_group = tuple(config_data_2_qi.keys())
        parameter = tuple(config_data_2_qi.values())
        njqca_config_query_battery = """
        SELECT variant_9 from `tabNJQCA Child` where item_group = %s and parent =%s"""
        
        njqca_config_query_battery_data= frappe.db.sql(njqca_config_query_battery,(item_group[0],self.name),as_dict=True)
        
        njqca_config_query_ram = """
        SELECT variant_6 from `tabNJQCA Child` where item_group = %s and parent =%s"""
        
        njqca_config_query_ram_data= frappe.db.sql(njqca_config_query_ram,(item_group[1],self.name),as_dict=True)
        
        njqca_config_query_storage = """
        SELECT variant_10 from `tabNJQCA Child` where item_group = %s and parent =%s"""
        
        njqca_config_query_storage_data= frappe.db.sql(njqca_config_query_storage,(item_group[2],self.name),as_dict=True)
        field_name_check_sql_1 = """
            SELECT options.quality_check
                FROM `tabNJ Quality Checks` qc
                LEFT JOIN `tabNj QC Options` options
                ON qc.name = options.parent
                INNER JOIN `tabNJ QC Check List` qc_check
                ON options.quality_check = qc_check.name
                AND qc_check.diagnostic_type = 'Automatic'
                WHERE qc.item_group in %s AND qc.inspection_type = %s  AND qc_check.njqca_parameter='Config' AND qc_check.parameter in %s """
        field_name_data_1 = frappe.db.sql(field_name_check_sql_1, (item_group, inspection_type, parameter), as_dict=True)
        def extract_numeric_and_suffix(value):
            if value is None or value.strip() == '':
                return None, ''  # Handle None and empty strings
            match = re.match(r'(\d+)\s*(.*)', value)
            if match:
                numeric_value = int(match.group(1))
                suffix = match.group(2).strip()
                return numeric_value, suffix
            return None, '' 

        check_mapping = {
            0: { "query_data": njqca_config_query_battery_data, "variant_field": "variant_9", "item_group": item_group[0] },  # Battery
            1: { "query_data": njqca_config_query_ram_data, "variant_field": "variant_6", "item_group": item_group[1] },  # RAM
            2: { "query_data": njqca_config_query_storage_data, "variant_field": "variant_10", "item_group": item_group[2] }  # Storage
        }

        for idx, field in enumerate(field_name_data_1):
            name_of_check = field['quality_check']
            
            child_exists = any(
                child.item_group in config_data_2_qi and child.check_name == name_of_check
                for child in new_qi.nj_quality_checks
            )

            if child_exists:
                continue

            if idx in check_mapping:
                query_data = check_mapping[idx]['query_data']
                variant_field = check_mapping[idx]['variant_field']
                item_group_value = check_mapping[idx]['item_group']

                options_value = ''
                max_suffix = ''  

                if query_data and query_data[0].get(variant_field) is not None:
                    if idx == 1 or idx == 2:  # RAM or Storage
                        numeric_values_with_suffix = [extract_numeric_and_suffix(x[variant_field]) for x in query_data if extract_numeric_and_suffix(x[variant_field])[0] is not None]
                        if numeric_values_with_suffix:
                            max_value, max_suffix = max(numeric_values_with_suffix, key=lambda x: (x[0], x[1]))  # Consider both numeric and suffix
                            options_value = f"{max_value} {max_suffix}".strip()  # Ensure no extra spaces
                    else:  # Other cases
                        options_value = query_data[0][variant_field]

                if options_value:
                    child_table = new_qi.append("nj_quality_checks", {})
                    child_table.check_name = name_of_check
                    # child_table.checks = field_name
                    child_table.options = options_value
                    child_table.item_group = item_group_value
        
        # for data in self.njqca_result_parameters:
        #     field_name_check_sql = """
        #         SELECT options.quality_check
        #         FROM `tabNJ Quality Checks` qc
        #         LEFT JOIN `tabNj QC Options` options
        #         ON qc.name = options.parent
        #         INNER JOIN `tabNJ QC Check List` qc_check
        #         ON options.quality_check = qc_check.name
        #         AND qc_check.diagnostic_type = 'Automatic'
        #         WHERE qc.item_group = %s AND qc.inspection_type = %s  AND qc_check.parameter = %s """
        #     field_name_data = frappe.db.sql(field_name_check_sql, (data.get("item_group"), inspection_type,data.get("parameter")), as_dict=True)
        #     if field_name_data and "quality_check" in field_name_data[0]:
        #         quality_check_value = field_name_data[0]["quality_check"] 
                
        #         # Pass it into the SQL query
        #         sql_check_option_automatic = frappe.db.sql("""
        #             SELECT check_options, score 
        #             FROM `tabQC Options` 
        #             WHERE parent = %s
        #         """, quality_check_value, as_dict=True)
                
        #     for field in field_name_data:
        #         name_of_check = field['quality_check']
        #         child_exists = any(
        #             child.item_group == data.get("item_group") and child.check_name == name_of_check
        #             for child in new_qi.nj_quality_checks
        #         )

        #         if not child_exists:
        #             child_table = new_qi.append("nj_quality_checks", {})
        #             child_table.check_name = field['quality_check']
        #             # child_table.checks = field_name
        #             child_table.item_group = data.get("item_group")
        #             child_table.options = data.get("value")
        for data in self.njqca_result_parameters:

            field_name_check_sql = """
                SELECT options.quality_check
                FROM `tabNJ Quality Checks` qc
                LEFT JOIN `tabNj QC Options` options
                ON qc.name = options.parent
                INNER JOIN `tabNJ QC Check List` qc_check
                ON options.quality_check = qc_check.name
                AND qc_check.diagnostic_type = 'Automatic'
                WHERE qc.item_group = %s AND qc.inspection_type = %s AND qc_check.parameter = %s
            """
            field_name_data = frappe.db.sql(field_name_check_sql, (data.get("item_group"), inspection_type, data.get("parameter")), as_dict=True)
            item_group_idx= frappe.db.sql("""
                SELECT item_group_idx
                FROM `tabNj Quality Readings`
                WHERE item_group = %s AND parent = %s""", (data.get("item_group"), new_qi.name), as_dict=True)
            item_group_idx_value = 0
            
            if item_group_idx:
                item_group_idx_value = int(item_group_idx[0]['item_group_idx'])

            if field_name_data:
                for field in field_name_data:
                    name_of_check = field["quality_check"]
                    sql_check_option_automatic = frappe.db.sql("""
                        SELECT check_options, score 
                        FROM `tabQC Options` 
                        WHERE parent = %s
                    """, name_of_check, as_dict=True)

                    # Fetch existing child table entries into a set for comparison
                    existing_entries = {
                        (child.item_group, child.check_name)
                        for child in new_qi.nj_quality_checks
                    }
                    # Check if the current data exists
                    if (data.get("item_group"), name_of_check) not in existing_entries:
                        child_table = new_qi.append("nj_quality_checks", {})
                        child_table.check_name = name_of_check
                        child_table.item_group = data.get("item_group")
                        # Default to data.get('value')
                        child_table.options = data.get('value')
                        if item_group_idx_value:
                            child_table.item_group_idx = item_group_idx_value

                    if sql_check_option_automatic:
                        for option in sql_check_option_automatic:
                            option_score = float(option["score"]) if option["score"] is not None else None
                            data_score = float(data.get("score")) if data.get("score") else None

                            if option_score == data_score:
                                
                                # Check if this combination already exists
                                if (data.get("item_group"), name_of_check) not in existing_entries:
                                    child_table = new_qi.append("nj_quality_checks", {})
                                    child_table.check_name = name_of_check
                                    child_table.item_group = data.get("item_group")
                                    child_table.options = option["check_options"]
                                    if item_group_idx_value:
                                        child_table.item_group_idx = item_group_idx_value
                                    existing_entries.add((data.get("item_group"), name_of_check))  # Add to the set to prevent further duplicates
                                break

        new_qi.save()

        if new_qi.name:
            njpulse_url = frappe.get_value("NJ Settings", {'parameter': 'njpluse_url_for_qi'}, "value")
            if not njpulse_url:
                frappe.throw("NJPulse URL is not found in NJ Settings.")
            if self.pwd:
                njpulse_url = njpulse_url + "api/authenticate?usr=" + self.created + "&pwd=" + self.pwd + "&encrypted_pwd=True&doctype_url=qi/" + new_qi.name

            return {"qi_name": new_qi.name, "njpulse_url": njpulse_url}
        else:
            return None

    except Exception as e:
        frappe.throw(f"error in saving NJ QI {str(e)}\n{traceback.format_exc()}")
        return None
    
@frappe.whitelist()
def get_itm_code_on_barcode(new_qi):
    barcode = new_qi.barcode
    if not barcode:
        return {"error":"barcode not found"}

    # Fetch Serial No details
    serial_no_data = frappe.db.get_value("Serial No", {"name": barcode},["item_code", "bios_serial_no", "item_group", "item_name", "warehouse", "purchase_rate", "purchase_date"],
                                         as_dict=True)
    if not serial_no_data:
        frappe.throw(_("Serial No '{0}' not found. Please select an existing Serial No.").format(barcode))
    
    result = {
        "item_code": serial_no_data.item_code,
        "bios_serial_number": serial_no_data.bios_serial_no,
        "item_group": serial_no_data.item_group,
        "item_name": serial_no_data.item_name,
        "warehouse": serial_no_data.warehouse,
        "base_price": serial_no_data.purchase_rate
    }

    for key,value in result.items():
        new_qi.set(key,value)
    
    # Check if the item group is a component
    is_component = frappe.db.get_value('Item Group', serial_no_data.item_group, 'is_component')

    if is_component == 0:
        preferred_prices = update_total_preferred_grade_a(barcode)
        attribute_values = preferred_prices.get("attribute_values")
        new_qi.set("preferred_a_grade_price",preferred_prices.get("preferred_a_grade_price"))
        for key in attribute_values:
            new_qi.set(key,attribute_values.get(key))
        result.update(preferred_prices)

    current_date = datetime.date.today()
    serial_item_date = serial_no_data.purchase_date
    difference = (current_date - serial_item_date).days

    if serial_no_data.item_group in ["laptops", "desktops", "chromebooks", "chromeboxes"] and difference < 0 and serial_no_data.purchase_date > datetime.strptime("2024-03-20", "%Y-%m-%d"):
        if serial_no_data.bios_serial_no and serial_no_data.bios_serial_no.startswith('nj') and serial_no_data.bios_serial_no == barcode:
            frappe.msgprint(_("Barcode and BIOS serial number should not both start with 'nj' and be identical. Please insert Dongle and run."))
            return {"disable_save": True}
        
        elif serial_no_data.bios_serial_no and serial_no_data.bios_serial_no != barcode:
            return {"enable_save": True}
        
        elif not serial_no_data.bios_serial_no or serial_no_data.bios_serial_no != barcode:
            frappe.msgprint(_("BIOS serial number not found for Serial No: <b>{0}</b>. Please insert Dongle and run.").format(barcode))
            return {"disable_save": True}

    if serial_no_data.warehouse:
        emp_data = get_active_emp(frappe.session.user)
        work_warehouse = emp_data.get('work_warehouse')
        if not work_warehouse:
            frappe.msgprint(_("Work Warehouse is not set for Employee: <b>{0}</b>").format(frappe.session.user))
        
        elif work_warehouse != serial_no_data.warehouse:
            material_transfer_items = [{
                'serial_no': barcode,
                't_warehouse': work_warehouse,
                'item_code': serial_no_data.item_code,
                's_warehouse': serial_no_data.warehouse,
            }]
            data = {
                "doctype": new_qi.doctype,
                "series": "NJ-QI-.YYYY.-.MM.-",
                "reference_serial_no": barcode,
                "stock_entry_type": "Material Transfer",
                "material_transfer_items": material_transfer_items
            }

            stock_entry_using_nj_lib(data)
            result['warehouse'] = work_warehouse
            new_qi.set('warehouse',work_warehouse)

    else:
        frappe.msgprint(_("Warehouse is not updated in Serial No: <b>{0}</b>").format(barcode))
        return {"disable_save": True}
    
    return new_qi

@frappe.whitelist()
def fill_nj_quality_reading_from_serial_or_itm_wizard(new_qi, inspection_type, is_defective="0"):
    barcode = new_qi.barcode
    if not barcode:
        frappe.throw("Error: Barcode is not found.")

    if not inspection_type:
        frappe.throw("Error: Inspection Type is not found.")
    
    response = frappe._dict()
    
    response = validation_for_nj_readings_in_nj_qi(barcode,inspection_type,is_defective)

    doc_data = response.get('doc_data')

    if response.get('sequence_list_for_nj_readings_data'):
        nj_quality_readings = []
        for nj_readings_data in response.get('sequence_list_for_nj_readings_data'):
            if nj_readings_data.get('quality_check'):
                nj_quality_readings.append({
                    'item_group': nj_readings_data.get('item_group'),
                    'quality_check': nj_readings_data.get('quality_check'),
                    'item': nj_readings_data.get('item'),
                    'item_group_idx': nj_readings_data.get('item_group_idx'),
                    'part_serial_no': nj_readings_data.get('part_serial_no'),
                    'previous_grade': nj_readings_data.get('previous_grade'),
                    'available_qty': nj_readings_data.get('available_qty'),
                    'previous_reference_doctype': nj_readings_data.get('previous_reference_doctype'),
                    'previous_reference_doctype_no': nj_readings_data.get('previous_reference_doctype_no')
                })
        # Clear existing table entries and add new ones
        new_qi.set('nj_quality_readings', [])
        for reading in nj_quality_readings:
            new_qi.append('nj_quality_readings', reading)
    
    if response.get('initial_mandatory_rows'):
        new_qi.set('mandatory_rows', response.get('initial_mandatory_rows'))
    

    if doc_data and doc_data[0].get('item_wizard'):
        new_qi.set('item_wizard', doc_data[0].get('item_wizard'))
    
    new_qi.save()
    
    base_url = frappe.get_value("NJ Settings", {'parameter': 'njpluse_url_for_qi'}, "value")
    if not base_url:
        frappe.throw("NJPulse URL is not found in NJ Settings.")
    njqi_link = f"{base_url}qi/{new_qi.name}/0"
    
    frappe.msgprint(f"NJ Quality readings updated successfully..!! for the QI  <strong><a href='{njqi_link}' target='_blank' > {new_qi.name}</a></strong> ")
   
    return True 

class NJQCA(Document):
    def on_submit(self):
        if self.power_on == 'Yes' and self.repack_item_code != '':
            if self.manual_repack_item_code is None or self.manual_repack_item_code == '':
                frappe.throw("Please fill the Manual Repack Item Code. If there is no option to fill Please Contact NPD Team")
                return None
            
            if self.item_template:
                tmp_model = frappe.db.get_value('Item', self.item_template, 'item_model')
                itm_model = frappe.db.get_value('Item', self.manual_repack_item_code, 'item_model')
                if tmp_model and tmp_model != self.model:
                    frappe.throw("Model: " + tmp_model + " in Item Template is not matching with Selected Model: " + self.model)
                    return None
                
                if itm_model and itm_model != self.model:
                    frappe.throw("Model: " + itm_model + " in Manual Repack Item Code is not matching with Selected Model: " + self.model)
                    return None
            
            try:
                check_item_code_vs_model_validation(self.manual_repack_item_code, self.model)
                if self.item_code != self.manual_repack_item_code:
                    self.make_stock_entry_using_nj_lib()
                open_draft_qi(self)
                update_serial_no_componont_for_grade(self)
                # update_serial_no_component_for_njqca(self)

            except Exception as e:
                frappe.db.rollback()
                frappe.throw("Error during submission: " + str(e))

    def make_stock_entry_using_nj_lib(self):

        accounting_cost_account = frappe.db.get_single_value('NewJaisa Configuration', 'default_operational_cost_account')
        stock_data = {
            "name": self.name,
            "doctype": self.doctype,
            "series": "NJ-STE-NJQCA-",
            "stock_entry_type": "Repack",
            "repack_items": get_repack_items(self),
            "expense_account": accounting_cost_account
        }
        stock_data_str = json.dumps(stock_data)
        stock_entry_using_nj_lib(stock_data_str)

def get_repack_items(self):
    get_repack_items_list = []

    get_repack_items_dict = {
		"repack_item_code": self.item_code,
		"repack_serial_no": self.serial_no,
		"repack_item_base_price": self.base_price,
        "repack_item_source_warehouse": self.warehouse,
	}
    get_repack_items_list.append(get_repack_items_dict)

    get_unpack_items_dict = {
        "unpack_serial_no": self.serial_no,
        "unpack_item_base_price": self.base_price,
        "unpack_item_target_warehouse": self.warehouse,
        "unpack_item_code": self.manual_repack_item_code,
    }
    get_repack_items_list.append(get_unpack_items_dict)

    return get_repack_items_list

@frappe.whitelist()
def model_change_for_serial_no(newmodel, serial_no):

    wizard_query = """Select name from `tabItem Wizards` where model = %s 
                    and part_list_status = 'Completed' order by modified desc"""
    new_item_wizard = frappe.db.sql(wizard_query, (newmodel), as_dict=1)

    qi_exists = """select name from `tabNJ Quality Inspection` where barcode = %s"""
    kitting_exists = """select name from `tabKitting` where serial_no = %s"""
    mpc_exists = """select name from `tabMachine Part Changes` where serial_no = %s"""
    mr_exists = """select parent from `tabMaterial Request Item` where serial_no = %s"""

    qi_exists_data = frappe.db.sql(qi_exists, (serial_no), as_dict=1)
    kitting_exists_data = frappe.db.sql(kitting_exists,serial_no,as_dict=1)
    mpc_exists_data = frappe.db.sql(mpc_exists,serial_no,as_dict=1)
    mr_exists_data = frappe.db.sql(mr_exists,serial_no,as_dict=1)

    serial_no_doc = frappe.get_doc('Serial No', serial_no)

    if qi_exists_data == [] and kitting_exists_data == [] and mpc_exists_data == [] and mr_exists_data == []:
        if new_item_wizard != []:
            item_wizard_doc = frappe.get_doc("Item Wizards",new_item_wizard[0]['name'])
            if item_wizard_doc.part_list_status != 'Completed':
                frappe.throw(f"'Part List' in Item Wizard: {new_item_wizard[0]['name']} is not completed. Please contact NPD Team.")
            if newmodel:
                serial_no_doc.serial_no_component = []
                serial_no_doc.save()
                update_component_in_serial_no(item_wizard_doc, serial_no_doc, newmodel)
                return { "status": 'success' }
        else:
            frappe.throw(f'Item Wizard is not there for Model <b>{newmodel}</b>. Please Contact NPD Team')
    else:

        new_item_wizard_query = """Select component_type,default_item_code from `tabComponent` where parent = %s"""
        new_item_wizard_data = frappe.db.sql(new_item_wizard_query, (new_item_wizard[0]['name']), as_dict=1)

        Item_code = frappe.db.get_value('Serial No', {'serial_no':serial_no}, 'item_code')
        if Item_code:
            item_template = frappe.db.get_value('Item', {'name':Item_code}, 'variant_of')

            if item_template:
                item_wizard = get_latest_item_wizard(item_template, Item_code)
                old_item_wizard_query = """select component_type,default_item_code from `tabComponent` where parent = %s"""
                old_item_wizard_data = frappe.db.sql(old_item_wizard_query, (item_wizard), as_dict=1)
                not_matched_item_groups = []
                for old in old_item_wizard_data:
                    for new in new_item_wizard_data:
                        if old.get('component_type') == new.get('component_type'):
                            if old.get('default_item_code') == new.get('default_item_code'):
                                continue
                            else:
                                not_matched_item_groups.append(old.get('component_type'))

                if not not_matched_item_groups:
                    item_wizard_doc = frappe.get_doc("Item Wizards",new_item_wizard[0]['name'])
                    serial_no_doc.serial_no_component = []
                    serial_no_doc.save()
                    update_component_in_serial_no(item_wizard_doc, serial_no_doc, newmodel)
                    return { "status": 'success' }
                else:
                    mr_data_query ="""select distinct(item_group) from `tabMaterial Request Item` where serial_no = %s AND post_order_status !='Completed' AND docstatus = 1"""
                    past_part_list_query = """select distinct(item_group) from `tabPast Part List` where parent = %s"""
                    mr_item_group_data = frappe.db.sql(mr_data_query, (serial_no), as_dict=1)
                    past_part_list_data = frappe.db.sql(past_part_list_query, (serial_no), as_dict=1)
                    if past_part_list_data:
                        for group in past_part_list_data:
                            if group['item_group'] in not_matched_item_groups:
                                frappe.throw(f'Item Group <b>{group["item_group"]}</b> is in Past Part List.Cannot change Model and Part List. Please contact NPD Team.')
                                return { "status": 'failed' }
                    for group in mr_item_group_data:
                        if group['item_group'] in not_matched_item_groups:
                            frappe.throw(f'Item Group <b>{group["item_group"]}</b> MR is Raised.Cannot change Model and Part List. Please contact NPD Team.')
                            return { "status": 'failed' }
                    else:
                        item_wizard_doc = frappe.get_doc("Item Wizards",new_item_wizard[0]['name'])
                        serial_no_doc.serial_no_component = []
                        serial_no_doc.save()
                        update_component_in_serial_no(item_wizard_doc, serial_no_doc, newmodel)
                        return { "status": 'success' }

            else:
                frappe.throw(f'There is no template for Item Code: <b>{Item_code}</b>.<br>Please contact <b>NPD Team</b>.')
        else:
            frappe.throw(f'Item Code {Item_code} not found in Serial No {serial_no}')

@frappe.whitelist()
def brand_model_validation(brand=None, model=None):
    brand = frappe.db.exists('Brand', {'name': brand})
    model = frappe.db.exists('Models', {'name': model})
    
    return {'brand': brand, 'model': model}

@frappe.whitelist()
def get_info_from_serial_no(doc=None):
    try:
        sle = []
        result = {}
        doc_json = json.loads(doc)
        bio_serial_no_in_ui = None

        emp_dept = get_active_emp(frappe.session.user, fields=['department'])

        if 'bios_serialno' in doc_json:
            bio_serial_no_in_ui = doc_json['bios_serialno']

            sql_query = """
                SELECT name,item_code, warehouse, purchase_rate,
                    bios_serial_no, model, item_group, brand
                FROM `tabSerial No`
                WHERE bios_serial_no = %s and status = 'Active' """

            sle = frappe.db.sql(sql_query, (bio_serial_no_in_ui), as_dict=1)

        if 'serial_no' in doc_json and not sle:

            serial_no = doc_json['serial_no']
            # get price from Stock Ledger Entry

            sql_query = """
                SELECT name,item_code, warehouse, purchase_rate,
                    bios_serial_no, model, item_group, brand
                FROM `tabSerial No`
                WHERE serial_no = %s and status = 'Active' """

            sle = frappe.db.sql(sql_query, (serial_no), as_dict=1)

            if sle and len(sle) > 0:
                sle_entry = sle[0]
                if sle_entry.get('bios_serial_no'):
                    if sle_entry.get('bios_serial_no') != bio_serial_no_in_ui:
                        frappe.throw(f"BIOS Serial No is not matching for Serial No: <b>{serial_no}</b>.")
                    else:
                        frappe.db.sql("""UPDATE `tabSerial No` SET bios_serial_no = %s WHERE serial_no = %s""", (bio_serial_no_in_ui,serial_no))

        if sle and len(sle) > 0:
            sle_entry = sle[0]
            item_code_data = frappe.get_value('Item', {'name': sle_entry.get('item_code')}, ['valuation_rate', 'item_model', 'brand', 'variant_of'], as_dict=1)
            result['serial_no'] = sle_entry.get('name')
            result['item_code'] = sle_entry.get('item_code')
            result['warehouse'] = sle_entry.get('warehouse')
            result['base_price'] = sle_entry.get('purchase_rate')
            result['item_template'] = item_code_data.get('variant_of')
            result['repack_itm_price'] = item_code_data.get('valuation_rate')
            result['department'] = emp_dept.get('department') if 'department' in emp_dept else None
            result['brand'] = sle_entry.get('brand') if sle_entry.get('brand') else item_code_data.get('brand')
            result['model'] = sle_entry.get('model') if sle_entry.get('model') else item_code_data.get('item_model')
            result['item_group'] = sle_entry.get('item_group') if sle_entry.get('item_group') else item_code_data.get('item_group')
            result['inspection_type'] = get_inspection_type() if not 'inspection_type' in doc_json else doc_json['inspection_type']

        sudden_drop = get_sudden_drop(doc_json['name'], doc_json['item_group'])

        if sudden_drop:
            result['sudden_drop'] = sudden_drop

        return result
    except Exception as e:
        return f"Error on submit: {str(e)}\n{traceback.format_exc()}"

@frappe.whitelist()
def after_save_njqca(docname):
    doc = frappe.get_doc("NJQCA", docname)
    if doc.bios_serialno:

        if doc.power_on == 'Yes':
            qi_draft_data = open_draft_qi(doc) 
            return qi_draft_data
        elif doc.power_on == 'No':
            frappe.msgprint(f"QI Draft is not created for Serial No: <b>{doc.serial_no}</b>.")

    else:
        frappe.throw(f"BIOS Serial No is not found for Serial No: <b>{doc.serial_no}</b>.")

def get_item_code_for_each_part(doc):
    item_group, item_template = '', ''
    part_data, part_mapping, child_attr_data = [], [], []

    try:
        if isinstance(doc, str):
            try:
                doc = json.loads(doc)
            except json.JSONDecodeError:
                frappe.throw("Invalid JSON string provided for doc.")

        parent_part_mapping = frappe.get_all( "Part Mapping",
            filters={"parent": doc.get('item_group')},
            fields=["item_group", "mappng_fields", "attribute_name"],
            order_by="idx"
        )

        for parent_row in parent_part_mapping:
            part_item_group = parent_row.get('item_group')

            part_mapping = frappe.get_all( "Part Mapping",
                filters={"parent": part_item_group},
                fields=["item_group", "mappng_fields", "attribute_name"],
                order_by="idx"
            )

            for row in doc.get('njqca_item_component', []):
                attribute_object = {}
                attribute_value = {}
                
                for mapping in part_mapping:
                    last_variant_values = {}
                    item_group = row.get('item_group')

                    if item_group == mapping.get('item_group'):
                        
                        if not mapping.get('mappng_fields'): continue
                        if mapping.get('mappng_fields'):
                            variants = mapping.get('mappng_fields').split('::')
                            for variant in variants:
                                last_variant_values[item_group] = last_variant_values.get(item_group, {})
                                last_variant_values[item_group][variant] = row.get(variant)
                            attribute_value = last_variant_values.get(item_group, {})
                            
                        if item_group.lower() == cpu.lower():
                            any_undefined = any(value is None for value in attribute_value.values())
                            cpu_value = unk_cpu if any_undefined else list(attribute_value.values())[0]
                            normalize_cpu = normalize_gen(cpu_value)
                            if normalize_cpu and len(normalize_cpu) > 0:
                                attribute_object[mapping.get('attribute_name')] = normalize_cpu[0]

                        elif item_group.lower() == ram.lower() and (row.get('variant_1') != 'SYSTEM MEMORY' and row.get('variant_1') != '[EMPTY]'):

                            if part_item_group == item_group:
                                if variant == 'variant_6':
                                    if 'GB' not in row.get(variant):
                                        continue
                                    else:
                                        attribute_object[mapping.get('attribute_name')] = row.get(variant)
                                        
                                if variant == 'variant_7':
                                    if row.get(variant) == '26':
                                        attribute_object[mapping.get('attribute_name')] = 'DDR4'
                                    elif row.get(variant) == '23':
                                        attribute_object[mapping.get('attribute_name')] = 'DDR3'
                                    elif 'ddr' in row.get(variant).lower():
                                        attribute_object[mapping.get('attribute_name')] = row.get(variant)
                                
                                if variant == 'variant_8':
                                    match = re.search(r'\d+', row.get(variant))
                                    if match:
                                        attribute_object[mapping.get('attribute_name')] = f"{match.group()} GHZ"
                                    else:
                                        attribute_object[mapping.get('attribute_name')] = 'UNKNOWN SPEED'
                            
                            else:
                                if variant == 'variant_6':
                                    if 'GB' not in row.get(variant):
                                        continue
                                    else:
                                        attribute_object[mapping.get('attribute_name')] = row.get(variant)
                        
                        elif item_group.lower() == storage.lower() and (row.get('variant_10') or not row.get('variant_1')) and attribute_value.get(list(attribute_value.keys())[0]):
                            
                            variant_type = ''
                            
                            if (row.get('variant_1') is not None and 'ssd' in row.get('variant_1', '').lower()) or \
                            (row.get('variant_6') is not None and ('nvme' in row.get('variant_6', '').lower() or 'ssd' in row.get('variant_5', '').lower())):
                                variant_type = ' SSD'

                            if variant == 'variant_1':

                                if 'interface' in mapping.get('attribute_name').lower():
                                    interfaces = {
                                        'SATA': ['sata', 'sata3', 'sata2', 'sata1', 'hdd', 'ssd'],
                                        'MSATA': ['msata'],
                                        'M.2 SATA': ['m.2 sata', 'ngff'],
                                        'M.2 NVME': ['m.2 nvme', 'nvme'],
                                        'M.2 PCL': ['pcl', 'pcie'],
                                    }

                                    for interface, keywords in interfaces.items():
                                        for keyword in keywords:
                                            if keyword in row.get(variant):
                                                attribute_object[mapping.get('attribute_name')] = interface
                                    
                                elif 'type' in mapping.get('attribute_name').lower():
                                    nj_types = {
                                        'SATA I': ['sata1', 'sata-1'],
                                        'SATA II': ['sata2', 'sata-2'],
                                        'SATA III': ['sata3', 'sata-3'],
                                        'MSATA': ['msata', 'm.2 msata'],
                                        'M.2 SATA 2280': ['m.2 sata 2280', 'm.2 sata', 'ngff 2280'],
                                        'M.2 SATA 2242': ['m.2 sata 2242', 'ngff 2242'],
                                        'M.2 NVMe 2280': ['m.2 nvme 2280', 'nvme 2280', 'pcie 2280'],
                                        'SSD': ['ssd', 'solid state drive'],
                                        'HDD': ['hdd', 'hard drive', 'harddisk'],
                                    }

                                    for nj_type, keywords in nj_types.items():
                                        for keyword in keywords:
                                            if keyword in row.get(variant):
                                                attribute_object[mapping.get('attribute_name')] = nj_type
                                            elif (row.get('variant_5') is not None and 'ssd' in row.get('variant_5', '').lower()):
                                                attribute_object[mapping.get('attribute_name')] = row.get('variant_5')
                                 
                            if variant == 'variant_10':
                                attribute_object[mapping.get('attribute_name')] = row.get(variant) + variant_type
                                
                set_part_data(item_group, attribute_object, row, part_data, doc)

        parent_item_group = doc.get('item_group')

        if parent_item_group:
            parent_filters = frappe.get_list("Part Mapping",
                filters={"parent": doc.get('item_group')},
                fields=["attribute_name"],
                order_by="idx"
            )

            parent_attribute_names = [item['attribute_name'] for item in parent_filters]

            for item in part_data:
                attr_data = item.get('attr_data', {})

                filtered_result = {key: attr_data[key] for key in parent_attribute_names if key in attr_data}
                
                if filtered_result:
                    child_attr_data.append(filtered_result)

            if doc.get('item_template'):
                consolidated = consolidate_ram_capacities(child_attr_data)
                consolidated = consolidate_storage(consolidated)
                repack_item_code = get_variant_from_value(item_template, consolidated)

                return {'data_attr': consolidated, 'repack_item_code': repack_item_code, 'part_data': part_data}
            else:
                return {'error': f'Item Template not found'}

    except Exception as e:
        frappe.throw("An error occurred: " + str(e))
        return {"error": f"An error occurred: {str(e)}"}
    
def set_part_data(part_item_group, attribute_object, row, part_data, doc):
    item_template = frappe.db.get_value('Item',
        {'item_group': part_item_group, 'has_variants': 1}, 'name' )
    
    attribute_object['Grade'] = Grade

    if len(attribute_object) > 1:
        part_item_code = get_variant_from_value(item_template, [attribute_object])
        if part_item_code and 'error' not in part_item_code:
            part_item_code_from_db = frappe.db.get_value("Item",
                {'item_name': part_item_code, 'has_variants': 0, 'item_group': part_item_group},
                'name' )
            
            if part_item_code_from_db:
                item_template = frappe.db.get_value( 'Item', {'name': part_item_code}, 'variant_of' )
                part_data.append({
                    'name': row.get('name'),
                    'attr_data': attribute_object,
                    'part_item_code': part_item_code,
                    'item_group': part_item_group,
                    'item_template': item_template
                })
        else:
            part_item_code = frappe.db.get_value('Serial No Component',
                                {'parent': doc.get('serial_no'), 'item_group' : part_item_group},
                                ['item'])
            item_template = frappe.db.get_value('Item', 
                                {'item_code': part_item_code, 'has_variants': 0, 'disabled': 0}, ['variant_of'])
            part_data.append({
                'name': row.get('name'),
                'part_item_code': part_item_code,
                'attr_data': attribute_object,
                'item_group': part_item_group,
                'item_template': item_template,
                'response': 'error'
            })
        
@frappe.whitelist()
def get_part_mapping(doc):
    
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except json.JSONDecodeError:
            frappe.throw("Invalid JSON string provided for part mapping.")

    if doc.get('njqca_item_component') and doc.get('item_group'):

        try:
            nj_settings = frappe.get_all("NJ Settings", filters={"doc_type": "NJQCA Child"},
                                fields=["parameter", "value"])

            for param in nj_settings:
                globals()[param.parameter] = param.value
            
            return json.dumps(get_item_code_for_each_part(doc))
            
        except Exception as e:
            frappe.throw(f"An error occurred: {str(e)}{str(traceback.format_exc())}")

def consolidate_ram_capacities(data):
    consolidated_data,ram_consolidation = [], {}

    for obj in data:
        for key, value in obj.items():
            if key.lower() == ram_capacity.lower():
                ram_value = value

                match = re.match(r'^(\d+)\s*GB\s*(\w+)?', ram_value, re.IGNORECASE)
                if match:
                    amount, type_ = match.groups()
                    total_amount = int(amount)
                    type_ = type_ or ''
                    
                    existing_value = ram_consolidation.get(key)
                    if existing_value:
                        existing_match = re.match(r'^(\d+)\s*GB\s*(\w+)?', existing_value, re.IGNORECASE)
                        if existing_match:
                            existing_amount, existing_type = existing_match.groups()
                            existing_type = existing_type or ''
                            
                            if existing_type.upper() == type_.upper():
                                ram_consolidation[key] = f"{int(existing_amount) + total_amount} GB {existing_type.strip()}"
                            else:
                                frappe.msgprint(f"Different RAM Type is not allowed")
                                return
                    else:
                        ram_consolidation[key] = ram_value
            else:
                consolidated_data.append({key: value})

    for key, value in ram_consolidation.items():
        consolidated_data.append({key: value})

    return consolidated_data

def consolidate_storage(data):
    storage_parts = []
    total_storage_capacity = 0
    storage_type = None 
    result_data = []
    
    for obj in data:
        for key, value in obj.items():
            if key.lower() == 'storage capacity':
                if 'SSD' in value.upper():
                    if storage_type and storage_type != 'SSD':
                        raise ValueError("Mix of SSD and HDD is not allowed")
                    storage_type = 'SSD'
                elif 'HDD' in value.upper():
                    if storage_type and storage_type != 'HDD':
                        raise ValueError("Mix of SSD and HDD is not allowed")
                    storage_type = 'HDD'
                
                match = re.match(r'^(\d+)\s*(TB|GB)\s*(SSD|HDD)?', value, re.IGNORECASE)
                if match:
                    amount = int(match.group(1))
                    unit = match.group(2).upper()
                    storage_kind = match.group(3) if match.group(3) else ""
                    
                    if unit == 'TB':
                        total_storage_capacity += amount * 1024
                        storage_parts.append(f"{amount} TB {storage_kind}")
                    elif unit == 'GB':
                        total_storage_capacity += amount
                        storage_parts.append(f"{amount} GB {storage_kind}")
                else:
                    result_data.append(obj)
            else:
                result_data.append(obj)
    
    if storage_parts:
        storage_parts.sort() 
        consolidated_storage = []
        current_capacity = 0
        
        for part in storage_parts:
            match = re.match(r'(\d+)\s*(TB|GB)\s*(SSD|HDD)?', part, re.IGNORECASE)
            if match:
                amount = int(match.group(1))
                unit = match.group(2)
                storage_kind = match.group(3) if match.group(3) else ""
                
                if unit == 'GB':
                    current_capacity += amount
                elif unit == 'TB':
                    current_capacity += amount * 1024

        if current_capacity >= 1024:
            tb_part = current_capacity // 1024
            gb_part = current_capacity % 1024
            if gb_part > 0:
                consolidated_storage.append(f"{tb_part} TB - {gb_part} GB {storage_kind}")
            else:
                consolidated_storage.append(f"{tb_part} TB {storage_kind}")
        else:
            consolidated_storage.append(f"{current_capacity} GB {storage_kind}")
        
        if len(consolidated_storage) > 1:
            result_data = [item for item in result_data if 'Storage Capacity' not in item]
            result_data.append({'Storage Capacity': ' - '.join(consolidated_storage)})
        else:
            result_data = [item for item in result_data if 'Storage Capacity' not in item]
            result_data.append({'Storage Capacity': consolidated_storage[0]})

    return result_data
                    
def normalize_gen(cpu_value):
    match = None
    if 'core' in cpu_value.lower():
        match = re.search(r"(\bI\d+)-([A-Za-z0-9]+)", cpu_value, re.IGNORECASE)
        
        if match:
            core = 'CORE ' + match.group(1).upper()
            alphanumeric_part = match.group(2)
            
            numeric_part = ''.join(filter(str.isdigit, alphanumeric_part))
            gen_number = str(int(numeric_part) // 1000)  # Extract the generation number
            
            if gen_number == '1':
                gen_number += 'ST'
            elif gen_number == '2':
                gen_number += 'ND'
            elif gen_number == '3':
                gen_number += 'RD'
            else:
                gen_number += 'TH'
            
            return [f"{core} - {gen_number} GEN"]

    if 'ryzen' in cpu_value.lower():
        match = re.match(r"([\w\s]+)(?=\s\d)", cpu_value, re.IGNORECASE)
        if match:
            return [match.group(1).upper()]
        
    if 'amd' in cpu_value.lower() and 'ryzen' not in cpu_value.lower():
        match = re.match(r"([\w\s]+)-([\w\d]+)", cpu_value, re.IGNORECASE)
    
        if match:
            return [match.group(1).upper()]
        
    cpu_value_upper = cpu_value.upper()
    if not match:
        for cpu_type in ['XEON', 'PENTIUM', 'ATOM']:
            if cpu_type in cpu_value_upper:
                return [f"INTEL {cpu_type}"]

    return []
    
@frappe.whitelist()
def get_variant_from_value(item_template=None, args=None):
    args_list = []
    if args:
        args_list = frappe.parse_json(args)

    if item_template and args_list:
        conditions = []

        for condition_dict in args_list:
            for key, value in condition_dict.items():
                normalized_value = value
                conditions.append(f"MAX(attribute = '{key.lower()}' AND attribute_value = '{normalized_value.lower()}') = 1")

        having_clause = " AND ".join(conditions)
        
        if having_clause:
            query = """
                SELECT parent FROM `tabItem Variant Attribute`
                WHERE variant_of = %s GROUP BY parent HAVING {}
            """.format(having_clause)
            variants = frappe.db.sql(query, (item_template,), as_dict=True)
            if variants and variants[0]['parent']:
                return variants[0]['parent']
            else:
                item_code = construct_item_code(item_template, args_list)
                return item_code

    return None

@frappe.whitelist()
def construct_item_code(item_template, args_list):
    try:
        if isinstance(args_list, str):
            args_list = frappe.parse_json(args_list)
        concatenated_string = item_template

        for condition_dict in args_list:
            for key, value in condition_dict.items():
                concatenated_string += f"-{value}"

        query = """
            SELECT item_code FROM `tabItem`
            WHERE item_code = %s and has_serial_no = 1 and disabled = 0
        """

        item_code = frappe.db.sql(query, (concatenated_string,), as_dict=True)

        if item_code:
            return item_code[0]['item_code']
        else:
            return {'error': concatenated_string}

    except Exception as e:
        print(f"An error occurred at construct_item_code: {str(e)}")

@frappe.whitelist()
def get_model(manufacturer_model):
    query, model_list = '', []

    if model_list == []:
        query = """SELECT DISTINCT mmc.parent AS model
                   FROM `tabManufacturer Model Child` AS mmc
                   LEFT JOIN `tabMake Child` AS mc ON mc.parent = mmc.parent
                   WHERE mmc.manufacturer_model = %s"""
        params = (manufacturer_model)
        model_list = frappe.db.sql(query, params, as_dict=True)
        if not model_list:
            frappe.msgprint(f"Manufacturer Model: <strong>{manufacturer_model}</strong> not found. Please contact <strong>NPD department</strong> for mapping the model.")

    return model_list
    
@frappe.whitelist()
def get_templates_by_model_and_brand(model=None, brand=None, item_group=None):
    template_query = """
        SELECT name FROM `tabItem` WHERE item_model = %s
        AND brand = %s AND item_group = %s AND has_variants = 1
    """

    templates = frappe.db.sql(template_query, (model, brand, item_group), as_dict=True)

    if templates:
        return templates[0].name
    else:
        return None
    
@frappe.whitelist()
def get_manual_repack_item_code_filtered_data(item_group, brand, model=None):
    if model:
        manual_repack_item_code_query = "SELECT name from `tabItem` where item_group = %(item_group)s AND brand = %(brand)s AND item_model = %(model)s AND has_variants = 0"
        manual_repack_item_code = frappe.db.sql(manual_repack_item_code_query, {'item_group': item_group, 'brand': brand, 'model': model})
    else:
        manual_repack_item_code_query = "SELECT name from `tabItem` where item_group = %(item_group)s AND brand = %(brand)s"
        manual_repack_item_code = frappe.db.sql(manual_repack_item_code_query, {'item_group': item_group, 'brand': brand})
    
    manual_repack_item_code = [item[0] for item in manual_repack_item_code]

    return manual_repack_item_code

@frappe.whitelist()
def get_part_item_code_filtered_data(item_group):
    get_part_item_code_query = """SELECT name FROM `tabItem` 
            WHERE item_group = %(item_group)s AND has_variants = 0 AND disabled = 0"""
    
    return frappe.db.sql(get_part_item_code_query, {'item_group': item_group})

@frappe.whitelist()
def get_sudden_drop(parent_name, item_group):
    try:
        njqca_battery_item_group = frappe.db.get_value('NJ Settings', {'parameter': 'njqca_battery_item_group'}, 'value')
        if njqca_battery_item_group == item_group:

            delta_query="""WITH FilteredResults AS (
                            SELECT value, idx 
                            FROM `tabNJQCA Result Parameters`
                            WHERE idx >= (
                                SELECT idx 
                                FROM `tabNJQCA Result Parameters`
                                WHERE parent = %(parent_name)s 
                                AND parameter = (
                                    SELECT value 
                                    FROM `tabNJQCA Result Parameters`
                                    WHERE parent = %(parent_name)s
                                        AND parameter = 'Battery_Discharging_Start_Time'
                                    ORDER BY idx DESC LIMIT 1
                                )
                            )
                            AND parameter <> 'Battery_Discharging_Start_Time'
                            AND parent = %(parent_name)s
                            ORDER BY idx
                        )
                        SELECT MAX(delta) AS max_delta, AVG(delta) AS avg_delta
                        FROM (
                            SELECT value - LEAD(value) OVER (ORDER BY idx) AS delta
                            FROM FilteredResults
                        ) AS DeltaValues"""
            
            delta = frappe.db.sql(delta_query, {'parent_name': parent_name}, as_dict=True)
            delta = delta[0]
            
            if not delta or delta.get('max_delta') is None or delta.get('avg_delta') is None:
                return "Yes"
            elif(float(delta.get('max_delta'))<3*float(delta.get('avg_delta'))):
                return f"No, max_delta: {delta.get('max_delta')}, avg_delta: {delta.get('avg_delta')}"
            else:
                return f"Yes, max_delta: {delta.get('max_delta')}, avg_delta: {delta.get('avg_delta')}"
        else:
            return None
            
    except Exception as e:
        return e
        
@frappe.whitelist()
def get_njqca_item_template(item_group, brand, model):
    try:
        wizard_list, item_templates = '', None

        item_templates = get_item_template(brand, model, item_group)
        if item_templates:
            wizard_list = has_item_wizards(item_templates)
            
        return {'item_template': item_templates, 'wizard_list': wizard_list}
    
    except Exception as e:
        frappe.throw(f"An error occurred at get_njqca_item_template: {str(e)}")
        return None

@frappe.whitelist()
def get_serial_no_attribute_data(serial_no):
    """
    Fetch item code for Adaptor and Display based on Serial No.
    """
    adap_dis_item_code = frappe.db.get_all(
        'Serial No Component',
        filters={
            'parent': serial_no,
            'item_group': ('in', ['Display', 'Laptop Adaptors'])
        },
        fields=['item', 'item_group', 'grade', 'quantity'],
    )
    for item in adap_dis_item_code:
        item['item_template'] = frappe.db.get_value('Item', item['item'], 'variant_of')
    
    if adap_dis_item_code:
        return adap_dis_item_code
    return None

@frappe.whitelist()
def update_serial_no_component_for_njqca(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)

    serial_no_doc = frappe.get_doc("Serial No", doc.get('serial_no'))

    attribute_table = [
        {
            "item_group": item.get('item_group'),
            "calculated_item_code": item.get('calculated_item_code'),
            "reference_doctype": item.get('parent'),
            "docname": item.get('parenttype'),
            "grade": item.get('grade'),
        }
        for section in ['njqca_display', 'njqca_laptop_ram', 'njqca_laptop_storage', 'njqca_adaptor']
        for item in doc.get(section, [])
    ]

    existing_item_groups = [component['item_group'] for component in attribute_table]
    serial_no_doc.serial_no_component = [
        sn for sn in serial_no_doc.serial_no_component if sn.item_group not in existing_item_groups
    ]

    for component in attribute_table:
        serial_no_doc.append("serial_no_component", {
            "item_group": component.get('item_group', ''),
            "item": component.get('calculated_item_code', ''),
            "grade": component.get('grade', ''),
            "reference_doctype_no": component.get('reference_doctype', ''),
            "reference_doctype": component.get('docname', ''),
            "is_available" : 1,
            "quantity": 1
        })

    for index, row in enumerate(serial_no_doc.serial_no_component, start=1):
        row.idx = index

    serial_no_doc.save()

@frappe.whitelist()
def get_item_code_filtered_data(doctype, txt, searchfield, start, page_len, filters):
    txt = ''
    parent = filters.get('parent')

    filters_data = [ ["parent", "=", parent] ]

    return frappe.get_all(
        "Item Attribute Value",
        filters=filters_data,
        fields=["attribute_value"],
        as_list=1,
        or_filters=[ ["attribute_value", "like", f"%{txt}%"] ]
    )

@frappe.whitelist()
def get_result_parameter(name, item_group, parameter):
    result = frappe.db.sql("""SELECT value FROM `tabNJQCA Result Parameters` 
                        WHERE item_group = %(item_group)s 
                        AND parameter = %(parameter)s AND parent = %(name)s""", 
                        {'name': name, 'item_group': item_group, 'parameter': parameter}, as_dict=True)
    
    if result:
        value = result[0].get('value')
        base_url = get_url()
        return f"{base_url}/app/file/{value}"
    else:
        return None