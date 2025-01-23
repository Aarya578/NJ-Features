import frappe
from frappe import _
from frappe.model.document import Document
logger = frappe.logger("productivity", allow_site=True, file_count=5)

class Productivity(Document):
    pass

@frappe.whitelist()
def fetch_productivity_data(doc):
    """Fetch productivity data and return it for frontend processing"""
    if isinstance(doc, str):
        doc = frappe.parse_json(doc)

    query = """
        SELECT 
            ste.posting_date,
            ste.serial_no,
            ste.stock_entry_name,
            ste.stock_entry_creation,
            ste.item_group,
            ste.item_code,
            ste.qty,
            ste.t_warehouse,
            ste.Source_dept,
            ste.Target_Dept,
            Pd.target_department,
            CASE 
                WHEN Pd.target_department = ste.Target_Dept THEN 1 
                ELSE 0 
            END AS dept_prd,
            wt.value AS weightage_value,
            ste.qty * wt.value AS Wtd_Qty -- New column calculating weighted quantity
        FROM (
            SELECT 
                a.posting_date,
                b.serial_no,
                a.name AS stock_entry_name,
                a.creation AS stock_entry_creation,
                c.item_group,
                b.item_code,
                b.qty,
                b.t_warehouse,
                LAG(b.target_department) OVER (PARTITION BY b.serial_no ORDER BY a.creation) AS Source_dept,
                b.target_department AS Target_Dept
            FROM
                `tabStock Entry` a
            INNER JOIN
                `tabStock Entry Detail` b ON a.name = b.parent
            INNER JOIN
                `tabItem` c ON b.item_code = c.name
            WHERE
                a.purpose = 'Material Transfer'
                AND a.docstatus = 1
                AND a.creation >= (NOW() - INTERVAL 10 DAY)
                AND b.t_warehouse IS NOT NULL
                AND b.t_warehouse != ''
                AND b.serial_no IS NOT NULL
                AND b.target_department != 'Stock Movement - NJ'
                AND c.item_group IN ('Laptops')
        ) ste
        INNER JOIN 
            `tabProductivity Department` Pd 
        ON 
            ste.Source_dept = Pd.parent 
            AND ste.target_Dept = Pd.target_department
        LEFT JOIN 
            `tabWeightage` wt 
        ON 
            ste.Source_dept = wt.parent 
            AND ste.item_group = wt.item_group
        WHERE 
            ste.Source_dept = %s
            OR ste.Target_Dept = %s
    """
    
    # Execute the query using the provided doc.department and debug options
    data = frappe.db.sql(query, (doc.department, doc.department), debug=1, explain=1, as_dict=True)
    logger.debug("=====data========",data)

    print('data', data)

    return data
