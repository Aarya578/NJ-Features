import frappe
from frappe import _
import traceback
from frappe.model.document import Document

class Productivity(Document):
    pass

@frappe.whitelist()
def fetch_productivity_data():
    try:
        query="""
            INSERT INTO `tabProductivity` (
                name,
                creation,
                modified,
                serial_no,
                stock_entry,
                stock_entry_creation,
                item_group,
                item_code,
                qty,
                source_warehouse,
                target_warehouse,
                source_department,
                target_department,
                source_role_profile,
                target_role_profile,
                itemgroup_weightage_value,
                wtd_qty,
                `user`,
                department_production,
                profile_production,
                match_production_flag
            )
            SELECT 
                UUID() AS name,              -- unique name
                NOW(2) AS creation,
                NOW(2) AS modified,
                ste.serial_no,
                ste.stock_entry_name AS stock_entry,
                ste.stock_entry_creation,
                ste.item_group,
                ste.item_code,
                ste.qty,
                ste.Src_warehouse AS source_warehouse,
                ste.t_warehouse AS target_warehouse,
                ste.Source_dept AS source_department,
                ste.Target_Dept AS target_department,
                ste.Source_Profile AS source_role_profile,
                ste.Target_Profile AS target_role_profile,
                wt.value AS itemgroup_weightage_value,
                ste.qty * wt.value AS wtd_qty,
                ste.owner AS `user`,
                CASE 
                    WHEN Pd.target_department = ste.Target_Dept THEN 1 
                    ELSE 0 
                END AS department_production,
                CASE 
                    WHEN ste.Target_Profile = Rp.target_profile THEN 1 
                    ELSE 0 
                END AS profile_production,
                CASE 
                    WHEN Pd.target_department = ste.Target_Dept 
                        OR ste.Target_Profile = Rp.target_profile THEN 1
                    ELSE 0
                END AS match_production_flag
            FROM (
                SELECT 
                    a.owner,
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
                FROM `tabStock Entry` a
                INNER JOIN `tabStock Entry Detail` b 
                    ON a.creation >= (CURRENT_DATE())
                    AND a.purpose = 'Material Transfer'
                    AND a.docstatus = 1
                    AND a.name = b.parent
                INNER JOIN `tabItem` c ON b.item_code = c.name
                WHERE
                    b.t_warehouse IS NOT NULL
                    AND b.t_warehouse != ''
                    AND b.serial_no IS NOT NULL
                    AND b.target_department != 'Stock Movement - NJ'
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
            WHERE 
                ste.Source_dept IS NOT NULL
                AND (
                    Pd.target_department = ste.Target_Dept
                    OR ste.Target_Profile = Rp.target_profile
                )
            ORDER BY ste.stock_entry_creation ASC;
        """
        frappe.db.sql(query)
        return "Data Fetched Successfully"
    except Exception as e:
        frappe.logger().error(f'Error in fetch_productivity_data: {e}')


@frappe.whitelist()
def fetch_data_kpi_dashboard(user):
    try:
        target_query="""
            SELECT 
                SUM(t.target) AS target,
                t.role_profile
            FROM (
                SELECT dcl.target, dcl.role_profile,dcl.user_name
                FROM `tabDepartment Change Log` as dcl left join 
                `tabEmployee` as emp on emp.user_id=dcl.user_name 
                left join `tabEmployee Checkin` as empc on empc.employee = concat("EMP-",emp.emp_id) AND DATE(empc.creation) = DATE(dcl.creation)
                WHERE user_name = %s
                AND dcl.owner = 'Administrator'
                AND dcl.creation >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01') and dcl.creation < current_date()
                AND empc.name is not null
                AND WEEKDAY(dcl.creation) != 6
                GROUP BY DATE(dcl.creation)
            ) AS t
            GROUP BY t.role_profile;
        """
        achived_query="""
            SELECT sum(wtd_qty) as achieved, source_role_profile as role_profile from `tabProductivity` where 
                user=%s and stock_entry_creation>=DATE_FORMAT(CURDATE(), '%%Y-%%m-01') and stock_entry_creation < current_date()
                group by source_role_profile;
            """     
     
        target_result= frappe.db.sql(target_query, user, as_dict=1)
        achived_result= frappe.db.sql(achived_query, user, as_dict=1)
        if target_result and achived_result:
            if len(target_result) >= len(achived_result):
                for i in range(len(target_result)):
                    for j in range(len(achived_result)):
                        if target_result[i].role_profile == achived_result[j].role_profile:
                            target_result[i]['achieved'] = achived_result[j].achieved
                return target_result
            else:
                for i in range(len(achived_result)):
                    for j in range(len(target_result)):
                        if target_result[j].role_profile == achived_result[i].role_profile:
                            achived_result[i]['target'] = target_result[j].target
                return achived_result
        else:
            frappe.logger().error(f'NO DATA in fetch_data_kpi_dashboard for {user}')
                    
    except Exception as e:
        frappe.logger().error(f'Error in fetch_data_kpi_dashboard: {e}')

    
