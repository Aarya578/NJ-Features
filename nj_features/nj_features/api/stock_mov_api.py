import json
import frappe
from frappe import _
from frappe.model.document import Document

@frappe.whitelist()
def process_stock_movement_data():
    data = frappe.request.data.decode('utf-8')
    data = json.loads(data)
    user_id = data['user_id']
    owner_warehouse = frappe.db.get_value("Employee", {'user_id': user_id}, 'work_warehouse')
    print(f'DATA_FROM_DJANGO_VIEWS ===15=== {data}')
    if data:
        stock_movement_data = stock_movement_draft(data, owner_warehouse)
        return stock_movement_data

def stock_movement_draft(data, owner_warehouse):
    if data['transfer_status'] == 'Stock Accept':
        print(f'INSIDE STOCK ACCEPT')
        existing_stock_movement = frappe.get_list(
            'Stock Movement',
            filters={
                'name': data['docname']
            })
        print("data['user_id']",data['user_id'])
        exisiting_draft_by_same_user_query = """
            SELECT DISTINCT `tabStock Movement`.name 
                FROM `tabStock Movement`
                LEFT JOIN `tabStock Movement Detail` ON `tabStock Movement`.name = `tabStock Movement Detail`.parent
                WHERE `tabStock Movement Detail`.parent IS NULL
                AND `tabStock Movement`.transfer_status = '{0}'
                AND `tabStock Movement`.default_target_warehouse = '{1}'
                AND `tabStock Movement`.owner = '{2}'
                AND `tabStock Movement`.docstatus = 0
                LIMIT 1
        """.format(data['transfer_status'], owner_warehouse, data['user_id'])
        exisiting_draft_by_same_user = frappe.db.sql(exisiting_draft_by_same_user_query, as_dict=True)
        print("exisiting_draft_by_same_user", exisiting_draft_by_same_user)

        print(f'EXISTING_STOCK_MOVEMENT ===26=== {existing_stock_movement}')

        if existing_stock_movement:
            stock_movement = frappe.get_doc('Stock Movement', data['docname'])
        if exisiting_draft_by_same_user:
            stock_movement = frappe.get_doc('Stock Movement', exisiting_draft_by_same_user[0].name)
        else:
            stock_movement = frappe.new_doc('Stock Movement')
            stock_movement.transfer_status = data['transfer_status']
            stock_movement.default_target_warehouse = owner_warehouse
            stock_movement.save()

        if data['scan_barcode'] and data['scan_barcode'].strip():
            serial_no_data = frappe.db.get_value("Serial No", {'name': data['scan_barcode']}, ['serial_no', 'item_code', 'warehouse'], as_dict=True)
            print(f'SERIAL_NO_DATA ===28=== {serial_no_data}')
            
            # Check if the item already exists in the Stock Movement
            existing_item = next((item for item in stock_movement.items if item.serial_no == serial_no_data['serial_no']), None)
            
            if not existing_item:
                stock_movement.append('items', {
                    'serial_no': serial_no_data['serial_no'],
                    's_warehouse': serial_no_data['warehouse'],
                    't_warehouse': owner_warehouse,
                    'item_code': serial_no_data['item_code'],
                    'qty': 1
                })
                stock_movement.save()

        print(f'STOCK_MOVEMENT_DRAFT ===16=== {stock_movement.as_dict()}')
        return stock_movement.as_dict()
    return {}
