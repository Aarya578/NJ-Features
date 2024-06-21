# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import json
import random
import frappe
from frappe import _
import datetime
# import frappe.frappe
from frappe.model.document import Document
import re
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
from nj_p1_features.nj_p1_features.doctype.nj_quality_inspection.nj_quality_inspection import validation_for_nj_readings_in_nj_qi,update_total_preferred_grade_a
from nj_features.nj_features.report.actual_qty_by_warehouse_owner.actual_qty_by_warehouse_owner import execute

def update_serial_no_componont_for_grade(self):
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
        # print('reading value is ', reading,'\n',dir(reading))
        if reading.item_group not in  [s.item_group for s in serial_no_doc.serial_no_component] :
            row = serial_no_doc.append('serial_no_component', {})
            row.item = reading.part_item_code
            row.item_group = reading.item_group
            row.grade = 'UNKNOWN'
            row.is_available = 1
            row.quantity = 1
            # row.reference_doctype = self.doctype
                # row.reference_doctype_no = self.namer
            
        else:
            for sn in serial_no_doc.serial_no_component :
                if reading.item_group == sn.item_group and reading.part_item_code :
                    # print('sn value is ', sn,'\n',dir(sn))
                    sn.item = reading.part_item_code
                    # sn.part_serial_no = reading.part_serial_no
                    # sn.Item = reading.part_item_code  
                    # sn.grade = reading.grade
                    # sn.is_available = reading.is_available
                    # sn.quantity = reading.is_available 
                    # sn.reference_doctype = self.doctype
                    # sn.reference_doctype_no = self.name
    serial_no_doc.save()


# def fill_automated_data_to_checks(self):
    # qc_check.
    
    
    

def open_draft_qi(self):
    inspection_type = frappe.db.get_value('NJ Settings', {'doc_type': 'NJQCA', 'parameter': 'qi_inspection_type'}, 'value')
    self.inspection_type = inspection_type
    # print('The inspectio type value is ',inspection_type)
    existing_qi = frappe.get_list('NJ Quality Inspection', filters={'barcode': self.serial_no,'inspection_type':inspection_type}, limit=1)
    if existing_qi:
        # Get the existing document
        new_qi = frappe.get_doc('NJ Quality Inspection', existing_qi[0].name)
        # print('Existing QI document found:', new_qi.name)
    else:
        new_qi = frappe.new_doc('NJ Quality Inspection')
        
        new_qi.inspection_type = inspection_type    
        new_qi.barcode = self.serial_no
        new_qi.njqca_laptop_name = self.name
        new_qi.inspected_by = new_qi.owner
    
    result = get_itm_code_on_barcode(new_qi)
    # print("chicken 65 new qi is ")
    # for k,v in new_qi.__dict__.items():
    #     print(k,"::::",v) if v else print("",end='')

    fill_nj_quality_reading_from_serial_or_itm_wizard(new_qi, inspection_type, is_defective="0")
    # print("new_qi=====>",new_qi.get('nj_quality_readings',''))
    
    for data in self.njqca_result_parameters:
        field_name_check_sql = """
        SELECT field_name,name_of_check,parameter from  `tabNJ QC Check List` where item_group=%s and parameter=%s"""
        field_name_data = frappe.db.sql(field_name_check_sql,(data.get("item_group"),data.get("parameter")),as_dict=True)
        print("field_name_data====109",field_name_data)
        
        if field_name_data ==[] or field_name_data is  None:
            frappe.throw(f"Automated checks are not created for this Parameter {data.get('parameter')} and Item Group {data.get('item_group')} ,Please contact Your Team Lead")

        child_exists = any(child.item_group == data.get("item_group") and child.check_name == field_name_data[0]['name_of_check'] for child in new_qi.nj_quality_checks)
        # print("child_exists===",child_exists)
        # if field_name_data==[] or field_name_data is None :
        #     frappe.throw(f"Automated checks are not created for this Parameter {data.get('parameter')} and Item Group {data.get('item_group')} ,Please contact Your Team Lead")

        if not child_exists:
            child_table = new_qi.append("nj_quality_checks", {})
            
            if field_name_data :
                child_table.check_name = field_name_data[0]['name_of_check']
                child_table.checks = field_name_data[0]['field_name']
                child_table.item_group  = data.get("item_group")
                child_table.options = data.get("value")
            # elif data.get('parameter') not in field_name_data[0]['parameter'] or field_name_data ==[]:
            #     frappe.throw(f"Automated checks are not created for this Parameter {data.get('parameter')} and Item Group {data.get('item_group')} ,Please contact Your Team Lead")
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
    # print("87 serial no data is ",serial_no_data)
    
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
    # print("curretn date is ",current_date," and the item date is ",serial_item_date )
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
        work_warehouse = frappe.db.get_value('Employee', {'user_id': frappe.session.user}, 'work_warehouse')
        if not work_warehouse:
            frappe.msgprint(_("Work Warehouse is not set for Employee: <b>{0}</b>").format(frappe.session.user))
        elif work_warehouse != serial_no_data.warehouse:
            # Logic to handle stock transfer
            stock_entry_items = [{
                'item_code': serial_no_data.item_code,
                'basic_rate': serial_no_data.purchase_rate,
                'serial_no': barcode
            }]
            data = {
                "serial_no": barcode,
                "stock_entry_type": "Material Transfer",
                "t_warehouse": work_warehouse,
                "series": "STE-NJ-QI-",
                "reference_serial_no": barcode,
                "doctype": "Stock Entry",
                "stock_entry_for_material_transfer_or_repack_items": stock_entry_items
            }
            stock_entry_using_nj_lib(data)
            result['warehouse'] = work_warehouse
            new_qi.set('warehouse',work_warehouse)

    else:
        frappe.msgprint(_("Warehouse is not updated in Serial No: <b>{0}</b>").format(barcode))
        return {"disable_save": True}
    # print("The get_itm_code_on_barcode is returning **** ",result)
    return new_qi



    

