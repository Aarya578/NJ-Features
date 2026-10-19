# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import re
import json
import frappe
import traceback
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, date_diff
from nj_lib.utils.common_utils import get_active_emp

class SecurityInwardRegistry(Document):
    def validate(self):
        self.validate_customer_return_duplicates()

    def validate_customer_return_duplicates(self):
        if self.registry_type == 'Customer Return' and self.get('customer_return_registry'):
            seen_serials = set()
            for row in self.customer_return_registry:
                if row.serial_no:
                    serial = str(row.serial_no).strip()
                    if serial in seen_serials:
                        frappe.throw(_(f"Duplicate Serial No '{serial}' found in Customer Return table."))
                    seen_serials.add(serial)

    def on_submit(self):
        try:
            self.validate_customer_return_duplicates()
            self.update_transfer_qty(state='submit')
            self.get_total_qty()
            self.update_user_accepted_details()

        except Exception as e:

            traceback_info = traceback.format_exc()
            frappe.throw(f"Error on submit: {str(e)}\n{traceback_info}") 
            frappe.db.rollback()

    def update_user_accepted_details(self):
        try:
            
            user = frappe.session.user

            if self.registry_type == 'Purchase':
                self.user_accepted_name = user
                self.db_set("user_accepted_name", user)

            elif self.registry_type == 'Accept Registry':
                user_dept = self.get_user_department(user)

                self.user_accepted_name = user
                self.accepted_dept = user_dept
                self.db_set("user_accepted_name", user)
                self.db_set("accepted_dept", user_dept)

                if self.stock_registry_no:
                    frappe.db.set_value(
                        "Security Inward Registry",
                        self.stock_registry_no,
                        {
                            "user_accepted_name": user,
                            "accepted_dept": user_dept
                        }
                    )
            frappe.db.commit()

        except Exception as e:
            traceback_info = traceback.format_exc()
            frappe.log_error(message=f"Error in update_user_accepted_details: {str(e)}\n{traceback_info}", title="Security Inward Registry")
            frappe.throw(f"Error updating accepted user details: {str(e)}")

    def get_user_department(self, user=None):
        try:
            if not user:
                user = frappe.session.user

            emp_data = get_active_emp(user, fields=['department'], ignore=True)
            if isinstance(emp_data, list):
                emp_data = emp_data[0] if emp_data else {}
            if emp_data and emp_data.get('department'):
                return emp_data.get('department')

            dept = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "department")
            if not dept:
                dept = frappe.db.get_value("Employee", {"user_id": user}, "department")
            return dept
        except Exception:
            return frappe.db.get_value("Employee", {"user_id": user or frappe.session.user}, "department")

    def on_cancel(self):
        try:
            self.update_transfer_qty(state='cancel')
            self.get_total_qty()

        except Exception as e:
            traceback_info = traceback.format_exc()
            frappe.throw(f"Error on submit: {str(e)}\n{traceback_info}") 
            frappe.db.rollback()

    def update_transfer_qty(self, state):
        try:
            if state == 'cancel':
                if self.get('purchase_inward_registry_child') and len(self.get('purchase_inward_registry_child')):
                    registry_select_query_with_ref = """
                        SELECT reference_item_group, SUM(actual_qty)
                        FROM `tabSecurity Inward Registry Child`
                        WHERE parent = %s
                        GROUP BY reference_item_group
                    """
                    
                    registry_select_qty = frappe.db.sql(
                        registry_select_query_with_ref, 
                        (self.get('name'),), 
                        as_dict=True
                    )

                    total_qty = 0
                    for row in registry_select_qty:
                        registry_update_query = """
                            UPDATE `tabSecurity Inward Registry Purchase Child`
                            SET actual_qty = actual_qty + %s 
                            WHERE parent = %s AND item_group = %s AND docstatus = 1
                        """
                        frappe.db.sql(
                            registry_update_query, 
                            (row['SUM(actual_qty)'], self.get('stock_registry_no'), row['reference_item_group'])
                        )
                        total_qty = total_qty + row['SUM(actual_qty)']

                    registry_update_query = """
                                            UPDATE `tabSecurity Inward Registry`
                                            SET total_qty = %s
                                            WHERE name = %s
                                            """
                    frappe.db.sql(
                        registry_update_query, 
                        (total_qty, self.get('stock_registry_no'))
                    )

            elif state == 'submit' and self.registry_type == 'Accept Registry':
                if self.get('purchase_inward_registry_child') and len(self.get('purchase_inward_registry_child')) > 0:
                    registry_select_query_with_ref = """
                        SELECT reference_item_group, SUM(actual_qty)
                        FROM `tabSecurity Inward Registry Child`
                        WHERE parent = %s
                        GROUP BY reference_item_group
                    """
                    
                    registry_select_qty = frappe.db.sql(
                        registry_select_query_with_ref, 
                        (self.get('name'),), 
                        as_dict=True
                    )

                    total_qty = 0
                    for row in registry_select_qty:
                        registry_update_query = """
                            UPDATE `tabSecurity Inward Registry Purchase Child`
                            SET actual_qty = actual_qty - %s 
                            WHERE parent = %s AND item_group = %s AND docstatus = 1
                        """
                        frappe.db.sql(
                            registry_update_query, 
                            (row['SUM(actual_qty)'], self.get('stock_registry_no'), row['reference_item_group'])
                        )
                    
                    registry_update_query = """
                                            UPDATE `tabSecurity Inward Registry`
                                            SET total_qty = %s
                                            WHERE name = %s
                                            """
                    frappe.db.sql(
                        registry_update_query, 
                        (total_qty, self.get('stock_registry_no'))
                    )
                    
            frappe.db.commit()

        except Exception as e:
            frappe.log_error(message=str(e), title="Error in update_transfer_qty")
            frappe.throw(_("An error occurred while updating transfer quantities."))


    def get_total_qty(self):
        try:
            total_qty = 0

            if self.transfer_registry and len(self.transfer_registry)>0:
                for item in self.transfer_registry:
                    total_qty += int(item.actual_qty)
            
            if self.purchase_inward_registry_purchase_child and len(self.purchase_inward_registry_purchase_child)>0:
                for item in self.purchase_inward_registry_purchase_child:
                    total_qty += int(item.actual_qty)
            
            if self.customer_return_registry and len(self.customer_return_registry)>0:
                for item in self.customer_return_registry:
                    total_qty += int(item.actual_qty)
            
            if self.purchase_inward_registry_child and len(self.purchase_inward_registry_child)>0:
                for item in self.purchase_inward_registry_child:
                    total_qty += int(item.actual_qty)

            self.db_set("total_qty", total_qty)

            return total_qty
        
        except Exception as e:
            traceback_info = traceback.format_exc()
            frappe.throw(f"Error on get_total_qty: {str(e)}\n{traceback_info}")
            return None

