# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import frappe
from frappe import _

def get_columns():
    return [
        _("Brand") + ":Link/Brand:100",
        _("Model") + ":Link/Models:100",
        _("Part") + ":Link/Item Group:100",
        _("Department") + ":Link/Department:150",
        _("Name") + ":Data:160",
        _("Description") + ":Data:400",
        _("Document") + ":Attach:180"
    ]

def get_data(filters):
    conditions = []

    if filters.get("brand"):
        conditions.append(f"AND kb.brand = '{filters['brand']}'")
        
    if filters.get("model"):
        conditions.append(f"AND kb.model = '{filters['model']}'")
        
    if filters.get("part"):
        conditions.append(f"AND kb.part = '{filters['part']}'")
        
    if filters.get("department"):
        conditions.append(f"AND kb.department = '{filters['department']}'")
        
    if filters.get("name"):
        conditions.append(f"AND kb.name1 = '{filters['name']}'")
        
    condition_sql = " ".join(conditions)
    
    query = f"""
        SELECT
			kb.brand,
            kb.model,
            kb.part,
            kb.department,
            kb.name1 AS name,
            kb.description,
            kb.attach AS document
        FROM `tabKnowledge Base` AS kb
        WHERE 
            kb.active = 1
            {condition_sql}
    """
    
    data = frappe.db.sql(query, filters, as_dict=1)
    print(f"query: {query}, data: {data}")
    return data

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    
    for row in data:
       document = row.get("document")
       if document:
            row["document"] = f'<a href="{document}" target="_blank">Download</a>'
    return columns, data
