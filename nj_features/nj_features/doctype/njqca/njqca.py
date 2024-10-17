import re
import json
import frappe
import datetime
from frappe import _
from frappe.model.document import Document
from nj_lib.utils.common_utils import get_active_emp,get_latest_item_wizard
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
from nj_p1_features.overrides.serial_no import update_component_in_serial_no
from nj_features.nj_features.doctype.inward.inward import get_item_template,has_item_wizards
from nj_features.nj_features.report.actual_qty_by_warehouse_owner.actual_qty_by_warehouse_owner import execute
from nj_p1_features.nj_p1_features.doctype.nj_quality_inspection.nj_quality_inspection import validation_for_nj_readings_in_nj_qi,update_total_preferred_grade_a

# logger = frappe.logger("NJQCA",allow_site = True ,file_count = 1)

def update_serial_no_componont_for_grade(self):
    try:
        serial_no_doc = frappe.get_doc("Serial No", self.serial_no)

        # serial_no_doc = frappe.get_doc("Serial No", {'serial_no': self.serial_no})
        # serial_no_doc.preferred_a_grade_price = self.preferred_a_grade_price
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
        
        # Save the Serial No document first
        serial_no_doc.save()
    except Exception as e:
        return {f'Error while updating the Serial No Component: {str(e)}'}

@frappe.whitelist()
def get_inspection_type():
    department = frappe.db.get_value('Employee', {'user_id': frappe.session.user}, 'department')
    inspection_type= frappe.db.get_value('Department', {'name': department}, 'inspection_type')
    if inspection_type:
        return inspection_type
    