@frappe.whitelist()
def fill_nj_quality_reading_from_serial_or_itm_wizard(new_qi, inspection_type, is_defective="0"):
    barcode = new_qi.barcode
    # print("barcode===",barcode)
    if not barcode or not inspection_type:
        frappe.throw("Error: Barcode or Inspection Type is not found.")
    
    response = frappe._dict()
    
    # try:
        # Assuming validation_for_nj_readings_in_nj_qi is the method being called
        
    response = validation_for_nj_readings_in_nj_qi(barcode,inspection_type,is_defective)
    # print('210 The response I"m getting --> ',response)
    # except Exception as e:
    #     frappe.throw(str(e))
    # print("e====",e)
    # print("response===195",response)
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
        # print('193 The nj readings are ',nj_quality_readings)
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
    frappe.msgprint("Quality readings updated successfully.")
    for k,v in new_qi.__dict__.items():
        print(k," :: ",v) if v else print("",end='')
    return True


class NJQCA(Document):  
  
    def on_submit(self):
        # Repack
        # print("self==220",self.njqca_result_parameters)
       
            
        if self.power_on == 'Yes' and self.repack_item_code != '':
            self.make_stock_entry_using_nj_lib()
            
            
            # get_attribute_price, preferred_purchase_price_ = 0, 0
            # get_attribute_value = ''
            # item_doc = frappe.get_doc("Item", {'name': self.repack_item_code})
            # serial_no_doc = frappe.get_doc("Serial No", {'serial_no': self.serial_no})
            # if serial_no_doc:
            #     get_model_price = frappe.db.get_value('Models', {'name': self.model}, 'model_price')
            #     if self.item_group:
            #         get_attribute_value = frappe.db.get_value('NJ Settings', {'parameter': self.item_group}, 'value')
            #     for attr in item_doc.attributes:
            #         attribute_value = frappe.db.get_value('Item Attribute Value', {'parent': attr.attribute, 'attribute_value': attr.attribute_value}, get_attribute_value, 'value', as_dict=1)
            #         print(f"\n\n attribute_value: {attribute_value}")
            #         # if attribute_value[0].value == 0:
            #         #     get_attribute_price += float(attribute_value[0].value)
                        
                        
            #     preferred_purchase_price_ = get_model_price + get_attribute_price
            #     serial_no_doc.preferred_purchase_price_ = preferred_purchase_price_
                
            # if self.bios_serialno:
            #     update_serial_no_componont_for_grade(self)
            #     department = frappe.db.get_value('Employee', {'user_id': frappe.session.user}, 'department')
            #     print("242 The department value is ",department)
            #     if department == "BG - Core IQC - NJ":
            #         open_draft_qi(self) 
            #         # self.save()
            #     else:
            #         print("QI draft will not open \nBecause you not belonging to the IQC Department")
            # else:
            #     frappe.throw(f"BIOS Serial No is not found for Serial No: <b>{self.serial_no}</b>.")
            
            
            
            # serial_no_components = ''
            # for row in self.njqca_item_component:
            #     # print("row.item_code   ------------------", row.item_code)
            #     if row.item_code:
            #         serial_no_components = [x for x in serial_no_doc.serial_no_component if x.item_group == row.item_group]
            #         # print("serial_no_components---------------",serial_no_components)
            #         # Update item_code for each matching Serial No Component entry
            #         for serial_no_component in serial_no_components:
            #             if serial_no_component.default.item_code:
            #                 row.item_code = serial_no_component.default_item_code
            #                 continue
                # else:
                #     serial_no_component.item= ''
        # else:
            # item_template = 'S-'+self.brand+' '+self.model
            # child_attr_data = []

            # for row in self.njqca_item_component:
            #     if row.attr_data:
            #         child_attr_data.append(frappe.parse_json(row.attr_data))

            # # print("child_attr_data:", child_attr_data)
            # data_attr = json.dumps(child_attr_data)
            
            # get_variant_from_value(item_template, data_attr)
            # frappe.throw("You are not allowed to submit NJQCA without system powering on and Repack Item Code")


    
    
    def make_stock_entry_using_nj_lib(self):
        accounting_cost_account = frappe.db.get_single_value('NewJaisa Configuration', 'default_operational_cost_account')
        stock_data = {
            "name": self.name,
            "item_code": self.item_code,
            "stock_entry_type": "Repack",
            "doctype": self.doctype,
            "series": "NJ-STE-NJQCA-",
            "serial_no": self.serial_no,
            "stock_entry_for_material_transfer_or_repack_items": stock_entry_for_material_transfer_or_repack_items_data(self),
            "repack_items": get_repack_items(self),
            # "unpack_items": get_unpack_items(self),
            "expense_account": accounting_cost_account
        }
        stock_data_str = json.dumps(stock_data)
        stock_entry_using_nj_lib(stock_data_str)
        


