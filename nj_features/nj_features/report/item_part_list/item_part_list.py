# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def get_columns():
    return [
        _("Creation") + ":Date:120",
        _("Machine Serial") + ":Link/Serial No:120",
        _("STE No") + ":Link/Stock Entry:120",
        _("Part Item Group") + ":Link/Item Group:120",
        _("Part Item Code") + ":Link/Item:120",
        _("s_warehouse") + ":Link/Warehouse:120",
        _("t_warehouse") + ":Link/Warehouse:120",
        _("Part Serial No") + ":Link/Serial No:120",
        _("Current Product WH") + ":Link/Warehouse:120",
        _("Product Item Code") + ":Link/Item:120"
    ]

def get_data(filters):

    serial_no = filters.get('serial_no')

    values = {'serial_no': serial_no}

    # SQL query
    query = """
        SELECT DISTINCT
		ddd.creation,
		bb.serial_no AS 'machine_serial',
		aaa.parent AS 'STE No',
		ccc.item_group AS 'part_item_group',
		aaa.item_code AS 'part_item_code',
		aaa.s_warehouse,
		aaa.t_warehouse,
		aaa.serial_no AS 'part_serial_no',
		eee.warehouse AS 'current_product_wh',
		eee.item_code AS 'product_item_code'
	FROM
		`tabStock Entry Detail` AS aaa
	INNER JOIN
		(
			SELECT aaaa.parent, aaaa.serial_no
			FROM `tabStock Entry Detail` aaaa
			WHERE aaaa.serial_no = %(serial_no)s
		) AS bb ON bb.parent = aaa.parent
	INNER JOIN `tabItem` AS ccc ON ccc.item_code = aaa.item_code
	INNER JOIN `tabStock Entry` AS ddd ON ddd.name = bb.parent
	INNER JOIN `tabSerial No` AS eee ON eee.serial_no = bb.serial_no
	WHERE
		ddd.purpose = 'Repack'
		AND aaa.docstatus = 1
		AND NOT (bb.serial_no = aaa.serial_no)
	ORDER BY
		bb.serial_no, aaa.parent;
    """
	
    data = frappe.db.sql(query, values, as_dict=1)
    print(f"data: {data}, query {query}")
    return data

def execute(filters):
    columns = get_columns()
    data = get_data(filters)
    return columns, data