@frappe.whitelist()
def validate_accept_registry(frm):
    if isinstance(frm, str):
        frm = json.loads(frm)
    
    if frm.get('registry_type') == 'Accept Registry':
        if frm.get('purchase_inward_registry_child') and len(frm['purchase_inward_registry_child']) > 0:
            inwarded_total = sum(
                int(row.get('received_qty', 0))
                for row in frm.get('sir_inwarded_qty_table', [])
            )

            recieved_total = sum(
                int(row.get('actual_qty', 0))
                for row in frm.get('purchase_inward_registry_child', [])
            )

            if not int(inwarded_total) != int(recieved_total):
                inwarded_qty = {}
                received_qty_details = {}

                for row in frm.get('sir_inwarded_qty_table', []):
                    item_group = row.get('item_group')
                    inwarded_qty[item_group] = inwarded_qty.get(item_group, 0) + int(row.get('received_qty', 0))

                for row in frm.get('purchase_inward_registry_child', []):
                    reference_item_group = row.get('reference_item_group')
                    received_qty_details[reference_item_group] = received_qty_details.get(reference_item_group, 0) + int(row.get('actual_qty', 0))

                for item_group, inward_qty in inwarded_qty.items():
                    received_qty = received_qty_details.get(item_group, 0)
                    if inward_qty != received_qty:
                        return {
                            "error": f"<b>Mismatch for {item_group}: Inwarded {inward_qty}, Received {received_qty}</b>"
                        }
            else:
                return {
                    "error": "<b>Total quantities match, which is not expected.</b>"
                    }

