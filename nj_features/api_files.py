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
def serializer_or_notserializer(item_code=None):
    if item_code:
        has_serial_no = frappe.db.get_value(
            "Item", {"name": item_code}, ["has_serial_no"], as_dict=True
        )
        return has_serial_no.has_serial_no if has_serial_no else 0
    return 0  # Return 0 if item code or has_serial_no is not found or is None

# @frappe.whitelist()
# def get_all_emp_warehouse(user):
#     dept = frappe.db.get_value('Employee', {'user_id':user}, 'department')
#     dept_values = frappe.db.get_value('Department', {'name':dept}, ['department_prefix', 'linked_warehouse'])
#     default_ww = dept_values[0] + '-Work-Warehouse - NJ'
#     print(f"dept: {dept}, dept_prefix: {dept_values}, default_ww: {default_ww}")
#     all_emp_ware = frappe.db.get_all('Warehouse', {'parent_warehouse': dept_values[1]}, 'name')
#     all_emp_ware_names = [warehouse['name'] for warehouse in all_emp_ware]
    
#     if default_ww in all_emp_ware_names:
#         all_emp_ware_names.remove(default_ww)
    
#     return all_emp_ware_names

@frappe.whitelist()
def get_all_emp_warehouse(user):
    dept = frappe.db.get_value('Employee', {'user_id': user}, 'department')
    dept_values = frappe.db.get_value('Department', {'name': dept}, ['department_prefix', 'linked_warehouse'])
    default_ww = dept_values[0] + '-Work-Warehouse - NJ'
    all_emp_ware = frappe.db.get_all('Warehouse', {'parent_warehouse': dept_values[1]}, ['name', 'available_capacity'])
    
    warehouse_info = {}
    for warehouse in all_emp_ware:
        warehouse_info[warehouse['name']] = warehouse['available_capacity']
    
    if default_ww in warehouse_info:
        del warehouse_info[default_ww]
    
    return warehouse_info