def open_draft_qi(self):
    # user_email = frappe.session
    inspection_type = get_inspection_type()
    if not inspection_type:
        inspection_type = self.inspection_type
    self.inspection_type = inspection_type
    existing_qi = frappe.get_list('NJ Quality Inspection', filters={'barcode': self.serial_no, 'inspection_type':inspection_type, 'docstatus': 0}, limit=1)
    if existing_qi:
        # Get the existing document
        new_qi = frappe.get_doc('NJ Quality Inspection', existing_qi[0].name)
    else:
        new_qi = frappe.new_doc('NJ Quality Inspection')
        
        new_qi.inspection_type = self.inspection_type    
        new_qi.barcode = self.serial_no
        new_qi.njqca_laptop_name = self.name
        new_qi.inspected_by = new_qi.owner
        if self.manual_repack_item_code :
            new_qi.item_code = self.manual_repack_item_code
            new_qi.item_name = self.manual_repack_item_code
    
    result = get_itm_code_on_barcode(new_qi)

    fill_nj_quality_reading_from_serial_or_itm_wizard(new_qi, inspection_type, is_defective="0")
    item_wizard_name = new_qi.get('item_wizard')
    item_group_data =''
    if item_wizard_name :
        component_type = """
        SELECT component_type from `tabComponent` where parent = %s"""
        component_type_data = frappe.db.sql(component_type,(item_wizard_name,),as_dict= True)
        item_group_data = [a['component_type'] for a in component_type_data]
        
    config_data_2_qi = frappe.db.get_value("NJ Settings",{"doc_type": "NJQCA","parameter":"config"},"value")

    config_data_2_qi = json.loads(config_data_2_qi)
   
    
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
    # logger.debug("njqca_config_query_storage_data-------------",njqca_config_query_storage_data,"njqca_config_query_ram_data--------",njqca_config_query_ram_data,"njqca_config_query_battery_data-----------",njqca_config_query_battery_data)
    field_name_check_sql_1 = """
          SELECT options.quality_check
            FROM `tabNJ Quality Checks` qc
            LEFT JOIN `tabNj QC Options` options
            ON qc.name = options.parent
            INNER JOIN `tabNJ QC Check List` qc_check
            ON options.quality_check = qc_check.name
            AND qc_check.diagnostic_type = 'Automatic'
            WHERE qc.item_group in %s AND qc.inspection_type = %s  AND qc_check.njqca_parameter='Config' AND qc_check.parameter in %s """
    field_name_data_1 = frappe.db.sql(field_name_check_sql_1, (item_group, inspection_type,parameter), as_dict=True)
    # logger.debug("field_name_data_1-----------------njqca----------129",field_name_data_1)
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
    
    for data in self.njqca_result_parameters:
        field_name_check_sql = """
            SELECT options.quality_check
            FROM `tabNJ Quality Checks` qc
            LEFT JOIN `tabNj QC Options` options
            ON qc.name = options.parent
            INNER JOIN `tabNJ QC Check List` qc_check
            ON options.quality_check = qc_check.name
            AND qc_check.diagnostic_type = 'Automatic'
            WHERE qc.item_group = %s AND qc.inspection_type = %s  AND qc_check.parameter = %s """
        field_name_data = frappe.db.sql(field_name_check_sql, (data.get("item_group"), inspection_type,data.get("parameter")), as_dict=True)
        for field in field_name_data:
            name_of_check = field['quality_check']
            child_exists = any(
                child.item_group == data.get("item_group") and child.check_name == name_of_check
                for child in new_qi.nj_quality_checks
            )

            if not child_exists:
                child_table = new_qi.append("nj_quality_checks", {})
                child_table.check_name = field['quality_check']
                # child_table.checks = field_name
                child_table.item_group = data.get("item_group")
                child_table.options = data.get("value")

    
    new_qi.save()
    
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
    if not barcode or not inspection_type:
        frappe.throw("Error: Barcode or Inspection Type is not found.")
    
    response = frappe._dict()
    
    response = validation_for_nj_readings_in_nj_qi(barcode,inspection_type,is_defective)
    
    if response.get('sequence_list_for_nj_readings_data'):
        nj_quality_readings = []
        for nj_readings_data in response.get('sequence_list_for_nj_readings_data'):
            if nj_readings_data.get('quality_check'):
                nj_quality_readings.append({
                    'item_group': nj_readings_data.get('item_group'),
                    'quality_check': nj_readings_data.get('quality_check'),
                    'item': nj_readings_data.get('item'),
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
        new_qi.save()
    
    if response.get('initial_mandatory_rows'):
        new_qi.set('mandatory_rows', response.get('initial_mandatory_rows'))
    
    if response.get('item_wizard'):
        new_qi.set('item_wizard', response.get('item_wizard'))
    
    new_qi.save()
    base_url = frappe.utils.get_url()
    njqi_link = f"{base_url}/app/nj-quality-inspection/{new_qi.name}"
    frappe.msgprint(f"NJ Quality readings updated successfully..!! for the QI  <strong><a href='{njqi_link}' target='_blank' > {new_qi.name}</a></strong> ")
   
    return True 

class NJQCA(Document):  
  
    def on_submit(self):
        if self.manual_repack_item_code is None or self.manual_repack_item_code == '':
            frappe.throw("Please fill the Manual Repack Item Code. If there is no option to fill Please Contact NPD Team")   
        if self.power_on == 'Yes' and self.repack_item_code != '':
            self.make_stock_entry_using_nj_lib()
            open_draft_qi(self)
    
    
    def make_stock_entry_using_nj_lib(self):

        accounting_cost_account = frappe.db.get_single_value('NewJaisa Configuration', 'default_operational_cost_account')
        stock_data = {
            "name": self.name,
            "item_code": self.item_code,
            "stock_entry_type": "Repack",
            "doctype": self.doctype,
            "series": "NJ-STE-NJQCA-",
            "serial_no": self.serial_no,
            "repack_items": get_repack_items(self),
            "expense_account": accounting_cost_account
        }
        stock_data_str = json.dumps(stock_data)
        print("\n\nstock_data",stock_data)
        stock_entry_using_nj_lib(stock_data_str)


# def stock_entry_for_material_transfer_or_repack_items_data(self):
#     stock_entry_for_material_transfer_or_repack_items_list = []
#     stock_entry_for_material_transfer_or_repack_items_dict = {
#         "item_code": self.item_code,
#         "basic_rate": self.base_price,
#         "serial_no": self.serial_no,
#     }
#     stock_entry_for_material_transfer_or_repack_items_list.append(stock_entry_for_material_transfer_or_repack_items_dict)
#     return stock_entry_for_material_transfer_or_repack_items_list


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
        "unpack_item_code": self.manual_repack_item_code,
        "unpack_serial_no": self.serial_no,
        "unpack_item_base_price": self.base_price,
        "unpack_item_target_warehouse": self.warehouse
    }
    get_repack_items_list.append(get_unpack_items_dict)
    
    return get_repack_items_list
 

@frappe.whitelist()
def after_save_njqca(docname):
    doc = frappe.get_doc("NJQCA", docname)
    if doc.bios_serialno:
        update_serial_no_componont_for_grade(doc)
        # department = frappe.db.get_value('Employee', {'user_id': frappe.session.user}, 'department')
        # department_setting = frappe.db.get_value("NJ Settings",{"doc_type": "NJQCA","parameter":"department"},"value")
        
        if doc.power_on == 'Yes':
            open_draft_qi(doc) 
            # self.save()
        elif doc.power_on == 'No':
            frappe.throw(f"QI Draft is not created for Serial No: <b>{doc.serial_no}</b>.")
        # else:
        #     frappe.throw(f"Your Department ' {department} 'is not allocated to do QI")
    else:
        frappe.throw(f"BIOS Serial No is not found for Serial No: <b>{doc.serial_no}</b>.")

@frappe.whitelist()
def model_change_for_serial_no(newmodel,serial_no):
    wizard_query = """Select name from `tabItem Wizards` where model = %s and part_list_status = 'Completed' order by modified desc"""

    item_wizard = frappe.db.sql(wizard_query, (newmodel), as_dict=1)
    qi_exists = """
    select name from `tabNJ Quality Inspection` where barcode = %s
    """
    kitting_exists = """
    select name from `tabKitting` where serial_no = %s
    """
    qi_exists_data = frappe.db.sql(qi_exists, (serial_no), as_dict=1)
    kitting_exists_data = frappe.db.sql(kitting_exists,serial_no,as_dict=1)
    if qi_exists_data == [] and kitting_exists_data == []:
        if item_wizard != []:
            item_wizard_doc = frappe.get_doc("Item Wizards",item_wizard[0]['name'])
            serial_no_doc = frappe.get_doc('Serial No', serial_no)
            if item_wizard_doc.part_list_status != 'Completed':
                frappe.throw(f"'Part List' in Item Wizard: {item_wizard[0]['name']} is not completed. Please contact NPD Team.")
            if newmodel:
                serial_no_doc.serial_no_component = []
                update_component_in_serial_no(item_wizard_doc, serial_no_doc, newmodel)
                return {
                    "status": 'success',
                }
        else:
            frappe.throw(f'Item Wizard is not there for Model <b>{newmodel}</b>. Please Contact NPD Team')
    else:
        frappe.msgprint(f"Part List Cannot be changed for Serial No <b>{serial_no}</b>. Because NJ QI or Kitting is Done")
            

@frappe.whitelist()
def brand_model_validation(brand=None, model=None):

    brand = frappe.db.exists('Brand', {'name': brand})
    model = frappe.db.exists('Models', {'name': model})
    
    return {'brand': brand, 'model': model}


@frappe.whitelist()
def get_info_from_serial_no(doc=None):
    result = {}
    doc_json = json.loads(doc)
    if doc_json:
        serial_no = doc_json['serial_no']
        serial_no_doc = frappe.get_doc('Serial No', {'name': serial_no}) # NJ - serial_no
        # get price from Stock Ledger Entry
        sql_query = """
            SELECT 
                item_code, warehouse, purchase_rate
            FROM
                `tabSerial No`
            WHERE
                serial_no = %s
        """
        sle = frappe.db.sql(sql_query, (serial_no), as_dict=1)
        
        
        if serial_no_doc:
            sle_entry = sle[0]
            repack_itm_price = frappe.get_value('Item', {'name': sle_entry.get('item_code')}, 'valuation_rate')

            result['item_code'] = sle_entry.get('item_code')
            result['model'] = serial_no_doc.model
            result['item_group'] = serial_no_doc.item_group
            result['brand'] = serial_no_doc.brand
            result['warehouse'] = sle_entry.get('warehouse')
            result['repack_itm_price'] = repack_itm_price
            result['base_price'] = sle_entry.get('purchase_rate')
    return result


def get_item_code_for_each_part(part_item_group,doc):
    try:
        item_template = ''
        part_mapping = frappe.get_all("Part Mapping", filters={"parent": part_item_group}, 
        fields=["item_group", "mappng_fields", "attribute_name"], order_by="idx")
        part_data = []
        child_attr_data = []
        for row in doc.njqca_item_component:
            
            attribute_object = {}
            for mapping in part_mapping:
                last_variant_values = {}
                item_group = row.item_group

                if item_group == mapping.item_group :
                    if mapping.mappng_fields:
                        variants = mapping.mappng_fields.split('::')
                        attribute_value = {}
                        for variant in variants:
                            last_variant_values[item_group] = last_variant_values.get(item_group, {})
                            last_variant_values[item_group][variant] = row.get(variant)
                        attribute_value = last_variant_values[item_group]

                    # getting value from NJ Settings - - creating cpu by concating "Core I5" and "7 GEN" as "Core I5 - 7TH GEN"
                    if item_group.lower() == cpu.lower():
                        any_attribute_undefined = any(value is None for value in attribute_value.values())
                        cpu_value = unk_cpu if any_attribute_undefined else ' - '.join(attribute_value.values())
                        normalize_cpu = normalize_gen(cpu_value)
                        attribute_object[mapping.attribute_name] = normalize_cpu

                    elif item_group.lower() == ram.lower() and (row.variant_1 != 'SYSTEM MEMORY' and row.variant_1 != '[EMPTY]'):
                        any_attribute_undefined = any(value is None for value in attribute_value.values())
                        ram_value = unk_ram if any_attribute_undefined else ' '.join(attribute_value.values())
                        attribute_object[mapping.attribute_name] = ram_value
                        if part_item_group == item_group :
                            if ram_speed in attribute_object and attribute_object[ram_speed] == 'UNBUFFERED MHZ':
                                attribute_object[ram_speed] = 'UNKNOWN SPEED'
                                            
                    elif item_group.lower() == storage.lower()  and (row.variant_10 or not row.variant_1) and attribute_value.get(list(attribute_value.keys())[0]) :
                        attribute_object[mapping.attribute_name] = attribute_value[list(attribute_value.keys())[0]] + " SSD" or unk_storage
                        if part_item_group == item_group :
                            attribute_object = set_storage_item_code(attribute_object)

                    if attribute_object and item_group != part_item_group:
                        child_attr_data.append(attribute_object)


            if part_item_group == item_group == mapping.item_group:
                item_template = frappe.db.get_value('Item',{'item_group':part_item_group,'has_variants':1},'name')
                attribute_object['Grade'] = Grade 
                if len(attribute_object) > 1 :
                    part_item_code = get_variant_from_value(item_template, [attribute_object])
                    if part_item_code and 'error' not in part_item_code:
                        part_item_code_from_db = frappe.db.get_value("Item",{'item_name':part_item_code,'has_variants':0,'item_group':part_item_group},'name')
                        if part_item_code_from_db:
                            part_data.append({'name':row.name,'attr_data':attribute_object,'part_item_code':part_item_code})
                            
        if part_item_group != doc.item_group :
            return part_data
        if part_item_group == doc.item_group :
            item_template = doc.get('item_template')
            item_template_exists = frappe.db.get_value('Item',{'item_name':item_template,'item_group':part_item_group,'has_variants':1},'name')
            if item_template_exists:
                consolidated = consolidate_ram_capacities(child_attr_data)
                repack_item_code = get_variant_from_value(item_template, consolidated)
                return {'data_attr': json.dumps(consolidated), 'repack_item_code': repack_item_code}
            else:
                return {"error" : f'Item Template {item_template} not found' }

    except Exception as e:
        return {"Error": f"Error raised {str(e)}"}
@frappe.whitelist()
def get_part_mapping(item_group, docname,model,item_template):
    doc = frappe.get_doc("NJQCA", docname)
    doc.model = model
    doc.item_template = item_template
    part_data = []
    if doc.njqca_item_component and doc.item_group:
        part_mapping = frappe.get_all("Part Mapping", filters={"parent": item_group}, 
        fields=["item_group", "mappng_fields", "attribute_name"], order_by="idx")
        nj_settings = frappe.get_all("NJ Settings", filters={"doc_type": "NJQCA Child"},
        fields=["parameter", "value"])

        for param in nj_settings:
            globals()[param.parameter] = param.value

        for part in part_mapping:
            result = get_item_code_for_each_part(part.get("item_group"),doc)
            if result and 'error' not in result:
                part_data.extend(result)
        repack_item_code = get_item_code_for_each_part(item_group,doc)
        repack_item_code['part_data'] = json.dumps(part_data)
        print('repack_item_code====================',repack_item_code)
        return repack_item_code


def consolidate_ram_capacities(data):
    consolidated_data = {}

    for obj in data:
        for key, value in obj.items():
            if key.lower() == ram_capacity.lower(): # getting value from NJ Settings
                ram_value = value
                
                match = re.match(r'^(\d+)\s*GB\s*(\w+)?', ram_value, re.IGNORECASE)

                if match:
                    amount, type_ = match.groups()
                    total_amount = int(amount)

                    if key in consolidated_data:
                        existing_parts = consolidated_data[key].split(' ', 1)
                        if len(existing_parts) == 2:
                            existing_amount, existing_type = existing_parts
                            
                            existing_type_without_unit = existing_type.replace('GB', '').strip()
                            
                            
                            if existing_type_without_unit.upper() == type_.upper():
                                consolidated_data[key] = f"{int(existing_amount) + total_amount} {existing_type}"
                            else:
                                frappe.msgprint(f"Different RAM Type is not allowed")
                                return
                        else:
                            consolidated_data[key] = f"{existing_parts[0]} GB, {amount} GB {type_.upper()}"
                    else:
                        consolidated_data[key] = ram_value
            else:
                consolidated_data[key] = value

    result = [{key: value} for key, value in consolidated_data.items()]
    
    return result

def consolidate_storage(data):
    total_storage_capacity = 0
    
    for obj in data:
        for key, value in obj.items():
            if key.lower() == 'storage capacity':
                if value and value.lower() != 'no storage':
                    match = re.match(r'^(\d+)\s*GB', value, re.IGNORECASE)
                    if match:
                        storage_amount = int(match.group(1))
                        total_storage_capacity += storage_amount
    
    return total_storage_capacity
def set_storage_item_code(obj):
    if obj :
        for key,value in obj.items():
            if value and value.lower() != 'no storage' :
                if key.lower() == 'storage type':
                    if value in "NVME DISK SSD ATA DISK SSD DISK SSD SCSI DISK SSD":
                        obj[key] = NVME_DISK
                if key.lower() == 'storage interface':
                    storage_interface_values = frappe.get_all("Item Attribute Value",{'parent':key},'abbr')
                    abbr_values = [value['abbr'] for value in storage_interface_values]
                    value = value.split("@")[0]
                    obj[key] = next((attr for attr in abbr_values if value in attr), None)
                        
        if len(obj) == 3:
            obj[storage_interface] = '2.5"'
    return obj
                
                    
def normalize_gen(gen_str):
    gen_pattern = r'(CORE [iI]\d+.*?)\s+(\d+)\s+GEN'

    match = re.search(gen_pattern, gen_str)

    if match:
        processor_type = match.group(1)
        gen_number = match.group(2)
        if gen_number == '1':
            gen_number = '1ST'
        elif gen_number == '2':
            gen_number = '2ND'
        elif gen_number == '3':
            gen_number = '3RD'
        else:
            gen_number += 'TH'

        normalized_gen = f"{processor_type} {gen_number} GEN"
        return normalized_gen
    else:
        return gen_str
    
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

def construct_item_code(item_template, args_list):
    concatenated_string = item_template
    for condition_dict in args_list:
        for key, value in condition_dict.items():
            concatenated_string += f"-{value}"
    query = """
        SELECT item_code FROM `tabItem`
        WHERE item_code = %s and has_serial_no = 1
    """

    item_code = frappe.db.sql(query, (concatenated_string,), as_dict=True)
    if item_code:
        return item_code[0]['item_code']
    else:
        return {'error': concatenated_string}

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
    get_part_item_code_query = "SELECT name from `tabItem` where item_group = %(item_group)s AND has_variants = 0"
    return frappe.db.sql(get_part_item_code_query, {'item_group': item_group})

@frappe.whitelist()
def get_backup_duration(parent_name, item_group):
    records=[]
    nj_settings_item_group = frappe.db.get_value('NJ Settings', {'parameter': 'show_backup'}, 'value')
    sudden_drop = frappe.db.get_value('NJ Settings', {'parameter': 'sudden_drop'}, 'value')

    if nj_settings_item_group == item_group:

        get_first_last_record_query = """
                                    SELECT parameter, value 
                                    FROM `tabNJQCA Result Parameters` 
                                    WHERE parent = %(parent_name)s 
                                    ORDER BY idx 
                                """
        records = frappe.db.sql(get_first_last_record_query, {'parent_name': parent_name}, as_list=True)

        if len( records)>2:
            time_format = "%H:%M:%S"
            try:
                time1_dt = datetime.datetime.strptime(records[0][0], time_format)
                time2_dt = datetime.datetime.strptime(records[len(records)-1][0], time_format)
        
                time_difference = abs(time2_dt - time1_dt)
            
            except ValueError as e:
            
                time_difference=None
            
            if(int(records[len(records)-1][1])>15):
                return time_difference, "Yes"

            i = 1
            while i < len(records):
                try:
                    previous_percentage = int(records[i-1][1])
                except ValueError:
                    i += 1
                    continue  

                try:
                    current_percentage = int(records[i][1])
                except ValueError:
                    i += 1
                    try:  
                        current_percentage = int(records[i][1])
                    except IndexError:
                        break
                
                change = previous_percentage - current_percentage
                if change >= int(sudden_drop):
                    return time_difference, "Yes"  
                
                i += 1 

            return time_difference,"No" 
    
        else:
            return None , None
    
@frappe.whitelist()
def get_njqca_item_template(item_group, brand, model):
    wizard_list = ''
    item_template = get_item_template(brand, model, item_group)
    if item_template:
        wizard_list = has_item_wizards(item_template)
        
    return {'item_template': item_template, 'wizard_list': wizard_list}