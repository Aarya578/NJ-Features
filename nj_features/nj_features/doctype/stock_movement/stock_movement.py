import json
import frappe
from frappe import _
from frappe.utils import flt, now_datetime
from collections import defaultdict
from datetime import datetime, timedelta
from frappe.model.document import Document
from nj_lib.utils.common_utils import get_active_emp
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
from nj_lib.utils.grade_valuation import is_grade_conversion
# from nj_p1_features.nj_p1_features.doctype.machine_part_changes.machine_part_changes import get_part_ledger_entry
logger = frappe.logger('Shopifys', allow_site=True, file_count=1)

DEPARTMENT_SLA_HOLIDAY_LIST = "Holiday List 2026"


def _split_department_names(departments):
    if not departments:
        return []

    return [department.strip() for department in str(departments).split(",") if department.strip()]


class StockMovement(Document):
    def prevent_duplicate_stock_movements(self):
        current_items = sorted([
            (row.item_code, row.qty, row.s_warehouse, row.t_warehouse)
            for row in self.items
        ])
        
        if not current_items:
            return

        total_qty = sum(row.qty for row in self.items)
        num_items = len(self.items)

        # Decide time limit based on size of the movement
        from frappe.utils import add_to_date, now_datetime
        if num_items > 1 or total_qty > 5:
            # Large transfer - check 24 hours
            time_limit = add_to_date(now_datetime(), hours=-24)
        else:
            # Small transfer - check 15 minutes to avoid blocking legitimate repeats
            time_limit = add_to_date(now_datetime(), minutes=-15)

        recent_movements = frappe.get_all(
            "Stock Movement",
            filters={
                "docstatus": 1,
                "creation": (">", time_limit),
                "name": ("!=", self.name)
            },
            pluck="name"
        )
        if not recent_movements:
            return

        # Get all details for these recent movements
        recent_details = frappe.get_all(
            "Stock Movement Detail",
            filters={"parent": ("in", recent_movements)},
            fields=["parent", "item_code", "qty", "s_warehouse", "t_warehouse"]
        )

        from collections import defaultdict
        grouped_items = defaultdict(list)
        for detail in recent_details:
            grouped_items[detail.parent].append(
                (detail.item_code, detail.qty, detail.s_warehouse, detail.t_warehouse)
            )

        for parent_name, items in grouped_items.items():
            if current_items == sorted(items):
                frappe.throw(
                    f"Duplicate Stock Movement detected: A submitted Stock Movement (<b><a href='/app/stock-movement/{parent_name}'>{parent_name}</a></b>) "
                    f"with the exact same items, quantities, and warehouses was already submitted recently."
                )

    def on_submit(self):
        try:
            # self.deparement_qty_check()
            check_warehouse_qty(self.name)
            self.time_stamp_update()
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
                        "repair_details": [
                            {"serial_no": row.serial_no, "category": row.category, "value": row.value}
                            for row in (self.repair_details or [])
                        ],
                    }
                    stock_entry = stock_entry_using_nj_lib(stock_entry_data)
                    self.updating_mr_qty_with_status()
                    return stock_entry
                else:
                    frappe.throw("None available in <b>Items</b> table.")

        except Exception as e:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), "Stock Movement Submit Failed")
            frappe.throw(f"Error while submitting Stock Entry: {e}")

    def time_stamp_update(self):
        current_time = now_datetime()
        for item in self.items:
            if not item.s_warehouse or not item.t_warehouse or item.s_warehouse == item.t_warehouse:
                continue

            s_department = frappe.db.get_value('Warehouse', item.s_warehouse, 'department')
            t_department = frappe.db.get_value('Warehouse', item.t_warehouse, 'department')
            if s_department == t_department:
                continue

            if not item.serial_no:
                continue

            for serial_no in item.serial_no.split('\n'):
                serial_no = serial_no.strip()
                if serial_no:
                    frappe.db.set_value('Serial No', serial_no, 'stock_enty_date_and_time', current_time)

    def validate_supplier_return(self):
        """
        Validate item codes when making supplier return
        - Called during Stock Movement Document submission
        - Checks if scanned serial item matches purchase receipt item
        - If they don't match, create a stock entry using make_stock_entry_using_nj_lib
        """
        if self.make_supplier_return != 1:
            return

        restricted_item_groups = {
            value.strip().lower()
            for value in get_nj_settings_comma_separated_values(
                "make_suppliers_return_item_groups"
            )
        }
        requires_repack = False

        if self.make_supplier_return == 1: 
            for item in self.items:
                if item.serial_no:
                    for serial_no in item.serial_no.split('\n'):
                        serial_no = serial_no.strip()
                        if serial_no:
                            serial_doc = frappe.get_doc("Serial No", serial_no)
                            serial_item_code = serial_doc.item_code

                            serial_item_group = serial_doc.item_group or frappe.db.get_value(
                                "Item", serial_item_code, "item_group"
                            )
                            if (
                                (serial_item_group or "").strip().lower()
                                in restricted_item_groups
                            ):
                                frappe.throw(
                                    f"Core Item Group <b>{serial_item_group}</b> is not allowed "
                                    f"when <b>Make Supplier Return</b> is checked. "
                                    f"Serial No: <b>{serial_no}</b>."
                                )

                            # ✅ Correct field from Serial No
                            purchase_receipt = serial_doc.purchase_receipt
                            
                            if purchase_receipt:
                                purchase_item_code = self.get_matching_purchase_item(
                                    purchase_receipt, serial_no, serial_item_code
                                )
                                
                                if serial_item_code != purchase_item_code:
                                    requires_repack = True

        if requires_repack:
            self.make_stock_entry_using_nj_lib()

    def updating_mr_qty_with_status(self):
        
        print("updating_mr_qty_with_status started for Stock Movement:", self.name)
        for item in self.items:
            target_department = frappe.db.get_value("Warehouse", item.t_warehouse, "department") if item.t_warehouse else None
            print(
                "Checking Stock Movement item:",
                item.item_code,
                "qty:",
                item.qty,
                "target warehouse:",
                item.t_warehouse,
                "target department:",
                target_department,
            )

            remaining_qty = flt(item.qty)
            if not item.item_code or remaining_qty <= 0:
                print("Skipping item because item_code is missing or qty is zero:", item.item_code, remaining_qty)
                continue

            is_consumables_warehouse = frappe.db.get_value(
                "Warehouse",
                item.t_warehouse,
                "used_for_consumables_stock",
            ) if item.t_warehouse else 0

            if int(is_consumables_warehouse or 0):
                material_request_items = frappe.db.sql(
                    """
                    SELECT
                        mri.name,
                        mri.parent,
                        mri.qty,
                        mr.fully_consumed_qty_departments,
                        IFNULL(mri.received_qty, 0) AS received_qty
                    FROM `tabMaterial Request Item` mri
                    INNER JOIN `tabMaterial Request` mr ON mr.name = mri.parent
                    WHERE
                        mr.docstatus = 1
                        AND mr.material_request_type = 'Material Issue'
                        AND (
                             IFNULL(mri.create_reference, '') LIKE 'All Departments%%'
                        )
                        AND IFNULL(mr.status, '') NOT IN ('Stopped', 'Cancelled')
                        AND mri.item_code = %s
                        AND IFNULL(mri.post_order_status, 'Not Completed') != 'Completed'
                        AND IFNULL(mri.received_qty, 0) < IFNULL(mri.qty, 0)
                    ORDER BY mr.transaction_date ASC, mr.creation ASC, mri.idx ASC
                    """,
                    (item.item_code,),
                    as_dict=True,
                    debug=True,
                )
                matching_department_items = [
                    mr_item
                    for mr_item in material_request_items
                    if target_department in _split_department_names(mr_item.get("fully_consumed_qty_departments"))
                ]
                print(
                    "Consumables MR items after fully_consumed_qty_departments match:",
                    "target_department:",
                    target_department,
                    "count:",
                    len(matching_department_items),
                )
                self._update_mr_items_received_qty(item, matching_department_items)
                continue

            if target_department == "Stores - NJ":
                material_request_items = frappe.db.sql(
                    """
                    SELECT
                        mri.name,
                        mri.parent,
                        mri.qty,
                        IFNULL(mri.received_qty, 0) AS received_qty
                    FROM `tabMaterial Request Item` mri
                    INNER JOIN `tabMaterial Request` mr ON mr.name = mri.parent
                    WHERE
                        mr.docstatus = 1
                        AND mr.material_request_type IN ('Manufacture', 'Purchase')
                        AND (
                            IFNULL(mr.mr_create_reference, '') LIKE 'NJ Production Planning%%'
                            OR IFNULL(mr.mr_create_reference, '') LIKE 'SRA Item Group NJ Production%%'
                        )
                        AND IFNULL(mr.status, '') NOT IN ('Stopped', 'Cancelled')
                        AND mri.item_code = %s
                        AND IFNULL(mri.post_order_status, 'Not Completed') != 'Completed'
                        AND IFNULL(mri.received_qty, 0) < IFNULL(mri.qty, 0)
                    ORDER BY mr.transaction_date ASC, mr.creation ASC, mri.idx ASC
                    """,
                    (item.item_code,),
                    as_dict=True,
                    debug=True,
                )
                self._update_mr_items_received_qty(item, material_request_items)
                continue

            if target_department:
                material_request_items = frappe.db.sql(
                    """
                    SELECT
                        mri.name,
                        mri.parent,
                        mri.qty,
                        mr.mr_rised_departments,
                        IFNULL(mri.received_qty, 0) AS received_qty
                    FROM `tabMaterial Request Item` mri
                    INNER JOIN `tabMaterial Request` mr ON mr.name = mri.parent
                    WHERE
                        mr.docstatus = 1
                        AND mr.material_request_type = 'Material Issue'
                        AND (
                            IFNULL(mr.mr_create_reference, '') LIKE 'Laptop Adaptor NJ Production%%'
                            OR IFNULL(mr.mr_create_reference, '') LIKE 'Laptop RAM NJ Production%%'
                            OR IFNULL(mr.mr_create_reference, '') LIKE 'Laptop Storage NJ Production%%'
                        )
                        AND IFNULL(mr.status, '') NOT IN ('Stopped', 'Cancelled')
                        AND mri.item_code = %s
                        AND IFNULL(mri.post_order_status, 'Not Completed') != 'Completed'
                        AND IFNULL(mri.received_qty, 0) < IFNULL(mri.qty, 0)
                    ORDER BY mr.transaction_date ASC, mr.creation ASC, mri.idx ASC
                    """,
                    (item.item_code,),
                    as_dict=True,
                    debug=True,
                )
                matching_department_items = [
                    mr_item
                    for mr_item in material_request_items
                    if target_department in _split_department_names(mr_item.get("mr_rised_departments"))
                ]
                print(
                    "Laptop component MR items after mr_rised_departments match:",
                    "target_department:",
                    target_department,
                    "count:",
                    len(matching_department_items),
                )
                self._update_mr_items_received_qty(item, matching_department_items)
                continue

            print("Skipping item because target is not Paint warehouse, Stores - NJ department, or MR raised department")

    def _update_mr_items_received_qty(self, item, material_request_items):
        remaining_qty = flt(item.qty)
        print("Matching Material Request Items found:", material_request_items)

        for mr_item in material_request_items:
            if remaining_qty <= 0:
                print("No remaining qty left for item:", item.item_code)
                break

            pending_qty = flt(mr_item.qty) - flt(mr_item.received_qty)
            print(
                "Processing MR Item:",
                mr_item.name,
                "MR:",
                mr_item.parent,
                "MR qty:",
                mr_item.qty,
                "current received_qty:",
                mr_item.received_qty,
                "pending_qty:",
                pending_qty,
                "remaining SM qty:",
                remaining_qty,
            )
            if pending_qty <= 0:
                print("Skipping MR Item because pending qty is zero:", mr_item.name)
                continue

            qty_to_update = min(remaining_qty, pending_qty)
            new_received_qty = flt(mr_item.received_qty) + qty_to_update
            values = {"received_qty": new_received_qty}

            if new_received_qty >= flt(mr_item.qty):
                values["post_order_status"] = "Completed"

            frappe.db.set_value(
                "Material Request Item",
                mr_item.name,
                values,
                update_modified=False,
            )
            print(
                "Updated MR Item:",
                mr_item.name,
                "qty_to_update:",
                qty_to_update,
                "new_received_qty:",
                new_received_qty,
                "status:",
                values.get("post_order_status", "unchanged"),
            )
            remaining_qty -= qty_to_update
        print("Remaining qty after MR updates for item", item.item_code, ":", remaining_qty)


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
                    'is_finished_item': 1,
                    'apply_grade_valuation': is_grade_conversion(
                        serial_item_code,
                        purchase_item_code,
                    ),
                }
                return_unpack_items_data.append(unpack_item)

        return return_unpack_items_data

    def on_cancel(self):
        try:
            self.revert_mr_qty_with_status()

            # Find and cancel the linked Stock Entry
            linked_stock_entries = frappe.get_all(
                "Stock Entry",
                filters={
                    "reference": self.name,
                    "reference_type": self.doctype,
                    "docstatus": 1
                },
                pluck="name"
            )
            for se_name in linked_stock_entries:
                se_doc = frappe.get_doc("Stock Entry", se_name)
                se_doc.flags.ignore_permissions = True
                se_doc.cancel()

        except Exception as e:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), "Stock Movement Cancel Failed")
            frappe.throw(f"Error while cancelling Stock Entry: {e}")

    def revert_mr_qty_with_status(self):
        print("revert_mr_qty_with_status started for Stock Movement:", self.name)
        for item in self.items:
            target_department = frappe.db.get_value("Warehouse", item.t_warehouse, "department") if item.t_warehouse else None
            print(
                "Reverting Stock Movement item:",
                item.item_code,
                "qty:",
                item.qty,
                "target warehouse:",
                item.t_warehouse,
                "target department:",
                target_department,
            )

            remaining_qty = flt(item.qty)
            if not item.item_code or remaining_qty <= 0:
                print("Skipping item because item_code is missing or qty is zero:", item.item_code, remaining_qty)
                continue

            is_consumables_warehouse = frappe.db.get_value(
                "Warehouse",
                item.t_warehouse,
                "used_for_consumables_stock",
            ) if item.t_warehouse else 0

            if int(is_consumables_warehouse or 0):
                material_request_items = frappe.db.sql(
                    """
                    SELECT
                        mri.name,
                        mri.parent,
                        mri.qty,
                        mr.fully_consumed_qty_departments,
                        IFNULL(mri.received_qty, 0) AS received_qty
                    FROM `tabMaterial Request Item` mri
                    INNER JOIN `tabMaterial Request` mr ON mr.name = mri.parent
                    WHERE
                        mr.docstatus = 1
                        AND mr.material_request_type = 'Material Issue'
                        AND (
                             IFNULL(mri.create_reference, '') LIKE 'All Departments%%'
                        )
                        AND IFNULL(mr.status, '') NOT IN ('Stopped', 'Cancelled')
                        AND mri.item_code = %s
                        AND IFNULL(mri.received_qty, 0) > 0
                    ORDER BY mr.transaction_date DESC, mr.creation DESC, mri.idx DESC
                    """,
                    (item.item_code,),
                    as_dict=True,
                )
                matching_department_items = [
                    mr_item
                    for mr_item in material_request_items
                    if target_department in _split_department_names(mr_item.get("fully_consumed_qty_departments"))
                ]
                self._revert_mr_items_received_qty(item, matching_department_items)
                continue

            if target_department == "Stores - NJ":
                material_request_items = frappe.db.sql(
                    """
                    SELECT
                        mri.name,
                        mri.parent,
                        mri.qty,
                        IFNULL(mri.received_qty, 0) AS received_qty
                    FROM `tabMaterial Request Item` mri
                    INNER JOIN `tabMaterial Request` mr ON mr.name = mri.parent
                    WHERE
                        mr.docstatus = 1
                        AND mr.material_request_type IN ('Manufacture', 'Purchase')
                        AND (
                            IFNULL(mr.mr_create_reference, '') LIKE 'NJ Production Planning%%'
                            OR IFNULL(mr.mr_create_reference, '') LIKE 'SRA Item Group NJ Production%%'
                        )
                        AND IFNULL(mr.status, '') NOT IN ('Stopped', 'Cancelled')
                        AND mri.item_code = %s
                        AND IFNULL(mri.received_qty, 0) > 0
                    ORDER BY mr.transaction_date DESC, mr.creation DESC, mri.idx DESC
                    """,
                    (item.item_code,),
                    as_dict=True,
                )
                self._revert_mr_items_received_qty(item, material_request_items)
                continue

            if target_department:
                material_request_items = frappe.db.sql(
                    """
                    SELECT
                        mri.name,
                        mri.parent,
                        mri.qty,
                        mr.mr_rised_departments,
                        IFNULL(mri.received_qty, 0) AS received_qty
                    FROM `tabMaterial Request Item` mri
                    INNER JOIN `tabMaterial Request` mr ON mr.name = mri.parent
                    WHERE
                        mr.docstatus = 1
                        AND mr.material_request_type = 'Material Issue'
                        AND (
                            IFNULL(mr.mr_create_reference, '') LIKE 'Laptop Adaptor NJ Production%%'
                            OR IFNULL(mr.mr_create_reference, '') LIKE 'Laptop RAM NJ Production%%'
                            OR IFNULL(mr.mr_create_reference, '') LIKE 'Laptop Storage NJ Production%%'
                        )
                        AND IFNULL(mr.status, '') NOT IN ('Stopped', 'Cancelled')
                        AND mri.item_code = %s
                        AND IFNULL(mri.received_qty, 0) > 0
                    ORDER BY mr.transaction_date DESC, mr.creation DESC, mri.idx DESC
                    """,
                    (item.item_code,),
                    as_dict=True,
                )
                matching_department_items = [
                    mr_item
                    for mr_item in material_request_items
                    if target_department in _split_department_names(mr_item.get("mr_rised_departments"))
                ]
                self._revert_mr_items_received_qty(item, matching_department_items)
                continue

    def _revert_mr_items_received_qty(self, item, material_request_items):
        remaining_qty = flt(item.qty)
        for mr_item in material_request_items:
            if remaining_qty <= 0:
                break

            qty_to_revert = min(remaining_qty, flt(mr_item.received_qty))
            new_received_qty = flt(mr_item.received_qty) - qty_to_revert
            values = {"received_qty": new_received_qty}

            if new_received_qty < flt(mr_item.qty):
                values["post_order_status"] = "Not Completed"

            frappe.db.set_value(
                "Material Request Item",
                mr_item.name,
                values,
                update_modified=False,
            )
            remaining_qty -= qty_to_revert

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
    child_warehouse_with_qty_query = """SELECT 
                w.name, 
                w.is_group,
                COALESCE(NULLIF(w.max_capacity, 0), q.max_capacity, 0) AS max_capacity,
                GREATEST(0, COALESCE(NULLIF(w.max_capacity, 0), q.max_capacity, 0) - COALESCE(sn.cnt, 0)) AS available_capacity
            FROM `tabWarehouse` w 
            LEFT JOIN `tabWarehouse Qty` q ON q.warehouse = w.name 
            LEFT JOIN (
                SELECT warehouse, COUNT(*) AS cnt
                FROM `tabSerial No`
                WHERE warehouse IN (SELECT name FROM `tabWarehouse` WHERE parent_warehouse = %(parent_warehouse)s)
                GROUP BY warehouse
            ) sn ON sn.warehouse = w.name
            WHERE w.parent_warehouse = %(parent_warehouse)s AND w.disabled = 0"""
    child_warehouse_with_qty = frappe.db.sql(child_warehouse_with_qty_query, {"parent_warehouse": parent_warehouse}, as_dict=1)

    for row in child_warehouse_with_qty:
        if row['is_group']: 
            all_emp_ware.extend(get_child_warehouses(row['name']))  
        else:
            if row['available_capacity'] and int(row['available_capacity']) > 0:
                all_emp_ware.append(row)  

    return all_emp_ware 