def stock_entry_for_material_transfer_or_repack_items_data(self):
    stock_entry_for_material_transfer_or_repack_items_list = []
    stock_entry_for_material_transfer_or_repack_items_dict = {
        "item_code": self.item_code,
        "basic_rate": self.base_price,
        "serial_no": self.serial_no,
    }
    stock_entry_for_material_transfer_or_repack_items_list.append(stock_entry_for_material_transfer_or_repack_items_dict)
    return stock_entry_for_material_transfer_or_repack_items_list


def get_repack_items(self):
    get_repack_items_list = []
    get_repack_items_dict = {
		"repack_item_code": self.manual_repack_item_code,
		"serial_no": self.serial_no,
		"repack_base_price": self.base_price,
        "repack_warehouse": self.warehouse
	}
    get_repack_items_list.append(get_repack_items_dict)
    
    return get_repack_items_list
 

@frappe.whitelist()
def after_save(docname):
    print("save method")
    doc = frappe.get_doc("NJQCA", docname)

    if doc.bios_serialno:
        update_serial_no_componont_for_grade(doc)
        department = frappe.db.get_value('Employee', {'user_id': frappe.session.user}, 'department')
        department_setting = frappe.db.get_value("NJ Settings",{"doc_type": "NJQCA","parameter":"department"},"value")
        print("department_setting==",department_setting)
        print("242 The department value is ",department)
        
        if department in department_setting:
            open_draft_qi(doc) 
            # self.save()
        else:
            frappe.throw(f"Your Department ' {department} 'is not allocated to do QI")
    else:
        frappe.throw(f"BIOS Serial No is not found for Serial No: <b>{doc.serial_no}</b>.")
            

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
        # print(f"sle: {sle}, serial_no: {serial_no}")
        
        # purchase_receipt_doc = frappe.db.sql("""
        #     SELECT name AS purchase_receipt, item_code AS item_code, base_rate AS base_rate 
        #     FROM `tabPurchase Receipt Item` 
        #     WHERE serial_no LIKE %s
        # """, ('%' + serial_no + '%'), as_dict=True)
        
        if serial_no_doc:
            sle_entry = sle[0]
            repack_itm_price = frappe.get_value('Item', {'name': sle_entry.get('item_code')}, 'valuation_rate')
            # purchase_price = frappe.get_value('Purchase Receipt', {'name': purchase_receipt_doc[0]['purchase_receipt']}, 'total')

            result['item_code'] = sle_entry.get('item_code')
            result['item_group'] = serial_no_doc.item_group
            result['brand'] = serial_no_doc.brand
            result['warehouse'] = sle_entry.get('warehouse')
            result['repack_itm_price'] = repack_itm_price
            # result['purchase_price'] = purchase_price
            result['base_price'] = sle_entry.get('purchase_rate')
            # result['purchase_receipt'] = purchase_receipt_doc[0]['purchase_receipt']
            if not serial_no_doc.bios_serial_no:
                serial_no_doc.bios_serial_no = doc_json.get('bios_serialno')
                serial_no_doc.barcode = doc_json.get('serialno')
                serial_no_doc.save()
    return result




