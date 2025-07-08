# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import json
import frappe
import traceback
from frappe import _
from datetime import datetime, date
from nj_lib.utils.common_utils import get_active_emp, get_active_user
from nj_features.nj_features.doctype.department_change_log.department_change_log import update_department_change_logs


@frappe.whitelist()
def create_user_and_warehouse(self):
    try:
        work_ware = None
        if isinstance(self, str):
            self = json.loads(self)

        db_department = frappe.db.get_value('Employee', {'name': self.get("name")}, 'department')
        
        user_email = create_user(self)

        if 'status' in user_email:
            return user_email
        
        return_data = { "user_id": user_email }
        
        if user_email is not None or user_email != "":
            if self.get("employee_asset_warehouse") is None:
                emp_ware = create_emp_ware(self, user_email)
                if emp_ware is not None:
                    return_data["employee_asset_warehouse"] = emp_ware
            
            if self.get("work_warehouse") is None or self.get("work_warehouse") == '':
                work_ware = create_work_ware(self, user_email)
                if work_ware is not None:
                    return_data["work_warehouse"] = work_ware

            # if db_department and db_department != self.get("department"):
            #     update_department_in_work_warehouse(self)
        else:
            frappe.throw("User not created using email: ", self.get("prefered_email"))

        return return_data
    
    except Exception as e:
        frappe.msgprint("Error while creating user and warehouse: ", e)

def update_department_in_work_warehouse(self):

    qty_check = frappe.db.get_value('NJ Settings', {'parameter': 'disable_qty_check'}, 'value')
    if qty_check is None:
        frappe.msgprint("Please set disable_qty_check in NJ Settings")
    
    work_ware = frappe.db.get_all( "Warehouse",
        {
            'warehouse_owner': self.get("user_id"), 'disabled': 0,
            'warehouse_type': ['!=', 'Employee Personal Warehouse']
        }, pluck="name"
    )

    existing_work_warehouse = self.get("work_warehouse")
    if existing_work_warehouse:
        if isinstance(existing_work_warehouse, str):
            existing_work_warehouse = [existing_work_warehouse]
        work_ware.extend(existing_work_warehouse)

    work_ware = list(set(work_ware))

    get_dept_from_warehouse = frappe.db.get_values("Warehouse",
        {'name': ('in', work_ware), 'disabled': 0},
        ["name", "department"], as_dict=True
    )

    if get_dept_from_warehouse and self.get('department') not in [d.get('department') for d in get_dept_from_warehouse] and qty_check == '0':
        query = """
            SELECT SUM(Bin.actual_qty) AS total_qty
            FROM `tabBin` Bin
            INNER JOIN `tabWarehouse` WH ON Bin.warehouse = WH.name
            WHERE WH.disabled = 0 AND Bin.actual_qty > 0 AND WH.name IN %s
        """

        data = frappe.db.sql(query, (tuple(work_ware),), as_dict=True)

        warehouse_info = [
            f"{d['name']} (Dept: {d['department'] or 'N/A'})"
            for d in get_dept_from_warehouse
        ]
        warehouse_str = ", ".join(warehouse_info)

        if data:
            total_qty = sum((d.get("total_qty") or 0) for d in data)

            if total_qty > 0:
                frappe.msgprint(
                    _("Please transfer the stock of <b>{0} Qty(s)</b> from the following warehouses: <br><b>{1}</b>").format(
                        total_qty, warehouse_str)
                )
                return None

    else:
        dept_work_ware = get_dept_work_warehouse(self.get('department'))
        if dept_work_ware and dept_work_ware != "pass":
            try:
                get_work_warehouse_doc = frappe.get_doc("Warehouse", self.get('work_warehouse'))
                get_work_warehouse_doc.parent_warehouse = dept_work_ware
                get_work_warehouse_doc.department = self.get('department')
                get_work_warehouse_doc.save(ignore_permissions=True)
            except Exception as e:
                frappe.throw(_("Error while updating work warehouse: {0}").format(str(e)))