def get_child_table(frm):
    valid_table_name = None

    if isinstance(frm, dict):
        if frm.get('purchase_inward_registry_purchase_child') and len(frm['purchase_inward_registry_purchase_child']) > 0:
            valid_table_name = frm['purchase_inward_registry_purchase_child'][0].get('doctype')

        elif frm.get('customer_return_registry') and len(frm['customer_return_registry']) > 0:
            valid_table_name = frm['customer_return_registry'][0].get('doctype')

        elif frm.get('transfer_registry') and len(frm['transfer_registry']) > 0:
            valid_table_name = frm['transfer_registry'][0].get('doctype')

        elif frm.get('purchase_inward_registry_child') and len(frm['purchase_inward_registry_child']) > 0:
            valid_table_name = frm['purchase_inward_registry_child'][0].get('doctype')
    else:
        if frm.purchase_inward_registry and len(frm.purchase_inward_registry) > 0:
            valid_table_name = frm.purchase_inward_registry[0].get('doctype')

        elif frm.customer_return_registry and len(frm.customer_return_registry) > 0:
            valid_table_name = frm.customer_return_registry[0].get('doctype')

        elif frm.transfer_registry and len(frm.transfer_registry) > 0:
            valid_table_name = frm.transfer_registry[0].get('doctype')

    if valid_table_name:
        return "tab" + valid_table_name
    
    return None

@frappe.whitelist()
def make_security_inward_registry(po_number, registry_type):
    po_data = frappe.get_doc('Purchase Order', po_number)
    po_data_dict = po_data.__dict__
    
    return po_data_dict


@frappe.whitelist()
def get_po_number_details(po_number: str, subtract_sir: int = 0):
    """
    Returns remaining qty per item_group for a PO.

    Default behavior:
      remaining = (PO qty) - (submitted Purchase Receipt qty)
      (SIR is ignored so you see the true outstanding against the PO.)

    If subtract_sir=1 is passed, we also subtract submitted SIR qty
    that are created directly against this PO (strict match on sir.po_number).
    """
    try:
        # --- Guard: PO must exist
        po_creation_date = frappe.db.get_value("Purchase Order", {"name": po_number}, "creation")
        if not po_creation_date:
            return {"error": f"Purchase Order {po_number} does not exist."}

        # --- Guard: restriction window
        po_restriction_days = frappe.db.get_single_value("NewJaisa Configuration", "po_restriction_days") or 0
        current_date = now_datetime()
        days_difference = date_diff(current_date.date(), po_creation_date.date())
        if int(po_restriction_days) > 0 and days_difference > int(po_restriction_days):
            return {"error": f"{po_restriction_days} days expired for this Purchase Order"}

        # --- Step 1: PO - PR per item_code, normalized to item_group
        items = get_item_code_details(po_number)  # [{'item_group': ..., 'item_code': ..., 'available_qty': ...}, ...]

        # --- Step 2: aggregate by item_group
        grouped = {}
        for row in items:
            ig = row["item_group"]
            grouped[ig] = grouped.get(ig, 0) + (row["available_qty"] or 0)

        result_rows = [{"item_group": ig, "available_qty": float(qty)} for ig, qty in grouped.items()]

        # --- Step 3 (optional): subtract SIR that are *directly* for this PO
        if int(subtract_sir) == 1:
            sir_map = get_inwarded_qty_by_item_group(po_number)
            for rec in result_rows:
                ig = rec["item_group"]
                sir_qty = sir_map.get(ig, 0.0)
                rec["available_qty"] = max(0.0, (rec["available_qty"] or 0.0) - sir_qty)

        return result_rows

    except Exception as e:
        frappe.throw(f"Error on get_po_number_details: {frappe.get_traceback()}")
        return None


