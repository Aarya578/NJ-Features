# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
import traceback
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, date_diff
from nj_lib.utils.common_utils import get_active_emp

class SecurityInwardRegistry(Document):
    def on_submit(self):
        try:
            self.update_transfer_qty(state='submit')
            self.get_total_qty()

        except Exception as e:

            traceback_info = traceback.format_exc()
            frappe.throw(f"Error on submit: {str(e)}\n{traceback_info}") 
            frappe.db.rollback()

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
def get_po_number_details(po_number):
    try:
        po_creation_date = frappe.db.get_value('Purchase Order', {'name': po_number}, ['creation'])
        
        if not po_creation_date:
            return {'error': f'Purchase Order {po_number} does not exist.'}

        current_date = now_datetime()
        po_restriction_days = frappe.db.get_single_value('NewJaisa Configuration', 'po_restriction_days')

        days_difference = date_diff(current_date.date(), po_creation_date.date())
        if days_difference > int(po_restriction_days):
            return {'error': f'{po_restriction_days} days expired for this Purchase Order'}
        
        grouped_data = {}
        
        row_res = get_item_code_details(po_number)

        for item in row_res:
            item_group = item['item_group']
            total_qty = item['available_qty']

            if item_group in grouped_data:
                grouped_data[item_group] += total_qty
            else:
                grouped_data[item_group] = total_qty

            purchase_inward_security_result = [
                {'item_group': k, 'available_qty': v} for k, v in grouped_data.items()
            ]

        purchase_inward_security_result = get_inwarded_qty_data(po_number, purchase_inward_security_result)
        purchase_inward_security_result = get_sir_inwarded_qty_data(po_number, purchase_inward_security_result)

        return purchase_inward_security_result

    except Exception as e:
        traceback_info = frappe.get_traceback()
        frappe.throw(f"Error on get_po_number_details: {str(e)}\n{traceback_info}")
        return None

def get_inwarded_qty_data(po_number, purchase_inward_security_result):
    query = """
        SELECT irpc.item_group, SUM(irpc.actual_qty) AS available_qty
        FROM `tabSecurity Inward Registry` sir
        INNER JOIN `tabSecurity Inward Registry Purchase Child` irpc
        ON irpc.parent = sir.name
        WHERE sir.po_number = %s AND sir.docstatus = 1 AND sir.total_qty > 0
        GROUP BY irpc.item_group
    """
    
    result = frappe.db.sql(query, po_number, as_dict=True)

    for initial in purchase_inward_security_result:
        item_group = initial['item_group']
        initial_qty = initial['available_qty']

        fetched_qty = next((r['available_qty'] for r in result if r['item_group'] == item_group), 0)
        
        initial['available_qty'] = initial_qty - fetched_qty
    
    return purchase_inward_security_result

def get_sir_inwarded_qty_data(po_number, purchase_inward_security_result):
    query = """
        SELECT irpc.item_group, SUM(irpc.received_qty) AS available_qty
        FROM `tabSecurity Inward Registry` sir
        INNER JOIN `tabSIR Inwarded Quantity` irpc
        ON irpc.parent = sir.name
        WHERE sir.reference_po_number = %s 
        AND sir.docstatus = 1 
        AND sir.total_qty > 0
        GROUP BY irpc.item_group
    """
    
    result = frappe.db.sql(query, (po_number,), as_dict=True)

    for initial in purchase_inward_security_result:
        item_group = initial['item_group']
        initial_qty = initial['available_qty']

        fetched_qty = next((r['available_qty'] for r in result if r['item_group'] == item_group), 0)
        
        initial['available_qty'] = max(0, initial_qty - fetched_qty)

    return purchase_inward_security_result


def get_item_code_details(po_number):
    try:
        available_qty_data = frappe.db.sql("""
            SELECT 
                poi.item_group, 
                poi.item_code, 
                SUM(poi.qty) - IFNULL(SUM(pri.qty), 0) AS available_qty
            FROM 
                `tabPurchase Order Item` poi
            LEFT JOIN 
                `tabPurchase Receipt Item` pri ON poi.item_code = pri.item_code 
                AND pri.purchase_order = poi.parent AND pri.docstatus = 1
            LEFT JOIN 
                `tabPurchase Receipt` pr ON pri.parent = pr.name AND pr.docstatus = 1
            WHERE 
                poi.parent = %s
            GROUP BY 
                poi.item_group, poi.item_code
        """, (po_number,), as_dict=1)

        for row in available_qty_data:
            parent_item_group = frappe.db.get_value('Item Group', row['item_group'], 'parent_item_group')
            if parent_item_group != 'Products':
                row['item_group'] = 'Others'

        return available_qty_data

    except Exception as e:
        traceback_info = frappe.get_traceback()
        frappe.throw(f"Error on get_item_code_details: {str(e)}\n{traceback_info}")
        return None

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
                {'parent': row.po_number, 'item_code': row.item_code, 'item_group': row.item_group},
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
                    AND pri.item_code = %s 
                    AND pr.docstatus = 1
            """, (row.po_number, row.item_code))[0][0] or 0 

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