@frappe.whitelist()
def update_work_warehouse(doc):
    try:
        if isinstance(doc, str):
            doc = json.loads(doc)
        query = """
                    UPDATE `tabWarehouse`
                    SET department = %s, previous_department = %s
                    WHERE name = %s
                """
        frappe.db.sql(query, (doc.get("department"), doc.get("previous_department"), doc.get("work_warehouse")))

        return True
    except Exception as e:
        frappe.throw("Error while updating work warehouse: ",e)

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
        
        if not parent_warehouse:
            frappe.throw("NJ Settings for 'asset_ware' is not defined")
            return None
        
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
    dept_data = frappe.db.get_value('Department', {'name': department}, ['department_prefix', 'work_warehouse_required'], as_dict=True)
    if dept_data:

        if dept_data.get('department_prefix') == None or dept_data.get('department_prefix') == '':
            frappe.throw(f"<b>Department Prefix</b> is not defined in <b>Department: {department}</b>")
            return None
        
        else:
            if dept_data.get('work_warehouse_required') == None or dept_data.get('work_warehouse_required') == '':
                frappe.throw(f"<b>Work Warehouse Required</b> is not defined in <b>Department: {department}</b>")
                return None
            
            if dept_data.get('work_warehouse_required') == 'Yes':

                dept_work_warehouse = dept_data.get('department_prefix') + '-Work-Warehouse - NJ'
                dept_work_warehouse_query = "SELECT name FROM `tabWarehouse` WHERE name = '{0}' AND disabled = 0".format(dept_work_warehouse)
                dept_work_warehouse_in_db = frappe.db.sql(dept_work_warehouse_query, as_dict=1)
                return dept_work_warehouse_in_db[0].get('name') if dept_work_warehouse_in_db and dept_work_warehouse_in_db[0] else None
            
            else:
                return "pass"
    
def create_emp_ware(self, user_email):
    employee_asset_dept = frappe.db.get_value('NJ Settings', {'parameter': 'employee_asset_dept'}, 'value')
    emp_ware_data = create_warehouse(user_email, employee_asset_dept, self.get('location'), self.get('emp_id'))
    return emp_ware_data

def create_work_ware(self, user_email):
    work_ware = None
    work_warehouse = []

    work_ware_reqd = frappe.db.get_value('Department', {'name': self.get('department')}, 'work_warehouse_required')

    if work_ware_reqd == 'Yes':
        warehouse_name = f"WK-{self.get('first_name').title()}-{self.get('emp_id')}"

        work_warehouse_in_db = frappe.db.sql(
            "SELECT name FROM `tabWarehouse` WHERE warehouse_name = %s AND disabled = 0",
            (warehouse_name,), as_dict=True
        )

        if work_warehouse_in_db:
            work_warehouse.append(work_warehouse_in_db[0].get('name'))

        if not work_warehouse:
            work_ware = create_warehouse(user_email, self.get('department'), self.get('location'), self.get('emp_id'), 'work_ware')

        return work_ware
    else:
        return None


@frappe.whitelist()
def get_previous_department(docname):
    previous_department = frappe.db.get_value('Employee', {'name': docname}, 'department')
    return previous_department

@frappe.whitelist()
def department_change_log(docname, cur_department, previous_department):
    changed_by = frappe.session.user
    update_department_change_logs()

    query = """
        SELECT user_id FROM `tabEmployee`
        WHERE work_warehouse = %(docname)s
        OR employee_asset_warehouse = %(docname)s AND status = 'Active'
    """
    params = {'docname': docname}
    changed_on = frappe.db.sql(query, params, as_dict=True)
    if previous_department != cur_department:
        new_doc = frappe.new_doc('Department Change Log')
        new_doc.flags.ignore_mandatory = True
        new_doc.previous_department = previous_department
        new_doc.current_department = cur_department
        new_doc.changed_by = changed_by
        new_doc.changed_on = ', '.join([row['user_id'] for row in changed_on]) if changed_on else 'No user found'
        new_doc.save()

    return previous_department

@frappe.whitelist()
def get_previous_role_profile(docname):
    return frappe.db.get_value('Employee', {'name': docname}, 'role_profile') or ''

@frappe.whitelist()
def role_profile_change_log(user_id, cur_role_profile, previous_role_profile, ramp_level=None, previous_ramp=None):
    if previous_role_profile != cur_role_profile:
        changed_by = frappe.session.user
        new_doc = frappe.new_doc('Department Change Log')

        new_doc.previous_role_profile = previous_role_profile
        new_doc.current_role_profile = cur_role_profile
        new_doc.previous_ramp_level = previous_ramp if previous_ramp else None
        new_doc.current_ramp_level = ramp_level if ramp_level else None
        new_doc.changed_by = changed_by
        new_doc.changed_on = user_id
        new_doc.save()

        return "Change log created successfully."