@frappe.whitelist()
def validate_stock_movement_for_grade(doc):

    print("\n")
    print("=" * 100)
    print("DEBUG validate_stock_movement_for_grade START")
    print("=" * 100)

    print("RAW DOC TYPE:", type(doc))

    if isinstance(doc, str):
        doc = json.loads(doc)

    print("DOC TYPE AFTER CONVERSION:", type(doc))
    print("DOC NAME:", doc.get("name"))
    print("DOCTYPE:", doc.get("doctype"))

    items = doc.get("items", [])

    print("ITEMS VALUE:", items)
    print("ITEM COUNT RECEIVED FROM UI:", len(items))

    for idx, row in enumerate(items, 1):
        print("\n--- UI ROW", idx, "---")
        print("ITEM CODE:", repr(row.get("item_code")))
        print("SERIAL NO:", repr(row.get("serial_no")))
        print("SOURCE WAREHOUSE:", repr(row.get("s_warehouse")))
        print("TARGET WAREHOUSE:", repr(row.get("t_warehouse")))

    error_messages = []
    model_mismatch_messages = []
    qty_check_cache = {
        "checked_keys": set(),
        "item_group_cache": {},
        "all_item_group_sla_checked": set(),
    }

    for row in doc.get('items', []):

        print("\n>>> CALLING validate_serial_no_and_department")
        print("SERIAL:", repr(row.get("serial_no")))

        result = validate_serial_no_and_department(
            row,
            doc,
            error_messages,
            model_mismatch_messages,
            qty_check_cache
        )

        print(
            "validate_serial_no_and_department RESULT:",
            result
        )

        print(
            "ERROR MESSAGES AFTER ROW:",
            error_messages
        )

        if not result:
            print(">>> RESULT FALSE - CONTINUING TO NEXT ROW")
            continue

    print("\nFINAL ERROR MESSAGES:", error_messages)

    if error_messages:
        print(">>> RETURNING ERRORS TO CLIENT <<<")

        return {
            "error": error_messages,
            "show_production_plan_prompt": bool(model_mismatch_messages),
        }

    print(">>> RETURNING SUCCESS <<<")

    return {
        "success": "Validation passed without errors."
    }

