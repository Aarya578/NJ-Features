import frappe

@frappe.whitelist()
def material_transfer(doc, work_warehouse=None):
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.stock_entry_type = "Material Transfer"
    stock_entry.company = frappe.db.get_single_value("Global Defaults", "default_company")
    iqc = frappe.get_doc('IQC', doc)
    sql_query = """
            SELECT 
                item_code, warehouse, incoming_rate, posting_date, posting_time
            FROM
                `tabStock Ledger Entry`
            WHERE
                serial_no LIKE %s
                AND is_cancelled = 0
            ORDER BY
                posting_date DESC, posting_time DESC, creation DESC
            LIMIT 1
        """
    sle = frappe.db.sql(sql_query, ('%'+iqc.serial_no+'%',), as_dict=1)
    sle_entry = sle[0]
    print(f"iqc for stock: {iqc}, {iqc.item_code}")
    stock_entry.append("items", {
        "item_code": iqc.item_code,
        "qty": 1,
        'uom': 'Nos',
        'conversion_factor': 1,
        'stock_uom': 'Nos',
        's_warehouse': sle_entry.warehouse,
        't_warehouse': work_warehouse,
        'basic_rate': sle_entry.incoming_rate,
        'serial_no': iqc.serial_no
    })

    if iqc.item_code:
        stock_entry.submit()
    else:
        frappe.msgprint(f"Item: <strong>{iqc.item_code}</strong> doesn't exist.")