def get_item_code_details(po_number: str):
    """
    For the given PO, returns rows:
      item_group, item_code, available_qty = SUM(PO qty) - SUM(submitted PR qty)
    Then normalizes non-'Products' groups to 'Others'.
    """
    try:
        available_qty_data = frappe.db.sql(
            """
            SELECT
                poi.item_group,
                poi.item_code,
                (COALESCE(SUM(poi.qty), 0) - COALESCE(SUM(pri.qty), 0)) AS available_qty
            FROM `tabPurchase Order Item` poi
            LEFT JOIN `tabPurchase Receipt Item` pri
                ON pri.purchase_order = poi.parent
               AND pri.purchase_order_item = poi.name
               AND pri.item_code = poi.item_code
               AND pri.docstatus = 1
            LEFT JOIN `tabPurchase Receipt` pr
                ON pr.name = pri.parent
               AND pr.docstatus = 1
            WHERE poi.parent = %(po)s
            GROUP BY poi.item_group, poi.item_code
            """,
            {"po": po_number},
            as_dict=True,
        )

        # Normalize item_group: anything not under 'Products' becomes 'Others'
        for row in available_qty_data:
            parent_group = frappe.db.get_value("Item Group", row["item_group"], "parent_item_group")
            if parent_group != "Products":
                row["item_group"] = "Others"

        return available_qty_data

    except Exception:
        frappe.throw(f"Error on get_item_code_details: {frappe.get_traceback()}")
        return []


def get_inwarded_qty_by_item_group(po_number: str):
    """
    Returns a map {item_group: qty} of submitted SIR quantities
    where the SIR is created *directly* against this PO.
    (We intentionally ignore reference_po_number for subtraction.)
    """
    rows = frappe.db.sql(
        """
        SELECT irpc.item_group,
               COALESCE(SUM(irpc.actual_qty), 0) AS security_available_qty
        FROM `tabSecurity Inward Registry` sir
        INNER JOIN `tabSecurity Inward Registry Purchase Child` irpc
            ON irpc.parent = sir.name
        WHERE sir.docstatus = 1
          AND sir.total_qty > 0
          AND sir.po_number = %(po)s                -- strict match, ignore reference_po_number
        GROUP BY irpc.item_group
        """,
        {"po": po_number},
        as_dict=True,
    )
    return {r["item_group"]: float(r["security_available_qty"] or 0) for r in rows}

@frappe.whitelist()
def recieved_qty_details( received_qty, item_code, po_number, item_group, available_qty):

    if int(received_qty) > int(available_qty):
        return {'error': 'Received quantity cannot be greater than available quantity.'}
    
    if received_qty:
        part_price = frappe.db.get_value('Purchase Order Item', {'parent': po_number, 'item_code': item_code, 'item_group': item_group}, ['rate'])
        calculated_price = float(part_price) * float(received_qty)
        return {"part_price": calculated_price}

@frappe.whitelist()
def get_ste_number_item_code(doctype, txt, searchfield, start, page_len, filters):
    ste_number = filters.get("ste_number")
    material_transfer_details = frappe.db.get_all(
        "Stock Entry Detail",
        filters={'parent': ste_number},
        fields=['item_code']
    )

    filtered_data = [d['item_code'] for d in material_transfer_details]

    filters_data = [ ["name", "in", filtered_data] ]
    result_data = frappe.get_all(
        "Item",
        filters=filters_data,
        fields=["name"],
        as_list=1,
        or_filters=[ ["name", "like", f"%{txt}%"] ]
    )

    return result_data

@frappe.whitelist()
def get_item_code_details_for_transfer(ste_number):
    material_transfer_details = frappe.db.get_all(
        "Stock Entry Detail",
        filters={'parent': ste_number},
        fields=['t_warehouse', 'qty', 'item_code', 's_warehouse', 'idx', 'serial_no']
    )

    result = []

    for row in material_transfer_details:
        s_warehouse_lc = frappe.db.get_value("Warehouse", {'name': row['s_warehouse']}, ['location'])
        t_warehouse_lc = frappe.db.get_value("Warehouse", {'name': row['t_warehouse']}, ['location'])

        if not s_warehouse_lc or not t_warehouse_lc:
            result.append({
                'error': f'Warehouse location cannot be empty at row <br><b>{row["idx"]}  .{row["item_code"]} at {ste_number}</b>'
            })
            continue
        
        if s_warehouse_lc == t_warehouse_lc:
            result.append({
                'error': f'The source and target warehouse cannot have the same location at row <br><b>{row["idx"]}  .{row["item_code"]} at {ste_number}</b>'
            })
        else:
            result.append(row)

    return result