def validate_serial_no_and_department(
    row,
    doc,
    error_messages,
    model_mismatch_messages=None,
    qty_check_cache=None,
    legacy_source_warehouse=None,
):
    
    
    has_serialized = frappe.db.get_value(
        'Item',
        {'name': row.get('item_code')},
        'has_serial_no'
    )

    print("HAS SERIAL NO:", repr(has_serialized))

    if not has_serialized:
        print(">>> STOPPED: ITEM IS NOT SERIALIZED <<<")
        return False

    s_warehouse = row.get('s_warehouse')
    t_warehouse = row.get('t_warehouse')
    serial_no = row.get('serial_no')

    print("\n" + "=" * 100)
    print("validate_serial_no_and_department")
    print("=" * 100)

    print("SERIAL:", repr(serial_no))
    print("ITEM CODE:", repr(row.get("item_code")))
    print("SOURCE WAREHOUSE:", repr(s_warehouse))
    print("TARGET WAREHOUSE:", repr(t_warehouse))

    department = frappe.db.get_value('Warehouse', {'name': t_warehouse}, 'department')
    target_is_employee_personal_warehouse = (
        frappe.db.get_value('Warehouse', t_warehouse, 'warehouse_type')
        == 'Employee Personal Warehouse'
    )
    print("_t ==department=================",department )
    s_department = frappe.db.get_value('Warehouse', {'name': s_warehouse}, 'department')
    print("_s ==department=================",s_department )

    print("SOURCE DEPARTMENT:", repr(s_department))
    print("TARGET DEPARTMENT:", repr(department))
    print(
        "SOURCE != TARGET:",
        s_department != department
    )

    if not department:
        error_messages.append(f"Target warehouse <b>{t_warehouse}</b> has no associated department.")
        return False

    department_doc = frappe.get_doc('Department', department)

    try:
        serial_doc = frappe.get_doc('Serial No', serial_no)
    except frappe.DoesNotExistError:
        error_messages.append(f"Serial No <b>{serial_no}</b> does not exist.")
        return False

    if serial_doc.get('grade_a_item_code') and not department_doc.get('allow_grade_a_items'):
        allowed_departments = frappe.get_all(
            'Department',
            filters={'allow_grade_a_items': 1},
            pluck='name',
            order_by='name asc',
        )
        allowed_department_names = (
            ', '.join(f'<b>{allowed_department}</b>' for allowed_department in allowed_departments)
            or '<b>No department is configured</b>'
        )
        error_messages.append(
            f"Serial No <b>{serial_no}</b> is marked as a Grade A item and cannot be "
            f"transferred to target department <b>{department}</b>. "
            f"Allowed target department(s): {allowed_department_names}."
        )
        return False

    if s_warehouse and t_warehouse and s_warehouse != t_warehouse and department != s_department:
        from nj_features.overrides.stock_entry import get_department_restriction_violation

        restriction_violation = get_department_restriction_violation(serial_no, department)
        if restriction_violation:
            error_messages.append(restriction_violation)
            return False

    current_doctype = (
        doc.get("doctype")
        if isinstance(doc, dict)
        else getattr(doc, "doctype", None)
    )

    # Rack Pick has its own production-plan priority validation. Skip only the
    # shared NJ Production Plan validation here; all validations below continue.
    if current_doctype == "Rack Pick" or current_doctype == "NJ Audit":
        production_plan_result = True
    else:
        production_plan_result = validate_serial_no_in_latest_nj_production_plan(
            serial_no,
            serial_doc,
            s_department,
            error_messages,
            doc,
            row
        )

    print(
        "PRODUCTION PLAN VALIDATION RESULT:",
        production_plan_result
    )

    print(
        "ERRORS AFTER PRODUCTION PLAN:",
        error_messages
    )

    if not production_plan_result:
        print(">>> STOPPED AT PRODUCTION PLAN VALIDATION <<<")
        return False
    gen_result = validate_serial_no_gen_wise(
        serial_no,
        serial_doc,
        department,
        s_department,
        error_messages
    )

    print(
        "GEN-WISE VALIDATION RESULT:",
        gen_result
    )

    print(
        "ERRORS AFTER GEN-WISE:",
        error_messages
    )

    if not gen_result:
        print(">>> STOPPED AT GEN-WISE VALIDATION <<<")
        return False

    if (
        current_doctype != "Stock Movement"
        and s_warehouse
        and t_warehouse
        and s_warehouse != t_warehouse
        and department != s_department
    ):
        frappe.db.set_value('Serial No', serial_no, 'stock_enty_date_and_time', now_datetime())

    core_item_groups = get_warehouse_and_department_sla_core_item_groups()
    row_item_group = serial_doc.get("item_group") or (
        frappe.db.get_value("Item", row.get("item_code"), "item_group")
        if row.get("item_code")
        else None
    )
    allow_model_change = frappe.db.get_value("Department", department, "allow_model_change")

    if (
        department != s_department
        and not allow_model_change
        and row_item_group in core_item_groups
    ):
        item_code = serial_doc.get("item_code")
        to_make = serial_doc.get("to_make")

        item_code_model = (
            frappe.db.get_value("Item", item_code, "item_model")
            if item_code
            else None
        )
        to_make_model = (
            frappe.db.get_value("Item", to_make, "item_model")
            if to_make
            else None
        )

        if item_code_model and to_make_model and item_code_model != to_make_model:
            frappe.db.set_value("Serial No", serial_no, "to_make", item_code)
            to_make = item_code
            to_make_model = item_code_model

        # Show error if To Make is empty or doesn't match Item Code
        if item_code and (not to_make or item_code != to_make):
            error_messages.append(
                f"Reconfiguration not allowed for Department <b>{department}</b>. "
                f"Item Code <b>{item_code}</b> and "
                f"To Make <b>{to_make or 'Empty'}</b> must be same."
            )
            return False

    sla_item_groups = get_warehouse_and_department_sla_item_groups()
    should_validate_sla = row_item_group in core_item_groups


    validation_cache = qty_check_cache if qty_check_cache is not None else {}
    all_item_group_sla_checked = validation_cache.setdefault(
        "all_item_group_sla_checked",
        set(),
    )
    part_level_sla_item_groups = get_part_level_sla_item_groups(department)
    combined_sla_restriction = is_combined_sla_restriction_enabled()

    combined_sla_checked = validation_cache.setdefault(
        "combined_sla_checked",
        set(),
    )
    combined_sla_cache_key = (department, "combined_core_and_part_sla")

    if (
        combined_sla_restriction
        and not target_is_employee_personal_warehouse
        and department
        and department != s_department
        and combined_sla_cache_key not in combined_sla_checked
    ):
        combined_sla_checked.add(combined_sla_cache_key)

        if not validate_combined_core_and_part_level_sla(
            department=department,
            source_department=s_department,
            target_warehouse=t_warehouse,
            core_sla_item_groups=sla_item_groups,
            part_level_sla_item_groups=part_level_sla_item_groups,
            error_messages=error_messages,
        ):
            return False

    sla_cache_key = (
        department,
        "part_level_sla",
    )

    if (
        not combined_sla_restriction
        and not target_is_employee_personal_warehouse
        and department
        and department != s_department
        and row_item_group not in core_item_groups
        and row_item_group in part_level_sla_item_groups
        and sla_cache_key not in all_item_group_sla_checked
    ):
        all_item_group_sla_checked.add(sla_cache_key)

        if not validate_all_item_groups_sla(
            department=department,
            source_department=s_department,
            target_warehouse=t_warehouse,
            item_group=row_item_group,
            part_level_sla_item_groups=part_level_sla_item_groups,
            error_messages=error_messages,
        ):
            return False

    if department and department != s_department:
        print("department and department != s_department=================",department and department != s_department )

        warehouse_sla = frappe.db.get_value("Department", department, "sla")
        department_sla = frappe.db.get_value("Department", department, "department_sla")
        if should_validate_sla and sla_item_groups:
            sla_item_group_placeholders = ", ".join(["%s"] * len(sla_item_groups))
        if (
            not target_is_employee_personal_warehouse
            and should_validate_sla
            and sla_item_groups
            and warehouse_sla
            and t_warehouse
        ):
            warehouse_sla_days = int(warehouse_sla)
            warehouse_aging = frappe.db.sql(
                f"""
                    SELECT
                        s.name AS serial_no,
                        s.warehouse,
                        GREATEST(
                            TIMESTAMPDIFF(
                                DAY,
                                TIMESTAMP(s.purchase_date, s.purchase_time),
                                NOW()
                            ) - COUNT(DISTINCT h.holiday_date),
                            0
                        ) AS max_age_days

                    FROM `tabSerial No` s

                    LEFT JOIN `tabHoliday` h
                        ON h.parent = 'Holiday List 2026'
                        AND h.holiday_date > DATE(TIMESTAMP(s.purchase_date, s.purchase_time))
                        AND h.holiday_date <= CURDATE()

                    WHERE
                        s.warehouse = %s
                        AND s.item_group IN ({sla_item_group_placeholders})

                    GROUP BY
                        s.name,
                        s.warehouse,
                        s.purchase_date,
                        s.purchase_time

                    ORDER BY
                        max_age_days DESC

                    LIMIT 1
                """,
                tuple([t_warehouse] + sla_item_groups),
                as_dict=True
            )

            max_age_days = warehouse_aging[0].get("max_age_days") if warehouse_aging else None
            max_age_serial_no = warehouse_aging[0].get("serial_no") if warehouse_aging else None
            if max_age_days is not None and int(max_age_days) > warehouse_sla_days:
                error_messages.append(
                    f"SLA exceeded for Department <b>{department}</b>. "
                    f"Warehouse SLA is <b>{warehouse_sla_days}</b> days, "
                    f"Serial No <b>{max_age_serial_no}</b> "
                    f"but max aging in warehouse <b>{t_warehouse}</b> is <b>{int(max_age_days)}</b> days."
                )
        if (
            not combined_sla_restriction
            and not target_is_employee_personal_warehouse
            and should_validate_sla
            and sla_item_groups
            and department_sla
        ):
            department_sla_days = int(department_sla)
            department_aging = frappe.db.sql(
                f"""
                SELECT
                    sn.name AS serial_no,
                    sn.stock_enty_date_and_time AS department_entry_date,
                    GREATEST(
                    TIMESTAMPDIFF(
                        DAY,
                        sn.stock_enty_date_and_time,
                        DATE_ADD(NOW(), INTERVAL 330 MINUTE)
                    ) - COUNT(DISTINCT h.holiday_date),
                    0
                ) AS department_age
                FROM `tabSerial No` sn
                INNER JOIN `tabWarehouse` w
                    ON w.name = sn.warehouse
                LEFT JOIN `tabHoliday` h
                    ON h.parent = %s
                    AND h.holiday_date > DATE(sn.stock_enty_date_and_time)
                    AND h.holiday_date <= CURDATE()
                WHERE
                    w.department = %s
                    AND (w.warehouse_type IS NULL
                        OR w.warehouse_type = ''
                        OR w.warehouse_type != 'Employee Personal Warehouse')
                    AND sn.item_group IN ({sla_item_group_placeholders})
                    AND sn.stock_enty_date_and_time IS NOT NULL
                GROUP BY
                    sn.name,
                    sn.stock_enty_date_and_time
                ORDER BY
                    department_age DESC
                LIMIT 1;
                """,
                tuple([DEPARTMENT_SLA_HOLIDAY_LIST, department] + sla_item_groups),
                as_dict=True 
            )
            department_age = department_aging[0].get("department_age") if department_aging else None
            department_age_serial = department_aging[0].get("serial_no") if department_aging else None
            if department_age is not None and int(department_age) > department_sla_days:
                error_messages.append(
                    f"SLA exceeded for Department <b>{department}</b>. "
                    f"Department SLA is <b>{department_sla_days}</b> days, "
                    f"but Serial No <b>{department_age_serial}</b> has department aging of <b>{int(department_age)}</b> days."
                )
                return False
        # suggested_warehouse_validation(doc, t_warehouse, error_messages)             
        deparement_qty_check_for_validation(doc, department, t_warehouse, error_messages, qty_check_cache)
    
    item_group_doc = frappe.get_doc(
        'Item Group',
        serial_doc.get('item_group')
    )

    print("\n" + "=" * 100)
    print("GRADE RESTRICTION PRE-CHECK")
    print("=" * 100)

    print(
        "SERIAL ITEM GROUP:",
        repr(serial_doc.get("item_group"))
    )

    print(
        "IS COMPONENT:",
        repr(item_group_doc.get("is_component"))
    )

    if int(item_group_doc.get("is_component")):

        bag_result = check_if_serial_exists_in_active_bag_list(
            serial_no,
            error_messages,
            doc
        )

        print(
            "ACTIVE BAG LIST RESULT:",
            bag_result
        )

        if not bag_result:
            print(">>> STOPPED AT ACTIVE BAG LIST CHECK <<<")
            return False


    restriction_item = frappe.get_all(
        "Item Group",
        {"check_restrictions": 1},
        "name"
    )

    restriction_item = [
        r.get("name")
        for r in restriction_item
    ]

    print(
        "CHECK_RESTRICTIONS ITEM GROUPS:",
        restriction_item
    )

    print(
        "CURRENT ITEM GROUP PRESENT:",
        serial_doc.get("item_group") in restriction_item
    )

    if serial_doc.get("item_group") not in restriction_item:
        print(
            ">>> STOPPED: ITEM GROUP NOT ENABLED FOR CHECK_RESTRICTIONS <<<"
        )
        return False

    print(">>> PASSED CHECK_RESTRICTIONS GATE <<<")

    print("\n--- BYPASS CHECK ---")
    print(
        "SERIAL BYPASS:",
        repr(serial_doc.get("bypass"))
    )

    if not serial_doc.get("bypass"):

        print(">>> PASSED BYPASS CHECK <<<")

        if department_doc.get('warrenty_restriction_check'):
            check_warranty_expiry(
                serial_doc,
                error_messages
            )

        s_inspection_type = (
            frappe.get_doc('Department', s_department)
            if s_department
            else None
        )

        is_component = frappe.db.get_value(
            'Item Group',
            serial_doc.get('item_group'),
            'is_component'
        )

        print("\n--- NON-COMPONENT GATE ---")
        print("IS COMPONENT:", repr(is_component))
        print("NOT IS COMPONENT:", not is_component)
        print("SOURCE DEPARTMENT:", repr(s_department))
        print("TARGET DEPARTMENT:", repr(department))
        print(
            "SOURCE != TARGET:",
            s_department != department
        )

        if not is_component and s_department != department:

            print(
                ">>> ENTERED NON-COMPONENT VALIDATION <<<"
            )

            check_lesson_validation = frappe.db.get_value(
                'NJ Settings',
                {'parameter': 'check_lesson_validation'},
                'value'
            )

            if (
                check_lesson_validation
                and int(check_lesson_validation)
            ):
                validate_lesson_completion_for_serial_model(
                    serial_doc,
                    error_messages
                )

            print(
                "ERRORS BEFORE ALLOWED GRADE CHECK:",
                error_messages
            )

            validate_allowed_serial_component_grades(
                serial_doc,
                department_doc,
                error_messages
            )

            print(
                "ERRORS AFTER ALLOWED GRADE CHECK:",
                error_messages
            )

            check_min_qty_and_max_qty(
                serial_doc,
                department_doc,
                error_messages
            )

            print(
                "ERRORS BEFORE validate_grade_restriction:",
                error_messages
            )

            print(
                ">>> NOW CALLING validate_grade_restriction <<<"
            )

            validate_grade_restriction(
                serial_doc,
                department_doc,
                error_messages
            )

            print(
                "ERRORS AFTER validate_grade_restriction:",
                error_messages
            )

            check_bag_list_validation(
                serial_doc,
                error_messages,
                department_doc
            )

            one_of_these_component_grades_must_be_true(
                serial_doc,
                department_doc,
                t_warehouse,
                error_messages
            )

        else:
            print(
                ">>> GRADE RESTRICTION SKIPPED HERE <<<"
            )
            print(
                "Reason -> not is_component:",
                not is_component
            )
            print(
                "Reason -> source != target:",
                s_department != department
            )

        # QI validation remains inside bypass = 0 flow
        if (
            s_department
            and s_department != department
            and s_inspection_type
            and s_inspection_type.get("inspection_types")
            and s_inspection_type.get("quality_inspection_status_for_stock_movement")
        ):
            print(">>> ENTERING QI VALIDATION <<<")

            check_qi_validation(
                serial_no,
                error_messages,
                s_warehouse,
                s_department,
                department
            )
        else:
            print(">>> QI VALIDATION NOT REQUIRED <<<")
            return True

    else:
        print(
            ">>> ALL RESTRICTIONS SKIPPED BECAUSE BYPASS = 1 <<<"
        )

    return True