@frappe.whitelist()
def get_role_profiles(department):
    """Fetch role profiles based on the selected department"""
    role_profiles = frappe.db.get_all("Role Profile", filters={"department": department}, fields=["name"])
    frappe.logger().info(f"Fetched Role Profiles for {department}: {role_profiles}")  # Debugging
    return [rp["name"] for rp in role_profiles]

@frappe.whitelist()
def get_ramp_level(role_profile, total_days):
    try:
        # Fetch the role profile document
        role_profile_doc = frappe.get_doc("Role Profile", role_profile)
        ramp_table = role_profile_doc.get("ramp_table")

        # Iterate through the ramp_table to find the matching range
        for row in ramp_table:
            from_days = int(row.from_days)
            to_days = int(row.to_days)
            if from_days <= total_days <= to_days:
                # Return both ramp_level and target
                return {
                    "ramp_level": row.ramp_level,
                    "target": row.target
                }

        # If no matching range is found, return a default value or None
        return {
            "ramp_level": "Level not defined",
            "target": None
        }
    except Exception as e:
        frappe.throw(f"Error calculating ramp level: {str(e)}")

@frappe.whitelist()
def update_employee_experience(docname, date_of_joining):
    try:
        # Fetch the current Employee document
        doc = frappe.get_doc("Employee", docname)
        
        # Initialize variables
        no_of_days = 0

        # Check if this department and role profile combination already exists
        existing_entry = None
        for entry in doc.employee_experience_table:
            if entry.department == doc.department and entry.role_profile == doc.role_profile:
                existing_entry = entry
                break
        
        if existing_entry:
            # If combination exists, increment the days
            no_of_days = int(existing_entry.no_of_days) + 1
            # Remove the existing entry to add an updated one
            doc.employee_experience_table.remove(existing_entry)
        else:
            # Handle the case where previous fields are empty
            if not doc.previous_department and not doc.previous_role_profile:
                # Calculate days from date_of_joining
                if isinstance(date_of_joining, str):
                    date_of_joining = datetime.strptime(date_of_joining, "%Y-%m-%d").date()
                elif isinstance(date_of_joining, datetime):
                    date_of_joining = date_of_joining.date()
                
                no_of_days = (datetime.today().date() - date_of_joining).days + 1
            elif not doc.previous_department and doc.previous_role_profile:
                no_of_days = 1
            else:
                no_of_days = 1

        # Get ramp level and target based on calculated days
        ramp_data = get_ramp_level(role_profile=doc.role_profile, total_days=no_of_days)
        ramp_level = ramp_data.get("ramp_level")
        target = ramp_data.get("target")
        
        # Add a new row to the Employee Experience child table
        doc.append("employee_experience_table", {
            "department": doc.department,
            "role_profile": doc.role_profile,
            "ramp_level": ramp_level,
            "target": target,
            "no_of_days": str(no_of_days)
        })
        
        # Save the document to persist changes
        doc.save()
        frappe.db.commit()
        return "Success"

    except Exception as e:
        frappe.log_error(f"Error updating employee experience: {str(e)}")
        frappe.throw(f"Error updating employee experience: {str(e)}")

