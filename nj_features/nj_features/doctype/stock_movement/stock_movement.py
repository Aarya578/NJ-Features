import json
import frappe
from frappe import _
from collections import defaultdict
from datetime import datetime, timedelta
from frappe.model.document import Document
from nj_lib.utils.common_utils import get_active_emp
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
logger = frappe.logger('Shopifys', allow_site=True, file_count=100)
class StockMovement(Document):
    def on_submit(self):
        # self.validate_supplier_return()
        try:
            if self.get("make_supplier_return"):
                self.validate_supplier_return()
                return

            material_transfer_items = []
            
            stock_entry_data = {
                "name": self.name,
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



    def validate_supplier_return(self):
        """
        Validate item codes when making supplier return
        - Called during Stock Movement Document submission
        - Checks if scanned serial item matches purchase receipt item
        - If they don't match, create a stock entry using make_stock_entry_using_nj_lib
        """
        # Check the value of make_supplier_return field (0 or 1)
        if self.make_supplier_return == 1: 
            for item in self.items:
                if item.serial_no:
                    for serial_no in item.serial_no.split('\n'):
                        if serial_no:
                            serial_doc = frappe.get_doc("Serial No", serial_no.strip())
                            serial_item_code = serial_doc.item_code
                            
                            purchase_receipt = serial_doc.purchase_document_no 
                            
                            if purchase_receipt:
                                # Get the matching purchase item code using the new method
                                purchase_item_code = self.get_matching_purchase_item(purchase_receipt, serial_no.strip(), serial_item_code)
                                
                                if serial_item_code != purchase_item_code:
                                    self.make_stock_entry_using_nj_lib()

    def get_matching_purchase_item(self, purchase_receipt, serial_no, serial_item_code):
        """
        Find matching purchase item code from Purchase Receipt Items
        First tries exact serial number match, then tries partial item code match
        """
        # First try to find exact serial number match
        purchase_item_code = frappe.db.get_value(
            "Purchase Receipt Item",
            {"parent": purchase_receipt, "serial_no": ['like', f"%{serial_no}%"]},
            ["item_code"],
        )
        
        if purchase_item_code:
            return purchase_item_code
        
        # If no exact serial match found, try partial item code matching
        # Get all items from the purchase receipt
        purchase_items = frappe.get_all(
            "Purchase Receipt Item",
            filters={"parent": purchase_receipt},
            fields=["item_code", "serial_no"]
        )
        
        
        # Extract the base pattern from serial item code (up to the last hyphen before "GRADE")
        if "GRADE" in serial_item_code:
            # Split by "GRADE" and take the first part, then remove the last hyphen if exists
            base_pattern = serial_item_code.split("GRADE")[0].rstrip("-")
            
            # Check each purchase item for partial match
            for purchase_item in purchase_items:
                purchase_item_code = purchase_item.get("item_code", "")
                
                # Check if the purchase item code starts with the same base pattern
                if purchase_item_code and base_pattern and purchase_item_code.startswith(base_pattern):
                    return purchase_item_code
        
        # Additional fallback: Try to match by removing the grade part from both codes
        if "GRADE" in serial_item_code:
            serial_base = serial_item_code.split("GRADE")[0].strip().rstrip("-")
            
            for purchase_item in purchase_items:
                purchase_item_code = purchase_item.get("item_code", "")
                if "GRADE" in purchase_item_code:
                    purchase_base = purchase_item_code.split("GRADE")[0].strip().rstrip("-")
                    
                    # Compare the base parts
                    if serial_base == purchase_base:
                        # logger.info(f"Fallback Match Found: {purchase_item_code}", "Debug Fallback Match")
                        return purchase_item_code
        
        frappe.log_error(f"No match found for serial: {serial_no} with item code: {serial_item_code}", "Debug No Match")
        # If still no match found, return None to trigger the original error
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
            "expense_account": cost_account
        }
        
        repack_items_data = self.get_repack_items()
        if repack_items_data and (len(repack_items_data) > 1):
            stock_data["repack_items"] = repack_items_data
            stock_entry_using_nj_lib(stock_data)

    def get_repack_items(self):
        """
        Prepare repack items data for stock entry
        """
        return_unpack_items_data = []

        main_item = self.items[0]
        # Add the main repack item (item being taken out)
        main_repack_item = {
            'repack_item_code': main_item.item_code,
            'repack_serial_no': main_item.serial_no,
            # 'repack_item_base_price': self.base_price,
            'repack_item_source_warehouse': main_item.s_warehouse,  # FIXED
        }
        return_unpack_items_data.append(main_repack_item)

        # Fetch Serial No document
        serial_no_value = main_item.serial_no.strip()
        serial_no_doc = frappe.get_doc("Serial No", serial_no_value)

        # Fetch Purchase Receipt linked to Serial No
        purchase_receipt = serial_no_doc.purchase_document_no

        if not purchase_receipt:
            frappe.throw(f"No Purchase Receipt linked to Serial No: {serial_no_value}")

        # Fetch Purchase Item Code using the improved matching method
        if not main_item.serial_no:
            frappe.throw("Serial No is missing in the Stock Movement Item.")
        
        # Use the new method to get matching purchase item code
        purchase_item_code = self.get_matching_purchase_item(purchase_receipt, serial_no_value, main_item.item_code)

        
        if not purchase_item_code:

            frappe.throw(f"Could not find the purchase item for Serial No: {serial_no_value}")

        # Add the unpack item (item being put in)
        unpack_item = {
            'unpack_serial_no': main_item.serial_no,
            'unpack_item_code': purchase_item_code,
            'unpack_item_target_warehouse': main_item.t_warehouse,  # FIXED
            # 'unpack_item_base_price': self.repack_item_price,
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
            pass
        
        s_inspection_type = frappe.get_doc('Department', s_department)
        is_component = frappe.db.get_value('Item Group', serial_doc.get('item_group'), 'is_component')

        if not is_component and s_department != department:
            validate_allowed_serial_component_grades(serial_doc, department_doc, error_messages)
            validate_grade_restriction(serial_doc, department_doc, error_messages)

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

def check_qi_validation(serial_no, error_messages, s_warehouse, s_department, t_department):

    s_department = frappe.db.get_value('Warehouse', {'name': s_warehouse}, 'department')

    s_inspection_type = frappe.get_doc('Department', s_department)

    inspection_types = [row.get('inspection_type') for row in s_inspection_type.get("inspection_types")]

    query = """
        SELECT se.creation, se.name
        FROM `tabStock Entry Detail` sed
        JOIN `tabStock Entry` se ON sed.parent = se.name
        WHERE se.stock_entry_type = "Material Transfer"
        AND sed.serial_no = %s
        AND se.docstatus = 1
        AND sed.target_department = %s
        ORDER BY se.creation DESC
        LIMIT 1
    """

    result = frappe.db.sql(query, (serial_no, s_department),explain=1, debug=1, as_dict=True)

    if result:
        creation_time = result[0]["creation"]
        formatted_time = creation_time.strftime("%Y-%m-%d %H:%M:%S")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        qi_query = """
            SELECT name
            FROM `tabNJ Quality Inspection`
            WHERE inspection_type IN %s AND docstatus = 1
            AND creation > %s
            AND barcode = %s
            order by creation desc
            LIMIT 1
        """

        qi_result = frappe.db.sql(qi_query, (tuple(inspection_types), formatted_time, serial_no),explain=1, debug=1, as_dict=True)

        t_inspection_type = frappe.get_doc('Department', t_department)

        if qi_result:
            qi_doc = frappe.get_doc('NJ Quality Inspection', qi_result[0]["name"])

            if qi_doc:
                if t_inspection_type.get("quality_inspection_status_for_stock_movement"):
                    quality_inspection_status_for_stock_movement = t_inspection_type.get("quality_inspection_status_for_stock_movement").split(",")

                    if t_inspection_type.get("quality_inspection_status_for_stock_movement") and qi_doc.get("status") not in quality_inspection_status_for_stock_movement:
                        expected_status = ", ".join(quality_inspection_status_for_stock_movement)
                        actual_status = qi_doc.get("status")
                        
                        error_messages.append(
                            f"NJ Quality Inspection <b>{qi_doc.name}</b> for serial no <b>{serial_no}</b> in warehouse <b>{s_warehouse}</b> has status <b>{actual_status}</b>, but expected status is <b>{expected_status}</b> in department <b>{t_department}</b>."
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

def validate_allowed_serial_component_grades(serial_doc, department_doc, error_messages):
    serial_components = serial_doc.get("serial_no_component", [])
    allowed_table = department_doc.get("allowed_item_group_grades", [])
    all_must_match = department_doc.get("all", False)

    print("all_must_match", all_must_match)

    # Step 1: Map allowed grades by item group
    allowed_map = defaultdict(set)
    for allowed in allowed_table:
        item_group = allowed.get("item_group")
        grades = allowed.get("restricted_grade", "").split(", ")
        allowed_map[item_group].update(grades)

    print("allowed map", allowed_map)

    # Step 2: Group serial components by item group
    components_by_group = defaultdict(list)
    for comp in serial_components:
        components_by_group[comp.get("item_group")].append(comp)

    print("components_by_group", components_by_group.items())

    # Step 3: Validate each item group against allowed grades
    for item_group, components in components_by_group.items():
        allowed_grades = allowed_map.get(item_group)

        print("allowed_grades", allowed_grades)

        if not allowed_grades:
            # Skip validation if item group is not in allowed table
            continue

        if all_must_match:
            # All components must match allowed grades
            for comp in components:
                comp_grade = comp.get("grade")
                if comp_grade not in allowed_grades:
                    error_messages.append(
                        f"Serial No <b>{serial_doc.name}</b>: Grade <b>{comp_grade}</b> for item group <b>{item_group}</b> is not allowed in department "
                        f"<b>{department_doc.name}</b>. Allowed grades are: <b>{', '.join(sorted(allowed_grades))}</b>."
                    )
                    break

        else:
            # At least one component must match
            if not any(c.get("grade") in allowed_grades for c in components):
                actual_grades = {c.get("grade") for c in components if c.get("grade")}
                error_messages.append(
                    f"Serial No <b>{serial_doc.name}</b>: The allowed grades for item group <b>{item_group}</b> in department <b>{department_doc.name}</b> are "
                    f"<b>{', '.join(sorted(allowed_grades))}</b>, but the component(s) have grade(s): <b>{', '.join(sorted(actual_grades))}</b>."
                )

    print("error_messages", error_messages)
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