def get_warehouse_and_department_sla_core_item_groups():
    return get_nj_settings_comma_separated_values("warehouse_and_department_sla_core_item_groups")

def get_warehouse_and_department_sla_item_groups():
    return get_nj_settings_comma_separated_values("warehouse_and_department_sla_item_groups")


def get_part_level_sla_item_groups(department):
    if not department:
        return []

    return frappe.get_all(
        "Part Level SLA",
        filters={"parent": department, "parenttype": "Department"},
        pluck="item_group",
    )


def is_combined_sla_restriction_enabled():
    value = frappe.db.get_value(
        "NJ Settings",
        {"parameter": "part_level_and_core_item_groups_restriction"},
        "value",
    )
    return str(value or "").strip() == "1"


def validate_combined_core_and_part_level_sla(
    department,
    source_department,
    target_warehouse,
    core_sla_item_groups,
    part_level_sla_item_groups,
    error_messages,
):
    """Run both target Department SLA checks and collect all failures."""

    core_sla_valid = validate_core_item_groups_department_sla(
        department=department,
        core_sla_item_groups=core_sla_item_groups,
        error_messages=error_messages,
    )
    part_level_sla_valid = validate_all_item_groups_sla(
        department=department,
        source_department=source_department,
        target_warehouse=target_warehouse,
        item_group=None,
        part_level_sla_item_groups=part_level_sla_item_groups,
        error_messages=error_messages,
        validate_moving_item_group=False,
    )

    return core_sla_valid and part_level_sla_valid


def validate_core_item_groups_department_sla(
    department,
    core_sla_item_groups,
    error_messages,
):
    """Report all core-item serials exceeding the target Department SLA."""

    department_sla = frappe.db.get_value(
        "Department",
        department,
        "department_sla",
    )
    if not department_sla or not core_sla_item_groups:
        return True

    department_sla_days = int(department_sla)
    item_group_placeholders = ", ".join(
        ["%s"] * len(core_sla_item_groups)
    )
    department_aging = frappe.db.sql(
        f"""
        SELECT
            sn.name AS serial_no,
            sn.item_group,
            GREATEST(
                TIMESTAMPDIFF(
                    DAY,
                    sn.stock_enty_date_and_time,
                    DATE_ADD(NOW(), INTERVAL 330 MINUTE)
                ) - COUNT(DISTINCT holiday.holiday_date),
                0
            ) AS department_age
        FROM `tabSerial No` sn
        INNER JOIN `tabWarehouse` w
            ON w.name = sn.warehouse
        LEFT JOIN `tabHoliday` holiday
            ON holiday.parent = %s
            AND holiday.holiday_date > DATE(sn.stock_enty_date_and_time)
            AND holiday.holiday_date <= CURDATE()
        WHERE
            w.department = %s
            AND (
                w.warehouse_type IS NULL
                OR w.warehouse_type = ''
                OR w.warehouse_type != 'Employee Personal Warehouse'
            )
            AND sn.item_group IN ({item_group_placeholders})
            AND sn.stock_enty_date_and_time IS NOT NULL
        GROUP BY
            sn.name,
            sn.item_group,
            sn.stock_enty_date_and_time
        ORDER BY department_age DESC
        """,
        tuple(
            [DEPARTMENT_SLA_HOLIDAY_LIST, department]
            + core_sla_item_groups
        ),
        as_dict=True,
    )

    overdue_serials = [
        row
        for row in department_aging
        if row.get("department_age") is not None
        and int(row.get("department_age")) > department_sla_days
    ]

    for overdue_serial in overdue_serials:
        error_messages.append(
            f"Core SLA | Serial No <b>{overdue_serial.get('serial_no')}</b> | "
            f"Item Group <b>{overdue_serial.get('item_group')}</b> | "
            f"Department <b>{department}</b> | "
            f"SLA <b>{department_sla_days}</b> days | "
            f"Department Aging "
            f"<b>{int(overdue_serial.get('department_age'))}</b> days | "
            f"Status <b>Overdue</b>."
        )

    return not overdue_serials