# get_item_code_for_each_part()





@frappe.whitelist()
def get_part_mapping(item_group, docname):
    doc = frappe.get_doc("NJQCA", docname)
    item_template = f"S-{doc.brand} {doc.model}"
    if doc.njqca_item_component and doc.item_group:
        part_mapping = frappe.get_all("Part Mapping", filters={"parent": doc.item_group}, 
        fields=["item_group", "mappng_fields", "attribute_name"], order_by="idx")

        nj_settings = frappe.get_all("NJ Settings", filters={"doc_type": "NJQCA Child"},
        fields=["parameter", "value"])
        # user_email = frappe.session.user
        # user = frappe.db.get_value("User", user_email, ["email"], as_dict=True)
        # user=user['email']
        # if user:
        #         sql="""SELECT employee_asset_warehouse from `tabEmployee` where prefered_email =%s """
        #         asset_warehouse=frappe.db.sql(sql,(user),as_dict=True)
        #         asset_warehouse=asset_warehouse[0]['employee_asset_warehouse']
        #         # show error msg
        #         sql_query="""SELECT name from `tabSerial No` where warehouse=%s
        #         """
        #         is_serial_no=frappe.db.sql(sql_query,(asset_warehouse),as_list=True)
        #         is_serial_no = [item for sublist in is_serial_no for item in sublist]
        # else:
        #     frappe.throw(f"User's Asset Warehouse {asset_warehouse} is not found ")
        # # error message for not existing user
        last_variant_values = {}
        for param in nj_settings:
            globals()[param.parameter] = param.value
            # user = frappe.db.get_value("User", {"email": user_email}, ["name"])
        # Fetching employee's asset warehouse from Employee doctype based on user's name
        
        # List to store attribute data for each row
        child_attr_data = []
        for row in doc.njqca_item_component:
            for mapping in part_mapping:
                # print("row.variant_2,,,,,,,,,,,,,,,,,,,",row.variant_2)
                # if row.variant_2 in is_serial_no:
                    
                # accept = frappe.db.exists("Serial No", row.variant_2)
                # print(f"Row: {row.name}, accept: {accept}, variant_2: {row.variant_2}") 
                # is_serial_no_available=frappe.db.exists('Serial No',)
                # if accept is None:
                #     row.accept = 'No'
                   
                item_group = row.item_group
                variants = mapping.mappng_fields.split('::')
                
                if item_group == mapping.item_group:
                    # print("now item_group is ",item_group, " mapping.item_group ",mapping.item_group)
                    for variant in variants:
                        last_variant_values[item_group] = last_variant_values.get(item_group, {})
                        last_variant_values[item_group][variant] = row.get(variant)
                    attribute_value = last_variant_values[item_group]
                    attribute_object = {}
                    # getting value from NJ Settings - - creating cpu by concating "Core I5" and "7 GEN" as "Core I5 - 7TH GEN"
                    # print("441 item_group.lower() == cpu.lower() is ",item_group.lower(), cpu.lower())
                    if item_group.lower() == cpu.lower():
                        # if row.variant_2 in is_serial_no:
                        #     print("row.variant_2:::::no processor ",row.variant_2)
                        #     attribute_object[mapping.attribute_name] = "No Processor"
                        # else:  
                        any_attribute_undefined = any(value is None for value in attribute_value.values())
                        cpu_value = unk_cpu if any_attribute_undefined else ' - '.join(attribute_value.values())
                        normalize_cpu = normalize_gen(cpu_value)
                        attribute_object[mapping.attribute_name] = normalize_cpu
                            
                    # getting value from NJ Settings - creating ram by concating "16 GB" and "DDR4" as "16 GB DDR4"
                    elif item_group.lower() == ram.lower() and (row.variant_1 != 'SYSTEM MEMORY' and row.variant_1 != '[EMPTY]'):
                        # if row.variant_2 in is_serial_no:
                        #     print("row.variant_2:::::no ram ",row.variant_2)
                        #     attribute_object[mapping.attribute_name] = "No Ram"
                        # else:
                        any_attribute_undefined = any(value is None for value in attribute_value.values())
                        ram_value = unk_ram if any_attribute_undefined else ' '.join(attribute_value.values())
                        attribute_object[mapping.attribute_name] = ram_value
                    
                                            
                    # getting value from NJ Settings
                    elif item_group.lower() == storage.lower()  and (not row.variant_3 or not row.variant_1) and attribute_value.get(list(attribute_value.keys())[0]) :
                        #  if row.variant_2 in is_serial_no:
                        #     print("row.variant_2:::::no storage ",row.variant_2)
                        #     attribute_object[mapping.attribute_name] = "No Storage"
                        # else:
                        attribute_object[mapping.attribute_name] = attribute_value[list(attribute_value.keys())[0]] + " SSD" or unk_storage
                    
                    
                    row.attr_data = json.dumps(attribute_object)   
                    # print("472 row.attr_Data is ",row.attr_data)         
                    child_attr_data.append(attribute_object)
                    # print("Child attr data is ",child_attr_data)

        consolidated = consolidate_ram_capacities(child_attr_data)
        doc.data_attr = json.dumps(consolidated)
        repack_item_code = get_variant_from_value(item_template, consolidated)
        # print("  doc.data_attr is ",  doc.data_attr," and the repack item code is ",repack_item_code)
        return repack_item_code

