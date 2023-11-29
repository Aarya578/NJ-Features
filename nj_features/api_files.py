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
	# search barcode no
	barcode_data = frappe.db.get_value(
		"Item Barcode", {"barcode": search_value}, ["barcode", "parent as item_code"], as_dict=True
	)
	if barcode_data:
		return barcode_data

	# search serial no
	serial_no_data = frappe.db.get_value(
		"Serial No", search_value, ["name as serial_no", "item_code", "warehouse"], as_dict=True
	)
	if serial_no_data:
		return serial_no_data

	# search batch no
	batch_no_data = frappe.db.get_value(
		"Batch", search_value, ["name as batch_no", "item as item_code"], as_dict=True
	)
	if batch_no_data:
		return batch_no_data

	return {}