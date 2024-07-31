# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def get_columns(filters):
    
    if filters.get("sheet_no") == "1":
        return [
			{"label": _("Item Code"), "fieldname": "name", "fieldtype": "Link", "options": "Item"},
			{"label": _("Brand"), "fieldname": "brand", "fieldtype": "Link", "options": "Brand"},
			{"label": _("Model"), "fieldname": "item_model", "fieldtype": "Link", "options": "Models"},
			{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group"}
		]
        
    if filters.get("sheet_no") == "2":
        return [
			{"label": _("Item Wizard"), "fieldname": "parent", "fieldtype": "Link", "options": "Warehouse"},
			{"label": _("Item Group"), "fieldname": "component_type", "fieldtype": "Link", "options": "Item Group"}
		]
    if filters.get("sheet_no") == "3":
        return [
			{"label": _("Item Wizard"), "fieldname": "name", "fieldtype": "Link", "options": "Item Wizards"},
			{"label": _("Model"), "fieldname": "model", "fieldtype": "Link", "options": "Models"}
		]
    if filters.get("sheet_no") == "4":
        return [
			{"label": _("Item Code"), "fieldname": "parent", "fieldtype": "Link", "options": "Item"},
			{"label": _("Item Attribute"), "fieldname": "attribute", "fieldtype": "Data"},
			{"label": _("Item Attribute Value"), "fieldname": "attribute_value", "fieldtype": "Data"}
		]
    if filters.get("sheet_no") == "5":
        return [
			{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item"},
			{"label": _("Item Variant"), "fieldname": "variant_of", "fieldtype": "Link", "options": "Item"}
		]
    
def get_data(filters):
    query = ""
	# Brand, Model, Item Group not filled in variant 
    if filters.get("sheet_no") == "1":
        query = """
			SELECT name, brand, item_model, item_group
			FROM `tabItem`
			WHERE (item_model IS NULL OR brand IS NULL)
				AND has_variants = 1 AND disabled = 0
				AND item_group NOT IN ('Services', 'Consumables', 'Administrative Expenses', 
    			'Networking Devices', 'Fixed asset', 'Consumable', 'Raw Material', 'Assets')
			LIMIT 1000
        """
    # Item Group present in Item Wizard, but not available in main Item Group like 'Laptops'
    if filters.get("sheet_no") == "2":
        query = """
			SELECT parent, component_type
			FROM `tabComponent` 
			WHERE component_type NOT IN (SELECT component_name FROM `tabAllowed Component`)
			LIMIT 1000
        """
    # Model is not matching with item template and selected model in item wizard
    if filters.get("sheet_no") == "3":
        query = """
			SELECT item_wizard.name, item_wizard.model
			FROM `tabItem Wizards` item_wizard 
			WHERE item_wizard.model <>(SELECT item.item_model FROM `tabItem` item WHERE item.name = item_wizard.item_template) 
			LIMIT 1000
        """
    # Attribute and attribute value not matching need to add in 'Item Attribute Value'
    if filters.get("sheet_no") == "4":
        query = """
			SELECT 
				item.parent,
				item.attribute,
				item.attribute_value
			FROM `tabItem Variant Attribute` AS item
			WHERE NOT EXISTS (
				SELECT 1
				FROM `tabItem Attribute Value` AS value
				WHERE item.attribute = value.parent
				AND (item.attribute_value IS NULL OR item.attribute_value = value.attribute_value)
			) LIMIT 1000
        """
    # Item Wizard not available for item template
    if filters.get("sheet_no") == "5":
        query = """
			SELECT sn.item_code, item.variant_of
			FROM `tabSerial No` sn
			LEFT JOIN `tabItem` item 
				ON item.name = sn.item_code
			LEFT JOIN `tabItem Wizards` wizard
				ON item.variant_of = wizard.item_template
			WHERE sn.item_group IN ('Laptops', 'Chromebooks')
				AND wizard.item_template IS NULL
			GROUP BY item_code LIMIT 1000
        """
    result = frappe.db.sql(query, as_dict=True)
    return result

def execute(filters=None):
	return get_columns(filters), get_data(filters)
