import json
import frappe
from frappe import _
from frappe.model.document import Document
from nj_features.nj_features.doctype.stock_movement.stock_movement import StockMovement
from nj_features.api_files import get_all_emp_warehouse

@frappe.whitelist()
def process_stock_movement_data():
    data = frappe.request.data.decode('utf-8')
    data = json.loads(data)
    user_id = data['user_id']
    owner_warehouse = frappe.db.get_value("Employee", {'user_id': user_id}, 'work_warehouse')
    has_serial_no = {'has_serial_no': 2}
    rack_target_warehouse_msg = {'rack_target_warehouse_msg': ''}
    rack_target_warehouse = {'rack_target_warehouse': ''}
    submit_status = {'submitStatus': 0}
    check_status = {'check_status': 0}
    
    print(f'DATA_FROM_DJANGO_VIEWS ===15=== {data}')
    if data:
        print(f'DATA IS AVAILABLE')
        stock_movement_data = stock_movement_draft(data, owner_warehouse, has_serial_no, submit_status,rack_target_warehouse_msg,rack_target_warehouse,check_status)
        print(f'STOCK MOVEMENT DATA: {stock_movement_data}')
        print('STOCK_MOVEMENT_ITEMS ===20== = ', stock_movement_data['items'])
        if data['checkStatus'] == 1:
            print(f'LENGTH OF THE ITEMS ===21=== {len(stock_movement_data["items"])}')
            check_status.update({'check_status': len(stock_movement_data['items'])})
    return stock_movement_data, has_serial_no, submit_status , rack_target_warehouse_msg,rack_target_warehouse,check_status

def stock_movement_draft(data, owner_warehouse, has_serial_no, submit_status,rack_target_warehouse_msg,rack_target_warehouse,check_status):
    if data.get('transfer_status') in ['Stock Accept', 'Racking']:
        
        print(f'INSIDE {data.get("transfer_status")}')

        stock_movement = get_or_create_stock_movement(data, owner_warehouse)

        print(f'-----------------STOCK MOVEMENT----------------- {stock_movement.items}')

        reset_scan_fields(stock_movement)

        names_to_delete = set()

        row_names = data.get('row_name')
        if isinstance(row_names, list):
            names_to_delete = set(item.get('row_name') for item in row_names)
        elif isinstance(row_names, str):
            names_to_delete.add(row_names)
    
        if data.get('deleteStatus') == 'true':
            print(f'NAME TO DELETE ==43== {names_to_delete}')
            delete_items(stock_movement, names_to_delete)
            stock_movement.save()
            return stock_movement.as_dict()

        # Check and update reasons for existing items
        if data.get('reason'):
            print(f'\n\n%%%%%%%%%%GOING TO UPDATE REASON%%%%%%%%%%%\n\n')
            update_item_reasons(stock_movement, data['row_name'], data['reason'])

        if data.get('scan_barcode') and data['scan_barcode'].strip():
            handle_serialized_item(data, stock_movement, has_serial_no, owner_warehouse,rack_target_warehouse_msg,rack_target_warehouse,check_status)
        
        if (data.get('scan_barcode') and data.get('scan_grade')) or ('scan_warehouse' in data and data['scan_warehouse']):
            handle_non_serialized_item(data, stock_movement, has_serial_no, owner_warehouse,rack_target_warehouse_msg,rack_target_warehouse,check_status)

        stock_movement.save()
        handle_submission(data, stock_movement, submit_status)
        
        print(f'STOCK_MOVEMENT_DRAFT ===16=== {stock_movement.as_dict()}')
        return stock_movement.as_dict()
    
    return {}

def update_item_reasons(stock_movement, row_name, reason):
    """
    Update the reason for the item in stock_movement where the item's name matches the row_name.
    """
    print('Updating item reason')

    for item in stock_movement.items:
        item_name = item.get('name')
        if item_name == row_name:
            print(f'Updating reason for item {item_name} to: {reason}')
            print(f'REASON ===76=== {item.get("reason", "")}')
            item.update({'reason':reason})

    stock_movement.save()
    print(f'Updated items: {stock_movement.items}')

def delete_items(stock_movement, names_to_delete):
    """
    Remove items from the stock movement if their name is in the names_to_delete set.
    """
    print('IAM GOING TO DELETE')

    for item in stock_movement.items:
        print(f'ITEM_FROM_DELETE ==69== {item.name}')
    
    stock_movement.items = [
        item for item in stock_movement.items
        if item.get('name') not in names_to_delete
    ]
    
    print(f'FROM DELETE STOCK_MOVEMNT_ITEMS ===76=== {stock_movement.items}')

    return stock_movement

