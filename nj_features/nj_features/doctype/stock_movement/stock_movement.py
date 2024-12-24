# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from datetime import datetime, timedelta
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


@frappe.whitelist()
def validate_stock_movement_for_grade(doc):
    print('\n\n')
    try:
        if isinstance(doc, str):
            doc = json.loads(doc)

        print(f'doc ----------------- {doc}')
        print(f'doc.items ----------------- {doc.get("items")}')

        error_messages = []  # List to collect error messages

        for row in doc.get('items'):
            department = frappe.db.get_value('Warehouse', {'name': row.get('t_warehouse')}, ['department'])

            if not department:
                error_messages.append(f"Target warehouse {row.get('t_warehouse')} has no associated department.")
                continue

            department_doc = frappe.get_doc('Department', department)

            for d in department_doc.get('stock_movement_restriction_table'):
                print('d ----------------------- 102', d.as_dict())
                print('---------------------109--------------------')

                print('warrenty_restriction', d.get('warrenty_restriction'))

                serial_doc = frappe.get_doc('Serial No', row.get('serial_no'))

                check_warranty_expiry(serial_doc)

                if check_warranty_expiry(serial_doc):
                    is_component = frappe.db.get_value('Item Group', serial_doc.get('item_group'), 'is_component')
                    print('is_component ----------------------- 104', is_component)

                    if not is_component:
                        for s in serial_doc.get('serial_no_component'):
                            print('\n\n')
                            print('s ----------------------- 106', s.as_dict())
                            print(f'{s.get("item_group")} ---- {d.get("item_group")} ----- s.get("grade") ----- {s.get("grade")} ----- d.get("restricted_grade") ----- {d.get("restricted_grade")}')
                            
                            if (s.get('item_group') == d.get('item_group')) and (s.get('grade') in d.get('restricted_grade').split(', ')):
                                error_messages.append(
                                    f"Serial No <b>{row.get('serial_no')}</b> for item_group <b>{s.get('item_group')}</b> has a grade <b>{s.get('grade')}</b> that is not allowed for department <b>{department_doc.name}</b>."
                                )
                    else:
                        print('it is not a component...132')
                else:
                    serial_doc = frappe.get_doc('Serial No', row.get('serial_no'))

                    is_component = frappe.db.get_value('Item Group', serial_doc.get('item_group'), 'is_component')
                    print('is_component ----------------------- 104', is_component)

                    if not is_component:
                        for s in serial_doc.get('serial_no_component'):
                            print('\n\n')
                            print('s ----------------------- 106', s.as_dict())
                            print(f'{s.get("item_group")} ---- {d.get("item_group")} ----- s.get("grade") ----- {s.get("grade")} ----- d.get("restricted_grade") ----- {d.get("restricted_grade")}')
                            
                            if (s.get('item_group') == d.get('item_group')) and (s.get('grade') in d.get('restricted_grade').split(', ')):
                                error_messages.append(
                                    f"Serial No <b>{row.get('serial_no')}</b> for item_group <b>{s.get('item_group')}</b> has a grade <b>{s.get('grade')}</b> that is not allowed for department <b>{department_doc.name}</b>."
                                )

        if error_messages:
            return {"error": error_messages}
        else:
            return {"success": "Validation passed without errors."}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in validate_stock_movement_for_grade")
        return {"error": str(e)}


def check_warranty_expiry(serial_doc):

    print('checking_warrenty_expiry_date')

    query = """
        SELECT DATE(creation) AS creation_date, warranty_days 
        FROM `tabPurchase Order` 
        WHERE name = %s
    """

    purchase_order = frappe.db.sql(query, serial_doc.get('purchase_order'), as_dict=True)

    if not purchase_order:
        frappe.throw("Purchase Order not found for the provided serial document.")

    creation_date = purchase_order[0]['creation_date']
    warranty_days = purchase_order[0]['warranty_days']

    if not warranty_days:
        return True  

    warranty_expiry_date = creation_date + timedelta(days=warranty_days)
    today_date = datetime.now().date()

    if today_date > warranty_expiry_date:
        return True 
    else:
        remaining_days = (warranty_expiry_date - today_date).days
        frappe.throw(f"The warranty is still valid. <b>{remaining_days} day(s)</b> remaining.")