# Copyright (c) 2025, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import math
import frappe
import pymysql
from frappe.model.document import Document
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error
logger = frappe.logger('nj_so_quanity', allow_site=True, file_count=1)

class SOQuantityCheck(Document):
        pass

SOQC_ITEM_GROUPS = [
    'Laptops(Bundle)',
    'Desktops(Bundle)',
    'Chromebooks(Bundle)',
    'AIO(Bundle)',
    'Chromeboxes(Bundle)',
    'Full Set Desktops(Bundle)',
    'MacBooks(Bundle)',
    'MacBooks',
    'Laptops',
    'Chromebooks',
    'Full Set Desktops',
    'Desktops',
    'AIO',
    'Chromeboxes'
]


def _safe_int(v, default=0) -> int:
    if v is None:
        return default
    s = str(v).strip()
    if s == "" or s.lower() == "none":
        return default
    try:
        return int(float(s))
    except Exception:
        return default


@frappe.whitelist()
def update_so_quantity_check(settings):
    """Update SO Quantity Check DocType with data from inventory and pending sales orders"""
    try:
        warehouses_list = []
        warehouses = settings.get('warehouses') or ''
        departments = settings.get('departments') or ''
        item_groups = settings.get('item_groups') or ''

        if warehouses:
            warehouses_list = [i.strip() for i in warehouses.split(',') if i.strip()]
        settings_item_groups = [i.strip() for i in item_groups.split(',') if i.strip()]
        item_groups_list = list(dict.fromkeys(settings_item_groups + SOQC_ITEM_GROUPS))
        departments_list = [d.strip() for d in departments.split(',') if d.strip()]

        warehouse_placeholders = ', '.join(['%s'] * len(warehouses_list))
        item_group_placeholders = ', '.join(['%s'] * len(item_groups_list))
        department_placeholders = ', '.join(['%s'] * len(departments_list))

        parent_warehouse_clause = f"OR b.warehouse IN ({warehouse_placeholders})" if warehouses_list else ""
        item_warehouse_clause = f"OR s.warehouse IN ({warehouse_placeholders})" if warehouses_list else ""
        # Step 1: Get inventory data from first query

        query = f"""
               WITH Parent_Stock AS (
                    SELECT 
                        TRIM(CONCAT(i.variant_of, ' ', COALESCE(proc.attribute_value, ''))) AS parent,
                        COUNT(b.serial_no) AS total_actual_qty_for_parent
                    FROM `tabItem` i
                    LEFT JOIN `tabSerial No` b ON i.item_code = b.item_code
                    LEFT JOIN `tabWarehouse` w ON b.warehouse = w.name
                    LEFT JOIN `tabSales Order` so ON b.sales_order_id = so.name
                    LEFT JOIN `tabItem Variant Attribute` proc
                        ON proc.parent = i.item_code
                        AND proc.attribute = 'Processor Type1'
                    WHERE 
                        b.item_group IN ({item_group_placeholders})
                        AND (w.department IN ({department_placeholders}) {parent_warehouse_clause})
                        AND b.is_replace = 0
                        AND (b.reserved_sales_order IS NULL OR b.reserved_sales_order = '')
                        AND (b.sales_order IS NULL OR b.sales_order = '')
                        AND (
                            b.return_reason IS NULL
                            OR b.return_reason = ''
                            OR b.return_reason != 'Repair'
                            OR (
                                b.return_reason = 'Repair'
                                AND (
                                    so.name IS NULL
                                    OR so.status = 'Closed'
                                    OR so.per_delivered = 100
                                )
                            )
                        )
                    GROUP BY i.variant_of, COALESCE(proc.attribute_value, '')
                ),

                Item_Stock AS (
                    SELECT 
                        s.item_code,
                        COUNT(s.serial_no) AS total_actual_qty_for_itemcode
                    FROM `tabSerial No` s
                    INNER JOIN `tabWarehouse` w ON w.name = s.warehouse
                    INNER JOIN `tabItem` i ON s.item_code = i.item_code
                    LEFT JOIN `tabSales Order` so ON s.sales_order_id = so.name
                    WHERE
                        i.item_group IN ({item_group_placeholders})
                        AND (w.department IN ({department_placeholders}) {item_warehouse_clause})
                        AND s.is_replace = 0
                        AND (s.reserved_sales_order IS NULL OR s.reserved_sales_order = '')
                        AND (s.sales_order IS NULL OR s.sales_order = '')
                        AND (
                            s.return_reason IS NULL
                            OR s.return_reason = ''
                            OR s.return_reason != 'Repair'
                            OR (
                                s.return_reason = 'Repair'
                                AND (
                                    so.name IS NULL
                                    OR so.status = 'Closed'
                                    OR so.per_delivered = 100
                                )
                            )
                        )
                    GROUP BY s.item_code
                ),

                Main_Data AS (
                    SELECT DISTINCT
                        i.shopify_variant_id,
                        i.item_code, 
                        i.item_group,
                        TRIM(CONCAT(i.variant_of, ' ', COALESCE(proc.attribute_value, ''))) AS parent,
                        ps.total_actual_qty_for_parent,
                        isq.total_actual_qty_for_itemcode
                    FROM `tabItem` i
                    LEFT JOIN `tabItem Variant Attribute` proc
                        ON proc.parent = i.item_code
                        AND proc.attribute = 'Processor Type1'
                    LEFT JOIN Parent_Stock ps ON ps.parent = TRIM(CONCAT(i.variant_of, ' ', COALESCE(proc.attribute_value, '')))
                    LEFT JOIN Item_Stock isq ON isq.item_code = i.item_code
                    WHERE i.item_group IN ({item_group_placeholders})
                )

                SELECT 
                    shopify_variant_id,
                    item_code, 
                    item_group,
                    total_actual_qty_for_itemcode AS actual_qty,
                    parent, 
                    total_actual_qty_for_parent
                FROM Main_Data
                ORDER BY shopify_variant_id, item_code;
            """

        params = (
            item_groups_list + departments_list + warehouses_list +
            item_groups_list + departments_list + warehouses_list +
            item_groups_list
        )

        inventory_data = frappe.db.sql(query, tuple(params), as_dict=True)

        stock_map = {}
        for row in inventory_data:
            item_code = row.get('item_code')
            if item_code:
                actual_qty = row.get('actual_qty', 0) or 0
                stock_map[item_code] = {
                    'parent1': row.get('parent', ''),
                    'actual_qty': actual_qty
                }

        # # Create a dictionary to store inventory data by item_code
        # stock_map = {}
        # for row in inventory_data:
        #     item_code = row.get('item_code')
        #     if item_code:
        #         # Ensure actual_qty is always a number, defaulting to 0 if None
        #         actual_qty = row.get('actual_qty', 0) or 0
        #         stock_map[item_code] = {
        #             'parent1': row.get('parent', ''),
        #             'actual_qty': actual_qty
        #         }

        # Step 2: Get sales order pending quantities from second query
        pending_so_data = frappe.db.sql("""
           SELECT 
                so_data.sales_order, so_data.item_code,
                so_data.pb_code, so_data.item_group,
                so_data.qty AS so_qty, IFNULL(dn_data.qty, 0) AS dn_qty,
                LEAST(so_data.qty, IFNULL(dn_data.qty, 0)) AS min_so_dn_qty,
                so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.qty, 0)) AS pending_qty,
                CONCAT(it2.variant_of, ' ', proc.attribute_value) AS variant_processor,

                SUM(so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.qty, 0))) 
                    OVER (PARTITION BY CONCAT(it2.variant_of, ' ', proc.attribute_value)) AS total_pending_by_variant,

                SUM(so_data.qty - LEAST(so_data.qty, IFNULL(dn_data.qty, 0))) 
                    OVER (PARTITION BY so_data.pb_code) AS total_pending_by_pb_code

            FROM (
                SELECT 
                    soi.parent AS sales_order, soi.item_code,
                    IFNULL(pb.item_code, soi.item_code) AS pb_code,
                    soi.qty, soi.item_group,
                    so.creation, soi.rate
                FROM `tabSales Order` so
                INNER JOIN `tabSales Order Item` soi ON so.name = soi.parent
                LEFT JOIN `tabProduct Bundle Item` pb ON soi.item_code = pb.parent
                LEFT JOIN `tabItem` it ON it.item_code = pb.item_code
                WHERE 
                    so.status NOT IN ('Closed', 'Completed', 'Cancelled')
                    AND so.docstatus = 1
                    AND so.creation > CURDATE() - INTERVAL 50 DAY
                    AND soi.item_group IN ('Laptops(Bundle)',
                                        'Desktops(Bundle)',
                                        'Chromebooks(Bundle)',
                                        'AIO(Bundle)',
                                        'Chromeboxes(Bundle)',
                                        'Full Set Desktops(Bundle)',
                                        'MacBooks(Bundle)',
                                        'MacBooks',
                                        'Laptops',
                                        'Chromebooks',
                                        'Full Set Desktops',
                                        'Desktops',
                                        'AIO',
                                        'Chromeboxes')
                    AND so.sale_type != 'Amazon'
                    AND (
                        pb.item_code IS NULL 
                        OR it.item_group IN ('Laptops(Bundle)',
                                        'Desktops(Bundle)',
                                        'Chromebooks(Bundle)',
                                        'AIO(Bundle)',
                                        'Chromeboxes(Bundle)',
                                        'Full Set Desktops(Bundle)',
                                        'MacBooks(Bundle)',
                                        'MacBooks',
                                        'Laptops',
                                        'Chromebooks',
                                        'Full Set Desktops',
                                        'Desktops',
                                        'AIO',
                                        'Chromeboxes')
                    )
            ) AS so_data

            LEFT JOIN (
                SELECT 
                    dni.against_sales_order,
                    dni.item_code, SUM(dni.qty) AS qty
                FROM `tabDelivery Note Item` dni
                WHERE 
                    dni.docstatus = 1 AND dni.qty > 0
                    AND dni.creation >= CURDATE() - INTERVAL 50 DAY
                    AND dni.item_group IN ('Laptops(Bundle)',
                                        'Desktops(Bundle)',
                                        'Chromebooks(Bundle)',
                                        'AIO(Bundle)',
                                        'Chromeboxes(Bundle)',
                                        'Full Set Desktops(Bundle)',
                                        'MacBooks(Bundle)',
                                        'MacBooks',
                                        'Laptops',
                                        'Chromebooks',
                                        'Full Set Desktops',
                                        'Desktops',
                                        'AIO',
                                        'Chromeboxes')
                GROUP BY dni.against_sales_order, dni.item_code
            ) AS dn_data 
            ON so_data.sales_order = dn_data.against_sales_order 
            AND so_data.item_code = dn_data.item_code

            LEFT JOIN `tabItem` it2 
                ON it2.item_code = so_data.pb_code

            LEFT JOIN `tabItem Variant Attribute` proc 
                ON proc.parent = it2.name
                AND proc.attribute LIKE '%Processor%'

            ORDER BY so_data.sales_order, so_data.item_code;
        """, as_dict=True)

        pending_qty_by_item = {}
        for row in pending_so_data:
            item_code = row.get('pb_code')
            if item_code:
                pending_qty = row.get('pending_qty', 0)
                if item_code in pending_qty_by_item:
                    pending_qty_by_item[item_code] += pending_qty
                else:
                    pending_qty_by_item[item_code] = pending_qty

        frappe.db.sql("DELETE FROM `tabSO Quantity Check`")
        frappe.db.commit()

        # Step 4: Insert ONLY items from inventory data
        # If they have pending SO, include that quantity
        count = 0
        now_time = frappe.utils.now()
        user = frappe.session.user or "Administrator"

        fields = [
            "name", "creation", "modified", "modified_by", "owner",
            "docstatus", "idx", "item_code", "parent1", "actual_qty",
            "so_quantity", "remaining_qty", "update_qty", "need_to_reduce",
            "remove_parent_qty", "update_qty2", "proportional_remove_qty", "sla", "estimated_time_of_dispatch"
        ]

        bundle_items = frappe.db.sql("SELECT DISTINCT item_code FROM `tabProduct Bundle Item`", as_dict=True)
        all_bundle_item_codes = {r.item_code for r in bundle_items if r.get('item_code')}
        all_item_codes = set(stock_map.keys()) | set(pending_qty_by_item.keys()) | all_bundle_item_codes
        values = []
        for item_code in all_item_codes:
            data = stock_map.get(item_code, {})
            parent1 = data.get('parent1', '')

            # Ensure we have numeric values for calculation
            actual_qty = data.get('actual_qty', 0) or 0
            so_quantity = pending_qty_by_item.get(item_code, 0) or 0

            # Calculate remaining quantity after pending sales orders
            remaining_qty = actual_qty - so_quantity

            # Calculate update_qty as MAX(remaining_qty, 0)
            update_qty = max(remaining_qty, 0)

            # Calculate need_to_reduce as IF(remaining_qty<0, ABS(remaining_qty), 0)
            need_to_reduce = abs(remaining_qty) if remaining_qty < 0 else 0

            # Since fields are of type "Data", convert values to string
            remaining_qty_str = str(remaining_qty)
            update_qty_str = str(update_qty)
            need_to_reduce_str = str(need_to_reduce)

            name = frappe.generate_hash(length=10)

            values.append((
                name, now_time, now_time, user, user,
                0, 0, item_code, parent1, str(actual_qty),
                str(so_quantity), remaining_qty_str, update_qty_str, need_to_reduce_str,
                "0", "0", None, 0, ""
            ))
            count += 1

        if values:
            frappe.db.bulk_insert("SO Quantity Check", fields, values)

        frappe.db.commit()
        log_error(f"SO Quantity Check updated for {count} items", "update_so_quantity_check", "Info")

        return True

    except pymysql.err.OperationalError as e:
        if e.args[0] == 2013:
            return False
        else:
            return False

    except Exception:
        log_error(frappe.get_traceback(), "update_so_quantity_check")
        return False