def validate_all_item_groups_sla(
    department,
    source_department,
    target_warehouse,
    item_group,
    part_level_sla_item_groups,
    error_messages,
    validate_moving_item_group=True,
):
    """Report every overdue serial covered by the target Department's part SLA."""

    if not department or department == source_department:
        return True

    if not target_warehouse or not source_department:
        return True

    if not part_level_sla_item_groups:
        return True

    if validate_moving_item_group and item_group not in part_level_sla_item_groups:
        return True

    item_group_placeholders = ", ".join(
        ["%s"] * len(part_level_sla_item_groups)
    )
    department_aging = frappe.db.sql(
        f"""
        SELECT
            sn.name AS serial_no,
            sn.item_group,
            sn.stock_enty_date_and_time AS department_entry_date,

            GREATEST(
                TIMESTAMPDIFF(
                    DAY,
                    sn.stock_enty_date_and_time,
                    DATE_ADD(NOW(), INTERVAL 330 MINUTE)
                ) - COUNT(DISTINCT holiday.holiday_date),
                0
            ) AS department_age,

            dal.sla,

            CASE
                WHEN GREATEST(
                    TIMESTAMPDIFF(
                        DAY,
                        sn.stock_enty_date_and_time,
                        DATE_ADD(NOW(), INTERVAL 330 MINUTE)
                    ) - COUNT(DISTINCT holiday.holiday_date),
                    0
                ) > dal.sla
                THEN 'Overdue'
                ELSE 'Within Limit'
            END AS age_status

        FROM `tabSerial No` sn

        INNER JOIN `tabWarehouse` w
            ON w.name = sn.warehouse

        LEFT JOIN `tabHoliday` holiday
            ON holiday.parent = %s
            AND holiday.holiday_date > DATE(sn.stock_enty_date_and_time)
            AND holiday.holiday_date <= DATE(DATE_ADD(NOW(), INTERVAL 330 MINUTE))

        LEFT JOIN `tabPart Level SLA` dal
            ON dal.parent = w.department
            AND dal.parenttype = 'Department'
            AND dal.item_group = sn.item_group

        WHERE
            w.department = %s

            AND (
                w.warehouse_type IS NULL
                OR w.warehouse_type = ''
                OR w.warehouse_type != 'Employee Personal Warehouse'
            )

            AND sn.item_group IN ({item_group_placeholders})
            AND sn.status = 'Active'
            AND sn.stock_enty_date_and_time IS NOT NULL

        GROUP BY
            sn.name,
            sn.item_group,
            sn.stock_enty_date_and_time,
            dal.sla

        ORDER BY
            department_age DESC
        """,
        tuple(
            [DEPARTMENT_SLA_HOLIDAY_LIST, department]
            + part_level_sla_item_groups
        ),
        as_dict=True,
    )

    overdue_serials = [
        row for row in department_aging if row.get("age_status") == "Overdue"
    ]

    for overdue_serial in overdue_serials:
        error_messages.append(
            f"Part Level SLA | Serial No <b>{overdue_serial.get('serial_no')}</b> | "
            f"Item Group <b>{overdue_serial.get('item_group')}</b> | "
            f"Department <b>{department}</b> | "
            f"SLA <b>{int(overdue_serial.get('sla'))}</b> days | "
            f"Department Aging <b>{int(overdue_serial.get('department_age'))}</b> days | "
            f"Status <b>Overdue</b>."
        )

    return not overdue_serials

def get_nj_settings_comma_separated_values(parameter):
    value = frappe.db.get_value(
        "NJ Settings",
        {"parameter": parameter},
        "value",
    )
    return [
        item_group.strip()
        for item_group in (value or "").split(",")
        if item_group and item_group.strip()
    ]

def validate_serial_no_in_latest_nj_production_plan(
    serial_no, serial_doc, s_department, error_messages, doc=None, transfer_row=None
):
    stock_entry_type = doc.get("stock_entry_type") if doc else None
    if stock_entry_type != "Material Transfer":
        return True

    nj_value = frappe.db.get_value('NJ Settings', {'parameter': 'stock_movement_function_restriction'}, 'value')
    if (nj_value or "").strip().lower() != "enable":
        return True

    dept_restriction = frappe.db.get_value('Department', s_department, 'run_production_planning') if s_department else 0
    if not int(dept_restriction or 0):
        return True

    source_warehouse = transfer_row.get("s_warehouse") if transfer_row else None
    source_warehouse_type = (
        frappe.db.get_value("Warehouse", source_warehouse, "warehouse_type")
        if source_warehouse
        else None
    )
    if not source_warehouse_type or source_warehouse_type in (
        "Employee Personal Warehouse",
        "Department Asset Warehouse",
    ):
        return True
    skipping_departments = get_nj_settings_comma_separated_values("skipping_department_for_rank_validation")
    if s_department in skipping_departments:
        return True
    stock_movement_item_groups = get_nj_settings_comma_separated_values("stock_movement_item_groups")
    serial_item_group = serial_doc.get("item_group")

    if not stock_movement_item_groups or serial_item_group not in stock_movement_item_groups:
        return True

    target_warehouse = transfer_row.get("t_warehouse") if transfer_row else None
    target_warehouse_values = (
        frappe.db.get_value(
            "Warehouse",
            target_warehouse,
            ["warehouse_type", "department"],
            as_dict=True,
        )
        if target_warehouse
        else {}
    ) or {}
    target_warehouse_type = target_warehouse_values.get("warehouse_type")
    target_department = target_warehouse_values.get("department")
    same_department = bool(s_department) and s_department == target_department

    # NJ Production Plan presence/missing-serial checks still run. Only Priority
    # Rank and Part Allocation rank validation is skipped when both warehouses
    # belong to the same department, or for the existing Operation Warehouse flow.
    skip_rank_validation = (
        same_department
    ) or (
        source_warehouse_type == "Operation Warehouse"
        and target_warehouse_type in ("Rack", "Transit", "Operation Warehouse")
    )


    nj_production_name = _get_latest_nj_production_plan_name()
    if not nj_production_name:
        error_messages.append(
            "Latest NJ Production Planning not found. "
            f"Serial No <b>{serial_no}</b> cannot be validated. Please contact the NPD team."
        )
        return False

    production_plan_row = frappe.db.get_value(
        "Final Production Planning Data",
        {
            "parent": nj_production_name,
            "parenttype": "NJ Production Planning",
            "parentfield": "lines",
            "serial_no": serial_no,
        },
        ["priority_rank", "current_department", "current_warehouse", "part_allocation"],
        as_dict=True,
    )

    if production_plan_row:
        serial_department = serial_doc.get("department")
        if production_plan_row.get("current_department") != serial_department:
            # The Serial No has moved away from the department recorded in this
            # NJPP row, so it no longer participates in that department's rank.
            return True

        if skip_rank_validation:
            return True

        return _validate_production_plan_rank_for_transfer(
            serial_no=serial_no,
            serial_item_group=serial_item_group,
            production_plan_name=nj_production_name,
            production_plan_row=production_plan_row,
            transfer_row=transfer_row,
            transfer_doc=doc,
            target_department=target_department,
            core_item_groups=stock_movement_item_groups,
            error_messages=error_messages,
        )

    missing_serial_row = frappe.db.get_value(
        "Missing Serial Nos",
        {
            "parent": nj_production_name,
            "parenttype": "NJ Production Planning",
            "parentfield": "missing_serial_nos",
            "serial_no": serial_no,
        },
        ["name", "reason"],
        as_dict=True,
    )

    if missing_serial_row:
        safe_reason = frappe.utils.escape_html(
            str(missing_serial_row.get("reason") or "Reason not available")
        )
        error_messages.append(
            f"Serial No <b>{serial_no}</b> is missing from the latest NJ Production Planning "
            f"<b>{nj_production_name}</b>. Reason: <b>{safe_reason}</b>."
        )
        return False

    error_messages.append(
        f"Serial No <b>{serial_no}</b> was not found in either Final Production Planning Data "
        f"or Missing Serial Nos of the latest NJ Production Planning "
        f"<b>{nj_production_name}</b>. Please contact the NPD team."
    )
    return False


def _get_transfer_serial_nos(transfer_doc):
    serial_nos = set()
    if not transfer_doc:
        return serial_nos

    for item_row in transfer_doc.get("items", []):
        serial_value = item_row.get("serial_no")
        if not serial_value:
            continue

        for value in str(serial_value).replace(",", "\n").split("\n"):
            value = value.strip()
            if value:
                serial_nos.add(value)

    return serial_nos


