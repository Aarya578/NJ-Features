# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import base64
import json
import random
import frappe
from frappe import _
from frappe.model.document import Document
import os
from barcode import Code128
from nj_features.barcode import CustomImgWriter
from io import BytesIO
from frappe.utils import get_url

class IQC(Document):   
    def on_submit(self):
        if self.power_on == 'Yes':
            stock_entry = frappe.new_doc("Stock Entry")
            stock_entry.stock_entry_type = "Repack"
            stock_entry.company = frappe.db.get_single_value("Global Defaults", "default_company")

            stock_entry.append("items", {
                "item_code": self.item_code,
                "qty": 1,
                'uom': 'Nos',
                'conversion_factor': 1,
                'stock_uom': 'Nos',
                's_warehouse': self.warehouse,
                'basic_rate': self.base_price,
                'set_basic_rate_manually': 0,
            })

            if frappe.get_value('Item', {'item_code': self.item_code}, 'has_serial_no') == 1:
                stock_entry.items[0].update({'serial_no': self.serial_no})

            stock_entry.append("items", {
                "item_code": self.repack_item_code,
                "qty": 1,
                "t_warehouse": self.warehouse,
                'uom': 'Nos',
                'conversion_factor': 1,
                'serial_no': self.serial_no,
                'stock_uom': 'Nos',
                'basic_rate': self.base_price,
                'set_basic_rate_manually': 0,
            })
            stock_entry.naming_series = "STE-IQC-"
            stock_entry.submit()
        serial_no_doc = frappe.get_doc("Serial No", {'serial_no': self.serial_no})
        if serial_no_doc:
            serial_no_doc.bios_serial_no = self.njhat_serialno
            serial_no_doc.purchase_price = self.base_price
            serial_no_doc.current_price = self.base_price
            if self.njhat_serialno:
                serial_no_doc.save()
            else:
                frappe.throw("NJHAT Serial No is not found.")


@frappe.whitelist()
def brand_model_validation(brand=None, model=None):
    brand = frappe.db.exists('Brand', {'name': brand})
    model = frappe.db.exists('Models', {'name': model})
    return {'brand': brand, 'model': model}


@frappe.whitelist()
def get_info_from_serial_no(doc=None):
    result = {}
    doc_json = json.loads(doc)
    if doc_json:
        serial_no = doc_json['serial_no']
        serial_no_doc = frappe.get_doc('Serial No', {'name': serial_no}) # NJ - serial_no
        # get price from Stock Ledger Entry
        sql_query = """
            SELECT 
                item_code, warehouse, incoming_rate, posting_date, posting_time
            FROM
                `tabStock Ledger Entry`
            WHERE
                serial_no LIKE %s
                AND is_cancelled = 0
            ORDER BY
                posting_date DESC, posting_time DESC, creation DESC
            LIMIT 1
        """
        sle = frappe.db.sql(sql_query, ('%'+serial_no+'%',), as_dict=1)
        # print(f"sle: {sle}, serial_no: {serial_no}")
        # purchase_receipt_doc = frappe.db.sql("""
        #     SELECT name AS purchase_receipt, item_code AS item_code, base_rate AS base_rate 
        #     FROM `tabPurchase Receipt Item` 
        #     WHERE serial_no LIKE %s
        # """, ('%' + serial_no + '%'), as_dict=True)
        
        if serial_no_doc:
            sle_entry = sle[0]
            repack_itm_price = frappe.get_value('Item', {'name': sle_entry.get('item_code')}, 'valuation_rate')
            # purchase_price = frappe.get_value('Purchase Receipt', {'name': purchase_receipt_doc[0]['purchase_receipt']}, 'total')

            result['item_code'] = sle_entry.get('item_code')
            result['item_group'] = serial_no_doc.item_group
            result['brand'] = serial_no_doc.brand
            result['warehouse'] = sle_entry.get('warehouse')
            result['repack_itm_price'] = repack_itm_price
            # result['purchase_price'] = purchase_price
            result['base_price'] = sle_entry.get('incoming_rate')
            # result['purchase_receipt'] = purchase_receipt_doc[0]['purchase_receipt']
            if not serial_no_doc.bios_serial_no:
                serial_no_doc.bios_serial_no = doc_json.get('njhat_serialno')
                serial_no_doc.barcode = doc_json.get('serialno')
                serial_no_doc.save()
    return result


