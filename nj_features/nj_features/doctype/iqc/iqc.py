# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import base64
import json
import frappe
from frappe import _
from frappe.model.document import Document
import os
from barcode import Code128
from barcode.writer import ImageWriter, SVGWriter
from io import BytesIO
from PIL import Image
from frappe.utils import get_url

class IQC(Document):   
    def submit(self):
        stock_entry = frappe.new_doc("Stock Entry")
        stock_entry.stock_entry_type = "Repack"
        stock_entry.company = frappe.db.get_single_value("Global Defaults", "default_company")

        stock_entry.append("items", {
            "item_code": self.item_code,
            "qty": 1,
            'uom': 'Nos',
            'conversion_factor': 1,
            'stock_uom': 'Nos',
            's_warehouse': self.source_warehouse,
            'basic_rate': self.base_price
        })

        if frappe.get_value('Item', {'item_code': self.item_code}, 'has_serial_no') == 1:
            stock_entry.items[0].update({'serial_no': self.serial_no})

        stock_entry.append("items", {
            "item_code": self.repack_item_code,
            "qty": 1,
            "t_warehouse": self.target_warehouse if self.target_warehouse else self.source_warehouse,
            'uom': 'Nos',
            'conversion_factor': 1,
            'serial_no': self.serial_no,
            'stock_uom': 'Nos',
            'set_basic_rate_manually': 1,
            'basic_rate': self.original_price
        })

        stock_entry.save()
        stock_entry_name = stock_entry.name

        # print(f"Update serial no based on IQC")
        # for row in self.iqc_item_component:
        #     if row:
        #         serial_no_doc = frappe.get_doc('Serial No', self.serial_no)
        #         item_code = get_variant(row.item_group, row.attr_data)
        #         row.item_code = item_code
        #         serial_no_doc.append('serial_no_component',{
        #             'item_group': row.item_group,
        #             'item': item_code
        #         })
        #         serial_no_doc.save()

        return {'stock_entry_name': stock_entry_name}
    
@frappe.whitelist()
def set_value_for_pricing(self):
    self_dict = json.loads(self)
    print(f":")
    purchase_price = frappe.db.get_value('Purchase Receipt', {'name': self_dict['purchase_receipt']}, 'total')
    base_price = frappe.db.get_value('Purchase Receipt Item', {'parent': self_dict['purchase_receipt'], 
    'item_code': self_dict['item_code']}, 'base_rate')
    repack_itm_price = ''
    # print(f"repack_itm_price: {repack_itm_price}")
    if self_dict['item_code']:
        repack_itm_price = frappe.db.get_value('Item', {'item_code': self_dict['item_code']}, 'valuation_rate')

    elif repack_itm_price is None or self_dict['item_template']:
        repack_itm_price = frappe.db.get_value('Item', {'item_code': self_dict['item_template']}, 'valuation_rate')
    else:
        repack_itm_price = base_price
    original_price = iqc_to_repack_pricing(purchase_price, base_price, repack_itm_price)

    return {"original_price": original_price.get('original_price', 0), "repack_itm_price": repack_itm_price, "base_price": base_price, "purchase_price": purchase_price}


@frappe.whitelist()
def get_attribute_parent(attribute_value):
    sql_query = f"""
        SELECT ia.attribute_name
        FROM `tabItem Attribute` AS ia
        JOIN `tabItem Attribute Value` AS iav ON ia.name = iav.parent
        WHERE iav.attribute_value = '{attribute_value}'
    """
    result = frappe.db.sql(sql_query, as_dict=True)
    return result

@frappe.whitelist()
def set_iqc_child_table(item_group):
    item_group_doc = frappe.get_doc('Item Group', item_group)
    components = []
    for component in item_group_doc.component_list:
        components.append({
            'component_name': component.component_name
        })
    return {'components':components}

@frappe.whitelist()
def get_po_from_pr(pr):
    query = frappe.db.sql(
        """SELECT Item_code, purchase_order FROM `tabPurchase Receipt Item` WHERE parent = %s """,
        (pr), as_dict=True)

    result = {"po": None, "item_code": []}

    for row in query:
        result["po"] = row["purchase_order"]
        result["item_code"].append(row["Item_code"]) 
    return result