def consolidate_ram_capacities(data):
    consolidated_data = {}

    for obj in data:
        for key, value in obj.items():
            if key.lower() == ram_capacity.lower(): # getting value from NJ Settings
                ram_value = value
                
                match = re.match(r'^(\d+)\s*GB\s*(\w+)', ram_value, re.IGNORECASE)

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
    
    # Iterate through the data to sum up storage capacities
    for obj in data:
        for key, value in obj.items():
            if key.lower() == 'storage capacity':
                if value.lower() != 'no storage':
                    # Extract numerical value from the string (e.g., '512 GB SSD')
                    match = re.match(r'^(\d+)\s*GB', value, re.IGNORECASE)
                    if match:
                        storage_amount = int(match.group(1))
                        total_storage_capacity += storage_amount
    
    return total_storage_capacity

def normalize_gen(gen_str):
    gen_pattern = r'(CORE [iI]\d+.*?)\s+(\d+)\s+GEN'

    match = re.search(gen_pattern, gen_str)

    if match:
        processor_type = match.group(1)
        gen_number = match.group(2)
        # print(f"\n processor_type: {processor_type}, gen_number: {gen_number}")
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
    
    if item_template:
        conditions = []

        for condition_dict in args_list:
            for key, value in condition_dict.items():
                normalized_value = value
                conditions.append(f"MAX(attribute = '{key.lower()}' AND attribute_value = '{normalized_value.lower()}') = 1")

        having_clause = " AND ".join(conditions)
        # print(f"\n\nhaving: {having_clause}")
        
        if having_clause:
            query = """
                SELECT parent FROM `tabItem Variant Attribute`
                WHERE variant_of = %s GROUP BY parent HAVING {}
            """.format(having_clause)
            variants = frappe.db.sql(query, (item_template,), as_dict=True)
            # print(f"\n\nhaving: {having_clause}, variant: {variants}")
            if variants and variants[0]['parent']:
                return variants[0]['parent']
            else:
                item_code = construct_item_code(item_template, args_list)
                return item_code

    return None

