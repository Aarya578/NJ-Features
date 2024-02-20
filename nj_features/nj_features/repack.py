import frappe

@frappe.whitelist()
def repack(inward):
    unk_ram = frappe.db.get_value('NJ Settings', {'doc_type': 'Inward', 'parameter': 'unk_ram'}, 'value')
    unk_pro = frappe.db.get_value('NJ Settings', {'doc_type': 'Inward', 'parameter': 'unk_pro'}, 'value')
    unk_storage = frappe.db.get_value('NJ Settings', {'doc_type': 'Inward', 'parameter': 'unk_storage'}, 'value')

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
        'basic_rate': inward.base_rate,
        'set_basic_rate_manually': 1
    })

    if frappe.get_value('Item', {'item_code': inward.item_code}, 'has_serial_no') == 1:
        # print(f"\n\ninward.serial_no_select: {stock_entry.items[0].item_code}")
        get_serial_no = frappe.db.sql(
            """SELECT name 
            FROM `tabSerial No` 
            WHERE item_code = %s 
                AND delivery_document_no IS NULL 
                AND warehouse = %s """,
            (inward.item_code, inward.source_warehouse),
            as_dict=True
        )
        stock_entry.items[0].update({'serial_no': get_serial_no[0].name})
        if(get_serial_no==None):
            frappe.msgprint(f"Serial No not found for  {inward.item_code} in {inward.source_warehouse}")
        
    item_name = f"S-{inward.brand}-{inward.model}-{unk_pro}-{unk_ram}-{unk_storage}"  
    item_code = frappe.db.get_value('Item', {'name': item_name }, 'name')
    
    stock_entry.append("items", {
        "item_code": item_code,
        "qty": 1,
        "t_warehouse": inward.target_warehouse,
        'uom': 'Nos',
        'conversion_factor': 1,
        'serial_no': inward.serial_no,
        'stock_uom': 'Nos',
        'set_basic_rate_manually': 0,
        'basic_rate': inward.base_rate,
    })

    if item_code:
        stock_entry.submit()
    else:
        frappe.msgprint(f"Item: <strong>{item_name}</strong> doesn't exist.")
        
    return stock_entry.name