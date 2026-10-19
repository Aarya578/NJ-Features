# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib

class NJAudit(Document):
    def validate(self):
        self.validate_unique_serial_numbers()

    def validate_unique_serial_numbers(self):
        seen_serial_numbers = set()
        duplicate_serial_numbers = set()

        for item in self.get('nj_audit_items', []):
            serial_no = (item.get('serial_no') or '').strip()
            if not serial_no:
                continue
            if serial_no in seen_serial_numbers:
                duplicate_serial_numbers.add(serial_no)
            seen_serial_numbers.add(serial_no)

        if duplicate_serial_numbers:
            serial_numbers = ', '.join(
                frappe.bold(serial_no) for serial_no in sorted(duplicate_serial_numbers)
            )
            frappe.throw(
                f"Serial No(s) {serial_numbers} are already scanned in this NJ Audit document.",
                title="Duplicate Serial No",
            )

    def on_submit(self):
        self.time_stamp_update()
        move_all_stock(self)

    def time_stamp_update(self):
        current_time = now_datetime()

        for item in self.get('nj_audit_items', []):
            source_warehouse = item.get('s_warehouse')
            target_warehouse = item.get('t_rack_warehouse')

            if (
                not source_warehouse
                or not target_warehouse
                or source_warehouse == target_warehouse
            ):
                continue

            source_department = frappe.db.get_value(
                'Warehouse', source_warehouse, 'department'
            )
            target_department = frappe.db.get_value(
                'Warehouse', target_warehouse, 'department'
            )

            if source_department == target_department or not item.get('serial_no'):
                continue

            for serial_no in item.get('serial_no').split('\n'):
                serial_no = serial_no.strip()
                if serial_no:
                    frappe.db.set_value(
                        'Serial No',
                        serial_no,
                        'stock_enty_date_and_time',
                        current_time,
                    )
        
@frappe.whitelist()
def move_all_stock(self):
    
    if isinstance(self, str):
        self = json.loads(self)
        
    stock_entry_for_material_transfer_or_repack_items = []
    serial_numbers_seen = set()
    
    stock_entry_data = {
        "name": self.get('name'),
        "doctype": self.get('doctype'),
        "stock_entry_type": "Material Transfer",
        "material_transfer_items": stock_entry_for_material_transfer_or_repack_items,
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
        nj_audit_stock_entry = stock_entry_using_nj_lib(stock_entry_data)
        if nj_audit_stock_entry:
            for row in self.get('nj_audit_items'):
                if row.get('s_warehouse') != row.get('t_rack_warehouse'):
                    row.db_set('s_warehouse', row.get('t_rack_warehouse'))
    return None

@frappe.whitelist()
def get_work_and_audit_warehouse():
    emp_data = frappe.db.get_value('Employee', {'user_id': frappe.session.user, 'status': 'Active'}, ['work_warehouse', 'department'], as_dict=1)
    
    if emp_data is None:
        frappe.throw("Employee data not found for user: {0}".format(frappe.session.user))
    
    if not emp_data.get('department'):
        frappe.throw(f"Department is missing for <b>Employee: {frappe.session.user}</b>.")
        
    if not emp_data.get('work_warehouse'):
        frappe.throw(f"Work warehouse is missing for <b>Employee: {frappe.session.user}</b>.")
    
    audit_warehouse = frappe.db.get_value('Department', {'name': emp_data.get('department')}, 'linked_warehouse')
    
    if not audit_warehouse:
        frappe.throw(f"Linked warehouse is missing for <b>Department: {emp_data.get('department')}</b>.")
    
    audit_interval = frappe.db.get_value('NJ Settings', {'parameter': 'audit_interval'}, 'value')
    
    stock_balance = get_stock_balance(audit_warehouse)
    
    return {
        'work_warehouse': emp_data.get('work_warehouse'),
        'audit_warehouse': audit_warehouse,
        'audit_interval': audit_interval,
        'stock_balance': stock_balance
    }

@frappe.whitelist()
def update_create_permission(doctype, nj_parameter, active_status=None):
    nj_audit_activation_level = frappe.db.get_value('NJ Settings', {'parameter': nj_parameter}, ['name', 'value'], as_dict=1)
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
def get_all_child_warehouses(parent_warehouse):
    child_warehouses = frappe.get_all('Warehouse', filters={'parent_warehouse': parent_warehouse, 'disabled': 0}, fields=['name', 'is_group'])
    
    if not child_warehouses:
        return frappe.throw("No child warehouses found for parent warehouse: {0}".format(parent_warehouse))
    
    group_warehouses = []
    non_group_warehouses = []
    
    for warehouse in child_warehouses:
        if warehouse.is_group:
            group_warehouses.append(warehouse.name)
            child_group_warehouses, child_non_group_warehouses = get_all_child_warehouses(warehouse.name)
            group_warehouses.extend(child_group_warehouses)
            non_group_warehouses.extend(child_non_group_warehouses)
        else:
            non_group_warehouses.append(warehouse.name)

    return group_warehouses, non_group_warehouses

def get_stock_balance(parent_warehouse):
    group_warehouses, non_group_warehouses = get_all_child_warehouses(parent_warehouse)
        
    allowed_item_group_check = []
    allowed_item_group_data = frappe.db.get_value('NJ Settings',{'parameter':'Item Group Check'},'value')
    if allowed_item_group_data:
        allowed_item_group_check = allowed_item_group_data.split(",")
        
    serial_count = 0
    for warehouse in non_group_warehouses:
        filters = {'warehouse': warehouse}
        
        if allowed_item_group_check:
            filters['item_group'] = ['in', allowed_item_group_check]
            
        serials = frappe.get_all('Serial No', filters=filters, fields=['name'])
        serial_count += len(serials)

    return serial_count

@frappe.whitelist()
def get_rack_balance(rack_name):
    serial_count = 0
    allowed_item_group_check = []
    allowed_item_group_data = frappe.db.get_value('NJ Settings',{'parameter':'Item Group Check'},'value')
    
    if allowed_item_group_data:
        allowed_item_group_check = allowed_item_group_data.split(",")

    rack_warehouse_in_db_query = """ select name from `tabWarehouse` where name = %s """
    rack_warehouse_in_db = frappe.db.sql(rack_warehouse_in_db_query, rack_name)

    if rack_warehouse_in_db and rack_warehouse_in_db[0][0]:

        filters = {'warehouse': rack_warehouse_in_db[0][0]}
            
        if allowed_item_group_check:
            filters['item_group'] = ['in', allowed_item_group_check]
            
        serials = frappe.db.get_all("Serial No", filters=filters,  fields=['name'])
        
        serial_count = len(serials)

    return {
        'serial_count': serial_count,
        'scan_rack': rack_warehouse_in_db[0][0] if rack_warehouse_in_db else ''
    }
