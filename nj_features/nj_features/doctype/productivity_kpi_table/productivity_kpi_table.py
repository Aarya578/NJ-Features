import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

class ProductivityKpiTable(Document):
    pass

def create_kpi_record(row_data):
    """Create a single ProductivityKpiTable record if it doesn't exist"""
    try:
        # Check if record with same serial_no and stock_entry_name already exists
        # existing = frappe.get_all("Productivity Kpi Table", 
        #     filters={
        #         "serial_no": row_data.serial_no,
        #         "stock_entry_name": row_data.stock_entry_name  # Ensure uniqueness per stock entry
        #     },
        #     limit=1  
        # )
        
        # if existing:
        #     return False  # Skip insertion if it already exists for the same stock entry

        # Insert new document
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
            "waghtage_value": row_data.weightage_value if hasattr(row_data, 'weightage_value') else None,
            "wtd_qty": row_data.wtd_qty,
            "dept_prd": row_data.dept_prd,
            "profile_prd": row_data.profile_prd,
            "match_prd_flag": row_data.match_prd_flag
        })
        print("Inserting KPI record for serial_no:========================46-------------", row_data.serial_no)
        print("doc========================46-------------", doc.as_dict())
        doc.insert(ignore_permissions=True)
        doc.submit()
        frappe.db.commit()
        return True
    except Exception as e:
        frappe.log_error(f"Error creating KPI record for {row_data.serial_no}: {str(e)}")
        return False


def delete_canceled_stock_entries():
    """Delete Productivity Kpi Table records with canceled stock entry names"""
    try:
        # Get all the canceled Stock Entries
        canceled_stock_entries = frappe.get_all("Stock Entry", 
            filters={"docstatus": 2},  # 2 indicates canceled status
            fields=["name"]
        )

        # If there are canceled stock entries, delete corresponding KPI records
        for stock_entry in canceled_stock_entries:
            frappe.db.sql("""
                DELETE FROM `tabProductivity Kpi Table`
                WHERE stock_entry_name = %s
            """, (stock_entry['name'],))
        
        print("Deleted KPI records for canceled Stock Entry names.", canceled_stock_entries)
        frappe.db.commit()
        frappe.logger().info("Deleted KPI records for canceled Stock Entry names.")
    except Exception as e:
        frappe.log_error(f"Error deleting KPI records for canceled Stock Entries: {str(e)}")

@frappe.whitelist()
def fetch_and_save_productivity_data():
    """Fetch productivity data and save unique records, also delete canceled stock entry data"""
    # First, remove records with canceled stock entry names
    delete_canceled_stock_entries()
    
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
                ste.Target_Profile
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
                    AND a.creation >= (CURDATE() - INTERVAL 1 DAY)
                    AND b.t_warehouse IS NOT NULL
                    AND b.t_warehouse != ''
                    AND b.serial_no IS NOT NULL
                    AND b.target_department != 'Stock Movement - NJ'
                    AND c.item_group IN ('Laptops', 'Chromebooks', 'Chromeboxes', 'Desktops', 'Full Set Desktops')
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
                ste.Source_dept IS NOT NULL 
            ORDER BY 
                ste.stock_entry_creation ASC;

    """
    
    # Fetch data from query
    data = frappe.db.sql(query, as_dict=True)
    total_records = len(data)
    successful_saves = 0
    
    for row in data:
        # Only create new record if it doesn't already exist
        if create_kpi_record(row):
            successful_saves += 1
            
    frappe.logger().info(f"Productivity KPI Update: Processed {total_records} records, Successfully saved {successful_saves} records")
    
    return {
        "total_records": total_records,
        "successful_saves": successful_saves
    }