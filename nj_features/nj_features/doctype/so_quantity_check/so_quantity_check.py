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
        try:
            frappe.db.sql("SET SESSION wait_timeout = 600")
            frappe.db.sql("SET SESSION net_read_timeout = 600")
            frappe.db.sql("SET SESSION net_write_timeout = 600")
        except Exception:
            pass

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
                        COUNT(b.name) AS total_actual_qty_for_parent
                    FROM `tabItem` i
                    LEFT JOIN `tabSerial No` b ON (i.name = b.item_code OR i.item_code = b.item_code)
                    LEFT JOIN `tabWarehouse` w ON b.warehouse = w.name
                    LEFT JOIN `tabSales Order` so ON b.sales_order_id = so.name
                    LEFT JOIN `tabItem Variant Attribute` proc
                        ON proc.parent = i.name
                        AND proc.attribute = 'Processor Type1'
                    WHERE 
                        COALESCE(b.item_group, i.item_group) IN ({item_group_placeholders})
                        AND (w.department IN ({department_placeholders}) {parent_warehouse_clause})
                        AND b.status = 'Active'
                        AND b.is_replace = 0
                        AND (b.reserved_sales_order IS NULL OR b.reserved_sales_order = '')
                        AND (b.sales_order IS NULL OR b.sales_order = '')
                        AND NOT EXISTS (
                            SELECT 1 FROM `tabDelivery Note Item` dni
                            JOIN `tabDelivery Note` dn ON dn.name = dni.parent
                            WHERE dni.serial_no = b.name AND dni.docstatus = 1
                              AND dn.is_return = 0
                              AND dn.status NOT IN ('Return Issued', 'Closed')
                              AND dn.name NOT IN (SELECT return_against FROM `tabDelivery Note` WHERE is_return = 1 AND docstatus = 1 AND return_against IS NOT NULL AND return_against != '')
                        )
                        AND (b.return_reason IS NULL OR b.return_reason = '' OR b.return_reason NOT IN ('Repair', 'Replace'))
                    GROUP BY i.variant_of, COALESCE(proc.attribute_value, '')
                ),

                Item_Stock AS (
                    SELECT 
                        s.item_code,
                        COUNT(s.name) AS total_actual_qty_for_itemcode
                    FROM `tabSerial No` s
                    INNER JOIN `tabWarehouse` w ON w.name = s.warehouse
                    INNER JOIN `tabItem` i ON (s.item_code = i.name OR s.item_code = i.item_code)
                    LEFT JOIN `tabSales Order` so ON s.sales_order_id = so.name
                    WHERE
                        COALESCE(s.item_group, i.item_group) IN ({item_group_placeholders})
                        AND (w.department IN ({department_placeholders}) {item_warehouse_clause})
                        AND s.status = 'Active'
                        AND s.is_replace = 0
                        AND (s.reserved_sales_order IS NULL OR s.reserved_sales_order = '')
                        AND (s.sales_order IS NULL OR s.sales_order = '')
                        AND NOT EXISTS (
                            SELECT 1 FROM `tabDelivery Note Item` dni
                            JOIN `tabDelivery Note` dn ON dn.name = dni.parent
                            WHERE dni.serial_no = s.name AND dni.docstatus = 1
                              AND dn.is_return = 0
                              AND dn.status NOT IN ('Return Issued', 'Closed')
                              AND dn.name NOT IN (SELECT return_against FROM `tabDelivery Note` WHERE is_return = 1 AND docstatus = 1 AND return_against IS NOT NULL AND return_against != '')
                        )
                        AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason NOT IN ('Repair', 'Replace'))
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

        # Step 2: Get sales order pending quantities with line-level delivery matching,
        hardware_groups_tuple = tuple(item_groups_list)

        # Imported inside the function: reservation_service imports
        # overrides.sales_order at module level, so a top-level import here risks
        # an import cycle.
        from nj_features.services.reservation_service import RTO_EXCLUSION_SQL

        pending_so_data = frappe.db.sql(f"""
            SELECT 
                so_comp.sales_order,
                so_comp.component_item_code,
                SUM(GREATEST(0, so_comp.line_ordered_qty - IFNULL(dn_line.line_delivered_qty, 0) * so_comp.multiplier)) AS total_pending_qty
            FROM (
                -- Direct stock items
                SELECT
                    so.name AS sales_order,
                    soi.name AS so_detail,
                    soi.item_code AS component_item_code,
                    soi.qty AS line_ordered_qty,
                    1.0 AS multiplier
                FROM `tabSales Order` so
                INNER JOIN `tabSales Order Item` soi ON so.name = soi.parent
                INNER JOIN `tabItem` it ON it.item_code = soi.item_code
                WHERE
                    so.status NOT IN ('Closed', 'Completed', 'Cancelled')
                    AND so.docstatus = 1
                    AND IFNULL(so.per_delivered, 0) < 100
                    AND so.sale_type != 'Amazon'
                    AND IFNULL(it.is_stock_item, 0) = 1
                    AND it.item_group IN %(hardware_groups)s
                    AND so.name NOT IN (
                        SELECT DISTINCT sales_order
                        FROM `tabNJ Refund`
                        WHERE refund_status IN ('Paid', 'Refunded', 'Initiated')
                          AND docstatus = 1
                          AND sales_order IS NOT NULL
                          AND sales_order != ''
                    )
                    -- An RTO'd order is not pending demand: the parcel came back,
                    -- so counting it here subtracted a unit from what Shopify was
                    -- allowed to advertise, for an order that will never ship.
                    -- Same list the allocator uses - see RTO_EXCLUSION_SQL. This
                    -- query is duplicated in shopify_inventory_targeted.py; the
                    -- two decide the same number and must stay in step.
                    {RTO_EXCLUSION_SQL}
                    AND (
                        so.creation > CURDATE() - INTERVAL 100 DAY
                        OR so.name IN (
                            SELECT DISTINCT dni_ret.against_sales_order
                            FROM `tabDelivery Note Item` dni_ret
                            INNER JOIN `tabDelivery Note` dn_ret ON dn_ret.name = dni_ret.parent
                            WHERE dn_ret.docstatus = 1 AND dn_ret.is_return = 1 AND dn_ret.posting_date > CURDATE() - INTERVAL 100 DAY
                        )
                    )

                UNION ALL

                -- Product Bundle component items
                SELECT
                    so.name AS sales_order,
                    soi.name AS so_detail,
                    pbi.item_code AS component_item_code,
                    (soi.qty * COALESCE(pbi.qty, 1)) AS line_ordered_qty,
                    COALESCE(pbi.qty, 1) AS multiplier
                FROM `tabSales Order` so
                INNER JOIN `tabSales Order Item` soi ON so.name = soi.parent
                INNER JOIN `tabItem` it_bundle ON it_bundle.item_code = soi.item_code
                INNER JOIN `tabProduct Bundle Item` pbi ON pbi.parent = soi.item_code
                INNER JOIN `tabItem` it_comp ON it_comp.item_code = pbi.item_code
                WHERE
                    so.status NOT IN ('Closed', 'Completed', 'Cancelled')
                    AND so.docstatus = 1
                    AND IFNULL(so.per_delivered, 0) < 100
                    AND so.sale_type != 'Amazon'
                    AND IFNULL(it_bundle.is_stock_item, 0) = 0
                    AND it_comp.item_group IN %(hardware_groups)s
                    AND so.name NOT IN (
                        SELECT DISTINCT sales_order
                        FROM `tabNJ Refund`
                        WHERE refund_status IN ('Paid', 'Refunded', 'Initiated')
                          AND docstatus = 1
                          AND sales_order IS NOT NULL
                          AND sales_order != ''
                    )
                    -- An RTO'd order is not pending demand: the parcel came back,
                    -- so counting it here subtracted a unit from what Shopify was
                    -- allowed to advertise, for an order that will never ship.
                    -- Same list the allocator uses - see RTO_EXCLUSION_SQL. This
                    -- query is duplicated in shopify_inventory_targeted.py; the
                    -- two decide the same number and must stay in step.
                    {RTO_EXCLUSION_SQL}
                    AND (
                        so.creation > CURDATE() - INTERVAL 100 DAY
                        OR so.name IN (
                            SELECT DISTINCT dni_ret.against_sales_order
                            FROM `tabDelivery Note Item` dni_ret
                            INNER JOIN `tabDelivery Note` dn_ret ON dn_ret.name = dni_ret.parent
                            WHERE dn_ret.docstatus = 1 AND dn_ret.is_return = 1 AND dn_ret.posting_date > CURDATE() - INTERVAL 100 DAY
                        )
                    )
            ) AS so_comp

            LEFT JOIN (
                SELECT
                    dni.so_detail,
                    SUM(dni.qty) AS line_delivered_qty
                FROM `tabDelivery Note Item` dni
                WHERE
                    dni.docstatus = 1
                    AND dni.so_detail IS NOT NULL
                    AND dni.so_detail != ''
                GROUP BY dni.so_detail
            ) AS dn_line ON so_comp.so_detail = dn_line.so_detail

            GROUP BY so_comp.sales_order, so_comp.component_item_code
            HAVING total_pending_qty > 0
        """, {"hardware_groups": hardware_groups_tuple}, as_dict=True)

        # Step 2.5: Map allocated/reserved serials per (sales_order, item_code)
        # to prevent double-deduction. An order whose machine is already reserved
        # (whether in Packing, FQC, or upstream in QC/L2/Testing) is covered by that serial
        # and must NOT deduct from unreserved sellable stock in ready departments.
        # Delivered units (sales_order) are handled by line_delivered_qty and excluded here.
        # Reject and Scrap departments/warehouses are strictly excluded from coverage.
        alloc_query = f"""
            SELECT 
                s.reserved_sales_order,
                IFNULL(NULLIF(s.to_make, ''), s.item_code) AS item_code,
                COUNT(s.name) AS allocated_qty
            FROM `tabSerial No` s
            INNER JOIN `tabWarehouse` w ON w.name = s.warehouse
            INNER JOIN `tabItem` i ON (s.item_code = i.name OR s.item_code = i.item_code)
            WHERE s.reserved_sales_order IS NOT NULL 
              AND s.reserved_sales_order != ''
              AND s.status = 'Active'
              AND s.is_replace = 0
              AND COALESCE(s.item_group, i.item_group) IN ({item_group_placeholders})
              AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason NOT IN ('Repair', 'Replace'))
              AND (w.department NOT LIKE '%%%%Reject%%%%' AND w.department NOT LIKE '%%%%Scrap%%%%')
              AND (s.warehouse NOT LIKE '%%%%Reject%%%%' AND s.warehouse NOT LIKE '%%%%Scrap%%%%')
            GROUP BY s.reserved_sales_order, IFNULL(NULLIF(s.to_make, ''), s.item_code)
        """
        alloc_params = tuple(item_groups_list)
        allocated_serials = frappe.db.sql(alloc_query, alloc_params, as_dict=True)
        alloc_map = {(r.reserved_sales_order, r.item_code): r.allocated_qty for r in allocated_serials}

        pending_qty_by_item = {}
        for row in pending_so_data:
            so_name = row.get("sales_order")
            item_code = row.get("component_item_code")
            if item_code:
                raw_pending = row.get("total_pending_qty", 0) or 0
                allocated_qty = alloc_map.get((so_name, item_code), 0)
                # Unallocated pending demand only, deducted once per (sales_order, component_item)
                unallocated_pending = max(0, raw_pending - allocated_qty)
                if unallocated_pending > 0:
                    pending_qty_by_item[item_code] = pending_qty_by_item.get(item_code, 0) + unallocated_pending

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
        log_error(f"OperationalError in update_so_quantity_check: {e}", "update_so_quantity_check")
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

        # Override in code: Packing & Dispatch = 1, Sales = 1, Inward = 1, intermediate depts capped at 15
        for d in depts_data:
            d_name = (d.get("name") or "").lower()
            if "packing & dispatch" in d_name or "sales" in d_name:
                d["department_sla"] = 1
            elif "inward" in d_name:
                d["department_sla"] = 1
            else:
                d["department_sla"] = min(max(int(d.get("department_sla") or 0), 0), 15)

        def is_dept_applicable(dept_row, item_grp):
            dept_name = str(dept_row.get("name") or "").lower()
            if "packing & dispatch" in dept_name or "sales" in dept_name:
                return True
            if not item_grp:
                return False
            groups_str = str(dept_row.get("sla_item_groups") or "").strip()
            if not groups_str or groups_str.lower() in ("none", "null"):
                return False  # Strictly ignore if empty
            allowed = [g.strip().lower() for g in groups_str.split(",") if g.strip()]
            return item_grp.strip().lower() in allowed

        def calculate_total_sla(cand_dept_name, cand_dept_seq, item_grp=None):
            d_name_lower = (cand_dept_name or "").lower()
            if "packing & dispatch" in d_name_lower or "sales" in d_name_lower:
                return 1
            # No early return for Inward. Inward's OWN SLA is 1 day (set above),
            # but a machine in Inward still has the whole line ahead of it, so it
            # takes the normal path: Inward's 1 day + every later department.
            # A `return 1` here (2026-09-28) made "machine just arrived" and "no
            # machine at all" (the fallback below starts from Inward) both read
            # as 1-day dispatch: 5,663 zero-stock listings showed "1 Day" and the
            # ETD > 3 pre-order gate switched off on that false figure.

            cand_sla = 0
            for d in depts_data:
                if d.get("name") == cand_dept_name:
                    cand_sla = d.get("department_sla", 0)
                    break

            app_depts = [d for d in depts_data if is_dept_applicable(d, item_grp)]
            seq_max_sla = {}
            for d in app_depts:
                if "inward" in (d.get("name") or "").lower():
                    continue
                seq = d.get("department_sequence")
                sla = d.get("department_sla") or 0
                if seq not in seq_max_sla or sla > seq_max_sla[seq]:
                    seq_max_sla[seq] = sla

            max_seq = max(seq_max_sla.keys()) if seq_max_sla else min_seq

            total = cand_sla
            for s in range(cand_dept_seq + 1, max_seq + 1):
                if s in seq_max_sla:
                    total += seq_max_sla[s]
            return min(math.ceil(total * 1.10), 45)

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
              AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason NOT IN ('Repair', 'Replace'))
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
              AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason NOT IN ('Repair', 'Replace'))
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
              AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason NOT IN ('Repair', 'Replace'))
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
              AND (s.return_reason IS NULL OR s.return_reason = '' OR s.return_reason NOT IN ('Repair', 'Replace'))
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

            if candidate_slas:
                sla_val = min(candidate_slas)
            else:
                # Fallback to full pipeline lead time from Inward (Seq 1)
                sla_val = calculate_total_sla("Inward  - NJ", min_seq, item_grp=item_grp)
                if not sla_val or sla_val <= 0:
                    sla_val = 14

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
        # Update remove_parent_qty for all rows using a LEFT JOIN so cleared shortfalls reset to '0'
        frappe.db.sql("""
            UPDATE `tabSO Quantity Check` t
            LEFT JOIN (
                SELECT parent1, SUM(CAST(need_to_reduce AS DECIMAL(10,2))) AS total
                FROM `tabSO Quantity Check`
                WHERE CAST(need_to_reduce AS DECIMAL(10,2)) > 0
                GROUP BY parent1
            ) s ON t.parent1 = s.parent1
            SET t.remove_parent_qty = CAST(COALESCE(s.total, 0) AS CHAR)
            WHERE t.parent1 IS NOT NULL AND t.parent1 != ''
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

def distribute_proportional_deduction(rows, total_remove_qty):
    """
    Distributes total_remove_qty across sibling rows of a parent using the
    Largest Remainder (Hamilton's) method instead of independent ROUND(),
    preventing over-deduction where multiple siblings round 0.5 up.

    rows: list of dicts with:
        name: str
        item_code: str
        update_qty: int/float/str
        pending_allocation_qty: int/float/str/None

    total_remove_qty: numeric (remove_parent_qty)

    Returns: list of dicts with:
        name: str
        proportional_remove_qty: int
        update_qty2: int
        pending_allocation_qty: int
    """
    try:
        remove_qty = int(float(total_remove_qty or 0))
    except (ValueError, TypeError):
        remove_qty = 0

    parsed_rows = []
    total_update_qty = 0
    for r in rows:
        try:
            u = int(float(r.get("update_qty") or 0))
        except (ValueError, TypeError):
            u = 0
        u_pos = max(0, u)
        total_update_qty += u_pos
        try:
            p_alloc = int(float(r.get("pending_allocation_qty") or 0))
        except (ValueError, TypeError):
            p_alloc = 0
        parsed_rows.append({
            "name": r.get("name"),
            "item_code": r.get("item_code") or "",
            "u_pos": u_pos,
            "raw_u": u,
            "p_alloc": p_alloc,
        })

    if remove_qty <= 0:
        results = []
        for r in parsed_rows:
            results.append({
                "name": r["name"],
                "proportional_remove_qty": 0,
                "update_qty2": r["u_pos"],
                "pending_allocation_qty": r["p_alloc"],
            })
        return results

    if total_update_qty <= 0:
        results = []
        for r in parsed_rows:
            results.append({
                "name": r["name"],
                "proportional_remove_qty": 0,
                "update_qty2": 0,
                "pending_allocation_qty": r["p_alloc"],
            })
        return results

    # Largest Remainder (Hamilton's) distribution across rows with u_pos > 0
    allocations = {}
    base_sum = 0
    candidates = []

    for r in parsed_rows:
        u_pos = r["u_pos"]
        if u_pos > 0:
            exact_share = (float(u_pos) / float(total_update_qty)) * float(remove_qty)
            base = int(exact_share)
            remainder = exact_share - base
            allocations[r["name"]] = base
            base_sum += base
            candidates.append({
                "name": r["name"],
                "item_code": r["item_code"],
                "u_pos": u_pos,
                "remainder": remainder,
            })
        else:
            allocations[r["name"]] = 0

    # Distribute the remaining units to rows with the largest fractional remainders.
    # Ties are broken by larger update_qty, then stable item_code and name.
    surplus = remove_qty - base_sum
    if surplus > 0:
        candidates.sort(
            key=lambda c: (-c["remainder"], -c["u_pos"], str(c["item_code"]), str(c["name"]))
        )
        for i in range(min(surplus, len(candidates))):
            allocations[candidates[i]["name"]] += 1

    results = []
    for r in parsed_rows:
        p_remove = allocations.get(r["name"], 0)
        net = r["raw_u"] - p_remove
        u_qty2 = max(0, net)
        p_alloc = net if net < 0 else r["p_alloc"]
        results.append({
            "name": r["name"],
            "proportional_remove_qty": p_remove,
            "update_qty2": u_qty2,
            "pending_allocation_qty": p_alloc,
        })

    return results


def update_proportional_qty_and_updt_qty():
    try:
        # Step 1: Fast SQL update for rows with no parent deduction needed.
        frappe.db.sql("""
            UPDATE `tabSO Quantity Check`
            SET proportional_remove_qty = '0',
                update_qty2 = CAST(GREATEST(CAST(COALESCE(NULLIF(update_qty, ''), '0') AS SIGNED), 0) AS CHAR)
            WHERE remove_parent_qty IS NULL 
               OR remove_parent_qty = '' 
               OR remove_parent_qty = '0'
               OR CAST(remove_parent_qty AS DECIMAL(10,2)) <= 0
        """)

        # Step 2: For rows belonging to parents with a positive shortfall (remove_parent_qty > 0),
        # distribute the deduction using the Largest Remainder (Hamilton's) method.
        # This fixes the double-subtraction bug where independent ROUND(0.5)
        # on siblings removed multiple units for a single-unit deficit.
        deficit_rows = frappe.db.sql("""
            SELECT name, parent1, item_code, update_qty, need_to_reduce, pending_allocation_qty
            FROM `tabSO Quantity Check`
            WHERE parent1 IS NOT NULL AND parent1 != ''
              AND CAST(COALESCE(NULLIF(remove_parent_qty, ''), '0') AS DECIMAL(10,2)) > 0
        """, as_dict=True)

        if deficit_rows:
            parents_map = {}
            for r in deficit_rows:
                parents_map.setdefault(r["parent1"], []).append(r)

            for parent1, p_rows in parents_map.items():
                remove_parent_qty = int(sum(float(r.get("need_to_reduce") or 0) for r in p_rows))
                allocations = distribute_proportional_deduction(p_rows, remove_parent_qty)
                for item_alloc in allocations:
                    frappe.db.sql("""
                        UPDATE `tabSO Quantity Check`
                        SET remove_parent_qty = %s,
                            proportional_remove_qty = %s,
                            update_qty2 = %s,
                            pending_allocation_qty = %s
                        WHERE name = %s
                    """, (
                        str(remove_parent_qty),
                        str(item_alloc["proportional_remove_qty"]),
                        str(item_alloc["update_qty2"]),
                        item_alloc["pending_allocation_qty"],
                        item_alloc["name"]
                    ))

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


def _pre_order_config_filters(settings):
    """Shared WHERE fragments for the pre-order WIP pool.

    A machine counts towards pre-order only while it is inside the build
    pipeline (between 'Part waiting' and 'Adaptor'), still free, and not
    already promised to anybody.
    """
    warehouses = settings.get("warehouses") or ""
    item_groups = settings.get("item_groups") or ""

    warehouses_list = [v.strip() for v in warehouses.split(",") if v.strip()]
    settings_item_groups = [v.strip() for v in item_groups.split(",") if v.strip()]
    item_groups_list = list(dict.fromkeys(settings_item_groups + SOQC_ITEM_GROUPS))

    return warehouses_list, item_groups_list


def get_pre_order_pools(settings, parents=None):
    """Count free machines per parent + Processor.

    The pool is keyed on parent + Processor deliberately. RAM and storage are
    FITTED DURING THE BUILD, so a chassis sitting in L2 is not yet an 8/256 or
    a 16/512 - it becomes whichever spec the parts going into it decide. Keying
    the pre-order pool on RAM/Storage splits it on an attribute that has not
    been chosen yet, which strands real build capacity across several
    sub-threshold buckets and hides models that can genuinely be supplied.

    Scope: the build window only - departments sequenced strictly between
    'Part waiting' and 'Adaptor' that declare sla_item_groups, EXCLUDING the
    ready-stock departments listed in NJ Inventory Settings.departments.
    Pre-order and ready stock are disjoint by construction - a machine is
    either sellable today (actual_qty) or promisable (pre_order_qty), never
    both. Machines before the window (Inward, Paint, Core IQC) are NOT
    promisable: they have not entered the line.

    The over-promise this used to cause is NOT solved by narrowing the key; it
    is solved in update_pre_order_qty, which CLAIMS the pool (one row takes it)
    instead of copying it to every variant sharing the parent. Do not re-split
    this key to fix a quantity bug - check the claim logic instead.

    Returns {config_key: free_qty} for configurations with at least one
    free machine, or None when the pool could not be computed (which is
    NOT the same as "no stock" - see update_pre_order_qty).
    """
    warehouses_list, item_groups_list = _pre_order_config_filters(settings)

    if not item_groups_list:
        log_error(
            "Item groups are required to update pre-order quantities",
            "update_pre_order_qty",
            "Error",
        )
        return None

    # Scope: the build window only - departments sequenced strictly between
    # 'Part waiting' and 'Adaptor' - MINUS the departments that already feed
    # ready stock.
    #
    # Business rule (2026-09-23, reverting the 2026-09-22 widening): only a
    # machine already inside the build window is promisable. A chassis sitting
    # in Inward, Paint or Core IQC has not entered the line and must not be
    # sold against. sla_item_groups is the gate that keeps a laptop out of a
    # desktop-only department.
    #
    # Bounds are looked up by name, never hardcoded, and are EXCLUSIVE at both
    # ends: 'Part waiting' itself is not build capacity, and 'Adaptor QC' is
    # past the point this pool is meant to cover.
    #
    # The NOT IN is not optional, and it matters MORE at this width, not less:
    # 'L1 - NJ' and 'L1 Line - NJ' sit inside the window and are also in the
    # ready-stock scope, so without it 42 machines (measured 2026-09-23) would
    # be sold twice - once as ready stock on their own variant, once as
    # pre-order on a sibling. The claim step cannot catch this, because it only
    # sees the pre-order pool and not what actual_qty already spent.
    ready_stock_depts = [
        d.strip() for d in (settings.get("departments") or "").split(",") if d.strip()
    ]

    part_waiting_seq = frappe.db.get_value(
        "Department", {"name": ["like", "%Part waiting%"]}, "department_sequence"
    )
    adaptor_seq = frappe.db.get_value(
        "Department", {"name": ["like", "%Adaptor%"]}, "department_sequence"
    )

    if part_waiting_seq is None or adaptor_seq is None:
        log_error(
            "Could not find the sequence for Part waiting or Adaptor - the "
            "pre-order build window cannot be bounded, so it is not computed",
            "update_pre_order_qty",
            "Error",
        )
        return None

    min_bound = min(part_waiting_seq, adaptor_seq)
    max_bound = max(part_waiting_seq, adaptor_seq)

    if ready_stock_depts:
        exclude_placeholders = ", ".join(["%s"] * len(ready_stock_depts))
        depts_list = frappe.db.sql_list(f"""
            SELECT name FROM `tabDepartment`
            WHERE department_sequence > %s AND department_sequence < %s
              AND sla_item_groups IS NOT NULL AND sla_item_groups != ''
              AND name NOT IN ({exclude_placeholders})
        """, tuple([min_bound, max_bound] + ready_stock_depts))
    else:
        log_error(
            "NJ Inventory Settings.departments is empty - pre-order pool cannot be "
            "separated from ready stock, so it is not computed",
            "update_pre_order_qty",
            "Error",
        )
        return None

    if not depts_list:
        log_error(
            "No pre-order departments remain after excluding the ready-stock scope",
            "update_pre_order_qty",
            "Error",
        )
        return None

    return _count_free_machines_by_config(depts_list, item_groups_list, warehouses_list, parents=parents)


def _count_free_machines_by_config(depts_list, item_groups_list, warehouses_list=None, parents=None):
    """Free machines per parent + Processor across the given departments.

    Shared by the pre-order pool and the company quantity so that both are
    counted with exactly the same idea of "free" - only the department scope
    differs. Returns {config_key: free_qty}.

    parents limits the count to those parent models (Item.variant_of) - used by
    the Sales Order sync to recount only what an order can have changed.
    """
    warehouses_list = warehouses_list or []
    parents = list(parents or [])
    parent_clause = (
        f"AND i.variant_of IN ({', '.join(['%s'] * len(parents))})" if parents else ""
    )

    item_group_placeholders = ", ".join(["%s"] * len(item_groups_list))
    department_placeholders = ", ".join(["%s"] * len(depts_list))
    warehouse_placeholders = ", ".join(["%s"] * len(warehouses_list))
    parent_warehouse_clause = (
        f"OR b.warehouse IN ({warehouse_placeholders})" if warehouses_list else ""
    )

    rows = frappe.db.sql(f"""
        SELECT
            CONCAT(
                COALESCE(i.variant_of, ''), '|',
                COALESCE(proc.attribute_value, '')
            ) AS config_key,
            COUNT(b.name) AS free_qty
        -- Driven from `tabSerial No`, not `tabItem`. The original shape was
        -- FROM `tabItem` i LEFT JOIN `tabSerial No` b
        --      ON (i.name = b.item_code OR i.item_code = b.item_code)
        -- and that OR stops MySQL using any index on the Item side: EXPLAIN
        -- reported type=ALL with "Range checked for each record" over 229,643
        -- Item rows, once per candidate serial. Widening the department scope
        -- to the whole plant made that cost real - 273s per run.
        --
        -- Only 3 Items in 247,243 have name <> item_code (all mis-typed
        -- accessories: a WIFI CARD and two SSDs), none of them in a pre-order
        -- item group, so the OR branch contributes nothing here. Verified: this
        -- form returns byte-identical pools (374 pools / 1,656 machines) in 73s.
        FROM `tabSerial No` b
        INNER JOIN `tabItem` i ON i.name = b.item_code
        LEFT JOIN `tabWarehouse` w ON b.warehouse = w.name
        INNER JOIN `tabDepartment` dp ON w.department = dp.name
        LEFT JOIN `tabItem Variant Attribute` proc
            ON proc.parent = i.name AND proc.attribute = 'Processor Type1'
        WHERE
            COALESCE(b.item_group, i.item_group) IN ({item_group_placeholders})
            AND (w.department IN ({department_placeholders}) {parent_warehouse_clause})
            AND dp.sla_item_groups IS NOT NULL AND dp.sla_item_groups != ''
            AND FIND_IN_SET(COALESCE(b.item_group, i.item_group), dp.sla_item_groups)
            AND b.status = 'Active'
            AND b.is_replace = 0
            AND (b.reserved_sales_order IS NULL OR b.reserved_sales_order = '')
            AND (b.sales_order IS NULL OR b.sales_order = '')
            AND NOT EXISTS (
                SELECT 1 FROM `tabDelivery Note Item` dni
                JOIN `tabDelivery Note` dn ON dn.name = dni.parent
                WHERE dni.serial_no = b.name AND dni.docstatus = 1
                  AND dn.is_return = 0
                  AND dn.status NOT IN ('Return Issued', 'Closed')
                  AND dn.name NOT IN (
                      SELECT return_against FROM `tabDelivery Note`
                      WHERE is_return = 1 AND docstatus = 1
                        AND return_against IS NOT NULL AND return_against != ''
                  )
            )
            AND (b.return_reason IS NULL OR b.return_reason = ''
                 OR b.return_reason NOT IN ('Repair', 'Replace'))
            -- An ungraded machine has no confirmed processor. Widening the pool
            -- to Inward/Core IQC brought these in, and the pool key would then
            -- advertise the ITEM MASTER's spec for a machine nobody has opened
            -- yet (e.g. "Optiplex 3050 | NO PROCESSOR" going live at 21 units).
            -- Pre-order is a promise about a specific build; we cannot make it
            -- for a machine whose CPU is unknown.
            AND proc.attribute_value IS NOT NULL
            AND TRIM(proc.attribute_value) != ''
            AND UPPER(TRIM(proc.attribute_value)) NOT IN ('NO PROCESSOR', 'UNKNOWN PROCESSOR')
            {parent_clause}
        GROUP BY config_key
        HAVING COUNT(b.name) > 0
    """, tuple(item_groups_list + depts_list + warehouses_list + parents), as_dict=True)

    return {r["config_key"]: int(r["free_qty"] or 0) for r in rows}


def get_company_qty_pools(settings, parents=None):
    """Free machines per parent + Processor across the whole company.

    This is the GATE for pre-order, not the quantity advertised. Business rule
    (2026-09-23): a configuration may be listed as pre-order only when the
    company as a whole holds more than pre_order_threshold free machines of it.
    What is pushed is still the build-window pool from get_pre_order_pools -
    the company quantity only decides whether that pool is shown or zeroed.

    Scope: every pipeline department (department_sequence > 0) that declares
    sla_item_groups, MINUS the ready-stock departments in NJ Inventory
    Settings.departments (that stock is already live quantity) and MINUS
    Reject/Scrap departments (not sellable stock). "Free" means exactly what
    it means for the pool - see _count_free_machines_by_config.

    Returns {config_key: qty}, or None when it could not be computed (which,
    as with the pool, is NOT the same as "no stock").
    """
    _, item_groups_list = _pre_order_config_filters(settings)
    if not item_groups_list:
        log_error(
            "Item groups are required to compute the company quantity",
            "update_pre_order_qty",
            "Error",
        )
        return None

    ready_stock_depts = [
        d.strip() for d in (settings.get("departments") or "").split(",") if d.strip()
    ]
    if not ready_stock_depts:
        log_error(
            "NJ Inventory Settings.departments is empty - company quantity cannot be "
            "separated from ready stock, so it is not computed",
            "update_pre_order_qty",
            "Error",
        )
        return None

    exclude_placeholders = ", ".join(["%s"] * len(ready_stock_depts))
    depts_list = frappe.db.sql_list(f"""
        SELECT name FROM `tabDepartment`
        WHERE department_sequence > 0
          AND sla_item_groups IS NOT NULL AND sla_item_groups != ''
          AND name NOT IN ({exclude_placeholders})
          AND name NOT LIKE %s AND name NOT LIKE %s
    """, tuple(ready_stock_depts + ["%Reject%", "%Scrap%"]))

    if not depts_list:
        log_error(
            "No company-quantity departments remain after excluding the ready-stock scope",
            "update_pre_order_qty",
            "Error",
        )
        return None

    return _count_free_machines_by_config(depts_list, item_groups_list, parents=parents)


def get_pre_order_exact_counts(settings):
    """How many pooled machines carry each exact item code.

    Used only to break ties in update_pre_order_qty: when several variants of
    one parent+Processor can each claim the whole pool, the listing should go
    to the variant the machines already are, not to whichever item code sorts
    first. Returns {item_code: qty}; an empty dict simply means the tie-break
    falls back to item_code order, which is the previous behaviour.
    """
    warehouses_list, item_groups_list = _pre_order_config_filters(settings)
    if not item_groups_list:
        return {}

    ready_stock_depts = [
        d.strip() for d in (settings.get("departments") or "").split(",") if d.strip()
    ]
    if not ready_stock_depts:
        return {}

    exclude_placeholders = ", ".join(["%s"] * len(ready_stock_depts))
    depts_list = frappe.db.sql_list(f"""
        SELECT name FROM `tabDepartment`
        WHERE department_sequence > 0
          AND sla_item_groups IS NOT NULL AND sla_item_groups != ''
          AND name NOT IN ({exclude_placeholders})
    """, tuple(ready_stock_depts))
    if not depts_list:
        return {}

    item_group_placeholders = ", ".join(["%s"] * len(item_groups_list))
    department_placeholders = ", ".join(["%s"] * len(depts_list))

    try:
        rows = frappe.db.sql(f"""
            SELECT i.item_code, COUNT(b.name) AS qty
            -- Same Serial-No-driven shape as get_pre_order_pools; see the note
            -- there for why the OR join was removed.
            FROM `tabSerial No` b
            INNER JOIN `tabItem` i ON i.name = b.item_code
            LEFT JOIN `tabWarehouse` w ON b.warehouse = w.name
            INNER JOIN `tabDepartment` dp ON w.department = dp.name
            WHERE
                COALESCE(b.item_group, i.item_group) IN ({item_group_placeholders})
                AND w.department IN ({department_placeholders})
                AND dp.sla_item_groups IS NOT NULL AND dp.sla_item_groups != ''
                AND FIND_IN_SET(COALESCE(b.item_group, i.item_group), dp.sla_item_groups)
                AND b.status = 'Active'
                AND b.is_replace = 0
                AND (b.reserved_sales_order IS NULL OR b.reserved_sales_order = '')
                AND (b.sales_order IS NULL OR b.sales_order = '')
                AND (b.return_reason IS NULL OR b.return_reason = ''
                     OR b.return_reason NOT IN ('Repair', 'Replace'))
            GROUP BY i.item_code
            HAVING COUNT(b.name) > 0
        """, tuple(item_groups_list + depts_list), as_dict=True)
    except Exception:
        # A tie-break is a nicety, never a reason to fail the allocation.
        log_error(frappe.get_traceback(), "get_pre_order_exact_counts", "Error")
        return {}

    return {r["item_code"]: int(r["qty"] or 0) for r in rows}


def update_pre_order_qty(settings):
    """Allocate the free WIP pool to SO Quantity Check rows, one claim per machine.

    The invariant this function exists to hold:

        SUM(pre_order_qty) across all rows sharing a parent + Processor never
        exceeds the number of physical machines free on the line for it.

    A configuration is only allocated at all when its company quantity (see
    get_company_qty_pools) is above pre_order_threshold; otherwise every row of
    it gets 0. The threshold is applied HERE and nowhere else - the Shopify
    push treats any pre_order_qty > 0 as a pre-order.

    That is why the pool is CLAIMED rather than copied. Several item codes (the
    RAM/SSD variants of one chassis) map to the same pool, and every one of them
    could legitimately be built from any machine in it - but only one may
    advertise it, or the same 37 machines get sold 11 times over. Copying the
    pool to every matching row is exactly what the pre-2026-09-22 code did:
    measured live, it advertised 3,857 units against 317 physical machines.

    Returns True on success, False on failure. A False return means the
    pre-order figures are NOT trustworthy for this cycle - callers must skip
    the Shopify pre-order push rather than treat the table as "no pre-orders".
    """
    try:
        pools = get_pre_order_pools(settings)

        if pools is None:
            # Could not compute the pool at all. Leave the table untouched:
            # zeroing it here is what strips live pre-orders off Shopify.
            log_error(
                "Pre-order pool could not be computed - SO Quantity Check left untouched",
                "update_pre_order_qty",
                "Error",
            )
            return False

        company_qty = get_company_qty_pools(settings)

        if company_qty is None:
            # Same reasoning as the pool: without the gate we cannot say which
            # configurations may be shown, so hold everything as it is.
            log_error(
                "Company quantity could not be computed - SO Quantity Check left untouched",
                "update_pre_order_qty",
                "Error",
            )
            return False

        # Imported here: shopify_inventory imports this module at load time.
        from nj_features.nj_features.api.shopify_inventory import get_inventory_sync_flags
        sync_flags = get_inventory_sync_flags()
        threshold = sync_flags["pre_order_threshold"]
        # pre_order_claim=0 (default since 2026-09-25): every row of the
        # configuration is given the pool, as before 2026-09-22. The invariant
        # in the docstring holds only when it is 1.
        claim_pool = bool(sync_flags["pre_order_claim"])

        # machines-per-exact-item-code, for the tie-break below
        exact_counts = get_pre_order_exact_counts(settings)

        # item code -> its exact configuration, for every row we might fill
        config_rows = frappe.db.sql("""
            SELECT
                t.name AS soqc_name,
                t.item_code,
                t.pending_allocation_qty,
                CONCAT(
                    COALESCE(i.variant_of, ''), '|',
                    COALESCE(proc.attribute_value, '')
                ) AS config_key
            FROM `tabSO Quantity Check` t
            INNER JOIN `tabItem` i ON i.item_code = t.item_code
            LEFT JOIN `tabItem Variant Attribute` proc
                ON proc.parent = i.name AND proc.attribute = 'Processor Type1'
        """, as_dict=True)

        def backlog(row):
            """Waiting demand on this row, as a positive number."""
            try:
                pending = int(float(row.get("pending_allocation_qty") or 0))
            except (TypeError, ValueError):
                pending = 0
            return abs(pending) if pending < 0 else 0

        # group the candidate rows by configuration
        candidates = {}
        for row in config_rows:
            key = row.get("config_key")
            if key in pools:
                candidates.setdefault(key, []).append(row)

        allocations = {}
        collisions = 0
        gated_configs = 0
        gated_units = 0
        for key, rows in candidates.items():
            free_qty = pools.get(key, 0)
            if free_qty <= 0:
                continue
            if company_qty.get(key, 0) <= threshold:
                # Not enough of this configuration company-wide: push 0.
                gated_configs += 1
                gated_units += free_qty
                continue
            if len(rows) > 1:
                collisions += 1

            def claimable(row):
                """What this row would be allowed to advertise.

                A row carrying a waiting backlog is capped at that backlog -
                the rule inherited from the original implementation.
                """
                waiting = backlog(row)
                return min(waiting, free_qty) if waiting else free_qty

            if not claim_pool:
                # Business rule: same pool on every variant of this config.
                for row in rows:
                    allocations[row["soqc_name"]] = claimable(row)
                continue

            # Claim by how much can actually be advertised, not by who is
            # waiting most. Picking the largest backlog caps the whole
            # configuration at that row's backlog, so a pool of 38 behind a
            # single row with a backlog of 1 would advertise 1 and strand 37.
            #
            # Among rows that can advertise the same amount - the usual case,
            # since siblings with no backlog all claim the full pool - prefer
            # the variant that the machines in the pool ACTUALLY are. Falling
            # through to item_code order picked a spec at random: the 7420(PIR)
            # listing went live as 16 GB/256 GB while all 32 machines were
            # 16 GB/512 GB. exact_match_qty is how many pooled machines carry
            # that row's own item code, so the advertised listing is the one
            # needing the least rework.
            rows.sort(key=lambda r: (
                -claimable(r),
                -exact_counts.get(r.get("item_code"), 0),
                str(r.get("item_code") or ""),
            ))
            winner = rows[0]
            allocations[winner["soqc_name"]] = claimable(winner)

        # One transaction: reset then allocate, so no reader ever observes the
        # table half-filled. Committing between the two is what produced the
        # all-zero window that stripped pre-orders off Shopify.
        frappe.db.sql("UPDATE `tabSO Quantity Check` SET pre_order_qty = 0 WHERE pre_order_qty != 0")

        for soqc_name, qty in allocations.items():
            frappe.db.sql(
                "UPDATE `tabSO Quantity Check` SET pre_order_qty = %s WHERE name = %s",
                (int(qty), soqc_name),
            )

        frappe.db.commit()

        allocated_units = sum(allocations.values())
        pool_units = sum(pools.values())
        log_error(
            f"Pre-order allocation complete: {len(allocations)} rows, "
            f"{allocated_units} units allocated from a pool of {pool_units} "
            f"machines across {len(pools)} configurations "
            f"({collisions} configurations had competing item codes; "
            f"{gated_configs} configurations / {gated_units} machines zeroed because "
            f"company quantity was not above the threshold of {threshold})",
            "update_pre_order_qty",
            "Info",
        )

        if claim_pool and allocated_units > pool_units:
            # Should be impossible by construction; shout if it ever happens.
            # In copy mode (claim_pool off) exceeding the pool is the intent.
            log_error(
                f"Pre-order allocation exceeded the physical pool "
                f"({allocated_units} > {pool_units}) - Shopify push must be held",
                "update_pre_order_qty",
                "Error",
            )
            return False

        return True

    except pymysql.err.OperationalError:
        # Previously swallowed silently, which left the whole table at zero for
        # a cycle with nothing in the logs to explain it.
        frappe.db.rollback()
        log_error(
            f"Database error while updating pre-order quantities:\n{frappe.get_traceback()}",
            "update_pre_order_qty",
            "Error",
        )
        return False

    except Exception:
        frappe.db.rollback()
        log_error(frappe.get_traceback(), "update_pre_order_qty", "Error")
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
                    "Error",
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


def get_pre_order_config_keys(item_codes):
    """parent + Processor key ("variant_of|processor") for each item code that has one."""
    item_codes = [c for c in (item_codes or []) if c]
    if not item_codes:
        return set()
    placeholders = ", ".join(["%s"] * len(item_codes))
    rows = frappe.db.sql_list(f"""
        SELECT DISTINCT CONCAT(i.variant_of, '|', proc.attribute_value)
        FROM `tabItem` i
        INNER JOIN `tabItem Variant Attribute` proc
            ON proc.parent = i.name AND proc.attribute = 'Processor Type1'
        WHERE i.item_code IN ({placeholders})
          AND COALESCE(i.variant_of, '') != ''
          AND COALESCE(proc.attribute_value, '') != ''
    """, tuple(item_codes))
    return set(rows)


def update_pre_order_qty_for_configs(settings, config_keys):
    """Recompute pre_order_qty for only these parent + Processor configurations.

    Used by the Sales Order sync (business rule 2026-09-26). Without it the
    order's sync re-pushed the LAST HOURLY pre-order figure, putting the
    machine just sold back on sale until the next hourly run (Shopify order
    #34095: available 2 -> 1 on the order, then straight back to 2).

    Same rules as update_pre_order_qty in copy mode (pre_order_claim = 0):
    the configuration is shown only when company qty is above
    pre_order_threshold, and then EVERY row of it gets the build-window pool
    (capped at its own backlog). Must not be used in claim mode - claims are
    global and belong to the hourly run.

    Returns True when the figures were recomputed and saved, False when they
    could not be computed (the caller must then keep the staged figures).
    """
    config_keys = {k for k in (config_keys or []) if k and "|" in k}
    if not config_keys:
        return True
    parents = sorted({k.split("|", 1)[0] for k in config_keys})

    try:
        from nj_features.nj_features.api.shopify_inventory import get_inventory_sync_flags
        flags = get_inventory_sync_flags()
        if flags["pre_order_claim"]:
            return False

        pools = get_pre_order_pools(settings, parents=parents)
        company_qty = get_company_qty_pools(settings, parents=parents)
        if pools is None or company_qty is None:
            return False

        placeholders = ", ".join(["%s"] * len(parents))
        rows = frappe.db.sql(f"""
            SELECT
                t.name AS soqc_name,
                t.pending_allocation_qty,
                CONCAT(COALESCE(i.variant_of, ''), '|', COALESCE(proc.attribute_value, '')) AS config_key
            FROM `tabSO Quantity Check` t
            INNER JOIN `tabItem` i ON i.item_code = t.item_code
            LEFT JOIN `tabItem Variant Attribute` proc
                ON proc.parent = i.name AND proc.attribute = 'Processor Type1'
            WHERE i.variant_of IN ({placeholders})
        """, tuple(parents), as_dict=True)

        for row in rows:
            key = row.get("config_key")
            if key not in config_keys:
                continue
            free_qty = pools.get(key, 0)
            qty = 0
            if free_qty > 0 and company_qty.get(key, 0) > flags["pre_order_threshold"]:
                # Same backlog cap as update_pre_order_qty.
                try:
                    pending = int(float(row.get("pending_allocation_qty") or 0))
                except (TypeError, ValueError):
                    pending = 0
                waiting = abs(pending) if pending < 0 else 0
                qty = min(waiting, free_qty) if waiting else free_qty
            frappe.db.sql(
                "UPDATE `tabSO Quantity Check` SET pre_order_qty = %s WHERE name = %s",
                (int(qty), row["soqc_name"]),
            )

        frappe.db.commit()
        return True

    except Exception:
        frappe.db.rollback()
        log_error(frappe.get_traceback(), "update_pre_order_qty_for_configs", "Error")
        return False
