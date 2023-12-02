# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from erpnext.controllers.item_variant import get_variant

class IQC(Document):
    def on_submit(self):
        print(f"Repack after submit of IQC")
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
            'basic_rate': self.base_price
        })

        stock_entry.append("items", {
            "item_code": self.repack_item_code,
            "qty": 1,
            "t_warehouse": self.warehouse,
            'uom': 'Nos',
            'conversion_factor': 1,
            'serial_no': self.serial_no,
            'stock_uom': 'Nos',
            'set_basic_rate_manually': 1,
            'basic_rate': self.original_price
        })

        stock_entry.submit()
        stock_entry_name = stock_entry.name

        print(f"Update serial no based on IQC")
        for row in self.iqc_item_component:
            if row:
                serial_no_doc = frappe.get_doc('Serial No', self.serial_no)
                item_code = get_variant(row.item_group, row.attr_data)
                row.item_code = item_code
                serial_no_doc.append('serial_no_component',{
                    'item_group': row.item_group,
                    'item': item_code
                })
                serial_no_doc.save()

        return {'stock_entry_name': stock_entry_name}

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
    po = frappe.get_doc('Purchase Receipt Item', {'parent': pr})

    if po:
        return po
    else:
        return None

@frappe.whitelist()
def get_list_of_variants(item_group):
    item_group_doc = frappe.get_doc('Item Group', item_group)
    item_attributes = [{'variant': attr.variant} for attr in item_group_doc.variants_of_item_group]
    return {
        'variants': item_attributes,
    }

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

@frappe.whitelist()
def iqc_to_repack_pricing(purchase_price, base_price, repack_itm_price=None):
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