@frappe.whitelist()
def updting_sla_department():
    try:
        # 1. Fetch all pipeline departments (department_sequence >= 1) including sla_item_groups
        min_seq = 1
        depts_data = frappe.db.sql("""
            SELECT name, department_sequence, department_sla, sla_item_groups
            FROM `tabDepartment`
            WHERE department_sequence >= %s
            ORDER BY department_sequence ASC
        """, (min_seq,), as_dict=True)

        if not depts_data:
            return True

        # Override Packing & Dispatch SLA to 1 (case-insensitive name match)
        for d in depts_data:
            if "packing & dispatch" in (d.get("name") or "").lower():
                d["department_sla"] = 1

        def is_dept_applicable(dept_row, item_grp):
            dept_name = str(dept_row.get("name") or "").lower()
            if "packing & dispatch" in dept_name:
                return True
            if not item_grp:
                return False
            groups_str = str(dept_row.get("sla_item_groups") or "").strip()
            if not groups_str or groups_str.lower() in ("none", "null"):
                return False  # Strictly ignore if empty
            allowed = [g.strip().lower() for g in groups_str.split(",") if g.strip()]
            return item_grp.strip().lower() in allowed

        def calculate_total_sla(cand_dept_name, cand_dept_seq, item_grp=None):
            is_pd = "packing & dispatch" in (cand_dept_name or "").lower()
            cand_sla = 1 if is_pd else 0
            for d in depts_data:
                if d.get("name") == cand_dept_name:
                    cand_sla = d.get("department_sla", 0)
                    break

            app_depts = [d for d in depts_data if is_dept_applicable(d, item_grp)]
            seq_max_sla = {}
            for d in app_depts:
                seq = d.get("department_sequence")
                sla = d.get("department_sla") or 0
                if seq not in seq_max_sla or sla > seq_max_sla[seq]:
                    seq_max_sla[seq] = sla

            max_seq = max(seq_max_sla.keys()) if seq_max_sla else min_seq

            total = cand_sla
            for s in range(cand_dept_seq + 1, max_seq + 1):
                if s in seq_max_sla:
                    total += seq_max_sla[s]
            # Apply 10% buffer (rounded up to the next full day)
            return math.ceil(total * 1.10)

        # --- Priority 4: Parent Base Model (variant_of) ---
        p4_rows = frappe.db.sql("""
            SELECT 
                i.variant_of AS parent_item,
                SUBSTRING_INDEX(GROUP_CONCAT(d.name ORDER BY d.department_sequence DESC), ',', 1) AS cand_dept_name,
                MAX(d.department_sequence) AS cand_dept_seq
            FROM `tabSerial No` s
            INNER JOIN `tabWarehouse` w ON w.name = s.warehouse
            INNER JOIN `tabDepartment` d ON d.name = w.department
            INNER JOIN `tabItem` i ON i.item_code = s.item_code
            WHERE (s.reserved_sales_order IS NULL OR s.reserved_sales_order = '')
              AND s.is_replace = 0
              AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason != 'Repair')
              AND d.department_sequence >= %s
              AND i.variant_of IS NOT NULL AND i.variant_of != ''
            GROUP BY i.variant_of
        """, (min_seq,), as_dict=True)

        # --- Priority 3: Parent Model + Processor Reconfig (parent1) ---
        p3_rows = frappe.db.sql("""
            SELECT 
                TRIM(CONCAT(i.variant_of, ' ', COALESCE(proc.attribute_value, ''))) AS parent_key,
                SUBSTRING_INDEX(GROUP_CONCAT(d.name ORDER BY d.department_sequence DESC), ',', 1) AS cand_dept_name,
                MAX(d.department_sequence) AS cand_dept_seq
            FROM `tabSerial No` s
            INNER JOIN `tabWarehouse` w ON w.name = s.warehouse
            INNER JOIN `tabDepartment` d ON d.name = w.department
            INNER JOIN `tabItem` i ON i.item_code = s.item_code
            LEFT JOIN `tabItem Variant Attribute` proc
                ON proc.parent = i.item_code AND proc.attribute = 'Processor Type1'
            WHERE (s.reserved_sales_order IS NULL OR s.reserved_sales_order = '')
              AND s.is_replace = 0
              AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason != 'Repair')
              AND d.department_sequence >= %s
              AND i.variant_of IS NOT NULL AND i.variant_of != ''
            GROUP BY i.variant_of, COALESCE(proc.attribute_value, '')
        """, (min_seq,), as_dict=True)

        # --- Priority 2: Same Shopify Variant ID ---
        p2_rows = frappe.db.sql("""
            SELECT 
                pb.shopify_variant_id,
                SUBSTRING_INDEX(GROUP_CONCAT(d.name ORDER BY d.department_sequence DESC), ',', 1) AS cand_dept_name,
                MAX(d.department_sequence) AS cand_dept_seq
            FROM `tabSerial No` s
            INNER JOIN `tabWarehouse` w ON w.name = s.warehouse
            INNER JOIN `tabDepartment` d ON d.name = w.department
            INNER JOIN `tabProduct Bundle Item` pbi ON pbi.item_code = s.item_code
            INNER JOIN `tabProduct Bundle` pb ON pb.name = pbi.parent
            WHERE (s.reserved_sales_order IS NULL OR s.reserved_sales_order = '')
              AND s.is_replace = 0
              AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason != 'Repair')
              AND d.department_sequence >= %s
              AND pb.shopify_variant_id IS NOT NULL AND pb.shopify_variant_id != ''
              AND COALESCE(pb.disable, 0) = 0
            GROUP BY pb.shopify_variant_id
        """, (min_seq,), as_dict=True)

        # --- Priority 1: Exact Item Code ---
        p1_rows = frappe.db.sql("""
            SELECT 
                s.item_code,
                SUBSTRING_INDEX(GROUP_CONCAT(d.name ORDER BY d.department_sequence DESC), ',', 1) AS cand_dept_name,
                MAX(d.department_sequence) AS cand_dept_seq
            FROM `tabSerial No` s
            INNER JOIN `tabWarehouse` w ON w.name = s.warehouse
            INNER JOIN `tabDepartment` d ON d.name = w.department
            WHERE (s.reserved_sales_order IS NULL OR s.reserved_sales_order = '')
              AND s.is_replace = 0
              AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason != 'Repair')
              AND d.department_sequence >= %s
            GROUP BY s.item_code
        """, (min_seq,), as_dict=True)

        # 1. Reset all rows
        frappe.db.sql("UPDATE `tabSO Quantity Check` SET sla = 0, estimated_time_of_dispatch = ''")

        # Maps for quick lookup:
        p4_map = {r.parent_item: (r.cand_dept_name, r.cand_dept_seq) for r in p4_rows if r.get("parent_item")}
        p3_map = {r.parent_key: (r.cand_dept_name, r.cand_dept_seq) for r in p3_rows if r.get("parent_key")}
        p2_map = {str(r.shopify_variant_id).strip(): (r.cand_dept_name, r.cand_dept_seq) for r in p2_rows if r.get("shopify_variant_id")}
        p1_map = {r.item_code: (r.cand_dept_name, r.cand_dept_seq) for r in p1_rows if r.get("item_code")}

        # Map item_code -> shopify_variant_id
        bundle_variant_rows = frappe.db.sql("""
            SELECT pbi.item_code, pb.shopify_variant_id
            FROM `tabProduct Bundle Item` pbi
            INNER JOIN `tabProduct Bundle` pb ON pb.name = pbi.parent
            WHERE pb.shopify_variant_id IS NOT NULL AND pb.shopify_variant_id != ''
              AND COALESCE(pb.disable, 0) = 0
        """, as_dict=True)
        item_to_variant_map = {r.item_code: str(r.shopify_variant_id).strip() for r in bundle_variant_rows}

        # Fetch all rows from tabSO Quantity Check to calculate department-specific SLA per item_group
        soqc_rows = frappe.db.sql("""
            SELECT sqc.name, sqc.item_code, i.item_group, sqc.parent1, i.variant_of
            FROM `tabSO Quantity Check` sqc
            LEFT JOIN `tabItem` i ON i.item_code = sqc.item_code
        """, as_dict=True)

        for row in soqc_rows:
            item_code = row.get("item_code")
            item_grp = row.get("item_group")
            parent1 = row.get("parent1")
            variant_of = row.get("variant_of")
            variant_id = item_to_variant_map.get(item_code)

            sla_val = 0

            candidate_slas = []

            # Priority 1: Exact Item Code (0 extra days)
            if item_code in p1_map:
                cand_name, cand_seq = p1_map[item_code]
                candidate_slas.append(calculate_total_sla(cand_name, cand_seq, item_grp=item_grp))

            # Priority 2: Same Shopify Variant ID (+2 extra days)
            if variant_id and variant_id in p2_map:
                cand_name, cand_seq = p2_map[variant_id]
                candidate_slas.append(calculate_total_sla(cand_name, cand_seq, item_grp=item_grp) + 2)

            # Priority 3: Parent Model + Processor (+2 extra days)
            if parent1 and parent1 in p3_map:
                cand_name, cand_seq = p3_map[parent1]
                candidate_slas.append(calculate_total_sla(cand_name, cand_seq, item_grp=item_grp) + 2)

            # Priority 4: Parent Base Model variant_of (+2 extra days)
            if variant_of and variant_of in p4_map:
                cand_name, cand_seq = p4_map[variant_of]
                candidate_slas.append(calculate_total_sla(cand_name, cand_seq, item_grp=item_grp) + 2)

            sla_val = min(candidate_slas) if candidate_slas else 0

            if sla_val > 0:
                etd_val = f"{sla_val} Day" if sla_val == 1 else f"{sla_val} Days"
                frappe.db.sql("""
                    UPDATE `tabSO Quantity Check`
                    SET sla = %s, estimated_time_of_dispatch = %s
                    WHERE name = %s
                """, (sla_val, etd_val, row.get("name")))

        frappe.db.commit()
        return True

    except Exception:
        log_error(frappe.get_traceback(), "updting_sla_department")
        return False



