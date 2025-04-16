# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt
from frappe.model.document import Document

class LaptopAllocation(Document):
    pass

@frappe.whitelist()
def allocate_laptop_parts():
    latest_doc_name = frappe.get_all(
        "NJ Production Planning",
        fields=["name"],
        order_by="creation desc",
        limit=1
    )

    if not latest_doc_name:
        frappe.throw("No Production Planning document found.")

    latest_doc = frappe.get_doc("NJ Production Planning", latest_doc_name[0].name)

    serial_list = []
    for row in latest_doc.get("suggested_serial_no"):
        if row.suggested_serial_no:
            serial_list.extend([s.strip() for s in row.suggested_serial_no.split(",") if s.strip()])

    if not serial_list:
        frappe.msgprint("No suggested serial numbers found in the latest production planning.")
        return []

    mr_items = frappe.db.sql("""
        SELECT parent AS material_request, item_code, serial_no AS against_serial_no, 
               stock_qty, qty AS mr_qty, item_group
        FROM `tabMaterial Request Item` 
        WHERE post_order_status IN ("Not Completed", " ") 
        AND serial_no IN %(serial_list)s
    """, {"serial_list": tuple(serial_list)}, as_dict=True)

    if not mr_items:
        frappe.msgprint("No Material Requests found for the suggested serial numbers.")
        return []

    warehouses = frappe.db.get_all("Warehouse", filters={"department": "Stores - NJ"}, pluck="name")
    if not warehouses:
        frappe.msgprint("No warehouses found under 'Stores - NJ' department.")
        return []

    # Fetch actual stock per item
    stock_data = {}
    stock_results = frappe.db.sql("""
        SELECT item_code, SUM(actual_qty) AS total_qty 
        FROM `tabBin` 
        WHERE warehouse IN %s 
        GROUP BY item_code
    """, (tuple(warehouses),), as_dict=True)

    for stock in stock_results:
        stock_data[stock["item_code"]] = flt(stock["total_qty"])

    virtual_stock_data = stock_data.copy()

    grouped_by_serial = {}

    for item in mr_items:
        serial_no = item["against_serial_no"]
        item_code = item["item_code"]
        mr_qty = flt(item["mr_qty"])
        available_stock = virtual_stock_data.get(item_code, 0)

        if available_stock >= mr_qty:
            allocated_status = "Allocated"
            status = "Available" if available_stock > 0 else "Not Available"

            row = {
                "material_request": item["material_request"],
                "item_code": item_code,
                "item_group": item["item_group"],
                "against_serial_no": serial_no,
                "mr_qty": mr_qty,
                "available_stock": available_stock,
                "status": status,
                "allocated_status": allocated_status
            }

            grouped_by_serial.setdefault(serial_no, []).append(row)

            virtual_stock_data[item_code] -= mr_qty

        else:
            res_item = allocated_other_part(item)

            if res_item:
                item_code_res = res_item.get("item_code")
                against_item_code = res_item.get("against_item_code")
                available_stock = flt(res_item.get("stock_qty", 0))

                if available_stock >= mr_qty:
                    allocated_status = "Allocated"
                else:
                    allocated_status = "Not Allocated"
            else:
                allocated_status = "Not Allocated"
                item_code_res = item_code
                against_item_code = ""
                available_stock = 0

            status = "Available" if available_stock > 0 else "Not Available"

            row = {
                "material_request": item["material_request"],
                "item_code": item_code_res,
                "item_group": item["item_group"],
                "against_serial_no": serial_no,
                "mr_qty": mr_qty,
                "available_stock": available_stock,
                "status": status,
                "allocated_status": allocated_status,
                "against_item_code": against_item_code
            }

            grouped_by_serial.setdefault(serial_no, []).append(row)

            if res_item:
                if item_code_res in virtual_stock_data:
                    virtual_stock_data[item_code_res] -= mr_qty

    # Only keep serials where all items are allocated
    final_result = []
    for serial_no, items in grouped_by_serial.items():
        if all(item["allocated_status"] == "Allocated" for item in items):
            final_result.extend(items)

    # ✅ Sort result to group all by serial number and material_request
    from operator import itemgetter
    final_result.sort(key=itemgetter("against_serial_no", "material_request"))

    print("final_result ---------------- ", final_result)
    return final_result