@frappe.whitelist()
def get_part_mapping(item_group):
    mappings = frappe.get_all("Part Mapping", filters={"parent": item_group},
    fields=["item_group", "mappng_fields", "attribute_name"], order_by="idx")

    values = frappe.get_all(
        "NJ Settings",
        filters={"doc_type": "IQC Child"}, fields=["parameter", "value"]
    )

    return {"mappings": mappings, "values": values}

@frappe.whitelist()
def get_variant_from_value(item_template=None, args=None):
    # print(f"\n\ntemplate: {item_template}, args: {args}")
    args_list = []
    if args:
        args_list = frappe.parse_json(args)
    
    if item_template:
        conditions = []

        for condition_dict in args_list:
            for key, value in condition_dict.items():
                conditions.append(f"MAX(attribute = '{key.lower()}' AND attribute_value = '{value.lower()}') = 1")

        having_clause = " AND ".join(conditions)
        # print(f"\n\nhaving: {having_clause}")
        
        if having_clause:
            query = """
                SELECT parent FROM `tabItem Variant Attribute`
                WHERE variant_of = %s
                GROUP BY parent
                HAVING {}
            """.format(having_clause)
            variants = frappe.db.sql(query, (item_template,), as_dict=True)
            # print(f"\n\nhaving: {having_clause}, variant: {variants}")
            if variants and variants[0]['parent']:
                return variants[0]['parent']
            else:
                item_code = construct_item_code(item_template, args_list)
                return item_code

    return None

def construct_item_code(item_template, args_list):
    # Generate the concatenated string
    concatenated_string = item_template
    for condition_dict in args_list:
        for key, value in condition_dict.items():
            concatenated_string += f"-{value}"
    print(f"\n\nconcatenated_string: {concatenated_string}\n")
    # Query the item_code based on the concatenated string
    query = """
        SELECT item_code FROM `tabItem`
        WHERE item_code = %s and has_serial_no = 1
    """

    item_code = frappe.db.sql(query, (concatenated_string,), as_dict=True)
    # print(f"\n\n\nitem_code: {item_code}\n")
    if item_code:
        return item_code[0]['item_code']
    else:
        frappe.msgprint(f'Serialized Item code: "{concatenated_string}" not found. Please contact NPD Team.')

@frappe.whitelist()
def get_model(manufacturer_model, make=None):
    query, model_list, new_model_list = '', [], []
    if manufacturer_model and make:
        query = """SELECT DISTINCT mmc.parent AS model
                   FROM `tabManufacturer Model Child` AS mmc
                   LEFT JOIN `tabMake Child` AS mc ON mc.parent = mmc.parent
                   WHERE mmc.manufacturer_model = %s AND mc.make = %s"""
        params = (manufacturer_model, make)
    model_list = frappe.db.sql(query, params, as_dict=True)
    # print(f"\n\n if model : {model_list}")

    if model_list == []:
        query = """SELECT DISTINCT mmc.parent AS model
                   FROM `tabManufacturer Model Child` AS mmc
                   LEFT JOIN `tabMake Child` AS mc ON mc.parent = mmc.parent
                   WHERE mmc.manufacturer_model = %s"""
        params = (manufacturer_model)
        model_list = frappe.db.sql(query, params, as_dict=True)
        # print(f"\n\n elif model ----- : {new_model_list}")
        if not model_list:
            frappe.msgprint(f"Manufacturer Model: <strong>{manufacturer_model}</strong> not found. Please contact <strong>NPD department</strong> for mapping the model.")

    return model_list
    
