# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib

class NJAudit(Document):
    def on_submit(self):
        self.move_all_stock()
    
    def move_all_stock(self):
        stock_entry_items = []
        if self.accept_rows:
            accept_rows_list = self.accept_rows.split(',')
            accept_rows_set = set(int(idx) for idx in accept_rows_list if idx.strip().isdigit())
        else:
            accept_rows_set = set()
       
        for idx, row in enumerate(self.nj_audit_items):
            if row.idx in accept_rows_set and row.is_available == 0:
                stock_entry_item = {
                    'item_code': row.item_code,
                    'serial_no': row.serial_no,
                    's_warehouse': row.warehouse,
                    'basic_rate': row.purchase_rate
                }
                if not any(item['serial_no'] == stock_entry_item['serial_no'] for item in stock_entry_items):
                    stock_entry_items.append(stock_entry_item)
        if stock_entry_items != []:
            data = {
                "stock_entry_type": "Material Transfer",
                "t_warehouse": self.work_warehouse,
                "series": "STE-AD-.YYYY.-.MM.-",
                "doctype": self.doctype,
                "name": self.name,
                "stock_entry_for_material_transfer_or_repack_items": stock_entry_items
            }
            stock_entry = stock_entry_using_nj_lib(data)
            
            if stock_entry:
                for idx, row in enumerate(self.nj_audit_items):
                    if row.idx in accept_rows_set:
                        row.db_set('warehouse', self.work_warehouse)
                        row.db_set('parent_warehouse', self.audit_warehouse)
 
@frappe.whitelist()
def get_work_and_audit_warehouse():
    emp_data = frappe.db.get_value('Employee', {'user_id': frappe.session.user}, ['work_warehouse', 'department'], as_dict=1)
    
    if emp_data is None:
        frappe.throw("Employee data not found!")
    
    if not emp_data.get('department'):
        frappe.throw(f"Department is missing for <b>Employee: {frappe.session.user}</b>.")
    if not emp_data.get('work_warehouse'):
        frappe.throw(f"Work warehouse is missing for the <b>Employee: {frappe.session.user}</b>.")
    
    audit_warehouse = frappe.db.get_value('Department', {'name': emp_data.get('department')}, 'linked_warehouse')
    
    audit_interval = frappe.db.get_value('NJ Settings', {'parameter': 'audit_interval'}, 'value')
    
    stock_balance = get_stock_balance(audit_warehouse)
    return {
        'work_warehouse': emp_data.get('work_warehouse'),
        'audit_warehouse': audit_warehouse,
        'audit_interval': audit_interval,
        'stock_balance': stock_balance
    }

@frappe.whitelist()
def get_scanned_serial_no_data(serial_no, audit_warehouse):
    is_serial_no_exists = frappe.db.exists('Serial No', serial_no)
    if is_serial_no_exists:
        serial_no_data = frappe.db.get_value('Serial No', {'name': serial_no}, ['name', 'warehouse', 'item_code', 'purchase_rate', 'item_group'], as_dict=1)
        ware_house = serial_no_data.get('warehouse')
        def check_warehouse(ware_house):
            parent_warehouse = frappe.db.get_value('Warehouse', {'name': ware_house}, 'parent_warehouse')
            if parent_warehouse == audit_warehouse:
                return [{
                    'serial_no': serial_no_data.get('name'),
                    'item_code': serial_no_data.get('item_code'),
                    'warehouse': serial_no_data.get('warehouse'),
                    'purchase_rate': serial_no_data.get('purchase_rate'),
                    'item_group': serial_no_data.get('item_group'),
                    'is_available': 1
                }]
            elif parent_warehouse == '' or parent_warehouse is None:
                return [{
                    'serial_no': serial_no_data.get('name'),
                    'item_code': serial_no_data.get('item_code'),
                    'warehouse': serial_no_data.get('warehouse'),
                    'purchase_rate': serial_no_data.get('purchase_rate'),
                    'item_group': serial_no_data.get('item_group'),
                }]
            return check_warehouse(parent_warehouse)
        return check_warehouse(ware_house)

    else:
        return None


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
    parent_warehouse = audit_warehouse
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
        serial_num_data  = frappe.db.get_all("Serial No",{'warehouse' : warehouses},{'name','warehouse','item_group','item_code'})
        serial_no_data.extend(serial_num_data)
    serial_no_count = serial_no_data.__len__()
    return serial_no_count