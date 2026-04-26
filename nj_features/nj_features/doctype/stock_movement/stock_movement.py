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
            # self.deparement_qty_check()
            check_warehouse_qty(self.name)
            if self.get("make_supplier_return"):
                self.validate_supplier_return()
            else:
                # Consumable repack is handled automatically by CustomStockEntry.on_submit()
                # via _create_consumable_repack_for_transfer() when the Material Transfer
                # SE below is submitted. No need to call make_repack here.
                material_transfer_items = []
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
        model_mismatch_messages = []
        qty_check_cache = {"checked_keys": set(), "item_group_cache": {}}

        for row in doc.get('items', []):
            if not validate_serial_no_and_department(row, doc, error_messages, model_mismatch_messages, qty_check_cache):
                continue

        if error_messages:
            return {
                "error": error_messages,
                "show_production_plan_prompt": bool(model_mismatch_messages),
            }

        return {"success": "Validation passed without errors."}

def validate_serial_no_and_department(row, doc=None, error_messages=None, model_mismatch_messages=None, qty_check_cache=None):
    doc = doc or {}
    error_messages = error_messages if error_messages is not None else []

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

    if department:
        allow_reconfig = frappe.db.get_value("Department", department, "allow_reconfig")

        if not allow_reconfig:
            item_code = serial_doc.get("item_code")
            print("item_code=================",item_code )
            to_make = serial_doc.get("to_make")
            print("to_make=================",to_make )
            
            item_code_model= frappe.db.get_value("Item", item_code, "item_model")
            print("item_code_model=================",item_code_model )
            to_make_model= frappe.db.get_value("Item", to_make, "item_model")
            print("to_make_model=================",to_make_model )

            if item_code_model and to_make_model and item_code_model != to_make_model:
                model_mismatch_message = (
                    f"Reconfiguration not allowed for Department <b>{department}</b>. "
                    f"Item Code Model <b>{item_code_model}</b> and To Make Model <b>{to_make_model}</b> must be same."
                )
                error_messages.append(model_mismatch_message)
                if model_mismatch_messages is not None:
                    model_mismatch_messages.append(model_mismatch_message)
                return False


            if item_code and to_make and item_code != to_make:
                error_messages.append(
                    f"Reconfiguration not allowed for Department <b>{department}</b>. "
                    f"Item Code <b>{item_code}</b> and To Make <b>{to_make}</b> must be same."
                )
                return False
        # department_sla = frappe.db.get_value("Department", department, "sla")
        # print("department_sla=================",department_sla )
        # if department_sla and t_warehouse:
        #     warehouse_aging = frappe.db.sql(
        #         """
        #         SELECT
        #             s.warehouse AS warehouse,
        #             MAX(DATEDIFF(CURDATE(), s.purchase_date)) AS max_age_days
        #         FROM `tabSerial No` s
        #         WHERE s.warehouse = %s
        #         """,
        #         (t_warehouse,),
        #         as_dict=True,
        #     )
        #     print("warehouse_aging=================",warehouse_aging )

        #     max_age_days = warehouse_aging[0].get("max_age_days") if warehouse_aging else None
        #     print("max_age_days=================",max_age_days )
        #     if max_age_days is not None and int(max_age_days) > int(department_sla):
        #         error_messages.append(
        #             f"SLA exceeded for Department <b>{department}</b>. "
        #             f"Department SLA is <b>{int(department_sla)}</b> days, "
        #             f"but max aging in warehouse <b>{t_warehouse}</b> is <b>{int(max_age_days)}</b> days."
        #         )
        #         return False
        warehouse_sla = frappe.db.get_value("Department", department, "sla")
        department_sla = frappe.db.get_value("Department", department, "department_sla")
        if warehouse_sla and t_warehouse:
            warehouse_sla_days = int(warehouse_sla)
            warehouse_aging = frappe.db.sql(
                """
                SELECT
                    s.warehouse AS warehouse,
                    MAX(DATEDIFF(CURDATE(), s.purchase_date)) AS max_age_days
                FROM `tabSerial No` s
                WHERE s.warehouse = %s
                """,
                (t_warehouse,),
                as_dict=True,
            )

            max_age_days = warehouse_aging[0].get("max_age_days") if warehouse_aging else None
            if max_age_days is not None and int(max_age_days) >= warehouse_sla_days:
                error_messages.append(
                    f"SLA exceeded for Department <b>{department}</b>. "
                    f"Warehouse SLA is <b>{warehouse_sla_days}</b> days, "
                    f"but max aging in warehouse <b>{t_warehouse}</b> is <b>{int(max_age_days)}</b> days."
                )
            elif department_sla:
                department_sla_days = int(department_sla)
                department_aging = frappe.db.sql(
                    """
                    WITH MaxAuditCreation AS (
                        SELECT
                            serial_no,
                            MAX(creation) AS max_creation_date
                        FROM `tabNJ Audit Items`
                        WHERE docstatus = 1
                        GROUP BY serial_no
                    ),
                    DeptEntry AS (
                        SELECT
                            serial_no,
                            MIN(creation) AS department_entry_date
                        FROM `tabStock Ledger Entry`
                        WHERE warehouse IN (
                            SELECT name FROM `tabWarehouse` WHERE department = %s
                        )
                        GROUP BY serial_no
                    )
                    SELECT
                        a.serial_no,
                        a.item_group,
                        a.item_code,
                        a.warehouse,
                        DATEDIFF(CURDATE(), a.creation) AS total_age,
                        DATEDIFF(CURDATE(), a.purchase_date) AS current_warehouse_age,
                        b.department,
                        mac.max_creation_date AS last_audit_date,
                        DATEDIFF(CURDATE(), d.department_entry_date) AS department_age
                    FROM `tabSerial No` a
                    JOIN `tabWarehouse` b ON a.warehouse = b.name
                    LEFT JOIN MaxAuditCreation mac ON a.serial_no = mac.serial_no
                    LEFT JOIN DeptEntry d ON a.serial_no = d.serial_no
                    WHERE
                        a.item_group IN ('Laptops', 'Chromebooks', 'Desktops', 'Chromeboxes', 'Full Set Desktops', 'AIO')
                        AND b.department = %s
                    ORDER BY d.department_entry_date ASC
                    """,
                    (department, department),
                    as_dict=True,
                )
                department_age = department_aging[0].get("department_age") if department_aging else None
                department_age_serial = department_aging[0].get("serial_no") if department_aging else None
                if department_age is not None and int(department_age) >= department_sla_days:
                    error_messages.append(
                        f"SLA exceeded for Department <b>{department}</b>. "
                        f"Department SLA is <b>{department_sla_days}</b> days, "
                        f"but Serial No <b>{department_age_serial}</b> has department aging of <b>{int(department_age)}</b> days."
                    )
                    return False
                     
        deparement_qty_check_for_validation(doc, department, t_warehouse, error_messages, qty_check_cache)

    if not check_if_serial_exists_in_active_bag_list(serial_no, error_messages):
        return False

    restriction_item = frappe.get_all("Item Group", {"check_restrictions": 1}, "name")
    restriction_item = [r.get("name") for r in restriction_item]

    if serial_doc.get("item_group") not in restriction_item:
        return False

    if not serial_doc.get("bypass"):

        if department_doc.get('warrenty_restriction_check'):  
            check_warranty_expiry(serial_doc, error_messages)

        s_inspection_type = frappe.get_doc('Department', s_department) if s_department else None
        is_component = frappe.db.get_value('Item Group', serial_doc.get('item_group'), 'is_component')

        if not is_component and s_department != department:
            check_lesson_validation = frappe.db.get_value('NJ Settings', {'parameter': 'check_lesson_validation'} , 'value')
            if check_lesson_validation and int(check_lesson_validation):
                validate_lesson_completion_for_serial_model(serial_doc, error_messages)
            validate_allowed_serial_component_grades(serial_doc, department_doc, error_messages)
            check_min_qty_and_max_qty(serial_doc, department_doc, error_messages)
            validate_grade_restriction(serial_doc, department_doc, error_messages)
            check_bag_list_validation(serial_doc, error_messages, department_doc)
            one_of_these_component_grades_must_be_true(serial_doc, department_doc, t_warehouse, error_messages)

        if (
                s_department and 
                s_department != department and 
                s_inspection_type and
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

def deparement_qty_check_for_validation(doc, department, t_warehouse, error_messages, qty_check_cache=None):
    if not t_warehouse:
        return

    checked_keys = (qty_check_cache or {}).setdefault("checked_keys", set())
    print("checked_keys=================",checked_keys )
    item_group_cache = (qty_check_cache or {}).setdefault("item_group_cache", {})
    print("item_group_cache=================",item_group_cache )
    cache_key = (department, t_warehouse)   
    if cache_key in checked_keys:
        return
    checked_keys.add(cache_key)

    department_qty_and_item_groups = frappe.db.sql(
        """
        SELECT
            d.name AS department,
            GROUP_CONCAT(pm.part) AS item_groups,
            d.max_qty
        FROM `tabWarehouse` w
        INNER JOIN `tabDepartment` d
            ON d.name = w.department
        LEFT JOIN `tabPart Multiselect` pm
            ON pm.parent = d.name
            AND pm.parenttype = 'Department'
            AND pm.parentfield = 'item_group'
        WHERE w.name = %s
        GROUP BY d.name, d.max_qty
        """,
        (t_warehouse,),
        as_dict=1,
    )
    print("department_qty_and_item_groups=================",department_qty_and_item_groups)

    if not department_qty_and_item_groups:
        return

    department_row = department_qty_and_item_groups[0]
    print("department_row=================",department_row)
    max_qty = float(department_row.get("max_qty") or 0)
    print("max_qty=================",max_qty)
    item_groups = [
        item_group.strip()
        for item_group in (department_row.get("item_groups") or "").split(",")
        if item_group and item_group.strip()
    ]
    print("item_groups=================",item_groups)

    if not department or not max_qty or not item_groups:
        return

    placeholders = ", ".join(["%s"] * len(item_groups))
    print("placeholders=================",placeholders)
    current_qty = frappe.db.sql(
        f"""
        SELECT COUNT(*) AS current_qty
        FROM `tabSerial No` sn
        INNER JOIN `tabWarehouse` w
            ON sn.warehouse = w.name
        WHERE sn.item_group IN ({placeholders})
          AND sn.status = 'Active'
          AND w.department = %s
        """,
        tuple(item_groups + [department]),
        as_dict=1,
    )
    print("current_qty=================",current_qty)
    current_qty_value = float((current_qty[0].get("current_qty") if current_qty else 0) or 0)
    print("current_qty_value=================",current_qty_value)

    transfer_qty_value = 0.0
    for item_row in doc.get("items", []):
        row_t_warehouse = item_row.get("t_warehouse")
        print("row_t_warehouse=================",row_t_warehouse)
        if not row_t_warehouse:
            continue

        row_department = frappe.db.get_value('Warehouse', {'name': row_t_warehouse}, 'department')
        if row_department != department:
            continue

        row_item_code = item_row.get("item_code")
        if not row_item_code:
            continue

        row_item_group = item_group_cache.get(row_item_code)
        if row_item_group is None:
            row_item_group = frappe.db.get_value("Item", row_item_code, "item_group")
            item_group_cache[row_item_code] = row_item_group

        if row_item_group in item_groups:
            transfer_qty_value += float(item_row.get("qty") or 0)
            print("transfer_qty_value=================",transfer_qty_value)

    final_qty = current_qty_value + transfer_qty_value
    print("final_qty=================",final_qty)
    if final_qty >= max_qty:
        error_messages.append(
            _(
                "Warehouse qty is full for Department <b>{0}</b>. "
                "Max Qty: <b>{1}</b>, Current Qty: <b>{2}</b>, Transfer Qty: <b>{3}</b>. "
                "You cannot transfer more than max qty."
            ).format(
                department,
                max_qty,
                current_qty_value,
                transfer_qty_value,
            )
        )

def check_if_serial_exists_in_active_bag_list(serial_no, error_messages):
    if not serial_no:
        return True

    bag_rows = frappe.db.sql(
        """
        SELECT
            parent,
            item,
            item_group,
            quantity,
            is_available
        FROM `tabBag List`
        WHERE serial_no = %s
          AND COALESCE(quantity, 0) > 0
          AND COALESCE(is_available, 0) = 1
          AND parenttype = "Serial No"
        ORDER BY modified DESC, creation DESC
        LIMIT 1
        """,
        (serial_no,),
        as_dict=True
    )

    if not bag_rows:
        return True

    row = bag_rows[0]
    parent_serial = row.get("parent")
    item_group = row.get("item_group") or ""
    item_code = row.get("item") or ""

    error_messages.append(
        f"Serial No <b>{serial_no}</b> cannot be transferred because it already exists "
        f"in the active Bag List of Serial No <b>{parent_serial}</b>."
        f"{' Item Group: <b>' + item_group + '</b>.' if item_group else ''}"
        f"{' Item Code: <b>' + item_code + '</b>.' if item_code else ''} "
        f"Please remove it from that Bag List first."
    )
    return False

def validate_lesson_completion_for_serial_model(serial_no_doc, error_messages):
    
    user = frappe.session.user
    model = serial_no_doc.model

    if not model:
        return

    enrolled_courses = frappe.get_all("LMS Batch Membership",
        filters={"member": user},
        pluck="course"
    )

    if not enrolled_courses:
        return

    matched_courses = []
    for course_name in enrolled_courses:
        course_doc = frappe.get_doc("LMS Course", course_name)
        course_models = [row.models for row in course_doc.model]
        if model in course_models:
            matched_courses.append(course_name)

    if not matched_courses:
        return

    chapters = frappe.get_all("Course Chapter",
        filters={"course": ["in", matched_courses]},
        pluck="name"
    )

    if not chapters:
        return

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

        if serial_no_doc.get("item_group") in ['Laptops']:
            s_department = frappe.db.get_value('Warehouse', {'name': s_warehouse}, 'department')
            s_inspection_type = frappe.get_doc('Department', s_department)
            inspection_types = [row.get('inspection_type') for row in s_inspection_type.get("inspection_types")]

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

                current_time = (datetime.now() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

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
    if serial_doc.get("item_group") != "Laptops":
        return

    serial_components = serial_doc.get("serial_no_component", [])
    include_bag_list = department_doc.get("blmh")

    allowed_table = department_doc.get("allowed_item_group_grades", [])
    all_must_match = department_doc.get("all", False)

    serial_set = {
        (comp.get("item_group"), comp.get("grade"))
        for comp in serial_components
        if comp.get("item_group") and comp.get("grade")
    }

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

    serial_item_groups_present = {
        comp.get("item_group")
        for comp in serial_components
        if comp.get("item_group") and int(comp.get("quantity", 0)) == 1
    }

    allowed_map = defaultdict(set)
    allowed_defective_checks = defaultdict(set)

    for entry in allowed_table:
        ig = entry.get("item_group")
        if not ig:
            continue
        if entry.get("restricted_grade"):
            grades = [g.strip() for g in entry.get("restricted_grade", "").split(",") if g.strip()]
            allowed_map[ig].update(grades)
        if entry.get("defects_type"):
            defects = [d.strip() for d in entry.get("defects_type", "").split(",") if d.strip()]
            allowed_defective_checks[ig].update(defects)

    print("allowed_defective_checks ===============", dict(allowed_defective_checks))

    if all_must_match:
        for ig, allowed_grades in allowed_map.items():
            if ig not in serial_item_groups_present:
                continue
            matched = any((ig, grade) in serial_set for grade in allowed_grades)
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

    for ig, allowed_defects in allowed_defective_checks.items():
        if not allowed_defects:
            continue
        if ig not in serial_item_groups_present:
            continue

        actual_defects = {d for ig2, d in serial_defects_set if ig2 == ig}

        if actual_defects and actual_defects.isdisjoint(allowed_defects):
            actual_display = ', '.join(sorted(actual_defects))
            allowed_display = ', '.join(sorted(allowed_defects))
            error_messages.append(
                f"Serial No <b>{serial_doc.name}</b>: In department <b>{department_doc.name}</b>, "
                f"for item group <b>{ig}</b>, only defect type(s) <b>{allowed_display}</b> are allowed, "
                f"but found: <b>{actual_display}</b>."
            )

    if include_bag_list:
        bag_components = serial_doc.get("bag_list", [])

        bag_set = {
            (comp.get("item_group"), comp.get("grade"))
            for comp in bag_components
            if comp.get("item_group") and comp.get("grade")
        }

        bag_item_groups_present = {
            comp.get("item_group")
            for comp in bag_components
            if comp.get("item_group") and int(comp.get("quantity", 0)) == 1
        }

        bag_defects_set = set()
        for comp in bag_components:
            ig = comp.get("item_group")
            if not ig:
                continue
            if comp.get("aesthetic_issue"):
                bag_defects_set.add((ig, "Aesthetic Issue"))
            if comp.get("functional_issue"):
                bag_defects_set.add((ig, "Functional Issue"))
            if comp.get("defects_type"):
                defects = [d.strip() for d in comp.get("defects_type", "").split(",") if d.strip()]
                for d in defects:
                    bag_defects_set.add((ig, d))

        if all_must_match:
            for ig, allowed_grades in allowed_map.items():
                if ig not in bag_item_groups_present:
                    continue
                matched = any((ig, grade) in bag_set for grade in allowed_grades)
                if not matched:
                    actual_grades = {grade for ig2, grade in bag_set if ig2 == ig}
                    actual_display = ', '.join(sorted(actual_grades)) if actual_grades else "None"
                    allowed_display = ', '.join(sorted(allowed_grades))
                    error_messages.append(
                        f"Serial No <b>{serial_doc.name}</b> (bag_list): In department <b>{department_doc.name}</b>, "
                        f"only grade(s) <b>{allowed_display}</b> are allowed for item group <b>{ig}</b>, "
                        f"but found: <b>{actual_display}</b>."
                    )
                    break
        else:
            match_found = False
            for ig, allowed_grades in allowed_map.items():
                if ig not in bag_item_groups_present:
                    continue
                if any((ig, grade) in bag_set for grade in allowed_grades):
                    match_found = True
                    break

            if not match_found:
                for ig, allowed_grades in allowed_map.items():
                    if ig not in bag_item_groups_present:
                        continue
                    actual_grades = {grade for ig2, grade in bag_set if ig2 == ig}
                    actual_display = ', '.join(sorted(actual_grades)) if actual_grades else "None"
                    allowed_display = ', '.join(sorted(allowed_grades))
                    error_messages.append(
                        f"Serial No <b>{serial_doc.name}</b> (bag_list): In department <b>{department_doc.name}</b>, "
                        f"for item group <b>{ig}</b>, only grade(s) <b>{allowed_display}</b> are allowed, "
                        f"but found: <b>{actual_display}</b>."
                    )

        for ig, allowed_defects in allowed_defective_checks.items():
            if not allowed_defects:
                continue
            if ig not in bag_item_groups_present:
                continue

            actual_defects = {d for ig2, d in bag_defects_set if ig2 == ig}

            if actual_defects and actual_defects.isdisjoint(allowed_defects):
                actual_display = ', '.join(sorted(actual_defects))
                allowed_display = ', '.join(sorted(allowed_defects))
                error_messages.append(
                    f"Serial No <b>{serial_doc.name}</b> (bag_list): In department <b>{department_doc.name}</b>, "
                    f"for item group <b>{ig}</b>, only defect type(s) <b>{allowed_display}</b> are allowed, "
                    f"but found: <b>{actual_display}</b>."
                )

    return error_messages

def validate_non_component_grade(serial_doc, department_doc, error_messages):
    result = frappe.db.get_value('Serial No', {'name': serial_doc.get('name')}, ['grade', 'item_group'])

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

    restrict_all = department_doc.get('restrict_all')
    include_bag_list = department_doc.get('blmnh')

    if int(restrict_all):
        item_wizard_name = serial_doc.get("item_wizard")
        if not item_wizard_name:
            return

        item_wizard_doc = frappe.get_doc("Item Wizards", item_wizard_name)

        mandatory_item_groups = set(
            row.get("component_type")
            for row in item_wizard_doc.get("component", [])
            if row.get("mandatory") == 1
        )

        component_grade_map = {}
        for component in serial_doc.get('serial_no_component', []):
            if component.get('quantity') == 1:
                component_grade_map[component.get('item_group')] = component.get('grade')

        if include_bag_list:
            for bag in serial_doc.get('bag_list', []):
                if bag.get('quantity') == 1:
                    item_group = bag.get('item_group')
                    if item_group and item_group not in component_grade_map:
                        component_grade_map[item_group] = bag.get('grade')

        restriction_map = {}
        for restriction in department_doc.get('stock_movement_restriction_table', []):
            item_group = restriction.get('item_group')
            grades = [g.strip() for g in restriction.get('restricted_grade', "").split(",")]
            restriction_map[item_group] = grades

        all_violating = True

        for item_group, restricted_grades in restriction_map.items():
            grade = component_grade_map.get(item_group)

            if grade is None:
                if item_group in mandatory_item_groups:
                    all_violating = False
                    break
                else:
                    continue

            if grade not in restricted_grades:
                all_violating = False
                break

        if all_violating and restriction_map:
            error_messages.append(
                f"Serial No.: <b>{serial_doc.name}</b> — all components "
                f"({', '.join(restriction_map.keys())}) have restricted grades "
                f"and are not allowed for Department: <b>{department_doc.name}</b>."
            )

    else:
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

        if include_bag_list:
            for bag in serial_doc.get('bag_list', []):
                for restriction in department_doc.get('stock_movement_restriction_table', []):
                    restricted_grades = restriction.get('restricted_grade', "").split(",")
                    restricted_item_group = restriction.get('item_group')

                    if (bag.get('item_group') == restricted_item_group and
                            bag.get('grade') in restricted_grades and
                            bag.get('quantity') == 1):
                        error_messages.append(
                            f"Serial No <b>{serial_doc.name}</b> (bag_list) for item_group <b>{bag.get('item_group')}</b> "
                            f"has a grade <b>{bag.get('grade')}</b> that is not allowed for department <b>{department_doc.name}</b>."
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

    for row in query:
        item_group = row['item_group']
        aesthetic_issue = row['aesthetic_issue']
        functional_issue = row['functional_issue']
        damage_types = []

        if aesthetic_issue == 1:
            damage_types.append("Aesthetic")
        if functional_issue == 1:
            damage_types.append("Technical")
        if not damage_types:
            damage_types = [""]

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

        if department_query:
            for department_row in department_query:
                results.append({ "department": department_row['department'] })

    return results

def get_special_max_qty_item_groups_from_nj_settings():
    value = frappe.db.get_value(
        "NJ Settings",
        {
            "doc_type": "Stock Movement",
            "parameter": "Restriction for min and max"
        },
        "value"
    ) or ""

    return [
        row.strip()
        for row in value.splitlines()
        if row and row.strip()
    ]

def check_min_qty_and_max_qty(serial_doc, department_doc, error_messages):
    # Fetch special item groups from NJ Settings instead of hardcoding
    special_item_groups = get_special_max_qty_item_groups_from_nj_settings()

    # Fetch mandatory components from Item Wizard
    item_wizards_mandatory_item_groups_data = frappe.db.get_all(
        'Component',
        {
            'parent': serial_doc.item_wizard,
            'mandatory': '1'
        },
        ['component_type', 'quantity']
    )

    mandatory_item_groups = [
        row.get("component_type")
        for row in item_wizards_mandatory_item_groups_data
    ]

    # Item Wizard quantity lookup
    iw_quantity_map = {
        row.get("component_type"): int(row.get("quantity") or 0)
        for row in item_wizards_mandatory_item_groups_data
        if row.get("component_type")
    }

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

            # Min quantity always from Department
            min_qty = int(row.get('min_quantity') or 0)

            # Max quantity:
            # For configured special item groups -> from Item Wizard qty
            # Everything else -> keep previous Department max flow
            if item_group in special_item_groups:
                max_qty = int(iw_quantity_map.get(item_group) or 0)
            else:
                max_qty = int(row.get('max_quantity') or 1)

            if total_quantity < min_qty or total_quantity > max_qty:
                error_messages.append(
                    f"Serial No <b>{serial_doc.name}</b> for item_group <b>{item_group}</b> "
                    f"has Total quantity <b>{total_quantity}</b> that is not allowed for department "
                    f"<b>{department_doc.name}</b>. "
                    f"(Min: {min_qty}, Max: {max_qty})"
                )

def one_of_these_component_grades_must_be_true(serial_doc, department_doc, t_warehouse, error_messages):
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

@frappe.whitelist()
def check_warehouse_qty(name):
    error_msg = ""

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

        if available_qty < 0:
            available_qty = 0.0

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
    return frappe.db.get_value('Stock Ledger Entry', {'warehouse': warehouse, 'item_code': item, 'is_cancelled': 0}, 'qty_after_transaction', order_by='creation desc')

def item_item_group(item):
    return frappe.db.get_value('Item', item, 'item_group')