def _validate_production_plan_rank_for_transfer(
    serial_no,
    serial_item_group,
    production_plan_name,
    production_plan_row,
    transfer_row,
    transfer_doc,
    target_department,
    core_item_groups,
    error_messages,
):
    rank = production_plan_row.get("priority_rank")
    try:
        selected_rank = int(flt(rank))
    except (TypeError, ValueError, OverflowError):
        selected_rank = 0

    if selected_rank <= 0:
        error_messages.append(
            f"Serial No <b>{serial_no}</b> does not have a valid Priority Rank in the latest "
            f"NJ Production Planning <b>{production_plan_name}</b>. Movement is not allowed."
        )
        return False

    source_warehouse = transfer_row.get("s_warehouse") if transfer_row else None
    target_warehouse = transfer_row.get("t_warehouse") if transfer_row else None
    if not source_warehouse or not target_warehouse:
        error_messages.append(
            f"Source Warehouse and Target Warehouse are required to validate the Priority Rank "
            f"for Serial No <b>{serial_no}</b>."
        )
        return False

    source_warehouse_type = frappe.db.get_value("Warehouse", source_warehouse, "warehouse_type")
    target_warehouse_type = frappe.db.get_value("Warehouse", target_warehouse, "warehouse_type")
    allowed_warehouse_types = {"Rack", "Transit", "Operation Warehouse"}

    if (
        source_warehouse_type not in allowed_warehouse_types
        or target_warehouse_type not in allowed_warehouse_types
    ):
        error_messages.append(
            f"Priority Rank validation is not configured for movement from "
            f"<b>{source_warehouse}</b> ({source_warehouse_type or 'Warehouse Type missing'}) to "
            f"<b>{target_warehouse}</b> ({target_warehouse_type or 'Warehouse Type missing'}) "
            f"for Serial No <b>{serial_no}</b>."
        )
        return False

    query_filters = {
        "production_plan": production_plan_name,
        "core_item_groups": tuple(core_item_groups),
    }

    if source_warehouse_type in ("Rack", "Transit"):
        rank_scope = "Department"
        current_department = production_plan_row.get("current_department")
        if not current_department:
            error_messages.append(
                f"Current Department is missing for Serial No <b>{serial_no}</b> in the latest "
                f"NJ Production Planning <b>{production_plan_name}</b>."
            )
            return False

        scope_condition = """
            AND FPPD.current_department = %(current_department)s
            AND WH.warehouse_type IN ('Rack', 'Transit')
        """
        query_filters["current_department"] = current_department
        scope_label = current_department
    else:
        rank_scope = "Warehouse"
        scope_condition = """
            AND SN.warehouse = %(source_warehouse)s
            AND WH.warehouse_type = 'Operation Warehouse'
        """
        query_filters["source_warehouse"] = source_warehouse
        scope_label = source_warehouse

    available_rows = frappe.db.sql(
        f"""
        SELECT
            FPPD.serial_no,
            FPPD.priority_rank,
            IFNULL(FPPD.part_allocation, 0) AS part_allocation,
            SN.warehouse,
            SN.item_group
        FROM `tabFinal Production Planning Data` FPPD
        INNER JOIN `tabSerial No` SN ON SN.name = FPPD.serial_no
        INNER JOIN `tabWarehouse` WH ON WH.name = SN.warehouse
        WHERE FPPD.parent = %(production_plan)s
          AND FPPD.parenttype = 'NJ Production Planning'
          AND FPPD.parentfield = 'lines'
          AND SN.warehouse IS NOT NULL
          AND SN.item_group IN %(core_item_groups)s
          AND SN.department = FPPD.current_department
          {scope_condition}
        """,
        query_filters,
        as_dict=True,
    )

    # Fetch the complete NJPP rank scope first, then filter that result using
    # the Target Department's SLA Item Groups before allocation/rank checks.
    target_sla_item_groups_value = (
        frappe.db.get_value("Department", target_department, "sla_item_groups")
        if target_department
        else None
    )
    target_sla_item_groups = {
        item_group.strip()
        for item_group in (target_sla_item_groups_value or "").split(",")
        if item_group and item_group.strip()
    }

    if target_sla_item_groups:
        if serial_item_group not in target_sla_item_groups:
            error_messages.append(
                f"Serial No <b>{serial_no}</b> belongs to Item Group "
                f"<b>{serial_item_group or 'Not Set'}</b>, which is not configured in "
                f"SLA Item Groups for Target Department <b>{target_department}</b>. "
                f"Movement is not allowed."
            )
            return False

        available_rows = [
            row
            for row in available_rows
            if row.get("item_group") in target_sla_item_groups
        ]

    selected_serial_nos = _get_transfer_serial_nos(transfer_doc)
    selected_part_allocation = bool(int(flt(production_plan_row.get("part_allocation") or 0)))
    part_allocated_rows = [
        row for row in available_rows
        if bool(int(flt(row.get("part_allocation") or 0)))
    ]

    if selected_part_allocation:
        priority_rows = part_allocated_rows
        priority_label = "Part Allocation"
    else:
        pending_part_allocated_rows = [
            row for row in part_allocated_rows
            if row.get("serial_no") not in selected_serial_nos
        ]
        if pending_part_allocated_rows:
            pending_part_allocated_rows.sort(
                key=lambda row: (
                    int(flt(row.get("priority_rank") or 0)),
                    row.get("serial_no") or "",
                )
            )
            pending_details = "<br>".join(
                f"{row.get('serial_no')} (Rank: {int(flt(row.get('priority_rank') or 0))}, "
                f"Warehouse: {row.get('warehouse')})"
                for row in pending_part_allocated_rows
            )
            error_messages.append(
                f"Serial No <b>{serial_no}</b> cannot be moved because Part Allocation Serial Nos "
                f"are still pending in the {rank_scope}-wise priority scope "
                f"<b>{scope_label}</b>:<br>{pending_details}"
            )
            return False

        priority_rows = [
            row for row in available_rows
            if not bool(int(flt(row.get("part_allocation") or 0)))
        ]
        priority_label = "normal"

    lower_ranked_rows = []

    for available_row in priority_rows:
        available_serial_no = available_row.get("serial_no")
        if available_serial_no in selected_serial_nos:
            continue

        try:
            available_rank = int(flt(available_row.get("priority_rank")))
        except (TypeError, ValueError, OverflowError):
            continue

        if available_rank < selected_rank:
            lower_ranked_rows.append(
                {
                    "serial_no": available_serial_no,
                    "rank": available_rank,
                    "warehouse": available_row.get("warehouse"),
                }
            )

    if not lower_ranked_rows:
        return True

    lower_ranked_rows.sort(key=lambda row: (row["rank"], row["serial_no"] or ""))
    pending_details = "<br>".join(
        f"{row['serial_no']} (Rank: {row['rank']}, Warehouse: {row['warehouse']})"
        for row in lower_ranked_rows
    )
    error_messages.append(
        f"Serial No <b>{serial_no}</b> with Rank <b>{selected_rank}</b> cannot be moved. "
        f"Lower-ranked {priority_label} Serial Nos are still available in the "
        f"{rank_scope}-wise priority scope "
        f"<b>{scope_label}</b>:<br>{pending_details}"
    )
    return False

def _get_latest_nj_production_plan_name():
    latest_plan = frappe.get_all(
        "NJ Production Planning",
        filters={"docstatus": ["!=", 2]},
        fields=["name"],
        order_by="creation desc",
        limit=1,
    )
    return latest_plan[0].name if latest_plan else None
def suggested_warehouse_validation(doc, t_warehouse, error_messages):

    if not t_warehouse:
        return

    serial_rows = []
    serial_nos = []

    for item_row in doc.get("items", []):
        row_t_warehouse = item_row.get("t_warehouse")
        row_serial_no = item_row.get("serial_no")

        if not row_t_warehouse or not row_serial_no:
            continue

        for serial_no in str(row_serial_no).split("\n"):
            serial_no = serial_no.strip()
            if not serial_no:
                continue

            serial_rows.append({
                "serial_no": serial_no,
                "t_warehouse": row_t_warehouse,
            })
            serial_nos.append(serial_no)


    unique_serial_nos = list(dict.fromkeys(serial_nos))

    if not unique_serial_nos:
        print("No serial numbers found, exiting...")
        return

    from nj_features.nj_features.doctype.department_recommendation_engine.department_recommendation_engine import bulk_apply

    for start in range(0, len(unique_serial_nos), 5):
        batch_serial_nos = unique_serial_nos[start:start + 5]
        bulk_apply("Serial No", json.dumps(batch_serial_nos))

    serial_docs = frappe.get_all(
        "Serial No",
        filters={"name": ["in", unique_serial_nos]},
        fields=["name", "suggested_warehouse"],
    )


    suggested_warehouse_map = {
        row.get("name"): row.get("suggested_warehouse")
        for row in serial_docs
    }


    for row in serial_rows:
        serial_no = row.get("serial_no")
        row_t_warehouse = row.get("t_warehouse")
        suggested_warehouse = suggested_warehouse_map.get(serial_no)


        if not suggested_warehouse:
            print("No suggested warehouse, skipping...")
            continue

        allowed_warehouses = [
            warehouse.strip()
            for warehouse in str(suggested_warehouse).split(",")
            if warehouse and warehouse.strip()
        ]


        if row_t_warehouse in allowed_warehouses:
            print("Warehouse is valid ✅")
            continue

        print("❌ Warehouse mismatch found")

        error_messages.append(
            f"Target warehouse <b>{row_t_warehouse}</b> is not allowed for Serial No <b>{serial_no}</b>. "
            f"Suggested warehouse should be one of <b>{', '.join(allowed_warehouses)}</b>."
        )


def deparement_qty_check_for_validation(doc, department, t_warehouse, error_messages, qty_check_cache=None):
    if not t_warehouse:
        return

    checked_keys = (qty_check_cache or {}).setdefault("checked_keys", set())
    item_group_cache = (qty_check_cache or {}).setdefault("item_group_cache", {})
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

    if not department_qty_and_item_groups:
        return

    department_row = department_qty_and_item_groups[0]
    max_qty = float(department_row.get("max_qty") or 0)
    item_groups = [
        item_group.strip()
        for item_group in (department_row.get("item_groups") or "").split(",")
        if item_group and item_group.strip()
    ]

    if not department or not max_qty or not item_groups:
        return

    placeholders = ", ".join(["%s"] * len(item_groups))
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
    current_qty_value = float((current_qty[0].get("current_qty") if current_qty else 0) or 0)

    transfer_qty_value = 0.0
    for item_row in doc.get("items", []):
        row_t_warehouse = item_row.get("t_warehouse")
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

    final_qty = current_qty_value + transfer_qty_value
    if final_qty > max_qty:
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

def check_if_serial_exists_in_active_bag_list(serial_no, error_messages, doc=None):
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

    if doc and parent_serial:
        all_doc_serials = set()
        for item in doc.get("items", []):
            row_serial_no = item.get("serial_no")
            if row_serial_no:
                for s in str(row_serial_no).split("\n"):
                    s = s.strip()
                    if s:
                        all_doc_serials.add(s)
        if parent_serial in all_doc_serials:
            return True

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
        
        valid_items = []
        for item in bag_list:
            if not (item.get("quantity", 0) > 0 and frappe.parse_json(item.get("is_available")) in [1, True, "1"]):
                continue
            
            comp_sn = item.get("serial_no")
            if comp_sn:
                status, wh = frappe.db.get_value("Serial No", comp_sn, ["status", "warehouse"]) or (None, None)
                if status != "Active" or not wh:
                    if item.get("name"):
                        frappe.db.set_value("Bag List", item.get("name"), {"is_available": 0, "quantity": 0}, update_modified=False)
                    continue
            else:
                laptop_wh = serial_doc.get("warehouse")
                if laptop_wh and item.get("item"):
                    avail = frappe.db.get_value("Bin", {"item_code": item.get("item"), "warehouse": laptop_wh}, "actual_qty") or 0.0
                    if avail < (item.get("quantity") or 1):
                        if item.get("name"):
                            frappe.db.set_value("Bag List", item.get("name"), {"is_available": 0, "quantity": 0}, update_modified=False)
                        continue

            valid_items.append(item)
        
        if valid_items:
            item_groups = list({item.get("item_group") for item in valid_items if item.get("item_group")})
            item_groups_str = ", ".join(f"<b>{group}</b>" for group in item_groups)
            error_messages.append(
                f"Serial No <b>{serial_doc.get('name')}</b> cannot be moved as it contains parts in a bag. "
                f"Item groups present in the bag: {item_groups_str}. Please remove them before proceeding."
            )