@frappe.whitelist()
def get_po_item_group(po_number):

    query = """
        SELECT 
            poi.item_group, 
            poi.item_code
        FROM 
            `tabPurchase Order Item` poi
        LEFT JOIN (
            SELECT 
                pri.item_code, SUM(pri.qty) AS total_receipt_qty
            FROM 
                `tabPurchase Receipt Item` pri
            INNER JOIN 
                `tabPurchase Receipt` pr ON pri.parent = pr.name
            WHERE 
                pri.purchase_order = %s AND pr.docstatus = 1
            GROUP BY 
                pri.item_code
        ) received_qty ON poi.item_code = received_qty.item_code
        WHERE 
            poi.parent = %s 
            AND (poi.qty > IFNULL(received_qty.total_receipt_qty, 0))
    """
    
    filtered_data = frappe.db.sql(query, (po_number, po_number), as_dict=1)

    return filtered_data


@frappe.whitelist()
def get_po_item_code(doctype, txt, searchfield, start, page_len, filters):

    filtered_data = frappe.db.sql(
        """
            SELECT item_code 
            FROM `tabPurchase Order Item` 
            WHERE parent = %s AND item_group = %s
        """,
        (filters.get('po_number'), filters.get('item_group')),
        as_dict=1  
    )

    if not filtered_data:
        return []
    
    filtered_data = [d['item_code'] for d in filtered_data]

    filters_data = [ ["name", "in", filtered_data] ]

    result_data = frappe.get_all("Item",
        filters=filters_data,
        fields=["name"],
        as_list=1,
        or_filters=[ ["name", "like", f"%{txt}%"] ]
    )
    return result_data

@frappe.whitelist()
def get_ste_number(doctype, txt, searchfield, start, page_len, filters):

    filtered_data = frappe.db.sql(
        """
            SELECT name from `tabStock Entry`
            WHERE stock_entry_type = %s
        """,(filters.get('stock_entry_type')),as_dict=1 )
    
    filtered_data = [ d['name'] for d in filtered_data ]
    filters_data  = [ ["name", "in", filtered_data] ]
    result_data = frappe.get_all("Stock Entry", 
        filters=filters_data,
        fields=["name"],
        as_list=1,
        or_filters=[ ["name", "like", f"%{txt}%"] ]
    )

    return result_data

@frappe.whitelist()
def get_target_warehouse(doctype, txt, searchfield, start, page_len, filters):
    source_warehouse = filters.get('source_warehouse', '')

    if source_warehouse:
        sr_location = frappe.db.get_value('Warehouse', {'name': source_warehouse}, ['location'])

    filtered_data = frappe.db.sql(
        """ SELECT name
            FROM `tabWarehouse` 
            WHERE location NOT IN (
                SELECT location 
                FROM `tabWarehouse` 
                WHERE name = %s
            ) """, (source_warehouse,), as_dict=1
    )

    filtered_data = [ d['name'] for d in filtered_data ]  

    filtered_data = [ ["name", "in", filtered_data] ]

    result_data = frappe.get_all("Warehouse", 
        filters=filtered_data,
        fields=["name"],
        as_list=1,
        or_filters=[ ["name", "like", f"%{txt}%"] ]
    )

    return result_data


@frappe.whitelist()
def get_registry_qty(frm):
    if isinstance(frm, str):
        frm = json.loads(frm)

    valid_table_name = get_child_table(frm)

    if(frm.get('registry_type') == 'Accept Registry'):
        if valid_table_name:
            query = """
                SELECT item_group, warehouse, item_code, SUM(actual_qty) AS qty 
                FROM `{}` 
                WHERE parent = %s AND docstatus = 1 
                GROUP BY item_code
            """.format(valid_table_name)

            out = frappe.db.sql(query, (frm.get('name'),), as_dict=True)

            if out:
                return out
    else:
        if valid_table_name:
            query = """
                SELECT item_group, warehouse, SUM(actual_qty) AS qty 
                FROM `{}` 
                WHERE parent = %s AND docstatus = 1 
                GROUP BY item_group
            """.format(valid_table_name)

            out = frappe.db.sql(query, (frm.get('name'),), as_dict=True)

            if out:
                return out

    return None