def construct_item_code(item_template, args_list):
    # Generate the concatenated string
    concatenated_string = item_template
    for condition_dict in args_list:
        for key, value in condition_dict.items():
            # normalized_value = normalize_gen(value)
            concatenated_string += f"-{value}"
    # Query the item_code based on the concatenated string
    query = """
        SELECT item_code FROM `tabItem`
        WHERE item_code = %s and has_serial_no = 1
    """

    item_code = frappe.db.sql(query, (concatenated_string,), as_dict=True)
    # f"\n\n\nitem_code: {item_code}\n")
    if item_code:
        return item_code[0]['item_code']
    else:
        return {'error': concatenated_string}

@frappe.whitelist()
def get_model(manufacturer_model, make=None):
    query, model_list, new_model_list = '', [], []
    if manufacturer_model and make:
        query = """SELECT DISTINCT mmc.parent AS model
                   FROM `tabManufacturer Model Child` AS mmc
                   LEFT JOIN `tabMake Child` AS mc ON mc.parent = mmc.parent
                   WHERE mmc.manufacturer_model = %s AND mc.make = %s"""
        params = (manufacturer_model, make)
    model_list = frappe.db.sql(query, params, as_dict=True)
    # print(f"\n\n if model : {model_list}")

    if model_list == []:
        query = """SELECT DISTINCT mmc.parent AS model
                   FROM `tabManufacturer Model Child` AS mmc
                   LEFT JOIN `tabMake Child` AS mc ON mc.parent = mmc.parent
                   WHERE mmc.manufacturer_model = %s"""
        params = (manufacturer_model)
        model_list = frappe.db.sql(query, params, as_dict=True)
        # print(f"\n\n elif model ----- : {model_list}")
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


# Config_array={'Processor':{"variant01":"i5","variant02":"4thGen"},"RAM":{"variant01":"4GB","variant02":"DDR4"}}
#lap_def={'Processor':["variant01","variant02"],"RAM":["variant01"]}
#i5 4thGen - 4GB
# part_mapping={'LAPTOP PROCESSOR':["variant06","variant07"],"LAPTOP RAM":["variant06"],"LAPTOP STORAGE":["variant10"]}

# class ItemConfig:
#     def __init__(self,config,part_mapping):
#         self.config=config
#         self.part_mapping=part_mapping
        
#     def get_part_config(self,type_data):
#         data_list=[]
#         for i in self.part_mapping[type_data]:
#             data_list.append(self.config[type_data][i])
#         return ' '.join(data_list)
    
#     def get_item_code(self):
#         item_code=[]
#         for part in self.part_mapping:
#             print(f"\npart:  {part}")
#             data=self.get_part_config(part)
#             item_code.append(data)
#         item_code_str='-'.join(item_code)
#         print(f"294 \n\n - item_code_str: {item_code_str}")