def allocated_other_part(item):
    print("\n\nitem ------------------ ", item)

    item_code = item.get("item_code")
    if not item_code:
        frappe.throw("Item Code is missing.")

    # Prepare query for one or more item codes (currently using just one)
    item_codes = [item_code]
    placeholders = ', '.join(['%s'] * len(item_codes))

    query = f"""SELECT 
                    LOWER(iva.attribute) AS item_attribute, 
                    LOWER(iva.attribute_value) AS attribute_value,
                    iva.parent AS item_code,
                    i.item_name,
                    i.item_model,
                    i.item_group,
                    i.variant_of AS parent
                FROM `tabItem Variant Attribute` iva
                INNER JOIN `tabItem` i ON iva.parent = i.name
                WHERE iva.parent IN ({placeholders})"""

    attribute_data = frappe.db.sql(query, tuple(item_codes), as_dict=True)
    attribute_data_info = {item['item_attribute']: item['attribute_value'] for item in attribute_data}
    print("attribute_data -------------------- ", attribute_data_info)

    item_wizard_name = frappe.db.get_value("Serial No", {'name': item.get("against_serial_no")}, 'item_wizard')
    # print("item_wizard_name", item_wizard_name)

    if not item_wizard_name:
        frappe.throw(f"Item Wizard not found for serial no: {item.get('against_serial_no')}")

    item_wizard_doc = frappe.get_doc("Item Wizards", item_wizard_name)
    # print("item_wizard_doc ------------ ", item_wizard_doc)

    for row in item_wizard_doc.get("items_attribute"):
            # print("row -------------- ", row.as_dict())
            for attr in attribute_data:
                if row.get("item_group", "").lower() in [attr.get("item_group", "").lower()] and row.get("item_attribute", "").lower() != "grade":
                    # print("attr -------------- ", row.get("item_attribute", "").lower(),  attr.get("item_attribute", "").lower())
                    # print("attr -------------- ", row.get("attribute_value", "").lower(), attr.get("attribute_value", "").lower())
                    if attr.get("item_attribute", "").lower() == row.get("item_attribute", "").lower() and \
                            attr.get("attribute_value", "").lower() != row.get("attribute_value", "").lower():

                        # print("\n\ninside_row -------------- ", row.as_dict())

                        attribute_data_info.update({
                            row.get("item_attribute", "").lower(): row.get("attribute_value", "").lower()
                        })

                        print("item_attribute_info -------------- ", attribute_data_info)
                        conditions = " OR ".join([
                        f"(LOWER(iva.attribute) = '{key.lower()}' AND LOWER(iva.attribute_value) = '{value.lower()}')"
                                    for key, value in attribute_data_info.items()
                                ])

                        query = f"""
                                    SELECT
                                        iva.parent AS item_code
                                    FROM
                                        `tabItem Variant Attribute` iva
                                    WHERE
                                        {conditions}
                                    GROUP BY
                                        iva.parent
                                    HAVING
                                        COUNT(*) = {len(attribute_data_info)}
                                """
                            
                        item_codes = frappe.db.sql(query, as_dict=True)

                        print("item_codes ---------------- ", item_codes)

                        stock_data = {}

                        for items in item_codes:

                            warehouses = frappe.db.get_all("Warehouse", filters={"department": "Stores - NJ"}, pluck="name")
                            print("warehouses ---------------- ", warehouses)
                            stock_results = frappe.db.sql("""
                                SELECT item_code, SUM(actual_qty) AS total_qty 
                                FROM `tabBin` 
                                WHERE warehouse IN %(warehouses)s
                                AND item_code = %(item_code)s
                                """, {
                                    "warehouses": tuple(warehouses),
                                    "item_code": items["item_code"]
                                }, as_dict=True)

                            print("stock_results ---------------- ", stock_results)

                            for stock in stock_results:
                                stock_data[stock["item_code"]] = flt(stock["total_qty"])
                            
                            
                            available_stock = stock_data.get(items.get("item_code"), 0)

                            print("available_stock ---------------- ", available_stock)

                            if available_stock > 0:
                                item.update(
                                    {
                                        "item_code": items["item_code"],
                                        "against_item_code": item.get("item_code"),
                                        "stock_qty": available_stock
                                    })
                                print("item ----------- 217 ", item)
                                return item