# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
from frappe.model.document import Document
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib

class NJAudit(Document):
    pass
        
@frappe.whitelist()
def move_all_stock(self):
    
    if isinstance(self, str):
        self = json.loads(self)
        
    stock_entry_for_material_transfer_or_repack_items = []
    serial_numbers_seen = set()
    
    stock_entry_data = {
        "stock_entry_type": "Material Transfer",
        "stock_entry_for_material_transfer_or_repack_items": stock_entry_for_material_transfer_or_repack_items,
        "series": "STE-AD-.YYYY.-.MM.-",
        "doctype": self.get('doctype'),
        "name": self.get('name'),
    }
    
    for row in self.get('nj_audit_items'):
        if row.get('s_warehouse') != row.get('t_rack_warehouse'):
            if row.get('serial_no') not in serial_numbers_seen:
                stock_entry_for_material_transfer_or_repack_items.append({
                    "item_code": row.get('item_code'),
                    "serial_no": row.get('serial_no'),
                    "s_warehouse": row.get('s_warehouse'),
                    "t_warehouse": row.get('t_rack_warehouse')
                })
                serial_numbers_seen.add(row.get('serial_no'))
    
    if stock_entry_for_material_transfer_or_repack_items:
        return stock_entry_using_nj_lib(stock_entry_data)
    return None

@frappe.whitelist()
def get_work_and_audit_warehouse():
    emp_data = frappe.db.get_value('Employee', {'user_id': frappe.session.user}, ['work_warehouse', 'department'], as_dict=1)
    
    if emp_data is None:
        frappe.throw("Employee data not found for user: {0}".format(frappe.session.user))
    
    if not emp_data.get('department'):
        frappe.throw(f"Department is missing for <b>Employee: {frappe.session.user}</b>.")
    if not emp_data.get('work_warehouse'):
        frappe.throw(f"Work warehouse is missing for the <b>Employee: {frappe.session.user}</b>.")
    
    audit_warehouse = frappe.db.get_value('Department', {'name': emp_data.get('department')}, 'linked_warehouse')
    
    if not audit_warehouse:
        frappe.throw(f"Linked warehouse is missing for the <b>Department: {emp_data.get('department')}</b>.")
    
    audit_interval = frappe.db.get_value('NJ Settings', {'parameter': 'audit_interval'}, 'value')
    
    stock_balance = get_stock_balance(audit_warehouse)
    return {
        'work_warehouse': emp_data.get('work_warehouse'),
        'audit_warehouse': audit_warehouse,
        'audit_interval': audit_interval,
        'stock_balance': stock_balance
    }

@frappe.whitelist()
def update_create_permission(doctype, active_status=None):
    nj_audit_activation_level = frappe.db.get_value('NJ Settings', {'parameter': 'nj_audit_activation_level'}, ['name', 'value'], as_dict=1)
    new_value = nj_audit_activation_level.get('value')
    if nj_audit_activation_level:
        if active_status == '1':
            current_value = nj_audit_activation_level.get('value')
            new_value = '0' if current_value == '1' else '1'
            
            frappe.db.set_value('NJ Settings', nj_audit_activation_level.get('name'), 'value', new_value)
            frappe.db.commit()
        values = [{'create': int(new_value)}, {'write': int(new_value)}]
        custom_docperm_records  = frappe.get_all('Custom DocPerm', {'parent': doctype}, 'name')
        docperm_records  = frappe.get_all('DocPerm', {'parent': doctype}, 'name')
        for value in values:
            if custom_docperm_records:
                for row in custom_docperm_records:
                    frappe.db.set_value('Custom DocPerm', row.name, value)
            if docperm_records:
                for row in docperm_records: 
                    frappe.db.set_value('DocPerm', row.name, value)
        
        return new_value
    
    else:
        frappe.throw('No NJ Settings found with parameter nj_audit_activation_level.')
        return None
    
@frappe.whitelist()
def get_stock_balance(audit_warehouse):
    grand_child_warehouse=[]
    item_group_data = []
    parent_warehouse = audit_warehouse
    item_group_data = frappe.db.get_value('NJ Settings',{'parameter':'Item Group Check'},'value')
    item_group_check = item_group_data.split(",")
    audit_warehouses_data = set(frappe.db.get_all("Warehouse", filters={'parent_warehouse': parent_warehouse}, pluck='name'))
    audit_warehouses_data.add(parent_warehouse)
    def add_child_warehouses(warehouse):
        child_warehouses = frappe.db.get_all("Warehouse", filters={'parent_warehouse': warehouse}, pluck='name')
        for child in child_warehouses:
            if child not in audit_warehouses_data:
                grand_child_warehouse.append(child)
                add_child_warehouses(child)
    for warehouse in list(audit_warehouses_data):
        if frappe.db.get_value('Warehouse',{'name':warehouse },'is_group') == 1:
            add_child_warehouses(warehouse)
        else:
            grand_child_warehouse.append(warehouse)
    new_grand_warehouse =[]
    for xar in grand_child_warehouse:
        if (frappe.db.get_value('Warehouse',{'name':xar },'is_group')) == 0:
            new_grand_warehouse.append(xar)
    serial_no_data = []
    for warehouses in new_grand_warehouse:
        serial_num_data = frappe.db.get_all(
    			"Serial No", 
    			filters={
        		'warehouse': warehouses, 
        		'item_group': ['in', item_group_check]
    			}, 
    			fields=['name', 'warehouse', 'item_group', 'item_code']
			)
        serial_no_data.extend(serial_num_data)
    serial_no_count = serial_no_data.__len__()
    return serial_no_count

@frappe.whitelist()
def get_rack_balance(rack_name):
    data =[]
    item_group_data = []
    item_group_data = frappe.db.get_value('NJ Settings',{'parameter':'Item Group Check'},'value')
    item_group_check = item_group_data.split(",")
    data = frappe.db.get_all(
    			"Serial No", 
    			filters={
        		'warehouse': rack_name, 
        		'item_group': ['in', item_group_check]
    			}, 
    			fields=['name','item_group']
			)
    rack_count = data.__len__()
    return rack_count