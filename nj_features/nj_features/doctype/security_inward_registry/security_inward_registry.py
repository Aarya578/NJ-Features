# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
import traceback
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

        if state == 'cancel':
            if self.get('transfer_registry') and len(self.get('transfer_registry')):
                for item in self.get('transfer_registry'):

                    registry_select_query = """SELECT actual_qty as qty
                        FROM `{}` WHERE name = %s and parent = %s and docstatus = 1""".format(item.get('reference_doctype'))

                    if item.get('reference_name') and item.get('reference_parent') and item.get('reference_doctype'):

                        registry_select_qty = frappe.db.sql(registry_select_query, (
                            item.get('reference_name'),  # child name
                            item.get('reference_parent')  # SIR name
                        ), debug=0, explain=0)
                        
                        if registry_select_qty and registry_select_qty[0][0]:
                            remaining_qty = int(registry_select_qty[0][0]) + int(item.get('actual_qty'))
                        else:
                            remaining_qty = int(item.get('actual_qty')) 


                        registry_update_query = """UPDATE `{}` SET actual_qty = %s
                            WHERE name = %s and parent = %s and docstatus = 1""".format(item.get('reference_doctype'))

                        registry_update = frappe.db.sql(registry_update_query, (
                            remaining_qty,
                            item.get('reference_name'),
                            item.get('reference_parent')
                        ), debug=0, explain=0)

        elif state == 'submit':
            if self.registry_type == 'Accept Registry':
                for item in self.get('transfer_registry'):
                    
                    registry_select_query_with_ref = """SELECT actual_qty as qty
                        FROM `{}` WHERE parent = %s and reference_name = %s 
                        and reference_parent = %s and docstatus = 1""".format(item.get('reference_doctype'))

                    registry_select_qty = frappe.db.sql(registry_select_query_with_ref, (
                        self.get('name'),  # parent
                        item.get('reference_name'),
                        item.get('reference_parent')
                    ), debug=0, explain=0)

                    if registry_select_qty and registry_select_qty[0][0]:
                        remaining_qty = int(registry_select_qty[0][0]) - int(item.get('actual_qty'))
                    else:
                        remaining_qty = 0

                    registry_update_query = """UPDATE `{}` SET actual_qty = %s
                        WHERE name = %s and parent = %s and docstatus = 1""".format(item.get('reference_doctype'))

                    registry_update = frappe.db.sql(registry_update_query, (
                        remaining_qty,
                        item.get('reference_name'),
                        item.get('reference_parent')
                    ), debug=0, explain=0)

    def get_total_qty(self):
        try:
            total_qty = 0

            if self.transfer_registry and len(self.transfer_registry)>0:
                for item in self.transfer_registry:
                    total_qty += int(item.actual_qty)
            
            if self.purchase_inward_registry and len(self.purchase_inward_registry)>0:
                for item in self.purchase_inward_registry:
                    total_qty += int(item.actual_qty)
            
            if self.customer_return_registry and len(self.customer_return_registry)>0:
                for item in self.customer_return_registry:
                    total_qty += int(item.actual_qty)

            self.db_set("total_qty", total_qty)
        
        except Exception as e:
            traceback_info = traceback.format_exc()
            frappe.throw(f"Error on get_total_qty: {str(e)}\n{traceback_info}")
            return None

def get_child_table(frm):
    valid_table_name = None

    if isinstance(frm, dict):
        if frm.get('purchase_inward_registry') and len(frm['purchase_inward_registry']) > 0:
            valid_table_name = frm['purchase_inward_registry'][0].get('doctype')

        elif frm.get('customer_return_registry') and len(frm['customer_return_registry']) > 0:
            valid_table_name = frm['customer_return_registry'][0].get('doctype')

        elif frm.get('transfer_registry') and len(frm['transfer_registry']) > 0:
            valid_table_name = frm['transfer_registry'][0].get('doctype')
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
    po_creation_date = frappe.db.get_value('Purchase Order', {'name': po_number}, ['creation'])

    purchase_inward_security_result = []
    
    if not po_creation_date:
        return {'error': f'Purchase Order {po_number} does not exist.'}

    current_date = now_datetime()

    days_difference = date_diff(current_date.date(), po_creation_date.date())
    if not days_difference > 14:
        result = get_po_item_group(po_number)

        for row in result:
            row_res = get_item__code_details(po_number, row['item_code'], row['item_group'])
            purchase_inward_security_result.append(row_res)

        return purchase_inward_security_result
    else:
        return {'error': '14 days expired for this Purchase Order'}



