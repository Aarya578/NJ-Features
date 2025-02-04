import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

class ProductivityKpiTable(Document):
    pass

def create_kpi_record(row_data):
    """Create a single ProductivityKpiTable record from query data"""
    try:
        doc = frappe.get_doc({
            "doctype": "Productivity Kpi Table",
            "posting_date": row_data.posting_date,
            "serial_no": row_data.serial_no,
            "stock_entry_name": row_data.stock_entry_name,
            "stock_entry_creation": row_data.stock_entry_creation,
            "item_group": row_data.item_group,
            "item_code": row_data.item_code,
            "qty": row_data.qty,
            "src_warehouse": row_data.Src_warehouse,
            "t_warehouse": row_data.t_warehouse,
            "source_dept": row_data.Source_dept,
            "target_dept": row_data.Target_Dept,
            "source_profile": row_data.Source_Profile,
            "target_profile": row_data.Target_Profile,
            "itemgroup_weightage_value": row_data.Itemgroup_weightage_value,
            "waghtage_value": row_data.weightage_value,
            "wtd_qty": row_data.wtd_qty,
            "dept_prd": row_data.dept_prd,
            "profile_prd": row_data.profile_prd,
            "match_prd_flag": row_data.match_prd_flag
        })
        doc.insert(ignore_permissions=True)
        doc.submit()
        frappe.db.commit()
        
        return True
    except Exception as e:
        frappe.log_error(f"Error creating KPI record for {row_data.serial_no}: {str(e)}")
        return False

@frappe.whitelist()
def fetch_and_save_productivity_data():
    """Fetch productivity data and save each row as a separate document"""
    query = """
    SELECT 
        ste.posting_date, ste.serial_no, ste.stock_entry_name, 
        ste.stock_entry_creation, ste.item_group, ste.item_code, 
        ste.qty, ste.Src_warehouse, ste.t_warehouse, ste.Source_dept, 
        ste.Target_Dept, ste.Source_Profile, ste.Target_Profile, 
        wt.value AS Itemgroup_weightage_value, 
        ste.qty * wt.value AS wtd_qty,
        CASE WHEN Pd.target_department = ste.Target_Dept THEN 1 ELSE 0 END AS dept_prd,
        CASE WHEN ste.Target_Profile = Rp.target_profile THEN 1 ELSE 0 END AS profile_prd,
        CASE 
            WHEN (CASE WHEN Pd.target_department = ste.Target_Dept THEN 1 ELSE 0 END = 1) 
            OR (CASE WHEN ste.Target_Profile = Rp.target_profile THEN 1 ELSE 0 END = 1) 
            THEN 1 ELSE 0 
        END AS match_prd_flag
    FROM (
        SELECT 
            a.posting_date, b.serial_no, a.name AS stock_entry_name,
            a.creation AS stock_entry_creation, c.item_group, b.item_code,
            b.qty, 
            LAG(b.t_warehouse) OVER (PARTITION BY b.serial_no ORDER BY a.creation) AS Src_warehouse,
            b.t_warehouse,
            LAG(b.target_department) OVER (PARTITION BY b.serial_no ORDER BY a.creation) AS Source_dept,
            b.target_department AS Target_Dept,
            LAG(b.target_role_profile) OVER (PARTITION BY b.serial_no ORDER BY a.creation) AS Source_Profile,
            b.target_role_profile AS Target_Profile
        FROM `tabStock Entry` a
        INNER JOIN `tabStock Entry Detail` b ON a.name = b.parent
        INNER JOIN `tabItem` c ON b.item_code = c.name
        WHERE 
            a.purpose = 'Material Transfer'
            AND a.docstatus = 1
            AND a.creation >= (NOW() - INTERVAL 15 DAY)
            AND b.t_warehouse IS NOT NULL
            AND b.t_warehouse != ''
            AND b.serial_no IS NOT NULL
            AND b.target_department != 'Stock Movement - NJ'
            AND c.item_group IN ('Laptops','Chromebooks','Chromeboxes','Desktops','Full Set Desktops')
    ) ste
    LEFT JOIN `tabProductivity Department` Pd 
        ON ste.Source_dept = Pd.parent 
        AND ste.Target_Dept = Pd.target_department
    LEFT JOIN `tabWeightage` wt 
        ON ste.Source_dept = wt.parent 
        AND ste.item_group = wt.item_group
    LEFT JOIN `tabProductivity Profile` Rp 
        ON Rp.parent = ste.Source_Profile 
        AND Rp.target_profile = ste.Target_Profile
    WHERE ste.Source_dept IS NOT NULL
    ORDER BY ste.stock_entry_creation ASC
    """
    
    data = frappe.db.sql(query, as_dict=True)
    print("data====",data)
    print("data=================95=================",data)
    
    # Track statistics
    total_records = len(data)
    successful_saves = 0
    
    # Process each row
    for row in data:
        if create_kpi_record(row):
            successful_saves += 1
    # Log the results
    frappe.logger().info(f"Productivity KPI Update: Processed {total_records} records, Successfully saved {successful_saves} records")
    
    return {
        "total_records": total_records,
        "successful_saves": successful_saves
    }