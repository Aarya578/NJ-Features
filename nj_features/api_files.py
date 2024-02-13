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
    # Search serial number
    serial_no_data = frappe.db.get_value(
        "Serial No", search_value, ["name as serial_no", "item_code", "warehouse"], as_dict=True
    )
    if serial_no_data:
        return {"serial_no": serial_no_data.get("serial_no"), "item_code": serial_no_data.item_code, "s_warehouse": serial_no_data.warehouse, "scan": 0}

    return {"scan": 1}


@frappe.whitelist()
def serializer_or_notserializer(item_code=None):
    if item_code:
        has_serial_no = frappe.db.get_value(
            "Item", {"name": item_code}, ["has_serial_no"], as_dict=True
        )
        return has_serial_no.has_serial_no if has_serial_no else 0
    return 0  # Return 0 if item code or has_serial_no is not found or is None

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
