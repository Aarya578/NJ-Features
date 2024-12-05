# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, date_diff

class SecurityInwardRegistry(Document):
    def on_submit(self):
        pass

    def on_cancel(self):
        pass

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
def get_item__code_details(po_number,item_code,  item_group):
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

    if received_qty > available_qty:
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

    filters_data = [
        ["name", "in", filtered_data],
    ]
    result_data = frappe.get_all(
        "Item",
        filters=filters_data,
        fields=["name"],
        as_list=1,
        or_filters=[
            ["name", "like", f"%{txt}%"]
        ]
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
            result.append(
                {
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

    filters_data = [
        ["name", "in", filtered_data],
    ]

    result_data = frappe.get_all("Item",
        filters=filters_data,
        fields=["name"],
        as_list=1,
        or_filters=[
            ["name", "like", f"%{txt}%"]
        ]
    )
    return result_data

@frappe.whitelist()
def get_ste_number(doctype, txt, searchfield, start, page_len, filters):

    filtered_data = frappe.db.sql(
        """
            SELECT name from `tabStock Entry`
            WHERE stock_entry_type = %s
        """,(filters.get('stock_entry_type')),as_dict=1 )
    
    filtered_data = [d['name'] for d in filtered_data]
    filters_data  = [
        ["name", "in", filtered_data],
    ]
    result_data = frappe.get_all("Stock Entry", 
        filters=filters_data,
        fields=["name"],
        as_list=1,
        or_filters=[
            ["name", "like", f"%{txt}%"]
        ]
    )

    return result_data

@frappe.whitelist()
def get_target_warehouse(doctype, txt, searchfield, start, page_len, filters):
    source_warehouse = filters.get('source_warehouse', '')

    if source_warehouse:
        sr_location = frappe.db.get_value('Warehouse', {'name': source_warehouse}, ['location'])

    filtered_data = frappe.db.sql(
        """
            SELECT name
            FROM `tabWarehouse` 
            WHERE location NOT IN (
                SELECT location 
                FROM `tabWarehouse` 
                WHERE name = %s
            )
        """,
        (source_warehouse,), as_dict=1
    )

    filtered_data = [d['name'] for d in filtered_data]  

    filtered_data = [
        ["name", "in", filtered_data],
    ]

    result_data = frappe.get_all("Warehouse", 
        filters=filtered_data,
        fields=["name"],
        as_list=1,
        or_filters=[
            ["name", "like", f"%{txt}%"]
        ]
    )

    return result_data


@frappe.whitelist()
def get_registry_qty(name, child_table):
    valid_table_name = frappe.db.escape(child_table).strip("'")

    query = "SELECT item_code, warehouse, SUM(actual_qty) AS qty FROM `{}` WHERE parent = %s and docstatus = 1 GROUP BY item_code".format(valid_table_name)

    out = frappe.db.sql(query, (name,), as_dict=True)

    if out:
        return out
    return None

@frappe.whitelist()
def get_stock_registry(stock_registry_no):
    try:
        registry_data_query = """
        (SELECT Date(creation) as date, item_code, actual_qty as qty, warehouse
        FROM `tabSecurity Inward Registry Child`
        WHERE parent = %s AND actual_qty > 0)
        
        UNION
        
        (SELECT Date(creation) as date, item_code, actual_qty as qty, warehouse
        FROM `tabCustomer Return for Security Inward Registry`
        WHERE parent = %s AND actual_qty > 0)
        
        UNION
        
        (SELECT Date(creation) as date, item_code, actual_qty as qty, warehouse
        FROM `tabSecurity Inward Registry Transfer Child`
        WHERE parent = %s AND actual_qty > 0)
        """
        
        stock_data = frappe.db.sql(registry_data_query, (stock_registry_no, stock_registry_no, stock_registry_no), as_dict=True)

        return stock_data
    
    except Exception as e:
        frappe.throw("Error in get_stock_registry ", e)