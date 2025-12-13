import json
import frappe
from frappe import _
from collections import defaultdict
from datetime import datetime, timedelta
from frappe.model.document import Document
from nj_lib.utils.common_utils import get_active_emp
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
from nj_p1_features.nj_p1_features.doctype.machine_part_changes.machine_part_changes import get_part_ledger_entry
logger = frappe.logger('Shopifys', allow_site=True, file_count=1)

class StockMovement(Document):
    def on_submit(self):
        try:
            check_warehouse_qty(self.name)
            if self.get("make_supplier_return"):
                self.validate_supplier_return()
            else:
                do_stock_entry_for_consumables=frappe.db.get_value('NJ Settings', {'parameter': 'do_stock_entry_for_consumables'}, 'value')
                material_transfer_items = []
                for row in self.items:
                    if do_stock_entry_for_consumables=="1" and row.s_warehouse and row.t_warehouse and row.serial_no and row.item_code and item_item_group(row.item_code) == "Laptops":
                        source_dept=warehouse_dept(row.s_warehouse)
                        if source_dept != warehouse_dept(row.t_warehouse):
                            consumables=consumables_for_department(row.item_code, source_dept, row.serial_no)
                            repack_items=[]                               
                            for consumable in consumables:
                                consumable_warehouse=get_consumables_warehouse(source_dept)
                                if not consumable_warehouse:
                                    frappe.throw(f"No consumable Warehouse found for department <b>{source_dept}</b>")
                                qty=warehouse_qty(consumable_warehouse, consumable)
                                if qty and qty >0:
                                    if not consumable_warehouse:
                                        frappe.throw(f"No consumable Warehouse found for department <b>{source_dept}</b>")
                                    repack_items.append({
                                        'qty': 1,
                                        'item_code': consumable,
                                        's_warehouse':consumable_warehouse ,                                         
                                    })
                            if repack_items:
                                make_repack(row.serial_no, repack_items, row.s_warehouse,self.name,self.doctype)                                                                      
                    material_transfer_items.append({
                        'qty': row.qty,
                        'item_code': row.item_code,
                        's_warehouse': row.s_warehouse,
                        't_warehouse': row.t_warehouse,
                        'reason': row.reason if row.reason else None,
                        'serial_no': row.serial_no if row.serial_no else None,
                    })

                if material_transfer_items:
                    stock_entry_data = {
                        "name": self.name,
                        "doctype": self.doctype,
                        "transfer_status": self.transfer_status,
                        "stock_entry_type": "Material Transfer",
                        "material_transfer_items": material_transfer_items,
                    }
                    return stock_entry_using_nj_lib(stock_entry_data)
                else:
                    frappe.throw("None available in <b>Items</b> table.")

        except Exception as e:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), "Stock Movement Submit Failed")
            frappe.throw(f"Error while submitting Stock Entry: {e}")

    def validate_supplier_return(self):
        """
        Validate item codes when making supplier return
        - Called during Stock Movement Document submission
        - Checks if scanned serial item matches purchase receipt item
        - If they don't match, create a stock entry using make_stock_entry_using_nj_lib
        """
        if self.make_supplier_return == 1: 
            for item in self.items:
                if item.serial_no:
                    for serial_no in item.serial_no.split('\n'):
                        serial_no = serial_no.strip()
                        if serial_no:
                            serial_doc = frappe.get_doc("Serial No", serial_no)
                            serial_item_code = serial_doc.item_code

                            # ✅ Correct field from Serial No
                            purchase_receipt = serial_doc.purchase_receipt
                            
                            if purchase_receipt:
                                purchase_item_code = self.get_matching_purchase_item(
                                    purchase_receipt, serial_no, serial_item_code
                                )
                                
                                if serial_item_code != purchase_item_code:
                                    self.make_stock_entry_using_nj_lib()


    def get_matching_purchase_item(self, purchase_receipt, serial_no, serial_item_code):
        """
        Find matching purchase item code from Purchase Receipt Items
        First tries exact serial number match, then tries partial item code match
        """
        # Try exact serial number match first
        purchase_item_code = frappe.db.get_value(
            "Purchase Receipt Item",
            {"parent": purchase_receipt, "serial_no": ['like', f"%{serial_no}%"]},
            ["item_code"]
        )
        
        if purchase_item_code:
            return purchase_item_code
        
        # Try partial match based on base pattern
        purchase_items = frappe.get_all(
            "Purchase Receipt Item",
            filters={"parent": purchase_receipt},
            fields=["item_code", "serial_no"]
        )

        if "GRADE" in serial_item_code:
            base_pattern = serial_item_code.split("GRADE")[0].rstrip("-").strip()

            for purchase_item in purchase_items:
                purchase_item_code = purchase_item.get("item_code", "")
                if purchase_item_code and purchase_item_code.startswith(base_pattern):
                    return purchase_item_code

            serial_base = base_pattern  # reuse base_pattern as serial_base

            for purchase_item in purchase_items:
                purchase_item_code = purchase_item.get("item_code", "")
                if "GRADE" in purchase_item_code:
                    purchase_base = purchase_item_code.split("GRADE")[0].rstrip("-").strip()
                    if serial_base == purchase_base:
                        return purchase_item_code

        frappe.log_error(
            f"No match found for serial: {serial_no} with item code: {serial_item_code}",
            "Debug No Match"
        )
        return None


    def make_stock_entry_using_nj_lib(self):
        """
        Create a stock entry (repack) when serial no item code doesn't match purchase receipt
        """
        cost_account = frappe.db.get_single_value('NewJaisa Configuration', 'default_operational_cost_account')

        stock_data = {
            "name": self.name,
            "doctype": self.doctype,
            "stock_entry_type": "Repack",
            "expense_account": cost_account,
            "items": []
        }

        repack_items_data = self.get_repack_items()
        if repack_items_data and len(repack_items_data) > 1:
            stock_data["repack_items"] = repack_items_data
            stock_entry_using_nj_lib(stock_data)

    def get_repack_items(self):
        return_unpack_items_data = []

        for item in self.items:
            if not item.serial_no:
                frappe.throw(f"Serial No is missing for Item Code: {item.item_code}")

            for serial_no_value in item.serial_no.strip().split('\n'):
                serial_no_value = serial_no_value.strip()
                if not serial_no_value:
                    continue

                serial_no_doc = frappe.get_doc("Serial No", serial_no_value)
                serial_item_code = serial_no_doc.item_code
                purchase_receipt = serial_no_doc.purchase_receipt

                if not purchase_receipt:
                    frappe.throw(f"No Purchase Receipt linked to Serial No: {serial_no_value}")

                purchase_item_code = self.get_matching_purchase_item(purchase_receipt, serial_no_value,item.item_code)

                if not purchase_item_code:
                    frappe.throw(f"Could not find matching item code in Purchase Receipt {purchase_receipt} for Serial No: {serial_no_value}")

                # ✅ Removed item_code match check, repack always

                main_repack_item = {
                    'repack_item_code': item.item_code,
                    'repack_serial_no': serial_no_value,
                    'repack_item_source_warehouse': item.s_warehouse,
                    'is_finished_item': 0
                }
                return_unpack_items_data.append(main_repack_item)

                unpack_item = {
                    'unpack_serial_no': serial_no_value,
                    'unpack_item_code': purchase_item_code,
                    'unpack_item_target_warehouse': item.t_warehouse,
                    'is_finished_item': 1
                }
                return_unpack_items_data.append(unpack_item)

        return return_unpack_items_data

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
        centralized_parent = frappe.db.get_value('Warehouse', {'centralized': 1, 'disabled': 0}, 'name')
        centralized_ware = frappe.db.get_all('Warehouse', {'parent_warehouse': centralized_parent}, ['name', 'available_capacity'])
        recommended_warehouses = {}
        centralized_warehouses = {}
        all_emp_ware = get_child_warehouses(dept_values[1])  

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
    
