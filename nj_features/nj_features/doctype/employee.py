# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import json
import frappe
from frappe import _

@frappe.whitelist()
def create_user_and_warehouse(self):
    if isinstance(self, str):
        self = json.loads(self)
    
    user_data = create_user(self)
    print("self is ", self)
    
    if "user_email" in user_data:
        return {
            "user_id": user_data.get("user_email"),
            "work_warehouse": user_data.get("work_ware"),
            "employee_asset_warehouse": user_data.get("emp_ware")
        }
    
    elif "status" in user_data:
        return {"user_status": str(user_data.get('status'))}

def create_user(self):
    emp_data = {}

    if isinstance(self, str):
        self = json.loads(self)

    if self.get('status') == 'Active':
        work_ware = ''
        user_email = frappe.db.exists("User", {"email": self.get('prefered_email')})
        
        if not user_email:
            # Create a new User if it does not exist
            restrict_ip = frappe.db.get_value('NJ Settings', {'doc_type': 'User', 'parameter': 'restrict_ip'}, 'value')
            user = frappe.new_doc('User')

            user.first_name = self.get('first_name', '').title()
            user.middle_name = self.get('middle_name', '').title() if 'middle_name' in self else ''
            user.last_name = self.get('last_name', '').title() if 'last_name' in self else ''
            user.email = self.get('prefered_email')
            user.gender = self.get('gender')
            user.birth_date = self.get('date_of_birth')
            user.send_welcome_email = 0
            user.threads_notify = 0
            user.allowed_in_mentions = 0
            user.role_profile_name = self.get('role_profile')
            user.restrict_ip = restrict_ip
            user.save(ignore_permissions=True)
            user_email = user.email
        else:
            previous_role_profile = frappe.db.get_value('Employee', {'user_id': user_email}, 'role_profile')
            if self.get('role_profile') != previous_role_profile:
                print(f'Changing role profile for user {user_email} from {previous_role_profile} to {self.get("role_profile")}')
                frappe.db.set_value('User', user_email, 'role_profile_name', self.get('role_profile'))

        # Determine the work warehouse
        work_ware_reqd = frappe.db.get_value('Department', {'name': self.get('department')}, 'work_warehouse_required')
        employee_asset_dept = frappe.db.get_value('NJ Settings', {'parameter': 'employee_asset_dept'}, 'value')

        if work_ware_reqd == 'Yes':
            warehouse_name = "WK-" + self.get('first_name').title() + "-" + self.get('emp_id')
            work_warehouse_in_db = frappe.db.get_value("Warehouse", {'warehouse_name': warehouse_name}, "name")
            print(f'work_warehouse_in_db: {work_warehouse_in_db}')
            if not work_warehouse_in_db:
                work_ware = create_warehouse(user_email, self.get('department'), self.get('emp_id'), 'work_ware')
            else:
                work_ware = work_warehouse_in_db
                get_dept_from_warehouse = frappe.db.get_value("Warehouse", {'name': work_warehouse_in_db}, "department")

                if get_dept_from_warehouse != self.get('department'):
                    print('not equal')
                    # Handle department change
                    get_work_warehouse_doc = frappe.get_doc('Warehouse', work_warehouse_in_db)
                    print(f'owner: {get_work_warehouse_doc.warehouse_owner}')
                    filters = {"warehouse_owner": get_work_warehouse_doc.warehouse_owner}
                    conditions = []
                    if filters.get("warehouse_owner"):
                        conditions.append(f"AND WH.warehouse_owner = '{filters['warehouse_owner']}'")
                    conditions_sql = " ".join(conditions)
                    print(f'conditions_sql: {conditions_sql}')
                    query = f"""
                        SELECT 
                            SUM(Bin.actual_qty) AS total_qty
                        FROM tabBin Bin
                        INNER JOIN tabWarehouse WH ON Bin.warehouse = WH.name
                        WHERE WH.disabled = 0 AND Bin.actual_qty > 0 {conditions_sql}
                        GROUP BY WH.warehouse_owner;
                    """

                    data = frappe.db.sql(query, filters, as_dict=1)
                    print(f'data: {data}')
                    if data:
                        # frappe.throw(_("Please Transfer the stock of <b>{0} quantity(s)</b> to the {1} department").format(data[0].get("total_qty"), get_dept_from_warehouse))
                        pass
                    else:
                        print(f'\nDepartment Change: {self.get("department")}\n')
                        dept_work_ware = get_dept_work_warehouse(self.get('department'))
                        print(f'dept_work_ware: {dept_work_ware}')
                        print(f'warehouse ======= {get_work_warehouse_doc}')
                        print(f'get_work_warehouse_doc.department: {get_work_warehouse_doc.department}')
                        if dept_work_ware:
                            get_work_warehouse_doc.parent_warehouse = dept_work_ware
                            get_work_warehouse_doc.department = self.get('department')
                            get_work_warehouse_doc.save(ignore_permissions=True)
                        else:
                            frappe.msgprint("Please create Department's Employee Work Warehouse Group i.e: INW-Work-Warehouse - NJ")
        else:
            pass

        # Determine the employee asset warehouse
        emp_ware_data = create_warehouse(user_email, employee_asset_dept, self.get('emp_id'))

        emp_data.update({
            "user_email": user_email,
            "work_ware": work_ware,
            "emp_ware": emp_ware_data
        })
        return emp_data
    else:
        return {"status": self.get('status')}