@frappe.whitelist()
def get_templates_by_model_and_brand(model=None, brand=None, item_group=None):
    template_query = """
        SELECT name FROM `tabItem` WHERE item_model = %s
        AND brand = %s AND item_group = %s AND has_variants = 1
    """

    templates = frappe.db.sql(template_query, (model, brand, item_group), as_dict=True)

    if templates:
        return templates[0].name
    else:
        return None

@frappe.whitelist()
def generate_and_save_barcode(serial_no, format='png'):
    my_code = Code128(serial_no, writer=CustomImgWriter())

    # Create BytesIO to store barcode SVG
    barcode_bytes = BytesIO()
    my_code.write(barcode_bytes)

    # Set the directory to save the file
    base_directory = frappe.get_site_path("public", "files")
    file_path = os.path.join(base_directory, f"{serial_no}.{format}")

    # Check if the file already exists
    if os.path.exists(file_path):
        os.remove(file_path)

    # Save the SVG content to a file
    with open(file_path, 'wb') as f:
        f.write(barcode_bytes.getvalue())

    website_url = get_url()
    return {'barcode_img': f'{website_url}/files/{serial_no}.{format}'}

# @frappe.whitelist()
# def get_variant_from_value(item_template=None, args=None):
#     print(f"\n\ntemplate: {item_template}, args: {args}")
#     args_list = []
#     if args:
#         args_list = frappe.parse_json(args)
    
#     if item_template:
#         conditions = []

#         for condition_dict in args_list:
#             for key, value in condition_dict.items():
#                 conditions.append(f"MAX(attribute = '{key.lower()}' AND attribute_value = '{value.lower()}') = 1")

#         having_clause = " AND ".join(conditions)
#         print(f"\n\nhaving: {having_clause}")
#         if having_clause:
#             query = f"""
#                 SELECT parent FROM `tabItem Variant Attribute`
#                 WHERE variant_of = %s
#                 GROUP BY parent
#                 HAVING {having_clause}
#             """
#             variants = frappe.db.sql(query, item_template, as_dict=True)
#             print(f"\n\nhaving: {having_clause}, variant: {variants}")
#             if variants:
#                 return variants[0]['parent']
#         else:
#             return None

# @frappe.whitelist()
# def get_model(manufacturer_model, make):
#     models = frappe.get_all("Models", filters={"njhat_model": manufacturer_model}, fields=["name"])
#     if len(models) == 1:
#         return models[0]['name']
    
#     elif len(models) > 1:
#         makes_list = []
#         for model in models:
#             makes = frappe.get_all("Make Child", filters={"parent": model.name, "make": make}, fields=["parent"])
#             if makes:
#                 makes_list.append(makes[0].parent)
        
#         if len(makes_list) > 0:
#             return makes_list
        
#         else:
#             frappe.throw(f"Match with make: {make} not found")
#     else:
#         frappe.throw("Model not found")

# @frappe.whitelist()
# def create_serial_no(item_code):
#     is_serial = frappe.get_value('Item', {'name': item_code}, 'has_serial_no')
#     if is_serial == 1:
#         new_serial = generate_random_code()
#         return new_serial
#     else:
#         return None

# def generate_random_code():
#     prefix = "NJ"
#     random_code = prefix + str(random.randint(100000, 999999))
#     return random_code

# @frappe.whitelist() # not used
# def get_item_code_price(item_code=None, pr=None):
#     purchase_price = frappe.db.get_value('Purchase Receipt', {'name': pr}, 'total')
#     base_price = frappe.db.get_value('Purchase Receipt Item', {'item_code': item_code, 'parent':pr}, 'base_rate')
#     return {"purchase_price": purchase_price, "base_price": base_price}