@frappe.whitelist()
def get_item_code_details(po_number, item_code, item_group):
    po_qty = frappe.db.get_value(
        'Purchase Order Item',
        {'parent': po_number, 'item_code': item_code, 'item_group': item_group},
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
    """, (po_number, item_code))[0][0] or 0 
    
    available_qty = float(po_qty) - float(total_received_qty)

    available_qty_in_sir_query = """
        SELECT actual_qty FROM `tabSecurity Inward Registry Transfer Child`
        WHERE po_no = %s AND item_code = %s AND docstatus = 1 AND actual_qty > 0 AND item_group = %s
        ORDER BY creation DESC, modified DESC LIMIT 1
    """

    available_qty_in_sir = frappe.db.sql(available_qty_in_sir_query, (po_number, item_code, item_group), as_dict=True)

    if available_qty_in_sir:
        available_qty = available_qty -float(available_qty_in_sir[0].get('actual_qty'))

    if available_qty < 0:
        available_qty = 0

    return {
        "item_code": item_code,
        "item_group": item_group,
        "po_qty": po_qty,
        "available_qty": available_qty
    }

@frappe.whitelist()
def recieved_qty_details(po_number, item_code, item_group, received_qty, available_qty):

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
        fields=['t_warehouse', 'qty', 'item_code', 's_warehouse', 'idx']
    )

    result = []

    for row in material_transfer_details:
        s_warehouse_lc = frappe.db.get_value("Warehouse", {'name': row['s_warehouse']}, ['location'])
        t_warehouse_lc = frappe.db.get_value("Warehouse", {'name': row['t_warehouse']}, ['location'])

        if s_warehouse_lc == t_warehouse_lc:
            result.append({
                'error': f'The source warehouse and target warehouse cannot have the same location at  row {row["idx"]}:{row["item_code"]}</b>'
            })
        else:
            result.append(row)

    return result

@frappe.whitelist()
def get_po_item_group(po_number):

    query = """
        SELECT poi.item_group, poi.item_code
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

    if valid_table_name:
        query = """
            SELECT item_code, warehouse, SUM(actual_qty) AS qty 
            FROM `{}` 
            WHERE parent = %s AND docstatus = 1 
            GROUP BY item_code
        """.format(valid_table_name)

        out = frappe.db.sql(query, (frm.get('name'),), as_dict=True)

        if out:
            return out

    return None

@frappe.whitelist()
def get_stock_registry(stock_registry_no):
    try:
        po_number = frappe.db.get_value("Security Inward Registry", stock_registry_no, "po_number")

        registry_data_query = """
            (SELECT name as reference_name, parent as reference_parent, Date(creation) as date,
            item_code, actual_qty as qty, warehouse, 'tabSecurity Inward Registry Child' as reference_doctype
            FROM `tabSecurity Inward Registry Child`
            WHERE parent = %(stock_registry_no)s AND actual_qty > 0)
            
            UNION
            
            (SELECT name as reference_name, parent as reference_parent, Date(creation) as date,
            item_code, actual_qty as qty, warehouse, 'tabCustomer Return for Security Inward Registry' as reference_doctype
            FROM `tabCustomer Return for Security Inward Registry`
            WHERE parent = %(stock_registry_no)s AND actual_qty > 0)
            
            UNION
            
            (SELECT name as reference_name, parent as reference_parent, Date(creation) as date,
            item_code, actual_qty as qty, warehouse, 'tabSecurity Inward Registry Transfer Child' as reference_doctype
            FROM `tabSecurity Inward Registry Transfer Child`
            WHERE parent = %(stock_registry_no)s AND actual_qty > 0)
        """
        
        stock_data = frappe.db.sql(registry_data_query, {'stock_registry_no': stock_registry_no}, as_dict=True)

        return_data = {"stock_data": stock_data }

        if po_number:
            return_data.update({"po_number": po_number})

        return return_data
    
    except Exception as e:
        frappe.throw("Error in get_stock_registry ", e)

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
            WHERE warehouse = %(warehouse)s AND actual_qty > 0 AND docstatus = 1 AND po_no = %(po_number)s)
            
            UNION
            
            (SELECT parent
            FROM `tabSecurity Inward Registry Transfer Child`
            WHERE warehouse = %(warehouse)s AND actual_qty > 0 AND docstatus = 1 AND po_no = %(po_number)s)
        """
            
        stock_data = frappe.db.sql(registry_data_query, {'warehouse': warehouse, 'po_number': po_number}, as_dict=True)

        return stock_data
    except Exception as e:
        traceback_info = traceback.format_exc()
        frappe.throw(f"Error on submit: {str(e)}\n{traceback_info}")
        return traceback_info