def get_or_create_stock_movement(data, owner_warehouse):
    print(f'DOCNAME PROVIDED: {data["docname"]}')
    existing_stock_movement = frappe.get_list('Stock Movement', filters={'name': data['docname']})
    
    if existing_stock_movement:
        stock_movement = frappe.get_doc('Stock Movement', data['docname'])
        print(f'FOUND EXISTING STOCK MOVEMENT: {stock_movement.name}')
    else:
        stock_movement = get_existing_draft(data, owner_warehouse)
        if not stock_movement:
            stock_movement = create_new_stock_movement(data, owner_warehouse)
    
    return stock_movement

def get_existing_draft(data, owner_warehouse):
    query = """
        SELECT DISTINCT `tabStock Movement`.name 
        FROM `tabStock Movement`
        LEFT JOIN `tabStock Movement Detail` ON `tabStock Movement`.name = `tabStock Movement Detail`.parent
        WHERE `tabStock Movement Detail`.parent IS NULL
        AND `tabStock Movement`.transfer_status = '{0}'
        AND `tabStock Movement`.{1} = '{2}'
        AND `tabStock Movement`.owner = '{3}'
        AND `tabStock Movement`.docstatus = 0
        LIMIT 1
    """.format(
        data['transfer_status'],
        'default_target_warehouse' if data['transfer_status'] == 'Stock Accept' else 'default_source_warehouse',
        owner_warehouse,
        data['user_id']
    )
    
    existing_draft = frappe.db.sql(query, as_dict=True)
    
    if existing_draft:
        stock_movement = frappe.get_doc('Stock Movement', existing_draft[0]['name'])
        print(f'FOUND EXISTING DRAFT: {stock_movement.name}')
        return stock_movement
    
    return None

def create_new_stock_movement(data, owner_warehouse):
    print('CREATING NEW DOC')
    stock_movement = frappe.new_doc('Stock Movement')
    stock_movement.transfer_status = data['transfer_status']
    setattr(
        stock_movement,
        'default_target_warehouse' if data['transfer_status'] == 'Stock Accept' else 'default_source_warehouse',
        owner_warehouse
    )
    stock_movement.owner = data['user_id']
    stock_movement.stock_entry_type = 'Material Transfer'
    stock_movement.save()
    print(f'NEW STOCK MOVEMENT CREATED: {stock_movement.name}')
    return stock_movement

def reset_scan_fields(stock_movement):
    """
    Reset the scan fields of the stock movement document.
    
    Args:
        stock_movement (StockMovement): The stock movement document.
    """
    stock_movement.scan_barcode = None
    stock_movement.scan_grade = None
    stock_movement.scan_warehouse = None

def handle_serialized_item(data, stock_movement, has_serial_no, owner_warehouse,rack_target_warehouse_msg,rack_target_warehouse,check_status):
    print('INSIDE SCAN BARCODE')
    serial_no_data = search_for_serial_or_batch_or_barcode_no(data['scan_barcode'])
    print(f'SERIAL_NO_DATA ==42== {serial_no_data}')

    if data['transfer_status'] == 'Stock Accept':
        if 'serial_no' in serial_no_data:
            print('INSIDE SERIALIZED DATA')
            has_serial_no['has_serial_no'] = 1
            stock_movement.scan_barcode = data['scan_barcode']
            print(f'SERIAL_NO_DATA ===28=== {serial_no_data}')
            
            existing_item = next((item for item in stock_movement.items if item.serial_no == serial_no_data['serial_no']), None)

            print('EXISTING ITEM: ', existing_item)

            if existing_item:
                raise frappe.ValidationError(_("<b>Serial No : {}</b> already exist. Please enter a valid one.".format(serial_no_data['serial_no'])))

            if not existing_item:
                new_item = {
                    'serial_no': serial_no_data['serial_no'],
                    'item_code': serial_no_data['item_code'],
                    'qty': 1
                }

                new_item.update({
                    's_warehouse': serial_no_data['warehouse'],
                    't_warehouse': owner_warehouse
                })
                stock_movement.append('items', new_item)
                stock_movement.save()
    elif data['transfer_status'] == 'Racking':
        print('INSIDE RACKING DATA OF SERIALIZED ITEM')
        if 'serial_no' in serial_no_data:
            if data['user_id']:
                # RACK TARGET WAREHOUSE MSG
                rack_warehouse_msg_data = get_all_emp_warehouse(data['user_id']).get('recommended','')
                rack_target_warehouse_msg.update({'rack_target_warehouse_msg': rack_warehouse_msg_data})
                print(f'TARGET RACK WAREHOUSE============211============= {rack_warehouse_msg_data}')
                # RACK TARGET WAREHOUSR DATA
                rack_warehouse_data = get_all_emp_warehouse(data['user_id']).get('warehouse','')
                rack_target_warehouse_list = rack_warehouse_data.split(',')
                rack_target_warehouse.update({'rack_target_warehouse': rack_target_warehouse_list})

                print(f'TARGET RACK WAREHOUSE============212============= {rack_warehouse_data}')
                
                has_serial_no['has_serial_no'] = 1
                stock_movement.scan_barcode = data['scan_barcode']
                print(f'SERIAL_NO_DATA ===28=== {serial_no_data}')
                
                existing_item = next((item for item in stock_movement.items if item.serial_no == serial_no_data['serial_no']), None)

                print('EXISTING ITEM: ', existing_item)

                if existing_item:
                    raise frappe.ValidationError(_("<b>Serial No : {}</b> already exist. Please enter a valid one.".format(serial_no_data['serial_no'])))

                if not existing_item and (data.get('rack_target_warehouse') or data.get('t_warehouse')):
    
                    new_item = {
                        'serial_no': serial_no_data['serial_no'],
                        'item_code': serial_no_data['item_code'],
                        'qty': 1
                    }

                    new_item.update({
                        's_warehouse': owner_warehouse,
                        't_warehouse': data.get('t_warehouse') if data.get('t_warehouse') else data.get('rack_target_warehouse')
                    })

                    stock_movement.append('items', new_item)
                    stock_movement.save()
                    
                    print("****************LENGTH_OF_ITEM_TO_UPDATED***************: ", len(stock_movement.items))

            stock_movement.save()

