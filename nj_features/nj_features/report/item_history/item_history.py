import frappe
from frappe import _

# Define the columns for the report
def get_columns():
    columns = [
        {"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 160},
        {"label": _("STE Number"), "fieldname": "ste_number", "fieldtype": "Data", "width": 120},
        {"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 180},
        {"label": _("Parent Warehouse"), "fieldname": "parent_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 180},
        {"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 180},
        {"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 380},
        {"label": _("Department Name"), "fieldname": "department_name", "fieldtype": "Data", "width": 180},
        {"label": _("Warehouse Owner"), "fieldname": "warehouse_owner", "fieldtype": "Link", "options": "User", "width": 180},
        {"label": _("Record Entry By"), "fieldname": "created_by", "fieldtype": "Link", "options": "User", "width": 180},
    ]
    return columns

# Define the data retrieval logic
def get_data(filters):
    conditions = []

    if filters.get("item_group"):
        conditions.append(f"AND sle.item_group = '{filters['item_group']}'")
    if filters.get("brand"):
        conditions.append(f"AND sle.brand = '{filters['brand']}'")
    if filters.get("warehouse"):
        conditions.append(f"AND sle.warehouse = '{filters['warehouse']}'")
    if filters.get("item"):
        conditions.append(f"AND sle.item_code = '{filters['item']}'")
    if filters.get("Doctype"):
        conditions.append(f"AND sle.voucher_type = '{filters['Doctype']}'")

    conditions_sql = " ".join(conditions)

    # SQL query to fetch data with serial_no filter
    query = f"""
    SELECT
        concat_ws(" ", sle.posting_date, sle.posting_time) AS date,
        sle.voucher_no AS ste_number,
        sle.item_code,
        sle.warehouse,
        w.parent_warehouse,
        d.name AS department,
        d.department_name,
        u2.full_name AS created_by,
        sle.serial_no,
        u1.full_name AS warehouse_owner,
        sle.voucher_type
    FROM
        `tabStock Ledger Entry` sle
    LEFT JOIN `tabStock Entry` stock ON sle.voucher_no = stock.name
    LEFT JOIN `tabWarehouse` w ON sle.warehouse = w.name
    LEFT JOIN `tabUser` u1 ON u1.email = w.warehouse_owner
    LEFT JOIN `tabUser` u2 ON u2.name = stock.owner
    LEFT JOIN `tabDepartment` d ON d.name = w.department  -- Assuming department is linked with tabWarehouse
    WHERE
        sle.company = %(company)s
        AND sle.is_cancelled = 0
        AND MATCH(sle.serial_no) AGAINST (%(serial_no)s)
        {conditions_sql}
    ORDER BY
        sle.posting_date DESC, sle.posting_time DESC, sle.creation DESC
    """

    data = frappe.db.sql(query, filters, as_dict=True)

    if filters.get("serial_no"):
        # Filter the data in Python based on serial_no
        serial_no_filter = filters["serial_no"].upper()
        data = [entry for entry in data if any(serial_no_filter in sn for sn in entry["serial_no"].split('\n'))]

    for entry in data:
        # Convert voucher_type to lowercase and replace spaces with hyphens
        entry["voucher_type_link"] = entry["voucher_type"].lower().replace(" ", "-")
    return data

def execute(filters):
    columns = get_columns()
    data = get_data(filters)
    return columns, data
