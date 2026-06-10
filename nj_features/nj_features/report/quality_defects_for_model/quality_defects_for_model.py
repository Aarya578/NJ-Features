# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def execute(filters=None):
    if not filters.get("model") or not filters.get("from_date") or not filters.get("to_date"):
        frappe.throw(_("Model, From Date, and To Date are mandatory."))

    item_code_condition = ""
    if filters.get("item_code"):
        item_code_condition = "AND QI.item_code = %(item_code)s"

    query = f"""
    (
        SELECT
            item_group,
            options,
            COUNT(*) AS option_score,
            COUNT(*) OVER (PARTITION BY item_group) AS item_group_score
        FROM (
            SELECT DISTINCT QI.barcode, NJQC.item_group, NJQC.options
            FROM `tabNJ Quality Inspection` QI
            INNER JOIN `tabNJ Checks` NJQC ON QI.name = NJQC.parent
            WHERE QI.model = %(model)s
              AND QI.report_date BETWEEN %(from_date)s AND %(to_date)s
              AND QI.docstatus = 1
              AND NJQC.score > 30
              {item_code_condition}
        ) AS distinct_data
        GROUP BY item_group, options
    )

    UNION ALL

    (
        SELECT
            'TOTAL' AS item_group,
            NULL AS options,
            NULL AS option_score,
            COUNT(DISTINCT QI.barcode) AS item_group_score
        FROM `tabNJ Quality Inspection` QI
        WHERE QI.model = %(model)s
          AND QI.report_date BETWEEN %(from_date)s AND %(to_date)s
          AND QI.docstatus = 1
          {item_code_condition}
    )

    ORDER BY item_group_score DESC, option_score DESC
    """

    data = frappe.db.sql(query, filters, as_dict=True)

    columns = [
        {"label": "Item Group", "fieldname": "item_group", "fieldtype": "Data", "width": 300},
        {"label": "Options", "fieldname": "options", "fieldtype": "Data", "width": 500},
        {"label": "Option Score", "fieldname": "option_score", "fieldtype": "Int", "width": 300},
        {"label": "Item Group Score", "fieldname": "item_group_score", "fieldtype": "Int", "width": 300},
    ]

    return columns, data