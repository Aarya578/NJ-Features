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

    department = doc.get("department")
    role_profile = frappe.db.get_value("Employee", {"department": department}, "role_profile")
    logger.debug(f"Role Profile for Department {department}: {role_profile}")

    query = """
        SELECT
            ste.posting_date,
            ste.serial_no,
            ste.stock_entry_name,
            ste.stock_entry_creation,
            ste.item_group,
            ste.item_code,
            ste.qty,
            ste.Src_warehouse,
            ste.t_warehouse,
            ste.Source_dept,
            ste.Target_Dept,
            ste.Source_Profile,
            ste.Target_Profile,
            wt.value AS Itemgroup_weightage_value,
            ste.qty * wt.value AS wtd_qty,
            CASE
                WHEN Pd.target_department = ste.Target_Dept THEN 1
                ELSE 0
            END AS dept_prd,
            CASE
                WHEN ste.Target_Profile = Rp.target_profile THEN 1
                ELSE 0
            END AS profile_prd,
            CASE
                WHEN
                    (CASE WHEN Pd.target_department = ste.Target_Dept THEN 1 ELSE 0 END = 1)
                    OR
                    (CASE WHEN ste.Target_Profile = Rp.target_profile THEN 1 ELSE 0 END = 1)
                THEN 1
                ELSE 0
            END AS match_prd_flag
        FROM (
            SELECT
                a.posting_date,
                b.serial_no,
                a.name AS stock_entry_name,
                a.creation AS stock_entry_creation,
                c.item_group,
                b.item_code,
                b.qty,
                LAG(b.t_warehouse) OVER (PARTITION BY b.serial_no ORDER BY a.creation) AS Src_warehouse,
                b.t_warehouse,
                LAG(b.target_department) OVER (PARTITION BY b.serial_no ORDER BY a.creation) AS Source_dept,
                b.target_department AS Target_Dept,
                LAG(b.target_role_profile) OVER (PARTITION BY b.serial_no ORDER BY a.creation) AS Source_Profile,
                b.target_role_profile AS Target_Profile
            FROM
                `tabStock Entry` a
            INNER JOIN
                `tabStock Entry Detail` b ON a.name = b.parent
            INNER JOIN
                `tabItem` c ON b.item_code = c.name
            WHERE
                a.purpose = 'Material Transfer'
                AND a.docstatus = 1
                AND a.creation >= (NOW() - INTERVAL 25 DAY)
                AND b.t_warehouse IS NOT NULL
                AND b.t_warehouse != ''
                AND b.serial_no IS NOT NULL
                AND b.target_department != 'Stock Movement - NJ'
                AND c.item_group IN ('Laptops', 'Chromebooks')
        ) ste
        LEFT JOIN
            `tabProductivity Department` Pd
        ON
            ste.Source_dept = Pd.parent
            AND ste.Target_Dept = Pd.target_department
        LEFT JOIN
            `tabWeightage` wt
        ON
            ste.Source_dept = wt.parent
            AND ste.item_group = wt.item_group
        LEFT JOIN
            `tabProductivity Profile` Rp
        ON
            Rp.parent = ste.Source_Profile
            AND Rp.target_profile = ste.Target_Profile
        WHERE
            ste.Source_dept = %s
            OR ste.Target_Dept = %s
    """

    # Execute the query with the department filter
    data = frappe.db.sql(query, (department, department), as_dict=True)
    logger.debug(f"Fetched Productivity Data for Department {department}: {data}")

    return {
        "productivity_data": data,
        "role_profile": role_profile
    }
