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
            nj_series = "STMR-.YYYY.-.MM.-"
            if self.transfer_status == "Stock Accept":
                nj_series = "STMA-.YYYY.-.MM.-"

            material_transfer_items = []
            
            stock_entry_data = {
                "name": self.name,
                "series": nj_series,
                "doctype": self.doctype,
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
    
    child_warehouses = frappe.db.get_all('Warehouse', {'parent_warehouse': parent_warehouse, 'disabled': 0}, ['name', 'available_capacity', 'max_capacity', 'is_group'])

    for row in child_warehouses:
        if row['is_group']: 
            all_emp_ware.extend(get_child_warehouses(row['name']))  
        else:
            if row['available_capacity'] and int(row['available_capacity']) > 0:
                all_emp_ware.append(row)  

    return all_emp_ware 

@frappe.whitelist()
def validate_stock_movement_for_grade(doc):
    try:
        if isinstance(doc, str):
            doc = json.loads(doc)

        error_messages = []

        for row in doc.get('items', []):
            if not validate_serial_no_and_department(row, error_messages):
                continue

        if error_messages:
            return {"error": error_messages}

        return {"success": "Validation passed without errors."}
    
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in validate_stock_movement_for_grade")
        return {"error": str(e)}


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

    if not serial_doc.get("bypass"):

        if department_doc.get('warrenty_restriction_check') and check_warranty_expiry(serial_doc, error_messages):
            print('Coming inside')
            validate_grade_restriction(serial_doc, department_doc, error_messages)

        s_inspection_type = frappe.db.get_value('Department', {'name': s_department}, ['inspection_type', 'quality_inspection_status_for_stock_movement'], as_dict=True)

        if (s_department and 
        s_department != department and 
        s_inspection_type.get("inspection_type") and  s_inspection_type.get("inspection_type") is not None and 
        s_inspection_type.get("quality_inspection_status_for_stock_movement") and s_inspection_type.get("quality_inspection_status_for_stock_movement") is not None):
        
            check_qi_validation(serial_no, error_messages, s_warehouse, s_department)
        else:
            return True

    return True


def check_qi_validation(serial_no, error_messages, s_warehouse, s_department):

    s_inspection_type = frappe.db.get_value('Department', {'name': s_department}, ['inspection_type', 'quality_inspection_status_for_stock_movement'], as_dict=True)

    query = """
        SELECT se.creation
        FROM `tabStock Entry Detail` sed
        JOIN `tabStock Entry` se ON sed.parent = se.name
        WHERE se.stock_entry_type = "Material Transfer"
        AND sed.serial_no = %s
        AND sed.t_warehouse = %s
        ORDER BY se.creation DESC
        LIMIT 1
    """

    result = frappe.db.sql(query, (serial_no, s_warehouse), as_dict=True)

    if result:
        creation_time = result[0]["creation"]
        formatted_time = creation_time.strftime("%Y-%m-%d %H:%M:%S")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        qi_query = """
            SELECT name
            FROM `tabNJ Quality Inspection`
            WHERE inspection_type = %s AND docstatus = 1
            AND creation BETWEEN %s AND %s
            order by creation desc
            LIMIT 1
        """

        qi_result = frappe.db.sql(qi_query, (s_inspection_type.get("inspection_type"), formatted_time, current_time), as_dict=True)

        if qi_result:
            qi_doc = frappe.get_doc('NJ Quality Inspection', qi_result[0]["name"])

            if qi_doc:
                quality_inspection_status_for_stock_movement = s_inspection_type.get("quality_inspection_status_for_stock_movement").split(",")

                if s_inspection_type.get("quality_inspection_status_for_stock_movement") and qi_doc.get("status") not in quality_inspection_status_for_stock_movement:
                    expected_status = ", ".join(quality_inspection_status_for_stock_movement)
                    actual_status = qi_doc.get("status")
                    
                    error_messages.append(
                        f"NJ Quality Inspection <b>{qi_doc.name}</b> for serial no <b>{serial_no}</b> in warehouse <b>{s_warehouse}</b> has status <b>{actual_status}</b>, but expected status is <b>{expected_status}</b>."
                    )

        else:
            error_messages.append(f"NJ Quality Inspection not found for serial no <b>{serial_no}</b> in warehouse <b>{s_warehouse}</b>.")


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
        
        return check_component_warranty(serial_doc, purchase_order[0], error_messages)

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


def validate_non_component_grade(serial_doc, department_doc, error_messages):
    result = frappe.db.get_value('Serial No', {'name':serial_doc.get('name')}, ['grade', 'item_group'])

    if result is None:
        error_messages.append(
            f"Item <b>{serial_doc.get('item_code')}</b> not found. Cannot validate grade restrictions for serial <b>{serial_doc.name}</b>."
        )
        return

    lap_grade, lap_item_group = result

    for restriction in department_doc.get('stock_movement_restriction_table', []):
        restricted_grades = restriction.get('restricted_grade', "").split(", ")
        restricted_item_group = restriction.get('item_group')

        if lap_item_group == restricted_item_group and lap_grade in restricted_grades:
            error_messages.append(
                f"Serial No <b>{serial_doc.name}</b> for item <b>{serial_doc.get('item_code')}</b> "
                f"with item_group <b>{lap_item_group}</b> has a grade <b>{lap_grade}</b> that is not allowed "
                f"for department <b>{department_doc.name}</b>."
            )
    
    for component in serial_doc.get('serial_no_component', []):
        for restriction in department_doc.get('stock_movement_restriction_table', []):
            restricted_grades = restriction.get('restricted_grade', "").split(", ")
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
        restricted_grades = [grade.upper() for grade in restriction.get('restricted_grade', "").split(", ")]
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