def update_parent_quantity():
    try:
        # Update remove_parent_qty for all rows using a single joined UPDATE query
        frappe.db.sql("""
            UPDATE `tabSO Quantity Check` t
            INNER JOIN (
                SELECT parent1, SUM(CAST(need_to_reduce AS DECIMAL(10,2))) AS total
                FROM `tabSO Quantity Check`
                WHERE CAST(need_to_reduce AS DECIMAL(10,2)) > 0
                GROUP BY parent1
            ) s ON t.parent1 = s.parent1
            SET t.remove_parent_qty = CAST(s.total AS CHAR)
        """)

        frappe.db.commit()
        log_error("SO Quantity Check parent quantity updated", "update_parent_quantity", "Info")

        return True

    except pymysql.err.OperationalError as e:
        if e.args[0] == 2013:
            return False
        else:
            return False

    except Exception:
        log_error(frappe.get_traceback(), "update_parent_quantity")
        return False

def update_proportional_qty_and_updt_qty():
    try:
        frappe.db.sql("""
            UPDATE `tabSO Quantity Check` t
            INNER JOIN (
                SELECT parent1, 
                    SUM(CAST(COALESCE(NULLIF(update_qty, ''), '0') AS DECIMAL(10,2))) AS total_update_qty
                FROM `tabSO Quantity Check`
                GROUP BY parent1
            ) s ON t.parent1 = s.parent1
            SET 
                t.proportional_remove_qty = CAST(
                    IF(s.total_update_qty > 0, 
                        ROUND((CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS DECIMAL(10,2)) / s.total_update_qty) * CAST(COALESCE(NULLIF(t.remove_parent_qty, ''), '0') AS DECIMAL(10,2))), 
                        0
                    ) AS SIGNED
                ),
                t.pending_allocation_qty = IF(
                    CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS SIGNED) -
                    CAST(
                        IF(s.total_update_qty > 0,
                            ROUND((CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS DECIMAL(10,2)) / s.total_update_qty) * CAST(COALESCE(NULLIF(t.remove_parent_qty, ''), '0') AS DECIMAL(10,2))),
                            0
                        ) AS SIGNED
                    ) < 0,
                    CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS SIGNED) -
                    CAST(
                        IF(s.total_update_qty > 0,
                            ROUND((CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS DECIMAL(10,2)) / s.total_update_qty) * CAST(COALESCE(NULLIF(t.remove_parent_qty, ''), '0') AS DECIMAL(10,2))),
                            0
                        ) AS SIGNED
                    ),
                    t.pending_allocation_qty
                ),
                t.update_qty2 = CAST(
                    IF(CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS DECIMAL(10,2)) <= 0,
                        0,
                        GREATEST(
                            CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS SIGNED) - 
                            CAST(
                                IF(s.total_update_qty > 0, 
                                    ROUND((CAST(COALESCE(NULLIF(t.update_qty, ''), '0') AS DECIMAL(10,2)) / s.total_update_qty) * CAST(COALESCE(NULLIF(t.remove_parent_qty, ''), '0') AS DECIMAL(10,2))), 
                                    0
                                ) AS SIGNED
                            ),
                            0
                        )
                    ) AS SIGNED
                )
        """)

        frappe.db.commit()
        log_error("SO Quantity Check proportional quantity and update quantity updated", "update_proportional_qty_and_updt_qty", "Info")
        return True

    except pymysql.err.OperationalError as e:
        if e.args[0] == 2013:
            return False
        else:
            return False

    except Exception:
        log_error(frappe.get_traceback(), "update_proportional_qty_and_updt_qty")
        return False