@frappe.whitelist()
def get_list_of_variants(item_group):
    item_group_doc = frappe.get_doc('Item Group', item_group)
    item_attributes = [{'variant': attr.variant} for attr in item_group_doc.variants_of_item_group]
    return {'variants': item_attributes}

@frappe.whitelist()
def get_list_of_attributes(variant):
    variant_doc = frappe.get_doc('Item Attribute', variant)
    attribute_list = [attr.attribute_value for attr in variant_doc.item_attribute_values]
    return {'options': attribute_list}

@frappe.whitelist()
def get_attribute_from_item_code(item_code):
    item_variant_doc = frappe.get_doc('Item Variant Attribute', {'parent': item_code})
    values = [{'attribute': attr.attribute, 'attribute_value': attr.attribute_value} for attr in item_variant_doc.attributes]
    return {'options': values}

def iqc_to_repack_pricing(purchase_price, base_price, repack_itm_price=None):
    if purchase_price is not None and base_price is not None:
        purchase_price = float(purchase_price)
        base_price = float(base_price)

        if repack_itm_price is None or repack_itm_price == '':
            repack_itm_price = base_price
        else:
            repack_itm_price = float(repack_itm_price)

        val = purchase_price - base_price + repack_itm_price
        factor = purchase_price / val
        original_price = repack_itm_price * factor
        return {'original_price': original_price}
    else:
        return {'error': 'purchase_price and base_price must not be None'}


@frappe.whitelist()
def get_items_from_pr(pr):
    return frappe.db.sql("""SELECT item_code from `tabPurchase Receipt Item` where parent = %s""", (pr), as_dict=1)

@frappe.whitelist()
def get_info_from_serial_no(serial_no=None):
    result = {}

    if serial_no:
        serial_no_doc = frappe.db.sql(""" SELECT item_code, item_group, brand, warehouse FROM `tabSerial No` WHERE name = %s""", 
        (serial_no), as_dict=1)

        if serial_no_doc:
            result['item_code'] = serial_no_doc[0].get('item_code', '')
            result['item_group'] = serial_no_doc[0].get('item_group', '')
            result['brand'] = serial_no_doc[0].get('brand', '')
            result['warehouse'] = serial_no_doc[0].get('warehouse', '')

            base_price = frappe.db.sql(""" SELECT valuation_rate FROM `tabItem` WHERE name = %s """, 
            (result['item_code']), as_dict=1)

            if base_price:
                result['valuation_rate'] = base_price[0].get('valuation_rate', '')

    return result

@frappe.whitelist()
def get_part_mapping(item_group):
    mappings = frappe.get_all(
        "Part Mapping",
        filters={"parent": item_group},
        fields=["item_group", "mappng_fields", "attribute_name"],
        order_by="idx",
    )

    return mappings

#Not used
def update_attr_data(doc, method):
    part_mappings = get_part_mapping(doc.item_group)

    if part_mappings:
        last_variant_values = {}

        for mapping in part_mappings:
            for row in doc.get("iqc_item_component"):
                item_group = row.item_group
                variants = mapping.get("mappng_fields").split("::")

                if (
                    item_group == mapping.get("item_group")
                    and all(variant in row.fields for variant in variants)
                ):
                    for variant in variants:
                        if variant in row.fields:
                            last_variant_values[item_group] = last_variant_values.get(
                                item_group, {}
                            )
                            last_variant_values[item_group][variant] = row.get(variant)

                    attribute_value = last_variant_values[item_group]
                    attribute_object = {}

                    if len(attribute_value) > 1:
                        attribute_object[mapping.get("attribute_name")] = " - ".join(
                            attribute_value.values()
                        )
                    else:
                        attribute_object[mapping.get("attribute_name")] = list(
                            attribute_value.values()
                        )[0]

                    row.attr_data = frappe.as_json(attribute_object)
                    print("attribute_object: ", attribute_object)

        doc.save()


@frappe.whitelist()
def get_variant_from_value(template=None, args=None):
    args_list = frappe.parse_json(args)
    
    if template:
        conditions = []

        for condition_dict in args_list:
            for key, value in condition_dict.items():
                conditions.append(f"MAX(attribute = '{key.lower()}' AND attribute_value = '{value.lower()}') = 1")

        having_clause = " AND ".join(conditions)
        
        if having_clause:
            query = f"""
                SELECT parent FROM `tabItem Variant Attribute`
                WHERE variant_of = %s
                GROUP BY parent
                HAVING {having_clause}
            """
        else:
            query = f"""
                SELECT parent FROM `tabItem Variant Attribute`
                WHERE variant_of = %s
                GROUP BY parent
            """

        variants = frappe.db.sql(query, template, as_dict=True)
        
        if variants:
            return variants[0]['parent']
        else:
            return None

    