# @frappe.whitelist()
# def get_item_code(parent):
    
    # details="""SELECT item_group, variant_1, variant_2, variant_3, variant_4, variant_5,
    #                 variant_6, variant_7, variant_8, variant_9, variant_10, variant_11,
    #                 variant_12, variant_13, variant_14, variant_15, variant_16, variant_17, variant_18, variant_19, variant_20 
    #             FROM `tabNJQCA Child` WHERE item_group IN ('LAPTOP RAM','LAPTOP STORAGE','LAPTOP PROCESSOR') AND parent = %s
    # """
    # data=frappe.db.sql(details,(parent),as_dict=True)
    
    # print(f"\n\ndata in njqca child: {data}")
    
    # extracted_data = {}
    # for item in data:
    #     item_group = item.get("item_group")
    #     variants = {
    #         f"variant{i:02d}": item.get(f"variant_{i}") for i in range(1, 21)
    #     }
    #     if item_group not in extracted_data:
    #         extracted_data[item_group] = []
    #     extracted_data[item_group].append(variants)
    
    # final_output = {}
    # for key, values in extracted_data.items():
    #     for idx, value in enumerate(values, start=1):
    #         item_key = f"{key}_{idx:02}"
    #         final_output[item_key] = value
    
    # final_output = {
    #     "LAPTOP STORAGE":{
    #         "variant01":"NVME DISK",
    #         "variant02":"None",
    #         "variant03":"None",
    #         "variant04":"1",
    #         "variant05":"/DEV/NVME0N1",
    #         "variant06":"None",
    #         "variant07":"GUID:1415D7B5-49D3-40AA-BC24-4CC8A9E2224E",
    #         "variant08":"NVME@0:1",
    #         "variant09":"None",
    #         "variant10":"256 GB",
    #         "variant11":"512",
    #         "variant12":"512",
    #         "variant13":"EUI.002538B571BCC023",
    #         "variant14":"1415D7B5-49D3-40AA-BC24-4CC8A9E2224E",
    #         "variant15":"None",
    #         "variant16":"None",
    #         "variant17":"None",
    #         "variant18":"None",
    #         "variant19":"None",
    #         "variant20":"None"
    #     },
    #     "LAPTOP RAM":{
    #         "variant01":"SYSTEM MEMORY",
    #         "variant02":"None",
    #         "variant03":"None",
    #         "variant04":"3",
    #         "variant05":"DMI:0003",
    #         "variant06":"8 GB",
    #         "variant07":"MEMORY",
    #         "variant08":"None",
    #         "variant09":"SLOT SYSTEM BOARD OR MOTHERBOARD",
    #         "variant10":"None",
    #         "variant11":"None",
    #         "variant12":"None",
    #         "variant13":"None",
    #         "variant14":"None",
    #         "variant15":"None",
    #         "variant16":"None",
    #         "variant17":"None",
    #         "variant18":"None",
    #         "variant19":"None",
    #         "variant20":"None"
    #     },
    #     "LAPTOP PROCESSOR":{
    #         "variant01":"CPU",
    #         "variant02":"INTEL(R) CORE(TM) I5-7300U CPU @ 2.60GHZ",
    #         "variant03":"INTEL",
    #         "variant04":"A",
    #         "variant05":"6.142.9",
    #         "variant06":"CORE I5",
    #         "variant07":"7 GEN",
    #         "variant08":"7300U",
    #         "variant09":"2",
    #         "variant10":"2.60GHZ",
    #         "variant11":"2",
    #         "variant12":"4",
    #         "variant13":"None",
    #         "variant14":"3",
    #         "variant15":"100000000",
    #         "variant16":"U3E1",
    #         "variant17":"None",
    #         "variant18":"None",
    #         "variant19":"None",
    #         "variant20":"None"
    #     }
    # }
    
    # print("\n\nfinal_output:", final_output)

    # a=ItemConfig(final_output, part_mapping)
    # a.get_item_code()

# @frappe.whitelist()
# def get_variant_from_value(item_template=None, args=None):
#     print(f"\n\ntemplate: {item_template}, args: {args}")
#     args_list = []
#     if args:
#         args_list = frappe.parse_json(args)
    
#     if item_template:
#         conditions = []

#         for condition_dict in args_list:
#             for key, value in condition_dict.items():
#                 conditions.append(f"MAX(attribute = '{key.lower()}' AND attribute_value = '{value.lower()}') = 1")

#         having_clause = " AND ".join(conditions)
#         print(f"\n\nhaving: {having_clause}")
#         if having_clause:
#             query = f"""
#                 SELECT parent FROM `tabItem Variant Attribute`
#                 WHERE variant_of = %s
#                 GROUP BY parent
#                 HAVING {having_clause}
#             """
#             variants = frappe.db.sql(query, item_template, as_dict=True)
#             print(f"\n\nhaving: {having_clause}, variant: {variants}")
#             if variants:
#                 return variants[0]['parent']
#         else:
#             return None

# @frappe.whitelist()
# def get_model(manufacturer_model, make):
#     models = frappe.get_all("Models", filters={"njhat_model": manufacturer_model}, fields=["name"])
#     if len(models) == 1:
#         return models[0]['name']
    
#     elif len(models) > 1:
#         makes_list = []
#         for model in models:
#             makes = frappe.get_all("Make Child", filters={"parent": model.name, "make": make}, fields=["parent"])
#             if makes:
#                 makes_list.append(makes[0].parent)
        
#         if len(makes_list) > 0:
#             return makes_list
        
#         else:
#             frappe.throw(f"Match with make: {make} not found")
#     else:
#         frappe.throw("Model not found")

# @frappe.whitelist()
# def create_serial_no(item_code):
#     is_serial = frappe.get_value('Item', {'name': item_code}, 'has_serial_no')
#     if is_serial == 1:
#         new_serial = generate_random_code()
#         return new_serial
#     else:
#         return None

# def generate_random_code():
#     prefix = "NJ"
#     random_code = prefix + str(random.randint(100000, 999999))
#     return random_code