# @frappe.whitelist()
# def get_list_of_variants(item_group):
#     item_group_doc = frappe.get_doc('Item Group', item_group)
#     item_attributes = [{'variant': attr.variant} for attr in item_group_doc.variants_of_item_group]
#     return {'variants': item_attributes}

# @frappe.whitelist()
# def get_list_of_attributes(variant):
#     variant_doc = frappe.get_doc('Item Attribute', variant)
#     attribute_list = [attr.attribute_value for attr in variant_doc.item_attribute_values]
#     return {'options': attribute_list}

# @frappe.whitelist()
# def get_attribute_from_item_code(item_code):
#     item_variant_doc = frappe.get_doc('Item Variant Attribute', {'parent': item_code})
#     values = [{'attribute': attr.attribute, 'attribute_value': attr.attribute_value} for attr in item_variant_doc.attributes]
#     return {'options': values}

# def iqc_to_repack_pricing(purchase_price, base_price, repack_itm_price=None): # not used
#     if purchase_price is not None and base_price is not None:
#         purchase_price = float(purchase_price)
#         base_price = float(base_price)

#         if repack_itm_price is None or repack_itm_price == '':
#             repack_itm_price = base_price
#         else:
#             repack_itm_price = float(repack_itm_price)

#         val = purchase_price - base_price + repack_itm_price
#         factor = purchase_price / val
#         original_price = repack_itm_price * factor
#         return {'original_price': original_price}
#     else:
#         return {'error': 'purchase_price and base_price must not be None'}


# @frappe.whitelist() # not used
# def get_items_from_pr(pr):
    
# @frappe.whitelist() # Not used
# def set_value_for_pricing(self):
#     self_dict = json.loads(self)
#     purchase_price = frappe.db.get_value('Purchase Receipt', {'name': self_dict['purchase_receipt']}, 'total')
#     base_price = frappe.db.get_value('Purchase Receipt Item', {'parent': self_dict['purchase_receipt'], 
#     'item_code': self_dict['item_code']}, 'base_rate')
#     repack_itm_price = ''
#     # print(f"repack_itm_price: {repack_itm_price}")
#     if self_dict['item_code']:
#         repack_itm_price = frappe.db.get_value('Item', {'item_code': self_dict['item_code']}, 'valuation_rate')

#     elif repack_itm_price is None or self_dict['item_template']:
#         repack_itm_price = frappe.db.get_value('Item', {'item_code': self_dict['item_template']}, 'valuation_rate')
#     else:
#         repack_itm_price = base_price
#     original_price = iqc_to_repack_pricing(purchase_price, base_price, repack_itm_price)

#     return {"original_price": original_price.get('original_price', 0)}


# @frappe.whitelist()
# def get_attribute_parent(attribute_value):
#     sql_query = f"""
#         SELECT ia.attribute_name FROM `tabItem Attribute` AS ia
#         JOIN `tabItem Attribute Value` AS iav ON ia.name = iav.parent
#         WHERE iav.attribute_value = '{attribute_value}'
#     """
#     result = frappe.db.sql(sql_query, as_dict=True)
#     return result

# @frappe.whitelist()
# def set_iqc_child_table(item_group):
#     item_group = item_group.lower()
#     item_group_doc = frappe.get_doc('Item Group', item_group)
#     components = []
#     for component in item_group_doc.component_list:
#         components.append({'component_name': component.component_name})
#     return {'components':components}

# @frappe.whitelist() #not used
# def get_po_from_pr(pr):
#     result = {"po": None, "item_code": []}
#     query = frappe.db.sql(
#         """SELECT Item_code, purchase_order FROM `tabPurchase Receipt Item` WHERE parent = %s """, (pr), as_dict=True)

#     for row in query:
#         result["po"] = row["purchase_order"]
#         result["item_code"].append(row["Item_code"]) 
#     return result
#     return frappe.db.sql("""SELECT item_code from `tabPurchase Receipt Item` where parent = %s""", (pr), as_dict=1)