def get_child_warehouses(parent_warehouse):
    all_emp_ware = []  
    child_warehouse_with_qty_query = """SELECT w.name, w.is_group,
                CASE 
                    WHEN q.available_capacity IS NULL THEN w.max_capacity
                    ELSE q.available_capacity
                END AS available_capacity,
                COALESCE(q.max_capacity, w.max_capacity) AS max_capacity
                FROM `tabWarehouse` w LEFT JOIN `tabWarehouse Qty` q ON q.warehouse = w.name 
                WHERE w.parent_warehouse = %s AND w.disabled = 0"""
    child_warehouse_with_qty = frappe.db.sql(child_warehouse_with_qty_query, parent_warehouse, as_dict=1)
    # child_warehouses = frappe.db.get_all('Warehouse', {'parent_warehouse': parent_warehouse, 'disabled': 0}, ['name', 'available_capacity', 'max_capacity', 'is_group'])

    for row in child_warehouse_with_qty:
        if row['is_group']: 
            all_emp_ware.extend(get_child_warehouses(row['name']))  
        else:
            if row['available_capacity'] and int(row['available_capacity']) > 0:
                all_emp_ware.append(row)  

    return all_emp_ware 

@frappe.whitelist()
def validate_stock_movement_for_grade(doc):
    
        if isinstance(doc, str):
            doc = json.loads(doc)

        error_messages = []

        for row in doc.get('items', []):
            if not validate_serial_no_and_department(row, error_messages):
                continue

        if error_messages:
            return {"error": error_messages}

        return {"success": "Validation passed without errors."}

