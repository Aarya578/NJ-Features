# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt



import frappe

# getting unique model no
@frappe.whitelist()
def get_unique_models():
    """Fetch distinct model numbers from Serial No table"""
    records = frappe.db.get_all(
        "Serial No",
        fields=["model"],
        distinct=True,
        pluck="model"
    )
    return [r for r in records if r]  



# total purchase price for all active laptops of a given model
@frappe.whitelist()
def get_total_purchase_price(model_no):
    total = frappe.db.sql("""
        SELECT SUM(purchase_price)
        FROM `tabSerial No`
        WHERE model = %s AND status = 'Active'
    """, (model_no,))[0][0]
    return total or 0


@frappe.whitelist()
def get_serial_no_data(model_no):
    query = """
        SELECT name from `tabSerial No`
        WHERE model = %s AND status='Active'
    """
    result = frappe.db.sql(query, (model_no,), as_dict=True)
    frappe.logger().info(f"Serial No Component data: {result}")
    serial_nos = [s["name"] for s in result]
    

@frappe.whitelist()
def get_serial_item_grade_price(model_no):
    query = """
        SELECT
            sn.name AS serial_no,
            comp.item_group AS item,
            comp.grade AS grade,
            ig.default_item_group_price AS price
        FROM `tabSerial No` sn
        LEFT JOIN `tabSerial No Component` comp
            ON sn.name = comp.parent
        LEFT JOIN `tabItem Group` ig
            ON comp.item_group= ig.name
        WHERE sn.model = %s
            AND sn.status = 'Active'
    """
    result = frappe.db.sql(query, (model_no,), as_dict=True)
    frappe.logger().info(f"Fetched serial/item/grade/price for model {model_no}: {result}")
    return result


    