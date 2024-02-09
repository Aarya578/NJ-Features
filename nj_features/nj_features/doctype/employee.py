# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import json
import frappe

@frappe.whitelist()
def create_user_and_warehouse(self):
    user_data = create_user(self)
    # if "error" in user_data:
    #     return user_data
    # print(f"user%%%%%%%%%%%%%%%%%%%%%%%: {user_data}, {type(user_data)}")
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

def create_user(self):
    # print(f"self =========== {self}")
    self = json.loads(self)
    # print(f"{self['status']}")
    try:
        if self['status'] == 'Active':
            restrict_ip = frappe.db.get_value('NJ Settings', {'doc_type': 'User', 'parameter': 'restrict_ip'}, 'value')
            # print(f"restrict_ip: {restrict_ip}")
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
            user.save(ignore_permissions=True)
            user.role_profile_name = self['role_profile']
            # user.module_profile = 
            user.restrict_ip = restrict_ip
            # print(f"create user: {user}")
            work_ware = create_warehouse(user, self['department'])
            emp_ware = create_warehouse(user)
            return {"user_email": user.email, "work_ware": work_ware, "emp_ware": emp_ware}
    except Exception as e:
        return {"Error while creating User": str(e)}

def create_warehouse(user, department=None):
    try:
        warehouse = frappe.new_doc('Warehouse')
        if department:
            parent_warehouse = frappe.db.get_value('Department', {'name': department}, 'linked_warehouse')
            warehouse.warehouse_name = user.full_name
            warehouse.warehouse_type = 'Transit'
            # print(f"parent_warehouse Depart -----: {parent_warehouse}")
        else:
            parent_warehouse = frappe.db.get_value('NJ Settings', {'doc_type': 'Employee', 'parameter': 'assert_ware'}, 'value')
            warehouse.warehouse_name = 'EMP - ' + user.full_name
            warehouse.warehouse_type = 'Employee Personal Warehouse'
            # print(f"parent_warehouse EMP @@@@@ : {parent_warehouse}")

        warehouse.parent_warehouse = parent_warehouse
        warehouse.warehouse_owner = user.email
        warehouse.save()
        # print(f"warehouse: ###################  {warehouse}")
        return warehouse.warehouse_name
    except Exception as e:
        return {"Error while creating Warehouse": str(e)}