def handle_non_serialized_item(data, stock_movement, has_serial_no, owner_warehouse, rack_target_warehouse_msg, rack_target_warehouse,check_status):
    scan_barcode = data.get("scan_barcode")
    scan_grade = data.get("scan_grade")
    scan_warehouse = data.get("scan_warehouse")

    print(f'scan_barcode: {scan_barcode}, scan_grade: {scan_grade}, scan_warehouse: {scan_warehouse}')
    non_serialized_data = search_for_non_serialized_item(scan_barcode, scan_grade, scan_warehouse)
    print(f'NON_SERIALIZED_DATA ===30=== {non_serialized_data}')

    print('%'*20)
    print(f'\nNON_SERIALIZED_WAREHOUSE ========= {data.get("scan_warehouse")}`\n')
    print('%'*20)
    
    item_code_from_non_serialized_data = f'{non_serialized_data}-{scan_grade}'
    print(f'item_code_from_non_serialized_data ===31=== {item_code_from_non_serialized_data}')

    database_item_codes = get_all_item_codes()

    warehouse_check = get_all_warehouse()

    print(f'CHECKING_WAREHOSUES ===32=== {warehouse_check}')

    if data['transfer_status'] == 'Stock Accept':

        if item_code_from_non_serialized_data in database_item_codes:
            # existing_item = next((item for item in stock_movement.items if item.item_code == item_code_from_non_serialized_data), None)
            
            # if existing_item:
            #     raise frappe.throw(f"<b>Item code : {item_code_from_non_serialized_data}</b> already exists.")
            
            if data['scan_warehouse']:
                if data['scan_warehouse'] not in warehouse_check:
                    raise frappe.throw(f"<b>Warehouse : {data['scan_warehouse']}</b> does not exist.")
            
            if non_serialized_data and data.get('qty'):
                print(f'\n\n**************QUANTITY ENTERED INSIDE NON_SERIALIZED_DATA***************\n\n')
                has_serial_no['has_serial_no'] = 1
                stock_movement.scan_barcode = scan_barcode
                stock_movement.scan_grade = scan_grade
                stock_movement.scan_warehouse = scan_warehouse
                
                if data['transfer_status'] == 'Stock Accept':
                    stock_movement.default_target_warehouse = owner_warehouse
                
                print(f'NON_SERIALIZED_DATA ===32=== {non_serialized_data}')
                
                new_item = {
                    'item_code': item_code_from_non_serialized_data,
                    'qty': data['qty']
                }

                new_item.update({
                    's_warehouse': scan_warehouse,
                    't_warehouse': owner_warehouse
                })
                
                stock_movement.append('items', new_item)
                stock_movement.save()
            else:
                stock_movement.scan_barcode = scan_barcode
                stock_movement.scan_grade = scan_grade
                stock_movement.scan_warehouse = scan_warehouse
        else:
            print('#############FAILED###############')
            reset_scan_fields(stock_movement)
            stock_movement.save()
            print(f'=========={stock_movement.scan_grade}==========={stock_movement.scan_barcode}')
            raise frappe.ValidationError(_("<b>Item code : {}</b> doesn't exist. Please enter a valid Item.".format(item_code_from_non_serialized_data)))
        
    elif data['transfer_status'] == 'Racking':
        if item_code_from_non_serialized_data in database_item_codes:
            print(f'===================STOCK_MOVEMENT_ITEMS INSIDE RACKING=============={stock_movement.items}')
            # existing_item = next((item for item in stock_movement.items if item.item_code == item_code_from_non_serialized_data), None)
            
            # if existing_item:
            #     raise frappe.throw(f"<b>Item code : {item_code_from_non_serialized_data}</b> already exists.")
            
            if non_serialized_data and data.get('qty'):
                print(f'\n\n**************QUANTITY ENTERED INSIDE NON_SERIALIZED_DATA***************\n\n')
                has_serial_no['has_serial_no'] = 1
                stock_movement.scan_barcode = scan_barcode
                stock_movement.scan_grade = scan_grade
                stock_movement.scan_warehouse = scan_warehouse
                
                stock_movement.default_source_warehouse = owner_warehouse
                
                # Fetch and update the target rack warehouse message and data
                if data['user_id']:
                    # RACK TARGET WAREHOUSE MSG
                    rack_warehouse_msg_data = get_all_emp_warehouse(data['user_id']).get('recommended', '')
                    rack_target_warehouse_msg.update({'rack_target_warehouse_msg': rack_warehouse_msg_data})
                    print(f'TARGET RACK WAREHOUSE============211============= {rack_warehouse_msg_data}')
                    
                    # RACK TARGET WAREHOUSE DATA
                    rack_warehouse_data = get_all_emp_warehouse(data['user_id']).get('warehouse', '')
                    rack_target_warehouse_list = rack_warehouse_data.split(',')
                    rack_target_warehouse.update({'rack_target_warehouse': rack_target_warehouse_list})
                    
                    print(f'TARGET RACK WAREHOUSE============212============= {rack_warehouse_data}')

                    print(f'NON_SERIALIZED_DATA ===32=== {non_serialized_data}')

                    if data['rack_target_warehouse'] or data['t_warehouse']:

                        print(f'RACK_TARGET_WAREHOUSE {data["rack_target_warehouse"]}===========346=========== T_WAREHOUSE {data["t_warehouse"]}')
                        
                        t_warehouse = data.get('t_warehouse') if data.get('t_warehouse') else data.get('rack_target_warehouse')
                    
                        new_item = {
                            'item_code': item_code_from_non_serialized_data,
                            'qty': data['qty']
                        }

                        new_item.update({
                            's_warehouse': owner_warehouse,
                            't_warehouse':t_warehouse,
                        })
                        
                        stock_movement.append('items', new_item)
                        stock_movement.save()
                    
                else:
                    t_warehouse = owner_warehouse

                
            else:
                stock_movement.scan_barcode = scan_barcode
                stock_movement.scan_grade = scan_grade
                stock_movement.scan_warehouse = scan_warehouse
        else:
            print('#############FAILED###############')
            reset_scan_fields(stock_movement)
            stock_movement.save()
            print(f'=========={stock_movement.scan_grade}==========={stock_movement.scan_barcode}')
            raise frappe.ValidationError(_("<b>Item code : {}</b> doesn't exist. Please enter a valid Item.".format(item_code_from_non_serialized_data)))
    

