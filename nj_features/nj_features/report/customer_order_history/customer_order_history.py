import frappe
from frappe import _

def get_columns():
    return [
        {"label": _("Serial No"), "fieldname": "serial_no", "fieldtype": "Link", "options": "Serial No"},
        {"label": _("Delivery Note"), "fieldname": "delivery_note", "fieldtype": "Link", "options": "Delivery Note"},
        {"label": _("DN Created On"), "fieldname": "creation", "fieldtype": "DateTime"},
        {"label": _("Sales Order"), "fieldname": "against_sales_order", "fieldtype": "Link", "options": "Sales Order"},
        {"label": _("Amazon Order ID"), "fieldname": "amazon_order_id", "fieldtype": "Data"},
        {"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier"},
        {"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item"},
        {"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group"}
    ]

def get_data(filters):
    conditions = []
    params = {}

    if filters.get("serial_no"):
        conditions.append("dni.serial_no = %(serial_no)s")
        params["serial_no"] = filters["serial_no"]
        
    if filters.get("delivery_note"):
        conditions.append("dn.name = %(delivery_note)s")
        params["delivery_note"] = filters["delivery_note"]
        
    if filters.get("sales_order"):
        conditions.append("so.name = %(sales_order)s")
        params["sales_order"] = filters["sales_order"]
        
    if filters.get("order_id"):
        order_id_fields = [
            'so.shopify_order_id',
            'so.ebay_order_id',
            'so.ebaytwo_order_id',
            'so.amazon_order_id',
            'so.shopclues_order_id',
            'so.flipkart_order_id',
            'so.order_id'
        ]
        order_condition = " OR ".join([f"{field} = %(order_id)s" for field in order_id_fields])
        params["order_id"] = filters["order_id"]
    else:
        order_condition = "1=1"

    conditions_str = " AND ".join(conditions) if conditions else "1=1"

    query = f"""
        SELECT 
            dni.serial_no AS serial_no,
            dn.name AS delivery_note,
            dn.creation AS creation,
            dni.against_sales_order AS against_sales_order,
            so.amazon_order_id AS amazon_order_id,
            sn.supplier_name AS supplier,
            dni.item_code AS item_code,
            sn.item_group AS item_group
        FROM 
            `tabDelivery Note` dn
        INNER JOIN 
            `tabDelivery Note Item` dni ON dni.parent = dn.name
        INNER JOIN 
            `tabSales Order` so ON so.name = dni.against_sales_order AND ({order_condition})
        INNER JOIN 
            `tabSerial No` sn ON sn.name = dni.serial_no
        WHERE dn.docstatus = 1 AND {conditions_str}
        ORDER BY
            dn.creation DESC
    """

    data = frappe.db.sql(query, params, as_dict=True)
    return data

def execute(filters): 
    if not any(filters.get(key) for key in ["serial_no", "delivery_note", "sales_order", "order_id"]):
        columns, data = [], []
    else:
        columns = get_columns()
        data = get_data(filters)
    return columns, data