def validate_serial_no_and_department(row, error_messages):

    has_serialized = frappe.db.get_value('Item', {'name': row.get('item_code')}, 'has_serial_no')

    if not has_serialized:
        return False
    
    s_warehouse = row.get('s_warehouse')
    t_warehouse = row.get('t_warehouse')
    serial_no = row.get('serial_no')

    department = frappe.db.get_value('Warehouse', {'name': t_warehouse}, 'department')
    s_department = frappe.db.get_value('Warehouse', {'name': s_warehouse}, 'department')
    

    if not department:
        error_messages.append(f"Target warehouse <b>{t_warehouse}</b> has no associated department.")
        return False

    department_doc = frappe.get_doc('Department', department)

    try:
        serial_doc = frappe.get_doc('Serial No', serial_no)
    except frappe.DoesNotExistError:
        error_messages.append(f"Serial No <b>{serial_no}</b> does not exist.")
        return False
    
    if serial_doc.get("item_group") not in ["Laptops"]:
            return False

    if not serial_doc.get("bypass"):

        if department_doc.get('warrenty_restriction_check'):  
            check_warranty_expiry(serial_doc, error_messages)
        
        s_inspection_type = frappe.get_doc('Department', s_department)
        is_component = frappe.db.get_value('Item Group', serial_doc.get('item_group'), 'is_component')

        if not is_component and s_department != department:
            check_lesson_validation = frappe.db.get_value('NJ Settings', {'parameter': 'check_lesson_validation'} , 'value')
            if check_lesson_validation and int(check_lesson_validation):
                validate_lesson_completion_for_serial_model(serial_doc, error_messages)
            validate_allowed_serial_component_grades(serial_doc, department_doc, error_messages)
            check_min_qty_and_max_qty(serial_doc, department_doc, error_messages)#this function will check the mandatory item groups, for those item groups, the qty in part list should be within range defined
            validate_grade_restriction(serial_doc, department_doc, error_messages)
            check_bag_list_validation(serial_doc, error_messages, department_doc)
            one_of_these_component_grades_must_be_true(serial_doc, department_doc, t_warehouse,error_messages)
        
        if (
                s_department and 
                s_department != department and 
                s_inspection_type.get("inspection_types") and  
                s_inspection_type.get("inspection_types") is not None and 
                s_inspection_type.get("inspection_types") != [] and
                s_inspection_type.get("quality_inspection_status_for_stock_movement") and 
                s_inspection_type.get("quality_inspection_status_for_stock_movement") is not None
            ):

            check_qi_validation(serial_no, error_messages, s_warehouse, s_department, department)
        else:
            return True

    return True

def validate_lesson_completion_for_serial_model(serial_no_doc, error_messages):
    
    user = frappe.session.user
    model = serial_no_doc.model

    if not model:
        return

    # Step 1: Get all enrolled courses via LMS Batch Membership
    enrolled_courses = frappe.get_all("LMS Batch Membership",
        filters={"member": user},
        pluck="course"
    )

    if not enrolled_courses:
        return

    # Step 2: Filter courses where model is in Course.models table
    matched_courses = []
    for course_name in enrolled_courses:
        course_doc = frappe.get_doc("LMS Course", course_name)
        course_models = [row.models for row in course_doc.model]  # assuming 'model' is the child table field
        if model in course_models:
            matched_courses.append(course_name)

    if not matched_courses:
        return

    # Step 3: Get chapters from those courses
    chapters = frappe.get_all("Course Chapter",
        filters={"course": ["in", matched_courses]},
        pluck="name"
    )

    if not chapters:
        return

    # Step 4: Get lessons linked in chapter.lesson (child table: Lesson Reference)
    required_lessons = set()
    for chapter in chapters:
        chapter_doc = frappe.get_doc("Course Chapter", chapter)
        lesson_names = [row.lesson for row in chapter_doc.lessons if row.lesson]
        
        for lesson_name in lesson_names:
            lesson_doc = frappe.get_doc("Course Lesson", lesson_name)
            lesson_models = [row.models for row in lesson_doc.model]
            if model in lesson_models:
                required_lessons.add(lesson_name)

    if not required_lessons:
        return

    # Step 5: Check which lessons are completed
    completed_lessons = frappe.get_all("LMS Course Progress",
        filters={
            "owner": user,
            "lesson": ["in", list(required_lessons)],
            "status": "Complete"
        },
        pluck="lesson"
    )

    not_completed = list(required_lessons - set(completed_lessons))

    if not_completed:
        lesson_list = ", ".join(not_completed)
        error_messages.append(
            f"❌ You must complete all LMS lessons for model '<b>{model}</b>' before using Serial No '<b>{serial_no_doc.name}</b>'.<br>Pending Lessons: <b>{lesson_list}</b>"
        )

