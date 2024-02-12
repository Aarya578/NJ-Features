# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import json
import frappe

@frappe.whitelist()
def create_user_and_warehouse(self):
    user_data = create_user(self)
    if "error" in user_data:
        return user_data
    try:
        user_email = user_data["user_email"]
        work_ware = user_data["work_ware"]
        emp_ware = user_data["emp_ware"]
        self = json.loads(self)
        emp = frappe.get_doc("Employee", self['name'])
        if emp:
            emp.user_id = user_email
            emp.work_warehouse= work_ware
            emp.employee_asset_warehouse = emp_ware
            emp.save(ignore_permissions=True)
            return {"user": user_email, "work_warehouse": work_ware, "employee_asset_warehouse": emp_ware}
        else:
            return {"error": "Employee instance not found."}
    except Exception as e:
        return {"error": str(e)}

def create_user(self):
    self = json.loads(self)
    try:
        if self['status'] == 'Active':
            user = frappe.get_doc("User", {"email": self['prefered_email']})
            if user:
                work_ware_reqd = frappe.db.get_value('Department', {'name': self['department']}, 'work_warehouse_required')
                if work_ware_reqd == 'Yes':
                    work_ware = create_warehouse(user, self['department'], self['emp_id'])
                else:
                    work_ware = None  # If work_warehouse is not required
                emp_ware = create_warehouse(user)  # Always create emp_warehouse
                return {"user_email": user.email, "work_ware": work_ware, "emp_ware": emp_ware}
            
            # If user doesn't exist, create a new user
            restrict_ip = frappe.db.get_value('NJ Settings', {'doc_type': 'User', 'parameter': 'restrict_ip'}, 'value')
            user = frappe.new_doc('User')
            user.first_name = self['first_name']
            if 'middle_name' in self:
                user.middle_name = self['middle_name']
            if 'last_name' in self:
                user.last_name = self['last_name']
            user.email = self['prefered_email']
            user.gender = self['gender']
            user.birth_date = self['date_of_birth']
            user.send_welcome_address = 1
            user.role_profile_name = self['role_profile']
            user.restrict_ip = restrict_ip
            user.save(ignore_permissions=True)

            work_ware_reqd = frappe.db.get_value('Department', {'name': self['department']}, 'work_warehouse_required')
            if work_ware_reqd == 'Yes':
                work_ware = create_warehouse(user, self['department'], self['emp_id'])
            else:
                work_ware = None  # If work_warehouse is not required
            emp_ware = create_warehouse(user)  # Always create emp_warehouse
            return {"user_email": user.email, "work_ware": work_ware, "emp_ware": emp_ware}
    except Exception as e:
        return {"Error while creating User": str(e)}


def create_warehouse(user, department=None, emp_id=None):
    try:
        parent_warehouse =''
        warehouse = frappe.new_doc('Warehouse')
        if department: #dept emp work warehouse
            prefix = frappe.db.get_value('Department', {'name': department}, 'department_prefix')
            parent_warehouse = prefix + '-Work-Warehouse - NJ'
            existing_parent = frappe.db.exists('Warehouse', {'name': parent_warehouse})
            if not existing_parent:
                frappe.msgprint('Please create Department Emp Work Warehouse Group')
            warehouse.warehouse_name = prefix + '-' + user.full_name + '-' + emp_id
        else: #emp warehouse
            parent_warehouse = frappe.db.get_value('NJ Settings', {'doc_type': 'Employee', 'parameter': 'assert_ware'}, 'value')
            warehouse.warehouse_name = 'EMP - ' + user.full_name

        warehouse.parent_warehouse = parent_warehouse
        warehouse.warehouse_owner = user.email
        warehouse.save()
        return warehouse.name
    except Exception as e:
        return {"Error while creating Warehouse": str(e)}
