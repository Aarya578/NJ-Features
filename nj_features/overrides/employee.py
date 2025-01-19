# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import json
import frappe
import traceback
from frappe import _
from nj_lib.utils.common_utils import get_active_emp, get_active_user

@frappe.whitelist()
def create_user_and_warehouse(self):
    try:
        if isinstance(self, str):
            self = json.loads(self)
        
        user_email = create_user(self)

        if 'status' in user_email:
            return user_email
        
        return_data = { "user_id": user_email }
        
        if user_email is not None or user_email != "":
            if self.get("employee_asset_warehouse") is None:
                emp_ware = create_emp_ware(self, user_email)
                if emp_ware is not None:
                    return_data["employee_asset_warehouse"] = emp_ware
            if self.get("work_warehouse") is None:    
                work_ware = create_work_ware(self, user_email)
                if work_ware is not None:
                    return_data["work_warehouse"] = work_ware
        else:
            frappe.throw("User not created using email: ", self.get("prefered_email"))

        return return_data

    except Exception as e:
        frappe.db.rollback()
        traceback_info = traceback.format_exc()
        frappe.throw(f"Error on save: {str(e)}\n{traceback_info}")
        return str(e)

def create_user(self):

    if self.get('status') == 'Active':
        user_data = get_active_user(self.get('prefered_email'), ignore=True)
        if user_data is None:
            restrict_ip = frappe.db.get_value('NJ Settings', {'doc_type': 'User', 'parameter': 'restrict_ip'}, 'value')
            new_user = frappe.new_doc('User')

            new_user.first_name = self.get('first_name', '').title()
            new_user.middle_name = self.get('middle_name', '').title()
            new_user.last_name = self.get('last_name', '').title()
            new_user.email = self.get('prefered_email')
            new_user.gender = self.get('gender')
            new_user.birth_date = self.get('date_of_birth')
            new_user.send_welcome_email = 0
            new_user.threads_notify = 0
            new_user.allowed_in_mentions = 0
            new_user.role_profile_name = self.get('role_profile')
            new_user.restrict_ip = restrict_ip
            try:
                new_user.save(ignore_permissions=True)
            except Exception as e:
                frappe.throw("Error while creating user: ",e)
                
            user_email = new_user.email
        else:
            user_email = user_data.get('name')
            emp_data = get_active_emp(user_email, fields=['role_profile'], exists=True, ignore=True)

            try:
                if emp_data and self.get('role_profile') != emp_data.get('role_profile'):
                    frappe.db.set_value('User', user_email, 'role_profile_name', self.get('role_profile'))
            except Exception as e:
                frappe.throw("Error while updating user role profile: ",e)
        
        return user_email
    else:
        return {"status": self.get('status')}

def create_warehouse(user, department, location, emp_id=None, warehouse_type=None):
    parent_warehouse, user_full_name, is_main_warehouse_exists = '', '', ''
    warehouse = frappe.new_doc('Warehouse')
    user_data = get_active_user(user, fields=['full_name'])
    user_full_name = user_data.get('full_name')
    if department and warehouse_type == 'work_ware':
        prefix = frappe.db.get_value('Department', {'name': department}, 'department_prefix')
        if not prefix:
            frappe.throw(f"<b>Department Prefix</b> is not defined in <b>Department: {department}</b>")
            return None
        
        parent_warehouse = prefix + '-Work-Warehouse - NJ'
        existing_parent = frappe.db.exists('Warehouse', {'name': parent_warehouse, 'disabled': 0})
        
        if not existing_parent:
            frappe.throw("Please create Department's Employee Work Warehouse Group i.e: INW-Work-Warehouse - NJ")
            return None
        
        wk_warehouse_name = 'WK-' + user_full_name + '-' + emp_id
        is_main_warehouse_exists = frappe.db.exists('Warehouse', {'warehouse_name': wk_warehouse_name}, 'name')
        if is_main_warehouse_exists:
            return is_main_warehouse_exists
        warehouse.warehouse_name = wk_warehouse_name
        warehouse.parent_warehouse = parent_warehouse
        warehouse.department = department
        
    else:
        parent_warehouse = frappe.db.get_value('NJ Settings', {'doc_type': 'Employee', 'parameter': 'asset_ware'}, 'value')
        emp_warehouse_name = 'EMP - ' + user_full_name + ' - ' + emp_id
        
        is_main_warehouse_exists = frappe.db.exists('Warehouse', {'warehouse_name': emp_warehouse_name, 'warehouse_owner': user}, 'name')
        if is_main_warehouse_exists:
            return is_main_warehouse_exists
        else:
            is_main_warehouse_exists = frappe.db.exists('Warehouse', {'parent_warehouse': parent_warehouse, 'warehouse_owner': user}, 'name')
            if is_main_warehouse_exists:
                return is_main_warehouse_exists
            
        warehouse.warehouse_name = emp_warehouse_name
        warehouse.parent_warehouse = parent_warehouse
        warehouse.department = department
        warehouse.warehouse_type = 'Employee Personal Warehouse'
        
        
    warehouse.warehouse_owner = user
    warehouse.location = location

    if is_main_warehouse_exists is None or is_main_warehouse_exists == '':
        try:
            warehouse.save(ignore_permissions=True)
        except Exception as e:
            frappe.throw("Error while creating employee asset warehouse: ",e)
            return None
    return warehouse.name