def check_qi_validation(serial_no, error_messages, s_warehouse, s_department, t_department):
    try:
        print("========== INSIDE check_qi_validation ==========")
        print("serial_no:", serial_no)
        print("s_warehouse:", s_warehouse)
        print("s_department:", s_department)
        print("t_department:", t_department)

        serial_no_doc = frappe.get_doc('Serial No', serial_no)
        print("serial exists:", bool(serial_no_doc))
        print("serial item_group:", serial_no_doc.get("item_group"))
        print("serial creation:", serial_no_doc.creation)

        s_inspection_type = frappe.get_doc('Department', s_department)
        print("department doc:", s_inspection_type.name)

        inspection_types = [
            row.get('inspection_type')
            for row in s_inspection_type.get("inspection_types")
            if row.get('inspection_type')
        ]

        print("inspection_types list:", inspection_types)

        if not inspection_types:
            print("NO inspection_types configured, returning without QI check")
            return

        result = frappe.db.sql(
            """
            SELECT se.creation, se.name
            FROM `tabStock Entry Detail` sed
            JOIN `tabStock Entry` se ON sed.parent = se.name
            WHERE se.stock_entry_type = "Material Transfer"
              AND sed.source_department != sed.target_department
              AND sed.serial_no = %s
              AND se.docstatus = 1
            ORDER BY se.creation DESC
            LIMIT 1
            """,
            (serial_no,),
            as_dict=True
        )

        print("latest previous stock entry result:", result)

        if result:
            formatted_time = result[0]["creation"].strftime("%Y-%m-%d %H:%M:%S")
        else:
            formatted_time = serial_no_doc.creation.strftime("%Y-%m-%d %H:%M:%S")

        current_time = (datetime.now() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

        print("QI search from:", formatted_time)
        print("QI search to:", current_time)

        qi_result = frappe.db.sql(
            """
            SELECT name, inspection_type, status, barcode, docstatus, creation, modified
            FROM `tabNJ Quality Inspection`
            WHERE inspection_type IN %s
              AND docstatus = 1
              AND barcode = %s
              AND modified BETWEEN %s AND %s
            ORDER BY creation DESC
            LIMIT 1
            """,
            (tuple(inspection_types), serial_no, formatted_time, current_time),
            as_dict=True
        )

        print("QI query result:", qi_result)

        if not qi_result:
            print("QI NOT FOUND, APPENDING ERROR")
            error_messages.append(
                f"NJ Quality Inspection not found for serial no <b>{serial_no}</b> "
                f"in warehouse <b>{s_warehouse}</b> between <b>{formatted_time}</b> and <b>{current_time}</b>."
            )
            print("error_messages after QI missing:", error_messages)
            return

        qi_doc = frappe.get_doc('NJ Quality Inspection', qi_result[0]["name"])
        print("QI doc found:", qi_doc.name)
        print("QI status:", qi_doc.get("status"))

        allowed_statuses = [
            status.strip()
            for status in s_inspection_type.get("quality_inspection_status_for_stock_movement").split(",")
            if status.strip()
        ]

        print("allowed_statuses:", allowed_statuses)

        if qi_doc.get("status") not in allowed_statuses:
            print("QI STATUS NOT ALLOWED, APPENDING ERROR")
            error_messages.append(
                f"NJ Quality Inspection <b>{qi_doc.name}</b> for serial no <b>{serial_no}</b> "
                f"has status <b>{qi_doc.get('status')}</b>, but allowed statuses are "
                f"<b>{', '.join(allowed_statuses)}</b>."
            )
            print("error_messages after status failed:", error_messages)
        else:
            print("QI PASSED")

    except Exception as e:
        print("EXCEPTION IN QI VALIDATION:", str(e))
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Error in check_qi_validation")
        error_messages.append(f"An error occurred during Quality Inspection validation. Error: {str(e)}")

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

    print("\n")
    print("=" * 100)
    print("DEBUG: validate_non_component_grade START")
    print("=" * 100)

    print("SERIAL NAME:", serial_doc.name)
    print("SERIAL ITEM CODE:", serial_doc.get("item_code"))
    print("SERIAL ITEM WIZARD:", serial_doc.get("item_wizard"))

    print("\nDEPARTMENT NAME:", department_doc.name)
    print(
        "RESTRICT ALL:",
        repr(department_doc.get("restrict_all")),
        "TYPE:",
        type(department_doc.get("restrict_all"))
    )
    print(
        "INCLUDE BAG LIST:",
        repr(department_doc.get("blmnh")),
        "TYPE:",
        type(department_doc.get("blmnh"))
    )

    print("\n--- MAIN SERIAL GRADE CHECK ---")

    result = frappe.db.get_value(
        'Serial No',
        {'name': serial_doc.get('name')},
        ['grade', 'item_group']
    )

    print("DB RESULT:", repr(result))

    if result is None:
        print("DEBUG: Serial No DB result is NONE")

        error_messages.append(
            f"Item <b>{serial_doc.get('item_code')}</b> not found. "
            f"Cannot validate grade restrictions for serial <b>{serial_doc.name}</b>."
        )
        return

    lap_grade, lap_item_group = result

    print("MAIN SERIAL GRADE:", repr(lap_grade))
    print("MAIN SERIAL ITEM GROUP:", repr(lap_item_group))

    print("\n--- DEPARTMENT RESTRICTION TABLE ---")

    restrictions = department_doc.get(
        'stock_movement_restriction_table', []
    )

    print("TOTAL RESTRICTION ROWS:", len(restrictions))

    for idx, restriction in enumerate(restrictions, 1):

        restricted_grades = restriction.get(
            'restricted_grade', ""
        ).split(",")

        restricted_item_group = restriction.get('item_group')

        print(
            f"RESTRICTION {idx}:",
            "ITEM GROUP =",
            repr(restricted_item_group),
            "GRADES =",
            repr(restricted_grades)
        )

        print(
            "MAIN SERIAL COMPARISON:",
            repr(lap_item_group),
            "==",
            repr(restricted_item_group),
            "->",
            lap_item_group == restricted_item_group,
            "|",
            repr(lap_grade),
            "IN",
            repr(restricted_grades),
            "->",
            lap_grade in restricted_grades
        )

        if (
            lap_item_group == restricted_item_group
            and lap_grade in restricted_grades
        ):
            print(">>> MAIN SERIAL RESTRICTION MATCHED <<<")

            error_messages.append(
                f"Serial No.: <b>{serial_doc.name}</b> "
                f"for Item: <b>{serial_doc.get('item_code')}</b> "
                f"with Item Group: <b>{lap_item_group}</b> "
                f"has Grade: <b>{lap_grade}</b> this is not allowed "
                f"for Department: <b>{department_doc.name}</b>."
            )

    restrict_all = department_doc.get('restrict_all')
    include_bag_list = department_doc.get('blmnh')

    print("\n--- RESTRICT ALL DECISION ---")
    print("restrict_all raw:", repr(restrict_all))
    print("int(restrict_all):", int(restrict_all))

    if int(restrict_all):

        print("\n>>> ENTERED RESTRICT ALL = 1 BRANCH <<<")

        item_wizard_name = serial_doc.get("item_wizard")

        print("ITEM WIZARD:", repr(item_wizard_name))

        if not item_wizard_name:
            print(
                "!!! RETURNING: ITEM WIZARD IS EMPTY !!!"
            )
            return

        item_wizard_doc = frappe.get_doc(
            "Item Wizards",
            item_wizard_name
        )

        mandatory_item_groups = set(
            row.get("component_type")
            for row in item_wizard_doc.get("component", [])
            if row.get("mandatory") == 1
        )

        print(
            "MANDATORY ITEM GROUPS:",
            repr(mandatory_item_groups)
        )

        component_grade_map = {}

        print("\n--- SERIAL COMPONENTS ---")

        components = serial_doc.get(
            'serial_no_component', []
        )

        print("TOTAL COMPONENT ROWS:", len(components))

        for idx, component in enumerate(components, 1):

            print(
                f"COMPONENT {idx}:",
                "ITEM GROUP =",
                repr(component.get('item_group')),
                "GRADE =",
                repr(component.get('grade')),
                "QTY =",
                repr(component.get('quantity')),
                "QTY TYPE =",
                type(component.get('quantity'))
            )

            if component.get('quantity') == 1:
                component_grade_map[
                    component.get('item_group')
                ] = component.get('grade')

                print("  -> ADDED TO COMPONENT GRADE MAP")
            else:
                print("  -> NOT ADDED BECAUSE QTY != 1")

        print(
            "FINAL COMPONENT GRADE MAP:",
            repr(component_grade_map)
        )

        if include_bag_list:

            print("\n--- BAG LIST ---")

            for idx, bag in enumerate(
                serial_doc.get('bag_list', []), 1
            ):

                print(
                    f"BAG {idx}:",
                    repr(bag.get('item_group')),
                    repr(bag.get('grade')),
                    repr(bag.get('quantity'))
                )

                if bag.get('quantity') == 1:
                    item_group = bag.get('item_group')

                    if (
                        item_group
                        and item_group not in component_grade_map
                    ):
                        component_grade_map[
                            item_group
                        ] = bag.get('grade')

        restriction_map = {}

        for restriction in restrictions:

            item_group = restriction.get('item_group')

            grades = [
                g.strip()
                for g in restriction.get(
                    'restricted_grade', ""
                ).split(",")
            ]

            restriction_map[item_group] = grades

        print(
            "RESTRICTION MAP:",
            repr(restriction_map)
        )

        all_violating = True
        present_component_found = False

        for item_group, restricted_grades in restriction_map.items():

            grade = component_grade_map.get(item_group)

            print(
                "CHECK ITEM GROUP:",
                repr(item_group),
                "FOUND GRADE:",
                repr(grade),
                "RESTRICTED GRADES:",
                repr(restricted_grades)
            )

            # Qty 0 / component not present -> ignore it
            if grade is None:
                print("  -> COMPONENT NOT PRESENT / QTY 0, IGNORING")
                continue

            present_component_found = True

            if grade not in restricted_grades:
                print("  -> PRESENT COMPONENT HAS ALLOWED GRADE")
                all_violating = False
                break

            print("  -> PRESENT COMPONENT HAS RESTRICTED GRADE")


        print("PRESENT COMPONENT FOUND:", present_component_found)
        print("FINAL all_violating:", all_violating)


        if present_component_found and all_violating:
            print(">>> RESTRICT ALL VIOLATION ADDED <<<")

            error_messages.append(
                f"Serial No.: <b>{serial_doc.name}</b> — all present restricted components "
                f"have restricted grades and are not allowed for Department: "
                f"<b>{department_doc.name}</b>."
            )

    else:

        print("\n")
        print("=" * 100)
        print(">>> ENTERED RESTRICT ALL = 0 BRANCH <<<")
        print("=" * 100)

        components = serial_doc.get(
            'serial_no_component', []
        )

        print(
            "TOTAL SERIAL COMPONENT ROWS:",
            len(components)
        )

        for component_index, component in enumerate(
            components, 1
        ):

            component_item_group = component.get(
                'item_group'
            )
            component_grade = component.get('grade')
            component_qty = component.get('quantity')

            print("\n")
            print(
                f"--- COMPONENT {component_index} ---"
            )

            print(
                "COMPONENT ITEM GROUP:",
                repr(component_item_group)
            )
            print(
                "COMPONENT GRADE:",
                repr(component_grade)
            )
            print(
                "COMPONENT QTY:",
                repr(component_qty)
            )
            print(
                "COMPONENT QTY TYPE:",
                type(component_qty)
            )

            for restriction_index, restriction in enumerate(
                restrictions, 1
            ):

                restricted_grades = restriction.get(
                    'restricted_grade', ""
                ).split(",")

                restricted_item_group = restriction.get(
                    'item_group'
                )

                print(
                    f"\n  RESTRICTION {restriction_index}:"
                )

                print(
                    "  RESTRICTED ITEM GROUP:",
                    repr(restricted_item_group)
                )

                print(
                    "  RESTRICTED GRADES:",
                    repr(restricted_grades)
                )

                item_group_match = (
                    component_item_group
                    == restricted_item_group
                )

                grade_match = (
                    component_grade
                    in restricted_grades
                )

                qty_match = (
                    component_qty == 1
                )

                print(
                    "  ITEM GROUP MATCH:",
                    item_group_match,
                    "|",
                    repr(component_item_group),
                    "==",
                    repr(restricted_item_group)
                )

                print(
                    "  GRADE MATCH:",
                    grade_match,
                    "|",
                    repr(component_grade),
                    "in",
                    repr(restricted_grades)
                )

                print(
                    "  QTY MATCH:",
                    qty_match,
                    "|",
                    repr(component_qty),
                    "== 1"
                )

                final_condition = (
                    item_group_match
                    and grade_match
                    and qty_match
                )

                print(
                    "  FINAL CONDITION:",
                    final_condition
                )

                if final_condition:

                    print(
                        "\n  >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>"
                    )
                    print(
                        "  >>> VIOLATION FOUND <<<"
                    )
                    print(
                        "  >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>"
                    )

                    error_messages.append(
                        f"Serial No <b>{serial_doc.name}</b> "
                        f"for item_group <b>{component_item_group}</b> "
                        f"has a grade <b>{component_grade}</b> "
                        f"that is not allowed for department "
                        f"<b>{department_doc.name}</b>."
                    )

        if include_bag_list:

            print("\n--- CHECKING BAG LIST ---")

            for bag in serial_doc.get('bag_list', []):

                for restriction in restrictions:

                    restricted_grades = restriction.get(
                        'restricted_grade', ""
                    ).split(",")

                    restricted_item_group = restriction.get(
                        'item_group'
                    )

                    print(
                        "BAG CHECK:",
                        repr(bag.get('item_group')),
                        repr(bag.get('grade')),
                        repr(bag.get('quantity')),
                        "VS",
                        repr(restricted_item_group),
                        repr(restricted_grades)
                    )

                    if (
                        bag.get('item_group')
                        == restricted_item_group
                        and bag.get('grade')
                        in restricted_grades
                        and bag.get('quantity') == 1
                    ):

                        print(
                            ">>> BAG LIST VIOLATION FOUND <<<"
                        )

                        error_messages.append(
                            f"Serial No <b>{serial_doc.name}</b> "
                            f"(bag_list) for item_group "
                            f"<b>{bag.get('item_group')}</b> "
                            f"has a grade <b>{bag.get('grade')}</b> "
                            f"that is not allowed for department "
                            f"<b>{department_doc.name}</b>."
                        )

    print("\n")
    print("=" * 100)
    print("FINAL ERROR MESSAGES:")
    print(error_messages)
    print("DEBUG: validate_non_component_grade END")
    print("=" * 100)

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
        if row.strip()
    ]