def create_warehouse(user, department, emp_id=None, warehouse_type=None):
    print(f'BEFORE ASSIGNING USER: {user} DEPARTMENT: {department} EMP_ID: {emp_id} WAREHOUSE_TYPE: {warehouse_type}')
    parent_warehouse, user_full_name, is_main_warehouse_exists = '', '', ''
    warehouse = frappe.new_doc('Warehouse')
    user_full_name = frappe.db.get_value('User', {'name': user}, 'full_name')
    print(f'department: {department} and warehouse_type: {warehouse_type}')
    if department and warehouse_type == 'work_ware':
        print(f'INSIDE DEPARTMENT AND WORK WARE')
        prefix = frappe.db.get_value('Department', {'name': department}, 'department_prefix')
        parent_warehouse = prefix + '-Work-Warehouse - NJ'
        existing_parent = frappe.db.exists('Warehouse', {'name': parent_warehouse})
        
        if not existing_parent:
            frappe.throw("Please create Department's Employee Work Warehouse Group i.e: INW-Work-Warehouse - NJ")
        
        wk_warehouse_name = 'WK-' + user_full_name + '-' + emp_id
        is_main_warehouse_exists = frappe.db.exists('Warehouse', {'warehouse_name': wk_warehouse_name}, 'name')
        if is_main_warehouse_exists:
            print(f'warehouse exists')
            warehouse.save(ignore_permissions=True)
            return is_main_warehouse_exists
        warehouse.warehouse_name = wk_warehouse_name
        warehouse.parent_warehouse = parent_warehouse
        warehouse.department = department
    else:
        parent_warehouse = frappe.db.get_value('NJ Settings', {'doc_type': 'Employee', 'parameter': 'asset_ware'}, 'value')
        print(f'PARENT WAREHOUSE INSIDE ELSE ==== {parent_warehouse}')
        emp_warehouse_name = 'EMP - ' + user_full_name + ' - ' + emp_id
        is_main_warehouse_exists = frappe.db.exists('Warehouse', {'warehouse_name': emp_warehouse_name, 'warehouse_owner': user}, 'name')
        if is_main_warehouse_exists:
            return is_main_warehouse_exists
        warehouse.warehouse_name = emp_warehouse_name
        warehouse.parent_warehouse = parent_warehouse
        warehouse.department = department
    warehouse.warehouse_owner = user
    if is_main_warehouse_exists is None or is_main_warehouse_exists == '':
        warehouse.save(ignore_permissions=True)
    return warehouse.name


def get_dept_work_warehouse(department):
    dept_prefix = frappe.db.get_value('Department', {'name': department}, 'department_prefix')
    dept_work_warehouse = dept_prefix + '-Work-Warehouse - NJ'
    dept_work_warehouse_in_db = frappe.db.get_value('Warehouse', {'name': dept_work_warehouse}, 'name')
    
    return dept_work_warehouse_in_db if dept_work_warehouse_in_db else None