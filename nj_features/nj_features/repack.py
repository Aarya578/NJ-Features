import frappe

@frappe.whitelist()
def repack(inward):
    unk_ram = frappe.db.get_value('NJ Settings', {'doc_type': 'Inward', 'parameter': 'unk_ram'}, 'value')
    unk_pro = frappe.db.get_value('NJ Settings', {'doc_type': 'Inward', 'parameter': 'unk_pro'}, 'value')
    unk_storage = frappe.db.get_value('NJ Settings', {'doc_type': 'Inward', 'parameter': 'unk_storage'}, 'value')
    
    if unk_ram is None and unk_pro is None and unk_storage is None:
        frappe.throw("NJ settings is required for <strong>'Inward'</strong> doctype")

    inward = frappe.get_doc("Inward", inward)
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.stock_entry_type = "Repack"
    stock_entry.company = frappe.db.get_single_value("Global Defaults", "default_company")
    supplier = frappe.db.get_value('Purchase Receipt', {'name': inward.purchase_receipt}, 'supplier')
    stock_entry.append("items", {
        "item_code": inward.item_code,
        "qty": 1,
        'uom': 'Nos',
        'conversion_factor': 1,
        'stock_uom': 'Nos',
        's_warehouse': inward.source_warehouse,
        'set_basic_rate_manually': 0,
        'basic_rate': inward.base_rate,
        'supplier':supplier, 
        
    })
    
    item_doc = frappe.get_doc('Item', inward.item_code)
    
    # Check if has_serial_no and has_batch_no are correctly fetched
    has_serial_no = item_doc.has_serial_no if item_doc else 0
    has_batch_no = item_doc.has_batch_no if item_doc else 0

    if ((has_batch_no == 1 and has_serial_no == 1) or (has_batch_no == 0 and has_serial_no == 0)):
        frappe.throw(f"Item: {inward.item_code} doesn't have both 'has_serial_no' and 'has_batch_no'")
        
    if has_serial_no == 1:
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
        if get_serial_no==None:
            frappe.msgprint(f"Serial No not found for  {inward.item_code} in {inward.source_warehouse}")
        else:
            stock_entry.items[0].update({'serial_no': get_serial_no[0].name})
        
    item_name = f"S-{inward.brand} {inward.model}-{unk_pro}-{unk_ram}-{unk_storage}"  
    item_code = frappe.db.get_value('Item', {'name': item_name }, 'name')
    
    if has_batch_no == 1:
        batch_data = frappe.get_all('Stock Ledger Entry',
            filters={'item_code': inward.item_code, 'warehouse': inward.source_warehouse},
            fields=['batch_no'],
            order_by='posting_date desc, posting_time desc',
            limit=1)
        print(f"batch_data: {batch_data}")
        if batch_data:
            stock_entry.items[0].update({
                'batch_no': batch_data[0].batch_no
            })
    
    stock_entry.append("items", {
        "item_code": item_code,
        "qty": 1,
        "t_warehouse": inward.target_warehouse,
        'uom': 'Nos',
        'conversion_factor': 1,
        'serial_no': inward.serial_no,
        'stock_uom': 'Nos',
        'basic_rate': inward.base_rate,
        'set_basic_rate_manually': 0,
        'supplier':supplier,
    
    })

    if item_code:
        stock_entry.naming_series = "STE-INW-"
        stock_entry.reference_serial_no = inward.serial_no
        stock_entry.reference_type = "Inward"
        stock_entry.save()
        stock_entry.reference = stock_entry.name
        stock_entry.submit()
        frappe.msgprint(f"Repack: <strong>{stock_entry.name}</strong> has been submitted successfully.")
    else:
        frappe.msgprint(f"Item: <strong>{item_name}</strong> doesn't exist.")
        
    return stock_entry.name