@frappe.whitelist()
def get_stock_registry(stock_registry_no):
    try:
        get_po_number = frappe.db.get_value('Security Inward Registry', stock_registry_no, 'po_number')
        stock_details = frappe.db.sql("""
            SELECT  
                poi.item_group, 
                poi.item_code, 
                poi.qty,
                poi.idx,
                sir.name AS reference_name, 
                sir.po_number AS po_number
            FROM `tabSecurity Inward Registry` sir
            INNER JOIN `tabPurchase Order Item` poi ON sir.po_number = poi.parent
            INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
            WHERE sir.name = %s
        """, (stock_registry_no,), as_dict=True)

        for row in stock_details:
            po_qty = frappe.db.get_value(
                'Purchase Order Item',
                {'parent': row.po_number, 'item_code': row.item_code, 'item_group': row.item_group, 'idx': row.idx},
                ['qty']
            )

            total_received_qty = frappe.db.sql("""
                SELECT SUM(pri.qty) 
                FROM 
                    `tabPurchase Receipt Item` pri
                INNER JOIN 
                    `tabPurchase Receipt` pr ON pri.parent = pr.name
                WHERE 
                    pri.purchase_order = %s 
                    AND pri.item_code = %s AND pri.idx = %s 
                    AND pr.docstatus = 1
            """, (row.po_number, row.item_code, row.idx))[0][0] or 0 

            available_qty = float(po_qty) - float(total_received_qty)

            row['available_qty'] = available_qty

        dash_board_data = frappe.db.sql("""
                                        SELECT * from `tabSecurity Inward Registry Purchase Child`
                                        WHERE parent = %s
                                    """, (stock_registry_no,), as_dict=True)
        
        if not stock_details:
            frappe.throw(f"No records found for Stock Registry {stock_registry_no}")

        for row in stock_details:
            parent_item_group = frappe.db.get_value('Item Group', row['item_group'], 'parent_item_group')
            if parent_item_group != 'Products':
                row['reference_item_group'] = 'Others'
            else:
                row['reference_item_group'] = row['item_group']
        
        return stock_details, dash_board_data, get_po_number

    except Exception as e:
        frappe.throw(f"Error fetching stock registry details: {str(e)}")

@frappe.whitelist()
def get_total_qty(doctype, docname):
    try:
        sir = frappe.get_doc(doctype, docname)
        return sir.get_total_qty()
    
    except Exception as e:
        frappe.throw(f"Error on submit: {str(e)}")
        return None
    
@frappe.whitelist()
def get_registry_in_warehouse(po_number=None):
    try:
        emp_data = get_active_emp(frappe.session.user)

        warehouse = emp_data.get('work_warehouse')
        registry_data_query = """
            (SELECT parent
            FROM `tabSecurity Inward Registry Child`
            WHERE warehouse = %(warehouse)s AND actual_qty > 0 AND docstatus = 1 AND reference_po_number = %(po_number)s)
            
            UNION
            
            (SELECT parent
            FROM `tabSecurity Inward Registry Transfer Child`
            WHERE warehouse = %(warehouse)s AND actual_qty > 0 AND docstatus = 1 AND reference_po_number = %(po_number)s)
        """
            
        stock_data = frappe.db.sql(registry_data_query, {'warehouse': warehouse, 'po_number': po_number}, as_dict=True)

        return stock_data
    except Exception as e:
        traceback_info = traceback.format_exc()
        frappe.throw(f"Error on submit: {str(e)}\n{traceback_info}")
        return traceback_info

