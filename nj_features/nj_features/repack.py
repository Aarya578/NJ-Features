import frappe

@frappe.whitelist()
def repack(inward):
    inward = frappe.get_doc("Inward", inward)
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.stock_entry_type = "Repack"
    stock_entry.company = frappe.db.get_single_value("Global Defaults", "default_company")

    stock_entry.append("items", {
        "item_code": inward.item_code,
        "qty": 1,
        'uom': 'Nos',
        'conversion_factor': 1,
        'stock_uom': 'Nos',
        's_warehouse': inward.source_warehouse,
        'basic_rate': inward.base_price,
        'set_basic_rate_manually': 1
    })

    if frappe.get_value('Item', {'item_code': inward.item_code}, 'has_serial_no') == 1:
        stock_entry.items[0].update({'serial_no': inward.serial_no})

    stock_entry.append("items", {
        "item_code": f"{inward.brand}-{inward.model}-unknown-unknown-unknown",
        "qty": 1,
        "t_warehouse": inward.target_warehouse,
        'uom': 'Nos',
        'conversion_factor': 1,
        'serial_no': inward.serial_no,
        'stock_uom': 'Nos',
        'set_basic_rate_manually': 1,
        'basic_rate': inward.base_price,
    })

    stock_entry.submit()