# @frappe.whitelist() # not used
# def get_item_code_price(item_code=None, pr=None):
#     purchase_price = frappe.db.get_value('Purchase Receipt', {'name': pr}, 'total')
#     base_price = frappe.db.get_value('Purchase Receipt Item', {'item_code': item_code, 'parent':pr}, 'base_rate')
#     return {"purchase_price": purchase_price, "base_price": base_price}

# @frappe.whitelist()
# def get_list_of_variants(item_group):
#     item_group_doc = frappe.get_doc('Item Group', item_group)
#     item_attributes = [{'variant': attr.variant} for attr in item_group_doc.variants_of_item_group]
#     return {'variants': item_attributes}

# @frappe.whitelist()
# def get_list_of_attributes(variant):
#     variant_doc = frappe.get_doc('Item Attribute', variant)
#     attribute_list = [attr.attribute_value for attr in variant_doc.item_attribute_values]
#     return {'options': attribute_list}

# @frappe.whitelist()
# def get_attribute_from_item_code(item_code):
#     item_variant_doc = frappe.get_doc('Item Variant Attribute', {'parent': item_code})
#     values = [{'attribute': attr.attribute, 'attribute_value': attr.attribute_value} for attr in item_variant_doc.attributes]
#     return {'options': values}

# def iqc_to_repack_pricing(purchase_price, base_price, repack_itm_price=None): # not used
#     if purchase_price is not None and base_price is not None:
#         purchase_price = float(purchase_price)
#         base_price = float(base_price)

#         if repack_itm_price is None or repack_itm_price == '':
#             repack_itm_price = base_price
#         else:
#             repack_itm_price = float(repack_itm_price)

#         val = purchase_price - base_price + repack_itm_price
#         factor = purchase_price / val
#         original_price = repack_itm_price * factor
#         return {'original_price': original_price}
#     else:
#         return {'error': 'purchase_price and base_price must not be None'}


# @frappe.whitelist() # not used
# def get_items_from_pr(pr):
    
# @frappe.whitelist() # Not used
# def set_value_for_pricing(self):
#     self_dict = json.loads(self)
#     purchase_price = frappe.db.get_value('Purchase Receipt', {'name': self_dict['purchase_receipt']}, 'total')
#     base_price = frappe.db.get_value('Purchase Receipt Item', {'parent': self_dict['purchase_receipt'], 
#     'item_code': self_dict['item_code']}, 'base_rate')
#     repack_itm_price = ''
#     # print(f"repack_itm_price: {repack_itm_price}")
#     if self_dict['item_code']:
#         repack_itm_price = frappe.db.get_value('Item', {'item_code': self_dict['item_code']}, 'valuation_rate')

#     elif repack_itm_price is None or self_dict['item_template']:
#         repack_itm_price = frappe.db.get_value('Item', {'item_code': self_dict['item_template']}, 'valuation_rate')
#     else:
#         repack_itm_price = base_price
#     original_price = iqc_to_repack_pricing(purchase_price, base_price, repack_itm_price)

#     return {"original_price": original_price.get('original_price', 0)}


# @frappe.whitelist()
# def get_attribute_parent(attribute_value):
#     sql_query = f"""
#         SELECT ia.attribute_name FROM `tabItem Attribute` AS ia
#         JOIN `tabItem Attribute Value` AS iav ON ia.name = iav.parent
#         WHERE iav.attribute_value = '{attribute_value}'
#     """
#     result = frappe.db.sql(sql_query, as_dict=True)
#     return result

# @frappe.whitelist()
# def set_iqc_child_table(item_group):
#     item_group = item_group.lower()
#     item_group_doc = frappe.get_doc('Item Group', item_group)
#     components = []
#     for component in item_group_doc.component_list:
#         components.append({'component_name': component.component_name})
#     return {'components':components}

# @frappe.whitelist() #not used
# def get_po_from_pr(pr):
#     result = {"po": None, "item_code": []}
#     query = frappe.db.sql(
#         """SELECT Item_code, purchase_order FROM `tabPurchase Receipt Item` WHERE parent = %s """, (pr), as_dict=True)

#     for row in query:
#         result["po"] = row["purchase_order"]
#         result["item_code"].append(row["Item_code"]) 
#     return result
#     return frappe.db.sql("""SELECT item_code from `tabPurchase Receipt Item` where parent = %s""", (pr), as_dict=1)