def check_min_qty_and_max_qty(serial_doc, department_doc, error_messages):

    # Get item groups configured in NJ Settings
    special_item_groups = get_special_max_qty_item_groups_from_nj_settings()

    # Fetch Item Wizard components
    item_wizard_components = frappe.db.get_all(
        'Component',
        {
            'parent': serial_doc.item_wizard
        },
        ['component_type', 'quantity', 'mandatory']
    )

    # Quantity from Item Wizard
    iw_quantity_map = {
        row.get("component_type"): int(row.get("quantity") or 0)
        for row in item_wizard_components
        if row.get("component_type")
    }

    # Check ONLY item groups configured in NJ Settings
    for row in department_doc.get('allowed_item_group_grades'):

        item_group = row.get('item_group')

        # IMPORTANT:
        # Ignore all other item groups
        if item_group not in special_item_groups:
            continue

        total_quantity = 0

        # Serial No components
        for col in serial_doc.get('serial_no_component', []):
            if col.get('item_group') == item_group:
                total_quantity += int(col.get('quantity') or 0)

        # Bag list components
        for col in serial_doc.get('bag_list', []):
            if col.get('item_group') == item_group:
                total_quantity += int(col.get('quantity') or 0)

        # Minimum comes from Department
        min_qty = int(row.get('min_quantity') or 0)

        # Maximum comes from Item Wizard
        max_qty = int(iw_quantity_map.get(item_group) or 0)

        if total_quantity < min_qty or total_quantity > max_qty:
            error_messages.append(
                f"Serial No <b>{serial_doc.name}</b> "
                f"for item_group <b>{item_group}</b> "
                f"has Total quantity <b>{total_quantity}</b> "
                f"that is not allowed for department "
                f"<b>{department_doc.name}</b>. "
                f"(Min: {min_qty}, Max: {max_qty})"
            )
# def get_special_max_qty_item_groups_from_nj_settings():
#     value = frappe.db.get_value(
#         "NJ Settings",
#         {
#             "doc_type": "Stock Movement",
#             "parameter": "Restriction for min and max"
#         },
#         "value"
#     ) or ""

#     return [
#         row.strip()
#         for row in value.splitlines()
#         if row and row.strip()
#     ]

# def check_min_qty_and_max_qty(serial_doc, department_doc, error_messages):
#     # Fetch special item groups from NJ Settings instead of hardcoding
#     special_item_groups = get_special_max_qty_item_groups_from_nj_settings()

#     # Fetch mandatory components from Item Wizard
#     item_wizards_mandatory_item_groups_data = frappe.db.get_all(
#         'Component',
#         {
#             'parent': serial_doc.item_wizard,
#             'mandatory': '1'
#         },
#         ['component_type', 'quantity']
#     )

#     mandatory_item_groups = [
#         row.get("component_type")
#         for row in item_wizards_mandatory_item_groups_data
#     ]

#     # Item Wizard quantity lookup
#     iw_quantity_map = {
#         row.get("component_type"): int(row.get("quantity") or 0)
#         for row in item_wizards_mandatory_item_groups_data
#         if row.get("component_type")
#     }

#     for row in department_doc.get('allowed_item_group_grades'):
#         item_group = row.get('item_group')

#         if item_group in mandatory_item_groups:
#             total_quantity = 0

#             # Sum quantity from serial_no_component
#             for col in serial_doc.get('serial_no_component', []):
#                 if col.get('item_group') == item_group:
#                     total_quantity += int(col.get('quantity') or 0)

#             # Sum quantity from bag_list
#             for col in serial_doc.get('bag_list', []):
#                 if col.get('item_group') == item_group:
#                     total_quantity += int(col.get('quantity') or 0)

#             # Min quantity always from Department
#             min_qty = int(row.get('min_quantity') or 0)

#             # Max quantity:
#             # For configured special item groups -> from Item Wizard qty
#             # Everything else -> keep previous Department max flow
#             if item_group in special_item_groups:
#                 max_qty = int(iw_quantity_map.get(item_group) or 0)
#             else:
#                 max_qty = int(row.get('max_quantity') or 1)

#             if total_quantity < min_qty or total_quantity > max_qty:
#                 error_messages.append(
#                     f"Serial No <b>{serial_doc.name}</b> for item_group <b>{item_group}</b> "
#                     f"has Total quantity <b>{total_quantity}</b> that is not allowed for department "
#                     f"<b>{department_doc.name}</b>. "
#                     f"(Min: {min_qty}, Max: {max_qty})"
#                 )

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
                AND item_group IN ('Laptops', 'Chromebooks', 'MacBooks')
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



def validate_serial_no_gen_wise(serial_no, serial_doc, department, s_department, error_messages):
    gen_item_groups = get_nj_settings_comma_separated_values("gen_item_groups")
    repair_system = get_nj_settings_comma_separated_values("repair_systems_for_gen_wise")
    serial_item_group = frappe.db.get_value("Item", serial_doc.get("item_code"), "item_group")
    serial_no_return_reason = frappe.db.get_value("Serial No", serial_no, "return_reason")
    sellable_dept = "Inward Salable - NJ"

    if repair_system and serial_no_return_reason in repair_system:
        return True
    if not gen_item_groups or serial_item_group not in gen_item_groups:
        return True

    parent_qty = flt(serial_doc.get("parent_qty"))
    is_above_gen = bool(serial_doc.get("laptop_gen"))
    parameter = "above_8th_gen" if is_above_gen else "below_8th_gen"
    gen_label = "above 8th gen" if is_above_gen else "below 8th gen"

    gen_settings = frappe.db.get_value(
        "NJ Settings",
        {"doc_type": "Stock Movement", "parameter": parameter},
        ["value", "value_rp"],
        as_dict=True,
    )

    if not gen_settings:
        error_messages.append(
            f"<b>NJ Settings</b> for <b>{parameter}</b> is not defined for <b>Stock Movement</b>."
        )
        return False

    allowed_departments = _split_department_names(gen_settings.get("value"))
    if department in allowed_departments:
        return True

    threshold_qty = flt(gen_settings.get("value_rp"))
    if is_above_gen and parent_qty > threshold_qty:
        return True

    if not is_above_gen:
        dept_wise_settings = frappe.db.get_value(
            "NJ Settings",
            {"doc_type": "Stock Movement", "parameter": "below_gen_restriction_dept_wise"},
            ["value", "value_rp"],
            as_dict=True,
        )

        restricted_source_departments = _split_department_names(
            dept_wise_settings.get("value") if dept_wise_settings else None
        )
        dept_wise_threshold_qty = flt(
            dept_wise_settings.get("value_rp") if dept_wise_settings else 0
        )

        if restricted_source_departments:
            if (
                s_department in restricted_source_departments
                and parent_qty <= dept_wise_threshold_qty
            ):
                restricted_departments_text = ", ".join(restricted_source_departments)
                error_messages.append(
                    f"Serial No <b>{serial_no}</b> parent qty <b>{parent_qty}</b> is less than or equal to "
                    f"<b>{dept_wise_threshold_qty}</b> for <b>below 8th gen</b>. You cannot move this serial no "
                    f"from source department <b>{s_department}</b>. Restricted source departments: "
                    f"<b>{restricted_departments_text}</b>."
                    f"Kindly Move this serial no to department<b> {sellable_dept} </b>. "
                )
                return False

            return True

    if parent_qty > threshold_qty:
        return True

    allowed_departments_text = ", ".join(allowed_departments) if allowed_departments else "not configured"
    error_messages.append(
        f"Serial No <b>{serial_no}</b> parent qty <b>{parent_qty}</b> is less than or equal to "
        f"<b>{threshold_qty}</b> for <b>{gen_label}</b>. You cannot move this serial no to "
        f"<b>{department}</b>. Allowed departments: <b>{allowed_departments_text}</b>."
    )
    return False