def update_employee_experience_table():
    """
    Daily update of experience for all active employees.
    Fixed date handling for all date formats.
    """
    try:
        # Get all active employees
        employees = frappe.get_all(
            "Employee",
            filters={"status": "Active"},
            fields=["name", "date_of_joining", "department", "role_profile"]
        )
        
        stats = {
            "total": len(employees),
            "success": 0,
            "errors": 0,
            "start_time": datetime.now()
        }
        
        for emp in employees:
            try:
                doc = frappe.get_doc("Employee", emp.name)
                
                # Find existing experience entry
                existing_entry = next(
                    (entry for entry in doc.employee_experience_table 
                     if entry.department == doc.department and entry.role_profile == doc.role_profile),
                    None
                )
                
                # Calculate days
                if existing_entry:
                    no_of_days = int(existing_entry.no_of_days) + 1
                    doc.employee_experience_table.remove(existing_entry)
                else:
                    if not doc.previous_department and not doc.previous_role_profile:
                        # Fixed date handling
                        join_date = None
                        if isinstance(emp.date_of_joining, str):
                            join_date = datetime.strptime(emp.date_of_joining, "%Y-%m-%d").date()
                        elif isinstance(emp.date_of_joining, datetime):
                            join_date = emp.date_of_joining.date()
                        elif isinstance(emp.date_of_joining, date):
                            join_date = emp.date_of_joining
                        else:
                            raise ValueError(f"Unsupported date format for {emp.name}")
                            
                        no_of_days = (date.today() - join_date).days + 1
                    else:
                        no_of_days = 1
                
                # Get ramp data and update
                ramp_data = get_ramp_level(role_profile=doc.role_profile, total_days=no_of_days)
                
                # Add new experience entry
                doc.append("employee_experience_table", {
                    "department": doc.department,
                    "role_profile": doc.role_profile,
                    "ramp_level": ramp_data["ramp_level"],
                    "target": ramp_data["target"],
                    "no_of_days": str(no_of_days)
                })
                
                # Update parent document
                doc.ramp_level = ramp_data["ramp_level"]
                doc.target = ramp_data["target"]
                
                doc.save()
                stats["success"] += 1
                
            except Exception as e:
                stats["errors"] += 1
                error_msg = f"Error updating employee {emp.name}: {str(e)}"
                frappe.log_error(error_msg, "Daily Employee Experience Update Error")
                continue
        
        # Commit all changes
        frappe.db.commit()
        
        # Log completion
        execution_time = datetime.now() - stats["start_time"]
        summary = (
            f"Daily update completed in {execution_time}.\n"
            f"Total Employees: {stats['total']}\n"
            f"Successful: {stats['success']}\n"
            f"Errors: {stats['errors']}"
        )
        frappe.log_error(summary, "Daily Employee Experience Update Summary")
        
    except Exception as e:
        error_msg = f"Critical error in daily experience update: {str(e)}"
        frappe.log_error(error_msg)

@frappe.whitelist()
def fetch_and_update_ramp_level(docname, department, role_profile):
    try:
        # Fetch the matching experience record
        exp_record = frappe.get_all(
            "Employee Experience",
            filters={
                "parent": docname,
                "department": department,
                "role_profile": role_profile
            },
            fields=["ramp_level"],
            order_by="creation desc",
            limit=1
        )

        if not exp_record or not exp_record[0].get("ramp_level"):
            frappe.throw(_("No ramp level found for the specified filters."))

        ramp_level = exp_record[0].ramp_level

        # Update the ramp_level in Employee
        frappe.db.set_value("Employee", docname, "ramp_level", ramp_level, update_modified=False)

        # Fetch the role profile document
        role_profile_doc = frappe.get_doc("Role Profile", role_profile)

        # Get the target from Ramp Table based on ramp_level
        target = None
        for ramp in role_profile_doc.ramp_table:
            if ramp.ramp_level == ramp_level:
                target = ramp.target
                break

        if not target:
            frappe.throw(_("No target found in Ramp Table for the specified ramp level."))


        # Update the target field in Employee
        frappe.db.set_value("Employee", docname, "target", target, update_modified=False)

        frappe.db.commit()
        return {
            "ramp_level": ramp_level,
            "target": target
        }

    except frappe.DoesNotExistError as e:
        error_message = f"Required document not found: {str(e)}"
        frappe.log_error(error_message, "Fetch and Update Ramp Level")

    except frappe.ValidationError as e:
        frappe.log_error(f"Validation error: {str(e)}", "Fetch and Update Ramp Level")
        raise

    except Exception as e:
        frappe.log_error(f"Error updating ramp level and target: {str(e)}", "Fetch and Update Ramp Level")
        frappe.throw(_("An unexpected error occurred while updating ramp level and target."))

@frappe.whitelist()
def auto_enroll_on_role_profile_change(employee):
    print("calling auto_enroll_on_role_profile_change")
    doc = frappe.get_doc("Employee", employee)
    if not doc.role_profile or not doc.user_id:
        frappe.throw("Missing role profile or user ID on employee.")

    query = """
        SELECT DISTINCT parent AS course
        FROM `tabCourse Role Profile`
        WHERE role_profile = %s
    """
    courses = frappe.db.sql(query, (doc.role_profile,), as_dict=True)

    enrolled_count = 0

    for row in courses:
        course = row.course

        if frappe.db.exists("LMS Batch Membership", {"user": doc.user_id, "course": course}):
            continue

        membership = frappe.new_doc("LMS Batch Membership")
        membership.user = doc.user_id
        membership.course = course
        membership.status = "Enrolled"
        membership.flags.ignore_permissions = True
        membership.insert()

        enrolled_count += 1

    return f"{enrolled_count} course(s) enrolled for user {doc.user_id}."
