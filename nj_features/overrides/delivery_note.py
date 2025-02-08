# Copyright (c) 2023, NewJaisa - IT Team
# For license information, please see license.txt

import frappe
import json
from frappe import _
from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote
from nj_lib.utils.common_utils import get_latest_item_wizard


class CustomDeliveryNote(DeliveryNote):
    def on_submit(self):
        super().on_submit()
        
        if not self.is_return:
            return
        
        self._process_serial_numbers()
    
    def _process_serial_numbers(self):

        for item in self.items:
            if not self._should_process_item(item):
                continue
            
            self._update_serial_number_components(item)
        
        frappe.db.commit()
    
    def _should_process_item(self, item):
       
        has_serial_no = frappe.db.get_value('Item', item.item_code, 'has_serial_no')
        
        return has_serial_no and item.serial_no
    
    def _update_serial_number_components(self, item):
       
        serial_list = item.serial_no.split('\n')
        
        for serial_no in serial_list:
            try:
                serial_no_doc = frappe.get_doc('Serial No', serial_no)
                
                item_template = frappe.db.get_value(
                    "Item", 
                    {'name': item.item_code}, 
                    'variant_of'
                )
                latest_item_wizard = self._get_latest_item_wizard(item_template, item.item_code)
                item_wizard_doc = frappe.get_doc('Item Wizards', latest_item_wizard)
                
                self._update_components(
                    serial_no_doc, 
                    item_wizard_doc, 
                    self.doctype, 
                    self.name
                )
                
            except Exception as e:
                frappe.log_error(
                    f"Error processing serial number {serial_no}: {str(e)}",
                    "CustomDeliveryNote Serial Number Update"
                )
    
    def _get_latest_item_wizard(self, item_template, item_code):

        return get_latest_item_wizard(item_template, item_code)
    
    def _update_components(self, serial_no_doc, item_wizard_doc, reference_doctype, reference_name):
      
        updated = False
        
        for item_component in item_wizard_doc.component:
            for serial_no_component in serial_no_doc.serial_no_component:
                    if serial_no_component.item_group == item_component.get("component_type"):
                        serial_no_component.quantity = '1'
                        serial_no_component.grade = 'UNKNOWN'
                        serial_no_component.reference_doctype = reference_doctype
                        serial_no_component.reference_doctype_no = reference_name
                        updated = True
        
        if updated:
            serial_no_doc.save(ignore_permissions=True) 

@frappe.whitelist()
def set_tracking_id_for_delivery_note(doc):

    if isinstance(doc, str):
        doc = json.loads(doc)

    dn_item = doc.get('items')[0].get('against_sales_order')

    sales_order_type = frappe.db.get_value('Sales Order', dn_item, 'sale_type')

    if sales_order_type == 'Amazon':
        return True
    
    return False


@frappe.whitelist()
def get_link_1(name):
    nj_setting_value = frappe.db.get_value("NJ Settings", {"parameter": "NJpulse_url"}, "value")
    
    link = frappe.db.get_list("Doc Attachment", {"doctypename": name, "file_type": "Video", "docstatus": 1}, ["linked_data"])
    for item in link:
        item["linked_data"] = nj_setting_value + item["linked_data"]
    return link


@frappe.whitelist()
def validate_delivery_bios(doc):
    error_message = []

    if isinstance(doc, str):
        doc = json.loads(doc)

    item_group_list = frappe.db.get_value('NJ Settings', {'parameter': 'bios_item_group'}, ['value'])

    if item_group_list:
        item_group_list = json.loads(item_group_list)

    for item in doc.get('items'):
        serial_no = item.get('serial_no', '').strip()
        item_group = item.get("item_group")
        idx = item.get("idx", "N/A")

        if serial_no:
            serial_list = serial_no.split('\n')

            for serial in serial_list:
                bios_serial_no = frappe.db.get_value('Serial No', serial, 'bios_serial_no')
                if not (bios_serial_no and item_group in item_group_list):
                    error_message.append(
                        f"<b>Row {idx}</b>: Serial No <b>{serial}</b> for item group <b>{item_group}</b> has no Bios Serial No"
                    )

    return error_message if error_message else True
