import json
import frappe
from frappe import _
from frappe.model.document import Document
from nj_features.nj_features.doctype.stock_movement.stock_movement import StockMovement

@frappe.whitelist()
def process_stock_movement_data():
    has_serial_no = {
        'has_serial_no': 2
        }
    submit_status = {
        'submitStatus': 0
        }
    
    data = frappe.request.data.decode('utf-8')
    data = json.loads(data)
    user_id = data['user_id']
    owner_warehouse = frappe.db.get_value("Employee", {'user_id': user_id}, 'work_warehouse')

    if data:
        stock_movement_data = stock_movement_draft(data, owner_warehouse, has_serial_no, submit_status)
    return stock_movement_data, has_serial_no, submit_status

def stock_movement_draft(data, owner_warehouse, has_serial_no, submit_status):
    if data['transfer_status'] == 'Stock Accept':
        existing_stock_movement = frappe.get_list(
            'Stock Movement',
            filters={'name': data['docname']}
        )
        if existing_stock_movement:
            stock_movement = frappe.get_doc('Stock Movement', data['docname'])
        else:
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

            if exisiting_draft_by_same_user:
                stock_movement = frappe.get_doc('Stock Movement', exisiting_draft_by_same_user[0]['name'])
            else:
                stock_movement = frappe.new_doc('Stock Movement')
                stock_movement.transfer_status = data['transfer_status']
                stock_movement.default_target_warehouse = owner_warehouse
                stock_movement.owner = data['user_id']
                stock_movement.stock_entry_type = 'Material Transfer'
                stock_movement.save()

        # MAKING THE SCAN_BARCODE ,SCAN_GRADE , SCAN_WAREHOUSE AS NONE
        stock_movement.scan_barcode = None
        stock_movement.scan_grade = None
        stock_movement.scan_warehouse = None

        if data['scan_barcode'] and data['scan_barcode'].strip():
            serial_no_data = search_for_serial_or_batch_or_barcode_no(data['scan_barcode'])
            if 'serial_no' in serial_no_data:
                has_serial_no['has_serial_no'] = 1
                stock_movement.scan_barcode = data['scan_barcode']
                
                existing_item = next((item for item in stock_movement.items if item.serial_no == serial_no_data['serial_no']), None)
                
                if not existing_item:
                    stock_movement.append('items', 
                            {
                            'serial_no': serial_no_data['serial_no'],
                            's_warehouse': serial_no_data['warehouse'],
                            't_warehouse': owner_warehouse,
                            'item_code': serial_no_data['item_code'],
                            'qty': 1
                            })
                    stock_movement.save()

        if data['scan_barcode'] and data['scan_grade'] and data['scan_warehouse']:

            non_serialized_data = search_for_non_serialized_item(data['scan_barcode'], data['scan_grade'], owner_warehouse)

            item_code_from_non_serialized_data = non_serialized_data + '-' + data['scan_grade']

            if non_serialized_data and data['qty']:
                has_serial_no['has_serial_no'] = 1
                stock_movement.scan_barcode = data['scan_barcode']
                stock_movement.scan_grade = data['scan_grade']
                stock_movement.scan_warehouse = data['scan_warehouse']
                stock_movement.default_source_warehouse = data['scan_warehouse']
                
                # Fetch list of item codes from the database
                database_items = frappe.get_all("Item", fields=["item_code"])
                database_item_codes = [item['item_code'] for item in database_items]

                if item_code_from_non_serialized_data in database_item_codes:
                    stock_movement.append('items', {
                        'item_code': item_code_from_non_serialized_data,
                        's_warehouse': data['scan_warehouse'],
                        't_warehouse': owner_warehouse,
                        'qty': data['qty']
                    })
                    stock_movement.save()
                else:
                    raise frappe.ValidationError(_("Item code not found in the database: {}".format(item_code_from_non_serialized_data)))
            else:
                stock_movement.scan_barcode = data['scan_barcode']
                stock_movement.scan_grade = data['scan_grade']
                stock_movement.scan_warehouse = data['scan_warehouse']

        stock_movement.save()

        stock_movement_data = stock_movement.as_dict()

        if data['submitStatus'] == 'true' and stock_movement_data['items'] != []: 
            submit_status['submitStatus'] = 1
            stock_movement.submit() 
        else:
            submit_status['submitStatus'] = 0
        return stock_movement.as_dict()
    return {}

@frappe.whitelist()
def search_for_serial_or_batch_or_barcode_no(search_value):
    serial_no_data = frappe.db.get_value(
        "Serial No", search_value, ["name as serial_no", "item_code", "warehouse"], as_dict=True
    )
    
    if serial_no_data:
        return {"serial_no": serial_no_data.get("serial_no"), "item_code": serial_no_data.item_code, "warehouse": serial_no_data.warehouse, "scan": 0}

    return {"scan": 1}

def search_for_non_serialized_item(scan_barcode, scan_grade, scan_warehouse):
    if '/' in scan_barcode:
        return scan_barcode
    elif '@' in scan_barcode:
        return scan_barcode.replace('@', '/')
    else:
        item_code = frappe.db.get_value('Non Serialized QR Code Mapping', {'name': scan_barcode}, 'item_code')
        return item_code if item_code else scan_barcode