@frappe.whitelist()
def get_templates_by_model_and_brand(model=None, brand=None, item_group=None):
    template_query = """
        SELECT name FROM `tabItem` WHERE item_model = %s
        AND brand = %s AND item_group = %s
    """

    templates = frappe.db.sql(template_query, (model, brand, item_group), as_dict=True)

    if templates:
        return templates[0].name
    else:
        return None
    

@frappe.whitelist()
def get_price_for_item_code(item_code=None, pr=None):
    item_unit_prize = "SELECT base_rate FROM `tabPurchase Receipt Item` WHERE item_code = %s AND parent = %s"
    base_price = frappe.db.sql(item_unit_prize, (item_code, pr), as_dict=True)

    if base_price:
        return base_price[0].base_rate
    else:
        return None


import os

@frappe.whitelist()
def generate_and_save_barcode(serial_no, format='svg'):
    # Generate Code128 barcode with SVGWriter
    my_code = Code128(serial_no, writer=SVGWriter())

    # Create BytesIO to store barcode SVG
    barcode_bytes = BytesIO()
    my_code.write(barcode_bytes)

    # Set the directory to save the file
    base_directory = frappe.get_site_path("public", "files")
    file_path = os.path.join(base_directory, f"{serial_no}.{format}")

    # Check if the file already exists
    if os.path.exists(file_path):
        os.remove(file_path)  # Remove the existing file

    # Save the SVG content to a file
    with open(file_path, 'wb') as f:
        f.write(barcode_bytes.getvalue())

    website_url = get_url()
    return {'barcode_img': f'{website_url}/files/{serial_no}.{format}'}


# @frappe.whitelist()
# def generate_and_save_barcode(serial_no, format='svg'):
#     my_code = Code128(serial_no, writer=SVGWriter())

#     barcode_bytes = BytesIO()
#     my_code.write(barcode_bytes)

#     # Open the barcode image using Pillow (PIL Fork)
#     img = Image.open(barcode_bytes)

#     # Resize the image to the specified dimensions
#     # target_width = 48  # in mm
#     # target_height = 36  # in mm
#     # width, height = img.size
#     # aspect_ratio = width / height
#     # new_width = int(target_width * 3.779527559)  # Convert mm to pixels (1mm = 3.779527559 pixels)
#     # new_height = int(new_width / aspect_ratio)

#     # img = img.resize((new_width, min(new_height, int(target_height * 3.779527559))))

#     base_directory = frappe.get_site_path("public", "files")
#     file_path = os.path.join(base_directory, f"{serial_no}.svg")

#     img.save(file_path, format="SVG")

#     return {'barcode_img': f'/files/{serial_no}.svg'}
    
# @frappe.whitelist()
# def generate_and_save_barcode(serial_no, format='png'):
#     # Generate Code128 barcode
#     my_code = Code128(serial_no, writer=ImageWriter())

#     # Create BytesIO to store barcode image
#     barcode_bytes = BytesIO()
#     my_code.write(barcode_bytes)

#     # Open the barcode image using Pillow (PIL Fork)
#     img = Image.open(barcode_bytes)

#     # Resize the image with improved quality
#     target_width = 96  # in mm
#     target_height = 32  # in mm
#     dpi = 600  # Adjust the DPI value for better quality

#     new_width = int(target_width * dpi / 25.4)  # Convert mm to pixels
#     new_height = int(target_height * dpi / 25.4)

#     img = img.resize((new_width, new_height), Image.ANTIALIAS)

#     # Set the directory to save the file
#     base_directory = frappe.get_site_path("public", "files")
#     file_path = os.path.join(base_directory, f"{serial_no}.{format}")

#     # Save the resized image as a PNG file
#     img.save(file_path, format="PNG", dpi=(dpi, dpi))

#     return {'barcode_img': f'http://127.0.0.1:8000/files/{serial_no}.{format}'}