def get_dept_work_warehouse(department):
    dept_prefix = frappe.db.get_value('Department', {'name': department}, 'department_prefix')
    if dept_prefix:
        dept_work_warehouse = dept_prefix + '-Work-Warehouse - NJ'
        dept_work_warehouse_query = "SELECT name FROM `tabWarehouse` WHERE name = '{0}' AND disabled = 0".format(dept_work_warehouse)
        dept_work_warehouse_in_db = frappe.db.sql(dept_work_warehouse_query, as_dict=1)
        return dept_work_warehouse_in_db[0].get('name') if dept_work_warehouse_in_db and dept_work_warehouse_in_db[0] else None
    else:
        frappe.throw(f"<b>Department Prefix</b> is not defined in <b>Department: {department}</b>")
        return None
def create_emp_ware(self, user_email):
    employee_asset_dept = frappe.db.get_value('NJ Settings', {'parameter': 'employee_asset_dept'}, 'value')
    emp_ware_data = create_warehouse(user_email, employee_asset_dept, self.get('location'), self.get('emp_id'))
    return emp_ware_data

def create_work_ware(self, user_email):
    work_warehouse = ''
    work_ware_reqd = frappe.db.get_value('Department', {'name': self.get('department')}, 'work_warehouse_required')
    if work_ware_reqd == 'Yes':
        warehouse_name = "WK-" + self.get('first_name').title() + "-" + self.get('emp_id')
        get_work_warehouse_query = "SELECT name FROM `tabWarehouse` WHERE warehouse_name = '{0}' AND disabled = 0".format(warehouse_name)
        work_warehouse_in_db = frappe.db.sql(get_work_warehouse_query, as_dict=1)
        if work_warehouse_in_db and work_warehouse_in_db[0]:
            work_warehouse = work_warehouse_in_db[0].get('name')
        if work_warehouse is None or work_warehouse == '':
            work_ware = create_warehouse(user_email, self.get('department'), self.get('location'), self.get('emp_id'), 'work_ware')
        else:
            work_ware = work_warehouse
            get_dept_from_warehouse = frappe.db.get_value("Warehouse", {'name': work_ware, 'disabled': 0}, "department")

            if get_dept_from_warehouse != self.get('department'):
                get_work_warehouse_doc = frappe.get_doc('Warehouse', work_warehouse)
                filters = {"warehouse_owner": get_work_warehouse_doc.warehouse_owner}
                conditions = []
                if filters.get("warehouse_owner"):
                    conditions.append(f"AND WH.warehouse_owner = '{filters['warehouse_owner']}'")
                conditions_sql = " ".join(conditions)
                query = f"""
                    SELECT SUM(Bin.actual_qty) AS total_qty
                    FROM tabBin Bin
                    INNER JOIN tabWarehouse WH ON Bin.warehouse = WH.name
                    WHERE WH.disabled = 0 AND Bin.actual_qty > 0 AND WH.name NOT LIKE 'EMP%' {conditions_sql}
                    GROUP BY WH.warehouse_owner;
                """

                data = frappe.db.sql(query, filters, as_dict=1)
                
                if data:
                    frappe.msgprint(_("Please Transfer the stock of <b>{0} quantity(s)</b> to the {1} department").format(data[0].get("total_qty"), get_dept_from_warehouse))
                    return None
                else:
                    dept_work_ware = get_dept_work_warehouse(self.get('department'))
                    if dept_work_ware:
                        get_work_warehouse_doc.parent_warehouse = dept_work_ware
                        get_work_warehouse_doc.department = self.get('department')
                        try:
                            get_work_warehouse_doc.save(ignore_permissions=True)
                        except Exception as e:
                            frappe.throw("Error while updating work warehouse: ",e)
                    else:
                        frappe.throw("Please create Department's Employee Work Warehouse Group i.e: INW-Work-Warehouse - NJ")
                        return None
        return work_ware
    else:
        return None

@frappe.whitelist()
def get_previous_department(docname):
    previous_department = frappe.db.get_value('Warehouse', {'name': docname}, 'department')
    # frappe.db.set_value('Warehouse', docname, 'previous_department', previous_department)
    # frappe.db.commit()
    return previous_department
@frappe.whitelist()
def department_change_log(docname, cur_department, previous_department):
    changed_by = frappe.session.user

    query = """
        SELECT user_id
        FROM `tabEmployee`
        WHERE work_warehouse = %(docname)s
        OR employee_asset_warehouse = %(docname)s
    """
    params = {'docname': docname}
    changed_on = frappe.db.sql(query, params, as_dict=True)
    if previous_department != cur_department:
        print(f'creating department change log')
        new_doc = frappe.new_doc('Department Change Log')
        new_doc.flags.ignore_mandatory = True
        new_doc.previous_department = previous_department
        new_doc.current_department = cur_department
        new_doc.changed_by = changed_by
        new_doc.changed_on = ', '.join([row['user_id'] for row in changed_on]) if changed_on else 'No user found'
        new_doc.save()
        new_doc.submit()

    return previous_department


@frappe.whitelist()
def get_previous_role_profile(docname):
    return frappe.db.get_value('Employee', {'name': docname}, 'role_profile') or ''
   

@frappe.whitelist()
def role_profile_change_log(user_id, cur_role_profile, previous_role_profile):

    if previous_role_profile != cur_role_profile:
        changed_by = frappe.session.user
        new_doc = frappe.new_doc('Department Change Log')
        new_doc.previous_role_profile = previous_role_profile
        new_doc.current_role__profile = cur_role_profile
        new_doc.changed_by = changed_by
        new_doc.changed_on =  user_id
        new_doc.save()
        new_doc.submit()
    return 'No changes in role profile detected.'

