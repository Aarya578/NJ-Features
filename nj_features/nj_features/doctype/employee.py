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
    if user_data:
        # try:
        user_email = user_data.get("user_email")
        work_ware = user_data.get("work_ware")
        emp_ware = user_data.get("emp_ware")
        

        return {"user": user_email, "work_warehouse": work_ware, "employee_asset_warehouse": emp_ware}
    
    #     # except Exception as e:
    # else:
    #     return {"error": str(e)}

def create_user(self):
    if isinstance(self, str):
        self = json.loads(self)
    if self.get('status') == 'Active':
        try:
            # Check if the warehouses already exist
            work_ware = ''
            user_email = frappe.db.exists("User", {"email": self.get('prefered_email')})
            if not user_email:
                restrict_ip = frappe.db.get_value('NJ Settings', {'doc_type': 'User', 'parameter': 'restrict_ip'}, 'value')
                user = frappe.new_doc('User')

                user.first_name = self.get('first_name')
                if 'middle_name' in self:
                    user.middle_name = self.get('middle_name')
                if 'last_name' in self:
                    user.last_name = self.get('last_name')
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

            work_ware_reqd = frappe.db.get_value('Department', {'name': self.get('department')}, 'work_warehouse_required')
            if work_ware_reqd == 'Yes':
                warehouse_name = "WK-" + self.get('first_name') + "-" + self.get('emp_id')
                work_warehouse_in_db = frappe.db.get_value("Warehouse", {'warehouse_name': warehouse_name}, "name")
                # if Employee wants to change the department then change the warehouse parent based on specified dept else create a new warehouse
                if not work_warehouse_in_db:
                    work_ware = create_warehouse(user_email, self.get('department'), self.get('emp_id'))
                else:
                    work_ware = work_warehouse_in_db
                    get_dept_from_warehouse = frappe.db.get_value("Warehouse", {'name': work_warehouse_in_db}, "department")
                    
                    
                    # Check for previous dept and current dept, if dept is changed now, Check the stock is available in his ware house or not 
                    if get_dept_from_warehouse != self.get('department'):
                        get_work_warehouse_doc = frappe.get_doc('Warehouse', work_warehouse_in_db)
                        
                        filters = {"warehouse_owner": get_work_warehouse_doc.warehouse_owner}
                
                        conditions = []
                        if filters.get("warehouse_owner"):
                            conditions.append(f"AND WH.warehouse_owner = '{filters['warehouse_owner']}'")
                        conditions_sql = " ".join(conditions)

                        query = f"""
                            SELECT 
                                SUM(Bin.actual_qty) AS total_qty
                            FROM 
                                tabBin Bin
                            INNER JOIN 
                                tabWarehouse WH ON Bin.warehouse = WH.name
                            WHERE 
                                WH.disabled = 0 AND Bin.actual_qty > 0 {conditions_sql}
                            GROUP BY
                                WH.warehouse_owner;
                            """

                        data = frappe.db.sql(query, filters, as_dict=1)
                        if data:
                            frappe.throw(_("Please Transfer the stock of {0} quantity(s) to the {1} department").format(data[0].get("total_qty"), get_dept_from_warehouse))
                        else:
                            dept_work_ware = get_dept_work_warehouse(self.get('department'))
                            if dept_work_ware:
                                get_work_warehouse_doc.parent_warehouse = dept_work_ware
                                get_work_warehouse_doc.department = self.get('department')
                                get_work_warehouse_doc.save(ignore_permissions=True)
                            else:
                                frappe.msgprint("Please create Department's Employee Work Warehouse Group i.e: INW-Work-Warehouse - NJ")
            else:
                frappe.msgprint("Please create Department's Employee Work Warehouse Group i.e: INW-Work-Warehouse - NJ")

            # if str(type(user)) != "<class 'str'>":
            is_emp_warehouse = 'EMP - ' + self.get('first_name')
            emp_work_warehouse_in_db = frappe.db.get_value("Warehouse", {'warehouse_name': is_emp_warehouse}, "name")
            if not emp_work_warehouse_in_db:
                department = self.get('department')
                emp_ware = create_warehouse(user_email, department)
            else:
                emp_ware = emp_work_warehouse_in_db
            return {"user_email": user_email, "work_ware": work_ware , "emp_ware": emp_ware}
        
        except Exception as e:
            frappe.throw(f"Error while creating User: {str(e)}")
    else:
        frappe.msgprint(f"Employee status is <b>{self.get('status')}</b>")


def create_warehouse(user, department, emp_id=None):
    try:
        parent_warehouse, user_full_name = '', ''
        warehouse = frappe.new_doc('Warehouse')
        # if str(type(user)) != "<class 'str'>":
        #     user = user.name
        user_full_name = frappe.db.get_value('User', {'name':user}, 'full_name')
        if department and emp_id: #dept emp work warehouse
            prefix = frappe.db.get_value('Department', {'name': department}, 'department_prefix')
            parent_warehouse = prefix + '-Work-Warehouse - NJ'
            existing_parent = frappe.db.exists('Warehouse', {'name': parent_warehouse})
            if not existing_parent:
                frappe.throw("Please create Department's Employee Work Warehouse Group i.e: INW-Work-Warehouse - NJ")
            warehouse.warehouse_name = 'WK-' + user_full_name + '-' + emp_id
            warehouse.warehouse_owner = user
            warehouse.department = department
        else: #emp warehouse
            parent_warehouse = frappe.db.get_value('NJ Settings', {'doc_type': 'Employee', 'parameter': 'asset_ware'}, 'value')
            warehouse.warehouse_name = 'EMP - ' + user_full_name
            warehouse.department = department
        warehouse.parent_warehouse = parent_warehouse
        warehouse.warehouse_owner = user
        warehouse.save()
        return warehouse.name
    
    except Exception as e:
        return {"Error while creating Warehouse": str(e)}
    
def get_dept_work_warehouse(department): # working
    dept_prefix = frappe.db.get_value('Department', {'name': department}, 'department_prefix')
    dept_work_warehouse = dept_prefix + '-Work-Warehouse - NJ'
    dept_work_warehouse_in_db = frappe.db.get_value('Warehouse', {'name':dept_work_warehouse}, 'name')
    if dept_work_warehouse_in_db:
        return dept_work_warehouse_in_db
    else:
        return None