@frappe.whitelist()
def get_customer_return_details(tracking_id):
    if not tracking_id or not str(tracking_id).strip():
        frappe.throw(_("Please enter a valid Tracking ID."))

    tracking_id = str(tracking_id).strip()

    # 1. Search in Delivery Note:
    # Only submitted (docstatus == 1), skip return (is_return == 0), skip draft and cancelled
    dns = frappe.db.get_all(
        "Delivery Note",
        filters={
            "tracking_id": tracking_id,
            "docstatus": 1,
            "is_return": 0
        },
        fields=["name"],
        order_by="creation desc"
    )

    if dns:
        dn_name = dns[0].name

        items = frappe.db.get_all(
            "Delivery Note Item",
            filters={"parent": dn_name},
            fields=["name", "item_code", "qty", "against_sales_order", "serial_no"]
        )

        packed_items = frappe.db.get_all(
            "Packed Item",
            filters={"parent": dn_name},
            fields=["name", "parent_item", "item_code", "qty", "serial_no", "parent_detail_docname"]
        )

        results = []
        item_by_name = {it.name: it for it in items}
        item_by_code = {it.item_code: it for it in items}
        first_so = next((it.against_sales_order for it in items if it.against_sales_order), None)

        packed_serials_found = False
        for pi in packed_items:
            pi_serials = [s.strip() for s in re.split(r"[\r\n,]+", pi.serial_no or "") if s.strip()]
            if pi_serials:
                packed_serials_found = True
                parent_dni = item_by_name.get(pi.parent_detail_docname) or item_by_code.get(pi.parent_item)
                so = parent_dni.against_sales_order if parent_dni and parent_dni.against_sales_order else first_so
                for s in pi_serials:
                    results.append({
                        "tracking_id": tracking_id,
                        "sales_order": so,
                        "item_code": pi.item_code,
                        "qty": 1,
                        "serial_no": s,
                        "reference_doctype": "Delivery Note",
                        "reference_name": dn_name
                    })

        item_serials_found = False
        for item in items:
            item_serials = [s.strip() for s in re.split(r"[\r\n,]+", item.serial_no or "") if s.strip()]
            if item_serials:
                item_serials_found = True
                for s in item_serials:
                    results.append({
                        "tracking_id": tracking_id,
                        "sales_order": item.against_sales_order,
                        "item_code": item.item_code,
                        "qty": 1,
                        "serial_no": s,
                        "reference_doctype": "Delivery Note",
                        "reference_name": dn_name
                    })

        # If neither packed_items nor items had serials, fallback to items
        if not packed_serials_found and not item_serials_found:
            for item in items:
                results.append({
                    "tracking_id": tracking_id,
                    "sales_order": item.against_sales_order,
                    "item_code": item.item_code,
                    "qty": abs(item.qty) if item.qty else 1,
                    "serial_no": None,
                    "reference_doctype": "Delivery Note",
                    "reference_name": dn_name
                })

        _validate_no_prior_submitted_sir(results)
        return results

    # 2. Search in Bold Desk History (reverse_awb)
    # Fetch details directly from Bold Desk History (not from DN)
    bdh_list = frappe.db.get_all(
        "Bold Desk History",
        filters={"reverse_awb": tracking_id},
        fields=["name", "ticket_id", "serial_no", "sales_order", "product_description", "product_item_code", "replacement_serial"]
    )

    if bdh_list:
        results = []
        for bdh in bdh_list:
            so = bdh.sales_order
            item_code = (bdh.product_description or bdh.product_item_code or "").strip()
            serials_str = (bdh.serial_no or bdh.replacement_serial or "").strip()
            serials = [s.strip() for s in re.split(r"[\r\n,]+", serials_str) if s.strip()]

            if serials:
                for s in serials:
                    results.append({
                        "tracking_id": tracking_id,
                        "sales_order": so,
                        "item_code": item_code,
                        "qty": 1,
                        "serial_no": s,
                        "reference_doctype": "Bold Desk History",
                        "reference_name": bdh.name
                    })
            else:
                results.append({
                    "tracking_id": tracking_id,
                    "sales_order": so,
                    "item_code": item_code,
                    "qty": 1,
                    "serial_no": None,
                    "reference_doctype": "Bold Desk History",
                    "reference_name": bdh.name
                })

        _validate_no_prior_submitted_sir(results)
        return results

    # 3. Not found in either
    frappe.throw(_(f"Tracking ID '{tracking_id}' not found in Delivery Note or Bold Desk History."))

def _validate_no_prior_submitted_sir(items):
    for res in items:
        if res.get("serial_no"):
            existing = frappe.db.sql("""
                SELECT parent
                FROM `tabCustomer Return for Security Inward Registry`
                WHERE serial_no = %s AND docstatus = 1
            """, (res["serial_no"],), as_dict=True)
            if existing:
                frappe.throw(_(f"Serial No '{res['serial_no']}' is already inwarded in submitted Security Inward Registry {existing[0].parent}."))