def check_bag_list_validation(serial_doc, error_messages, department_doc):
    if serial_doc and department_doc.get("check_for_bag_list"):
        bag_list = serial_doc.get("bag_list", [])
        
        # Filter items with quantity > 0
        valid_items = [item for item in bag_list if item.get("quantity", 0) > 0]
        
        if valid_items:
            item_groups = list({item.get("item_group") for item in valid_items if item.get("item_group")})
            item_groups_str = ", ".join(f"<b>{group}</b>" for group in item_groups)
            error_messages.append(
                f"Serial No <b>{serial_doc.get('name')}</b> cannot be moved as it contains parts in a bag. "
                f"Item groups present in the bag: {item_groups_str}. Please remove them before proceeding."
            )

def check_qi_validation(serial_no, error_messages, s_warehouse, s_department, t_department):
    try:
        serial_no_doc = frappe.get_doc('Serial No', serial_no)

        # Only validate for laptops
        if serial_no_doc.get("item_group") in ['Laptops']:
            # Get source department and inspection types
            s_department = frappe.db.get_value('Warehouse', {'name': s_warehouse}, 'department')
            s_inspection_type = frappe.get_doc('Department', s_department)
            inspection_types = [row.get('inspection_type') for row in s_inspection_type.get("inspection_types")]

            # Find the last material transfer entry for this serial
            query = """
                SELECT se.creation, se.name
                FROM `tabStock Entry Detail` sed
                JOIN `tabStock Entry` se ON sed.parent = se.name
                WHERE se.stock_entry_type = "Material Transfer"
                AND sed.source_department != sed.target_department
                AND sed.serial_no = %s
                AND se.docstatus = 1
                ORDER BY se.creation DESC
                LIMIT 1
            """
            result = frappe.db.sql(query, (serial_no,), as_dict=True)

            if result and inspection_types:
                creation_time = result[0]["creation"]
                formatted_time = creation_time.strftime("%Y-%m-%d %H:%M:%S")

                # Convert current time to IST (UTC+5:30)
                current_time = (datetime.now() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

                # Fetch QI created between transfer and now
                qi_query = """
                    SELECT name
                    FROM `tabNJ Quality Inspection`
                    WHERE inspection_type IN %s
                    AND docstatus = 1
                    AND barcode = %s
                    AND modified BETWEEN %s AND %s
                    ORDER BY creation DESC
                    LIMIT 1
                """
                qi_result = frappe.db.sql(
                    qi_query,
                    (tuple(inspection_types), serial_no, formatted_time, current_time),
                    as_dict=True
                )

                # Get target department rules
                t_inspection_type = frappe.get_doc('Department', t_department)

                if qi_result:
                    qi_doc = frappe.get_doc('NJ Quality Inspection', qi_result[0]["name"])

                    if qi_doc and s_inspection_type.get("quality_inspection_status_for_stock_movement"):
                        allowed_statuses = [
                            status.strip() for status in s_inspection_type.get("quality_inspection_status_for_stock_movement").split(",")
                        ]

                        if qi_doc.get("status") not in allowed_statuses:
                            expected_status = ",".join(allowed_statuses)
                            actual_status = qi_doc.get("status")

                            error_messages.append(
                                f"NJ Quality Inspection <b>{qi_doc.name}</b> for serial no <b>{serial_no}</b> "
                                f"in warehouse <b>{s_warehouse}</b> has status <b>{actual_status}</b>, "
                                f"but target department <b>{t_department}</b> only allows status: <b>{expected_status}</b>."
                            )
                else:
                    error_messages.append(
                        f"NJ Quality Inspection not found for serial no <b>{serial_no}</b> in warehouse <b>{s_warehouse}</b> "
                        f"between <b>{formatted_time}</b> and <b>{current_time}</b>."
                    )

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Error in check_qi_validation")
        error_messages.append(f"An error occurred during Quality Inspection validation. Please check logs. Error: {str(e)}")

def check_warranty_expiry(serial_doc, error_messages):
    try:
        query = """
            SELECT DATE(creation) AS creation_date, warranty_days, part_warranty, all_except
            FROM `tabPurchase Order` 
            WHERE name = %s
        """
        purchase_order = frappe.db.sql(query, serial_doc.get('purchase_order'), as_dict=True)

        if not purchase_order:
            return

        is_component = frappe.db.get_value('Item Group', serial_doc.get('item_group'), 'is_component')

        if not is_component:
            return check_general_warranty(serial_doc, purchase_order[0], error_messages)
        else:
            check_general_warranty(serial_doc, purchase_order[0], error_messages)
            check_component_warranty(serial_doc, purchase_order[0], error_messages)
            return

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in check_warranty_expiry")
        error_messages.append(f"Error in warranty expiry check: {str(e)}")

def check_general_warranty(serial_doc, purchase_order, error_messages):
    creation_date = purchase_order.get('creation_date')
    warranty_days = purchase_order.get('warranty_days')

    if not warranty_days:
        return True

    warranty_expiry_date = creation_date + timedelta(days=warranty_days)
    today_date = datetime.now().date()

    if today_date > warranty_expiry_date:
        return True

    remaining_days = (warranty_expiry_date - today_date).days
    error_messages.append(f"The warranty is still valid for item_code <b>{serial_doc.get('item_code')}</b>. <b>{remaining_days} day(s)</b> remaining.")
    return False

def check_component_warranty(serial_doc, purchase_order, error_messages):
    if purchase_order.get('part_warranty'):
        if purchase_order.get('all_except'):
            return check_specific_part_warranty(serial_doc, purchase_order, error_messages)
        return check_component_expiry(serial_doc, purchase_order, error_messages)

def check_specific_part_warranty(serial_doc, purchase_order, error_messages):
    query = """
        SELECT item_group, warranty_days
        FROM `tabPurchase Order Warrenty for Specific Parts`
        WHERE parent = %s
    """
    warranty_for_specific_parts = frappe.db.sql(query, serial_doc.get('purchase_order'), as_dict=True)
    
    warranty_for_specific_parts_list = [row.get("item_group") for row in warranty_for_specific_parts]

    if serial_doc.get('item_group') in warranty_for_specific_parts_list:
        return True

    return check_general_warranty(purchase_order, error_messages)

def check_component_expiry(serial_doc, purchase_order, error_messages):
    po_doc = frappe.get_doc('Purchase Order', serial_doc.get('purchase_order'))

    for idx, row in enumerate(po_doc.get('purchase_order_warrenty_for_specific_parts'), start=1):
        if row.get("item_group") == serial_doc.get("item_group"):
            warranty_days = row.get('warranty_days')
            creation_date = po_doc.get('creation')

            if warranty_days:
                if isinstance(creation_date, datetime):
                    creation_date = creation_date.date()

                warranty_expiry_date = creation_date + timedelta(days=warranty_days)
                today_date = datetime.now().date()

                if today_date > warranty_expiry_date:
                    return True

                remaining_days = (warranty_expiry_date - today_date).days
                error_messages.append(
                    f"Serial No: <b>{serial_doc.get('name')}</b>, Row: <b>{idx}</b> - "
                    f"The general warranty is still valid. <b>{remaining_days} day(s)</b> remaining."
                )
                return False
    return True

def validate_grade_restriction(serial_doc, department_doc, error_messages):
    try:
        is_component = frappe.db.get_value('Item Group', serial_doc.get('item_group'), 'is_component')

        if not is_component:
            validate_non_component_grade(serial_doc, department_doc, error_messages)
        else:
            validate_component_grade(serial_doc, department_doc, error_messages)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in validate_grade_restriction")
        error_messages.append(f"Error in grade restriction validation: {str(e)}")

def validate_allowed_serial_component_grades(serial_doc, department_doc, error_messages):
    """
    Validate serial components of a laptop against allowed grades and defect types in a department.

    Args:
        serial_doc (dict): Serial document containing item_group, serial_no_component.
        department_doc (dict): Department document containing allowed_item_group_grades, all flag.
        error_messages (list): List to append error messages to.
    """
    if serial_doc.get("item_group") != "Laptops":
        return

    serial_components = serial_doc.get("serial_no_component", [])
    allowed_table = department_doc.get("allowed_item_group_grades", [])
    all_must_match = department_doc.get("all", False)

    # ----------------------------
    # Build serial sets
    # ----------------------------
    # Grades
    serial_set = {
        (comp.get("item_group"), comp.get("grade"))
        for comp in serial_components
        if comp.get("item_group") and comp.get("grade")
    }

    # Defects
    serial_defects_set = set()
    for comp in serial_components:
        ig = comp.get("item_group")
        if not ig:
            continue
        if comp.get("aesthetic_issue"):
            serial_defects_set.add((ig, "Aesthetic Issue"))
        if comp.get("functional_issue"):
            serial_defects_set.add((ig, "Functional Issue"))
        if comp.get("defects_type"):
            defects = [d.strip() for d in comp.get("defects_type", "").split(",") if d.strip()]
            for d in defects:
                serial_defects_set.add((ig, d))
                
    print("serial_defects_set ===============", serial_defects_set)

    # Track item groups present
    serial_item_groups_present = {comp.get("item_group") for comp in serial_components if comp.get("item_group")}

    # ----------------------------
    # Build allowed maps
    # ----------------------------
    allowed_map = defaultdict(set)  # For grades
    allowed_defective_checks = defaultdict(set)  # For defects

    for entry in allowed_table:
        ig = entry.get("item_group")
        if not ig:
            continue
        # Grades
        if entry.get("restricted_grade"):
            grades = [g.strip() for g in entry.get("restricted_grade", "").split(",") if g.strip()]
            allowed_map[ig].update(grades)
        # Defects
        if entry.get("defects_type"):
            defects = [d.strip() for d in entry.get("defects_type", "").split(",") if d.strip()]
            allowed_defective_checks[ig].update(defects)

    print("allowed_defective_checks ===============", dict(allowed_defective_checks))

    # ----------------------------
    # Grades validation
    # ----------------------------
    if all_must_match:
        for ig, allowed_grades in allowed_map.items():
            if ig not in serial_item_groups_present:
                continue
            matched = any((ig, grade) in serial_set for grade in allowed_grades)
            print(f"Checking grades for {ig}: matched = {matched}")
            if not matched:
                actual_grades = {grade for ig2, grade in serial_set if ig2 == ig}
                actual_display = ', '.join(sorted(actual_grades)) if actual_grades else "None"
                allowed_display = ', '.join(sorted(allowed_grades))
                error_messages.append(
                    f"Serial No <b>{serial_doc.name}</b>: In department <b>{department_doc.name}</b>, "
                    f"only grade(s) <b>{allowed_display}</b> are allowed for item group <b>{ig}</b>, "
                    f"but found: <b>{actual_display}</b>."
                )
                break
    else:
        match_found = False
        for ig, allowed_grades in allowed_map.items():
            if ig not in serial_item_groups_present:
                continue
            if any((ig, grade) in serial_set for grade in allowed_grades):
                match_found = True
                break

        if not match_found:
            for ig, allowed_grades in allowed_map.items():
                if ig not in serial_item_groups_present:
                    continue
                actual_grades = {grade for ig2, grade in serial_set if ig2 == ig}
                actual_display = ', '.join(sorted(actual_grades)) if actual_grades else "None"
                allowed_display = ', '.join(sorted(allowed_grades))
                error_messages.append(
                    f"Serial No <b>{serial_doc.name}</b>: In department <b>{department_doc.name}</b>, "
                    f"for item group <b>{ig}</b>, only grade(s) <b>{allowed_display}</b> are allowed, "
                    f"but found: <b>{actual_display}</b>."
                )

    # ----------------------------
    # Defects validation
    # ----------------------------
    for ig, allowed_defects in allowed_defective_checks.items():
        # Skip item groups with no defects restriction
        if not allowed_defects:
            continue

        if ig not in serial_item_groups_present:
            continue

        # Collect actual defects for this item group
        actual_defects = {d for ig2, d in serial_defects_set if ig2 == ig}

        # If NONE of the actual defects are allowed → error
        if actual_defects and actual_defects.isdisjoint(allowed_defects):
            actual_display = ', '.join(sorted(actual_defects))
            allowed_display = ', '.join(sorted(allowed_defects))
            error_messages.append(
                f"Serial No <b>{serial_doc.name}</b>: In department <b>{department_doc.name}</b>, "
                f"for item group <b>{ig}</b>, only defect type(s) <b>{allowed_display}</b> are allowed, "
                f"but found: <b>{actual_display}</b>."
            )

        # ✅ If at least one defect is allowed, nothing is appended

    return error_messages


def validate_non_component_grade(serial_doc, department_doc, error_messages):
    result = frappe.db.get_value('Serial No', {'name':serial_doc.get('name')}, ['grade', 'item_group'])

    if result is None:
        error_messages.append(
            f"Item <b>{serial_doc.get('item_code')}</b> not found. Cannot validate grade restrictions for serial <b>{serial_doc.name}</b>."
        )
        return

    lap_grade, lap_item_group = result

    for restriction in department_doc.get('stock_movement_restriction_table', []):
        restricted_grades = restriction.get('restricted_grade', "").split(",")
        restricted_item_group = restriction.get('item_group')

        if lap_item_group == restricted_item_group and lap_grade in restricted_grades:
            error_messages.append(
                f"Serial No.: <b>{serial_doc.name}</b> for Item: <b>{serial_doc.get('item_code')}</b> "
                f"with Item Group: <b>{lap_item_group}</b> has Grade: <b>{lap_grade}</b> this is not allowed "
                f"for Department: <b>{department_doc.name}</b>."
            )
    
    for component in serial_doc.get('serial_no_component', []):
        for restriction in department_doc.get('stock_movement_restriction_table', []):
            restricted_grades = restriction.get('restricted_grade', "").split(",")
            restricted_item_group = restriction.get('item_group')

            if (component.get('item_group') == restricted_item_group and
                    component.get('grade') in restricted_grades and
                    component.get('quantity') == 1):
                    error_messages.append(
                        f"Serial No <b>{serial_doc.name}</b> for item_group <b>{component.get('item_group')}</b> "
                        f"has a grade <b>{component.get('grade')}</b> that is not allowed for department <b>{department_doc.name}</b>."
                    )

def validate_component_grade(serial_doc, department_doc, error_messages):
    for restriction in department_doc.get('stock_movement_restriction_table', []):
        restricted_grades = [grade.upper() for grade in restriction.get('restricted_grade', "").split(",")]
        if (serial_doc.get('item_group') == restriction.get('item_group') and
                get_item_code_and_warehouse(serial_doc.get('item_code')).upper() in restricted_grades):
            error_messages.append(
                f"Serial No <b>{serial_doc.name}</b> for item_group <b>{serial_doc.get('item_group')}</b> "
                f"has a grade <b>{serial_doc.get('grade')}</b> that is not allowed for department <b>{department_doc.name}</b>."
            )

def get_item_code_and_warehouse(item_code):
    try:
        grade = frappe.db.get_value("Item Variant Attribute", {"parent": item_code, "attribute": "Grade"}, "attribute_value")
        if not grade:
            return

        return grade
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in get_item_code_and_warehouse")
        return
    
@frappe.whitelist()
def get_grades_from_part_list(search_value):
    query = frappe.db.sql(
        """
            SELECT   item_group ,aesthetic_issue , functional_issue
            FROM `tabSerial No Component`
            WHERE parent = %s and lower(grade) in ('grade c','grade d')
        """,
        search_value,
        as_dict=True
    )

    results = []

    # Loop through each item_group from the query result
    for row in query:
        item_group = row['item_group']
        aesthetic_issue = row['aesthetic_issue']
        functional_issue = row['functional_issue']
        damage_types = []

        if aesthetic_issue == 1:
            damage_types.append("Aesthetic")
        if functional_issue == 1:
            damage_types.append("Technical")
        if not damage_types:  # If both issues are 0
            damage_types = [""]

        # Fetch department value from the Repairability child table
        department_query = frappe.db.sql(
            """
                SELECT department
                FROM `tabRepairability`
                WHERE parent = %s {damage_type_condition}
            """.format(
                damage_type_condition="AND damage_type IN %s" if damage_types[0] else ""
            ),
            (item_group, tuple(damage_types)) if damage_types[0] else (item_group,),
            as_dict=True
        )

        # If department data is found, append it to the result list
        if department_query:
            for department_row in department_query:
                results.append({ "department": department_row['department'] })

    # Return the consolidated results
    return results

def check_min_qty_and_max_qty(serial_doc, department_doc, error_messages):
    # Get mandatory item groups
    item_wizards_mandatory_item_groups_data = frappe.db.get_all(
        'Component',
        {'parent': serial_doc.item_wizard, 'mandatory': '1'},
        'component_type'
    )
    mandatory_item_groups = [row.get("component_type") for row in item_wizards_mandatory_item_groups_data]
    for row in department_doc.get('allowed_item_group_grades'):
        item_group = row.get('item_group')
        if item_group in mandatory_item_groups:
            total_quantity = 0
            # Sum quantity from serial_no_component
            for col in serial_doc.get('serial_no_component', []):
                if col.get('item_group') == item_group:
                    total_quantity += int(col.get('quantity') or 0)
            # Sum quantity from bag_list
            for col in serial_doc.get('bag_list', []):
                if col.get('item_group') == item_group:
                    total_quantity += int(col.get('quantity') or 0)
            # Compare with min/max
            min_qty = int(row.get('min_quantity') or 0)
            max_qty = int(row.get('max_quantity') or 1)

            if total_quantity < min_qty or total_quantity > max_qty:
                error_messages.append(
                    f"Serial No <b>{serial_doc.name}</b> for item_group <b>{item_group}</b> "
                    f"has a Total quantity <b>{total_quantity}</b> that is not allowed for department <b>{department_doc.name}</b>. "
                    f"(Min: {min_qty}, Max: {max_qty})"
                )

def one_of_these_component_grades_must_be_true(serial_doc, department_doc, t_warehouse,error_messages):
    if not department_doc.get('one_of_these_component_grades_must_be_true'):
        return

    sql_query = """
        SELECT DISTINCT O.name
        FROM `tabSerial No` Sr
        INNER JOIN `tabSerial No Component` Comp ON Sr.name = Comp.parent
        LEFT JOIN `tabOne of These Component Grades Must Be True` O 
            ON (O.item_group = Comp.item_group)
        INNER JOIN `tabDepartment` d
        WHERE O.grade = Comp.grade
        AND O.parent = %s
        AND d.name = %s
        AND Sr.name = %s
        AND (
                (Comp.aesthetic_issue = 1 AND d.damage_type = 'Aesthetic')
            OR (Comp.functional_issue = 1 AND d.damage_type = 'Technical')
        )
    """

    result = frappe.db.sql(
        sql_query,
        (department_doc.name, department_doc.name, serial_doc.name),
        as_dict=True
    )

    # if not result:
    #     error_messages.append(f'This Serial No: <b>{serial_doc.name}</b> is not allowed to be moved to <b>{department_doc.name}</b> Department. Validate Item group , Grade and Work required for this Serial No to know the reason')

@frappe.whitelist()
def check_warehouse_qty(name):
    error_msg = ""

    # Get total qty per target warehouse from Stock Movement Detail
    warehouse_data_query = """
        SELECT SUM(qty) AS total_qty, t_warehouse 
        FROM `tabStock Movement Detail` 
        WHERE parent = %s 
        GROUP BY t_warehouse
    """  
    warehouse_data = frappe.db.sql(warehouse_data_query, (name,), as_dict=True)

    if not warehouse_data:
        return None

    for row in warehouse_data:
        warehouse = row.get("t_warehouse")
        total_qty = float(row.get("total_qty") or 0)

        # Get available capacity from Warehouse & Serial No
        # available_capacity = max_capacity - current_occupied_qty_in_serial_no
        capacity_query = """
            SELECT
                COALESCE(w.max_capacity, 0) 
                - COALESCE(sn.current_qty, 0) AS available_capacity
            FROM `tabWarehouse` w
            LEFT JOIN (
                SELECT warehouse, COUNT(*) AS current_qty
                FROM `tabSerial No`
                WHERE warehouse = %(warehouse)s
                GROUP BY warehouse
            ) AS sn
                ON sn.warehouse = w.name
            WHERE w.name = %(warehouse)s
        """

        result = frappe.db.sql(capacity_query, {"warehouse": warehouse}, as_dict=True)

        available_qty = 0.0
        if result and result[0].get("available_capacity") is not None:
            available_qty = float(result[0].get("available_capacity") or 0)

        # Optional: don't allow negative available qty
        if available_qty < 0:
            available_qty = 0.0

        # Compare requested qty vs available capacity
        if total_qty > available_qty:
            error_msg += (
                f"Total qty for warehouse <b>{warehouse}</b> is <b>{total_qty}</b>, "
                f"but available capacity (based on Serial No) is <b>{available_qty}</b>.<br>"
            )

    if error_msg:
        frappe.throw(error_msg)

    return None


def warehouse_dept(warehouse):
    return frappe.db.get_value('Warehouse', warehouse, 'department')

def warehouse_qty(warehouse, item):
    return frappe.db.get_value('Stock Ledger Entry', {'warehouse': warehouse, 'item_code': item, 'is_cancelled': 0}, 'qty_after_transaction',order_by='creation desc')


def item_item_group(item):
    return frappe.db.get_value('Item', item, 'item_group')

def consumables_for_department(item, department, serial_no):
    iw=frappe.db.get_value('Serial No', serial_no, 'item_wizard')
    pattern=f"%{department}%"
    query=""" 
        Select item_code from `tabConsumables` where parent=%(item_wizard)s and (departments like %(pattern)s) ;
       """
    consubles_items=[]
    if iw:
        result=frappe.db.sql(query,{'item_wizard':iw,'pattern':pattern},as_dict=True)
        if result:
            for item in result:
                consubles_items.append(item.get('item_code'))
    return consubles_items

def get_consumables_warehouse(department):
    return frappe.db.get_value('Warehouse', {'department': department, 'used_for_consumables_stock':1}, 'name')
    
def make_repack(serial_no, repack_items,source_warehouse,name,doctype):
    if serial_no and repack_items:
        item_code=frappe.db.get_value('Serial No', serial_no, 'item_code')
        qty=1
        part_rate=0.0
        valuation_rate_parent_serial_no=get_part_ledger_entry(item_code,serial_no)
        part_rate+=valuation_rate_parent_serial_no
        new_stock_entry={
            "doctype": doctype,
            "name": name,
            "stock_entry_type": "Repack",
            "parent_serial_no":serial_no,
            "repack_items":[]
        }
        new_stock_entry.append("repack_items",{
            "repack_item_code":item_code,
            "qty":qty,
            "repack_serial_no":serial_no,
            "repack_item_source_warehouse":source_warehouse,
            "unpack_item_base_price":valuation_rate_parent_serial_no            
        })
        for item in repack_items:
            valuation_rate=get_part_ledger_entry(item.get('item_code'))
            if not valuation_rate:
                part_rate+=valuation_rate_parent_serial_no
            new_stock_entry.append("repack_items",{
                "repack_item_code":item.get('item_code'),
                "qty":item.get('qty'),
                "repack_item_source_warehouse":item.get('s_warehouse'),
                "repack_item_base_price":valuation_rate
            })
        new_stock_entry.append("repack_items",{
            "unpack_item_code":item_code,
            "qty":qty,
            "unpack_item_target_warehouse":source_warehouse,
            "unpack_serial_no":serial_no,
            "unpack_item_base_price":part_rate
        })
        return stock_entry_using_nj_lib(new_stock_entry)

def get_valuation_rate(warehouse, item_code):
    return frappe.db.get_value('Stock Ledger Entry', {'warehouse': warehouse, 'item_code': item_code, 'is_cancelled': 0}, 'valuation_rate',order_by='creation desc')