def update_pre_order_qty(settings):
    """Update pre-order quantities using parent stock from Part waiting to Packing & Dispatch."""
    try:
        warehouses = settings.get("warehouses") or ""
        item_groups = settings.get("item_groups") or ""

        warehouses_list = [value.strip() for value in warehouses.split(",") if value.strip()]
        item_groups_list = [value.strip() for value in item_groups.split(",") if value.strip()]

        settings_item_groups = [value.strip() for value in item_groups.split(",") if value.strip()]
        item_groups_list = list(dict.fromkeys(settings_item_groups + SOQC_ITEM_GROUPS))

        if not item_groups_list:
            log_error(
                "Item groups are required to update pre-order quantities",
                "update_pre_order_qty",
                "Warning",
            )
            return False

        # Fetch minimum sequence threshold dynamically from 'Part waiting' department (seq >= 10)
        min_seq_row = frappe.db.sql("""
            SELECT department_sequence 
            FROM `tabDepartment` 
            WHERE name LIKE '%Part waiting%' 
            ORDER BY department_sequence ASC 
            LIMIT 1
        """, as_dict=True)
        min_seq = min_seq_row[0].get("department_sequence", 10) if min_seq_row else 10

        depts_list = frappe.db.sql_list("""
            SELECT name FROM `tabDepartment`
            WHERE department_sequence >= %s
        """, (min_seq,))

        if not depts_list:
            return True

        item_group_placeholders = ", ".join(["%s"] * len(item_groups_list))
        department_placeholders = ", ".join(["%s"] * len(depts_list))
        warehouse_placeholders = ", ".join(["%s"] * len(warehouses_list))
        parent_warehouse_clause = (
            f"OR b.warehouse IN ({warehouse_placeholders})" if warehouses_list else ""
        )

        update_query = f"""
            UPDATE `tabSO Quantity Check` t
            LEFT JOIN (
                SELECT
                    TRIM(CONCAT(i.variant_of, ' ', COALESCE(proc.attribute_value, ''))) AS parent,
                    COUNT(b.serial_no) AS total_actual_qty_for_parent
                FROM `tabItem` i
                LEFT JOIN `tabSerial No` b ON i.item_code = b.item_code
                LEFT JOIN `tabWarehouse` w ON b.warehouse = w.name
                LEFT JOIN `tabSales Order` so ON b.sales_order_id = so.name
                LEFT JOIN `tabItem Variant Attribute` proc
                    ON proc.parent = i.item_code
                    AND proc.attribute = 'Processor Type1'
                WHERE
                    b.item_group IN ({item_group_placeholders})
                    AND (w.department IN ({department_placeholders}) {parent_warehouse_clause})
                    AND b.is_replace = 0
                    AND (b.reserved_sales_order IS NULL OR b.reserved_sales_order = '')
                    AND (b.sales_order IS NULL OR b.sales_order = '')
                    AND (
                        b.return_reason IS NULL
                        OR b.return_reason = ''
                        OR b.return_reason != 'Repair'
                        OR (
                            b.return_reason = 'Repair'
                            AND (
                                so.name IS NULL
                                OR so.status = 'Closed'
                                OR so.per_delivered = 100
                            )
                        )
                    )
                GROUP BY i.variant_of, COALESCE(proc.attribute_value, '')
            ) ps ON t.parent1 = ps.parent
            SET t.pre_order_qty = IF(
                ps.total_actual_qty_for_parent IS NOT NULL AND ps.total_actual_qty_for_parent > 0,
                IF(
                    CAST(COALESCE(NULLIF(t.pending_allocation_qty, ''), '0') AS SIGNED) < 0,
                    LEAST(ABS(CAST(COALESCE(NULLIF(t.pending_allocation_qty, ''), '0') AS SIGNED)), ps.total_actual_qty_for_parent),
                    ps.total_actual_qty_for_parent
                ),
                0
            )
        """

        params = item_groups_list + depts_list + warehouses_list
        frappe.db.sql(update_query, tuple(params))
        frappe.db.commit()
        log_error(
            "SO Quantity Check pre-order quantity updated using parent stock",
            "update_pre_order_qty",
            "Info",
        )
        return True

    except pymysql.err.OperationalError:
        return False

    except Exception:
        log_error(frappe.get_traceback(), "update_pre_order_qty")
        return False


