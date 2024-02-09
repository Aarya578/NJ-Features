import frappe

@frappe.whitelist()
def on_submit(doc, handler=""):
    print(f"on submit")
    frappe.throw("ON Submit")
    crt_amzsl_inv(doc.name)
   # crt_amzdn(doc.name)

@frappe.whitelist()
def crt_amzsl_inv(sales_order_name):
    so = frappe.get_doc("Sales Order", sales_order_name)
    if so.naming_series == "SO-Amazon-" and so.order_type == "Sales":
        si = frappe.new_doc("Sales Invoice")
        si.update({ 
            "customer": so.customer,
            "naming_series": 'SINV-',
            "sales_channel": 'Amazon',
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.add_days(frappe.utils.today(), 30),  # Adjust the due date as needed
            "items": []
        })
        for item in so.items:
            si.append("items", {
                "item_code": item.item_code,
                "rate": item.rate,
                "qty": item.qty,
                "sales_order": sales_order_name
            })
        si.insert(ignore_permissions=True)
        si.submit()
        frappe.msgprint(frappe._("Sales invoice created",si.name), indicator="green", alert=True)
        frappe.db.commit()
        return si.name
    else:
        pass

# for stock entry
@frappe.whitelist()
def search_for_serial_or_batch_or_barcode_no(search_value):
	# Search barcode number
	barcode_data = frappe.db.get_value(
		"Item Barcode", {"barcode": search_value}, ["barcode", "parent as item_code"], as_dict=True
	)
	if barcode_data:
		return barcode_data

    # Search item code
	item_code_data = frappe.db.get_value(
		"Item", {"item_code": search_value}, ["item_code"], as_dict=True
	)
	if item_code_data:
		return {"item_code": item_code_data.item_code}
	# Search serial number
	serial_no_data = frappe.db.get_value(
		"Serial No", search_value, ["name as serial_no", "item_code", "warehouse"], as_dict=True
	)
	if serial_no_data:
		return serial_no_data

	# Search batch number
	batch_no_data = frappe.db.get_value(
		"Batch", search_value, ["name as batch_no", "item as item_code"], as_dict=True
	)
	if batch_no_data:
		return batch_no_data

	return {}

@frappe.whitelist()
def serializer_or_notserializer(serial_no=None):
    if serial_no:
        item_code = frappe.db.get_value(
            "Serial No", {"name": serial_no}, ["item_code"], as_dict=True
        )
        if item_code and item_code.item_code:
            has_serial_no = frappe.db.get_value(
                "Item", {"name": item_code.item_code}, ["has_serial_no"], as_dict=True
            )
            return has_serial_no.has_serial_no if has_serial_no else 0
    return 0  # Return 0 if item code or has_serial_no is not found or is None

