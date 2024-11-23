# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from nj_lib.utils.common_utils import get_active_emp
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib

class StockMovement(Document):
    def on_submit(self):
        try:
            material_transfer_items = []
            
            stock_entry_data = {
                "name": self.name,
                "doctype": self.doctype,
                "department": self.department,
                "series": "STE-SM-.YYYY.-.MM.-",
                "transfer_status": self.transfer_status,
                "stock_entry_type": "Material Transfer",
                "material_transfer_items": material_transfer_items,
            }
            
            for row in self.items:
                material_transfer_items.append({
                    'qty': row.qty,
                    'item_code': row.item_code,
                    's_warehouse': row.s_warehouse,
                    't_warehouse': row.t_warehouse,
                    'reason': row.reason if row.reason else None,
                    'serial_no': row.serial_no if row.serial_no else None,
                })

            if material_transfer_items:
                return stock_entry_using_nj_lib(stock_entry_data)
            else:
                frappe.throw("None available in <b>Items</b> table.")

        except Exception as e:
            frappe.db.rollback()
            frappe.throw("Error while submitting Stock Entry: ", e)

@frappe.whitelist()
def get_all_emp_warehouse(user):
    try:
        emp_dept = get_active_emp(user, fields=['department'])
        dept_values = frappe.db.get_value('Department', {'name': emp_dept.get('department')}, ['department_prefix', 'linked_warehouse'])
        if not dept_values:
            frappe.throw('Department values not found')

        if not dept_values[1]:
            frappe.throw("Enter <strong>Work Warehouse</strong> in Department: {}".format(emp_dept.get('department')))

        default_ww = dept_values[0] + '-Work-Warehouse - NJ' if dept_values[0] else ''
        all_emp_ware = frappe.db.get_all('Warehouse', {'parent_warehouse': dept_values[1], 'available_capacity': ('>', 0), 'disabled': 0}, ['name', 'available_capacity', 'max_capacity'])
        centralized_parent = frappe.db.get_value('Warehouse', {'centralized': 1, 'disabled': 0}, 'name')
        centralized_ware = frappe.db.get_all('Warehouse', {'parent_warehouse': centralized_parent}, ['name', 'available_capacity'])
        recommended_warehouses = {}
        centralized_warehouses = {}

        for warehouse in all_emp_ware:
            recommended_warehouses[warehouse['name']] = warehouse['available_capacity']

        for warehouse in centralized_ware:
            centralized_warehouses[warehouse['name']] = warehouse['available_capacity']

        if default_ww in recommended_warehouses:
            del recommended_warehouses[default_ww]

        formatted_recommended = '\n'.join([f"{warehouse}  =>  {capacity} qty" for warehouse, capacity in recommended_warehouses.items()])
        formatted_centralized = '\n'.join([f"{warehouse} => {capacity} qty" for warehouse, capacity in centralized_warehouses.items()])
        warehouse = ','.join(recommended_warehouses.keys())
        return {
            'recommended': formatted_recommended,
            'centralized': formatted_centralized,
            'warehouse': warehouse
        }
        
    except Exception as e:
        return {'error in emp': str(e)}