def get_all_item_codes():
    database_items = frappe.get_all("Item", fields=["item_code"])
    return [item['item_code'] for item in database_items]

def get_all_warehouse():
    database_items = frappe.get_all("Warehouse", fields=["name"])
    return [item['name'] for item in database_items]

def handle_submission(data, stock_movement, submit_status):
    print(f'GOING TO SUBMIT THE DOC FOR {data["transfer_status"]}')
    stock_movement_data = stock_movement.as_dict()
    
    if data['submitStatus'] == 'true' and stock_movement_data['items']:
        print("IAM GOING TO SUBMIT")
        submit_status['submitStatus'] = 1
        stock_movement.submit()
    else:
        print("IAM NOT GOING TO SUBMIT")
        submit_status['submitStatus'] = 0

@frappe.whitelist()
def search_for_serial_or_batch_or_barcode_no(search_value):
    serial_no_data = frappe.db.get_value(
        "Serial No", search_value, ["name as serial_no", "item_code", "warehouse"], as_dict=True
    )
    if serial_no_data:
        return {
            "serial_no": serial_no_data.get("serial_no"), 
            "item_code": serial_no_data.item_code, 
            "warehouse": serial_no_data.warehouse, 
            "scan": 0
        }
    return {"scan": 1}

def search_for_non_serialized_item(scan_barcode, scan_grade, scan_warehouse):
    if '/' in scan_barcode:
        return scan_barcode
    elif '@' in scan_barcode:
        return scan_barcode.replace('@', '/')
    else:
        item_code = frappe.db.get_value('Non Serialized QR Code Mapping', {'name': scan_barcode}, 'item_code')
        return item_code if item_code else scan_barcode