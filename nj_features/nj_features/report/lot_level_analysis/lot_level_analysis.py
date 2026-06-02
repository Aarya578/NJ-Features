import frappe

def execute(filters=None):
    filters = filters or {}

    model = filters.get("model") or ""
    supplier = filters.get("supplier") or ""
    purchase_order = filters.get("purchase_order") or ""

    # Run the query only if at least one filter is provided
    if not (model or supplier or purchase_order):
        return [], []

    # Create pattern strings with wildcards for LIKE clauses
    model_pattern = f"%{model}%"
    supplier_pattern = f"%{supplier}%"
    purchase_order_pattern = f"%{purchase_order}%"

    query = """
    -- Part 1: Total Units
    (SELECT 
        Supplier,
        model,
        '1. Total Units' AS Label,
        COUNT(name) AS Numbers,
        ROUND(AVG(purchase_price)) AS Purchase,
        ROUND(COUNT(name) * AVG(purchase_price)) AS Total
    FROM `tabSerial No`
    WHERE model LIKE %(model_pattern)s
      AND supplier LIKE %(supplier_pattern)s
      AND purchase_order LIKE %(purchase_order_pattern)s
      AND item_group = 'Laptops'
    GROUP BY 1, 2, 3)

    UNION

    -- Part 2: Net Added
    (SELECT 
        supplier,
        model,
        item_group AS Label,
        Net_Added,
        Rate,
        Net_Added * Rate AS Total
    FROM (
        SELECT 
            Sr.supplier,
            Sr.model,
            SED2.item_group,
            ROUND(SUM(CASE WHEN SED2.t_warehouse IS NULL THEN SED2.qty ELSE 0 END), 0)
            - ROUND(SUM(CASE WHEN SED2.s_warehouse IS NULL AND NOT (RIGHT(Sr2.item_code, 7) IS NULL OR UPPER(RIGHT(Sr2.item_code, 7)) = 'GRADE C') THEN SED2.qty ELSE 0 END), 0)
            AS Net_Added,
            ROUND(AVG(CASE WHEN IP.price_list_rate != 0 THEN IP.price_list_rate ELSE SED2.amount END), 0) AS Rate
        FROM `tabSerial No` Sr
        INNER JOIN `tabStock Entry Detail` SED1 ON SED1.serial_no = Sr.name
        INNER JOIN `tabStock Entry Detail` SED2 ON SED1.parent = SED2.parent AND SED2.qty = 1
        LEFT JOIN `tabSerial No` Sr2 ON Sr2.name = SED2.serial_no
        LEFT JOIN `tabItem Price` IP ON IP.item_code = SED2.item_code AND IP.buying = 1
        WHERE SED1.item_group = 'Laptops'
          AND NOT (SED2.item_group = 'Laptops')
          AND SED1.s_warehouse IS NOT NULL
          AND SED1.t_warehouse IS NULL
          AND SED1.docstatus = 1
          AND SED2.docstatus = 1
          AND Sr.model LIKE %(model_pattern)s
          AND Sr.supplier LIKE %(supplier_pattern)s
          AND Sr.purchase_order LIKE %(purchase_order_pattern)s
          AND SED1.parent NOT LIKE 'NJ-QI-%%'
        GROUP BY 1, 2, 3
        HAVING Net_Added > 0
    ) Final)

    UNION

    -- Part 3: Scrap Units
    (SELECT 
        Supplier,
        model,
        'Z. Scrap Units' AS Label,
        COUNT(name) AS Numbers,
        ROUND(AVG(purchase_price)) AS Purchase,
        ROUND(-1 * COUNT(name) * AVG(purchase_price)) AS Total
    FROM `tabSerial No`
    WHERE model LIKE %(model_pattern)s
      AND supplier LIKE %(supplier_pattern)s
      AND purchase_order LIKE %(purchase_order_pattern)s
      AND item_group = 'Laptops'
      AND delivery_document_type = 'Stock Entry'
    GROUP BY 1, 2, 3)

    ORDER BY 1, 2, 6 DESC
    """

    data = frappe.db.sql(query, {
        "model_pattern": model_pattern,
        "supplier_pattern": supplier_pattern,
        "purchase_order_pattern": purchase_order_pattern
    }, as_dict=True)

    columns = [
        {"label": "Supplier", "fieldname": "Supplier", "fieldtype": "Data", "width": 200},
        {"label": "Model", "fieldname": "model", "fieldtype": "Data", "width": 200},
        {"label": "Label", "fieldname": "Label", "fieldtype": "Data", "width": 200},
        {"label": "Numbers", "fieldname": "Numbers", "fieldtype": "Int", "width": 200},
        {"label": "Purchase", "fieldname": "Purchase", "fieldtype": "Currency", "width": 200},
        {"label": "Total", "fieldname": "Total", "fieldtype": "Currency", "width": 200}
    ]

    return columns, data