def update_minimum_qty_after_proportional() -> bool:
    """
    Applies minimum qty on top of update_qty2 (post proportional removal) WITHOUT increasing total qty.

    Rule:
      - If is_minimum_qty_is_required == 1 and min_qty > 0 and update_qty2 < min_qty
        => we try to raise that row to min_qty.
      - The extra qty needed is taken by reducing other rows within SAME parent1 group.
        * Non-required rows can be reduced down to 0
        * Required rows can be reduced down to their min_qty (not below min)

    Safety check (your manager’s point):
      - We apply mins only if the group has enough reducible qty.
      - If not enough => skip mins for that parent1 (do NOT create qty).
    """

    try:
        # parents where min is required and current qty is below min
        parents = frappe.db.sql(
            """
            SELECT parent1
            FROM `tabSO Quantity Check`
            WHERE
                COALESCE(is_minimum_qty_is_required, 0) = 1
                AND COALESCE(min_qty, 0) > 0
                AND CAST(COALESCE(NULLIF(update_qty2, ''), '0') AS UNSIGNED) < COALESCE(min_qty, 0)
            GROUP BY parent1
            """,
            as_dict=True,
        )

        if not parents:
            return True

        for pr in parents:
            parent1 = pr.get("parent1")
            if not parent1:
                continue

            rows = frappe.db.sql(
                """
                SELECT name, item_code, update_qty2, is_minimum_qty_is_required, min_qty
                FROM `tabSO Quantity Check`
                WHERE parent1 = %s
                """,
                (parent1,),
                as_dict=True,
            )

            # Parse current quantities
            items = []
            for r in rows:
                qty = _safe_int(r.get("update_qty2"), 0)
                min_req = 1 if _safe_int(r.get("is_minimum_qty_is_required"), 0) == 1 else 0
                min_qty = _safe_int(r.get("min_qty"), 0)
                items.append({
                    "name": r.get("name"),
                    "item_code": r.get("item_code"),
                    "qty": qty,
                    "min_req": min_req,
                    "min_qty": min_qty,
                    "new_qty": qty,  # will update
                })

            # Required items and deficits
            required = [x for x in items if x["min_req"] == 1 and x["min_qty"] > 0]
            if not required:
                continue

            deficits = []
            total_deficit = 0
            for x in required:
                if x["qty"] < x["min_qty"]:
                    d = x["min_qty"] - x["qty"]
                    deficits.append((x, d))
                    total_deficit += d

            if total_deficit <= 0:
                continue

            # Donors: where can we reduce qty from?
            donors = []
            reducible_total = 0

            for x in items:
                if x["min_req"] == 1 and x["min_qty"] > 0:
                    # required can donate only above its min
                    excess = max(x["qty"] - x["min_qty"], 0)
                else:
                    # non-required can donate down to 0
                    excess = max(x["qty"], 0)

                if excess > 0:
                    donors.append((x, excess))
                    reducible_total += excess

            # ✅ Safety check (this is why manager told sum(update_qty) vs sum(min_qty_to_add))
            # If we cannot "fund" the minimum deficits by reducing others, SKIP this parent
            if reducible_total < total_deficit:
                log_error(
                    f"[MIN-QTY] Skipped parent={parent1}: need={total_deficit}, reducible={reducible_total}",
                    "update_minimum_qty_after_proportional",
                    "Warning",
                )
                continue

            # Step A: raise required items to min (consume deficit)
            for x, d in deficits:
                x["new_qty"] = x["qty"] + d  # becomes min_qty exactly

            # Step B: reduce donors to keep total constant
            remaining = total_deficit

            # reduce largest donors first
            donors.sort(key=lambda t: t[1], reverse=True)

            for x, excess in donors:
                if remaining <= 0:
                    break

                take = min(excess, remaining)
                x["new_qty"] = x["new_qty"] - take
                remaining -= take

            # Apply updates
            for x in items:
                if x["name"] and x["new_qty"] != x["qty"]:
                    frappe.db.set_value(
                        "SO Quantity Check",
                        x["name"],
                        "update_qty2",
                        str(int(max(x["new_qty"], 0)))
                    )

            frappe.db.commit()

        log_error("Minimum qty applied after proportional qty", "update_minimum_qty_after_proportional", "Info")
        return True

    except pymysql.err.OperationalError as e:
        # mysql connection lost
        if e.args and e.args[0] == 2013:
            return False
        return False

    except Exception:
        log_error(frappe.get_traceback(), "update_minimum_qty_after_proportional")
        return False
