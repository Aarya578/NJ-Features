# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from frappe import _  # Add this line

class DispatchSecurityCheckpoints(Document):
    pass


@frappe.whitelist()
def scan_serial_no_data(serial_no, doc_name=None):
    """
    Function to fetch sales invoice, delivery note, and item code details for the scanned serial number,
    and validate if both sales invoice and delivery note are mandatory for 'Amazon' sales channel,
    and if for other channels, the Sales Invoice status must be 'Paid' unless approved.
    
    Args:
        serial_no (str): The serial number being checked.
        doc_name (str, optional): The name of the current document (to avoid checking against itself).
    
    Returns:
        dict: Contains serial number details, sales invoice, delivery note, and item code information.
    """
    serial_no_doc = frappe.get_doc('Serial No', serial_no)
    
    item_code = serial_no_doc.item_code if serial_no_doc.item_code else 'Not Available'
    # print(f'=================================item-code=======',item_code)
    
    sales_invoices = frappe.db.get_list('Sales Invoice', 
        filters={
            'serial_no': ['like', '%' + serial_no + '%'],
            'docstatus': 1  
        },
        fields=['name', 'status', 'approved']  
    )

    delivery_notes = frappe.db.get_list('Delivery Note', 
        filters={
            'serial_no': ['like', '%' + serial_no + '%'],
            'docstatus': 1  
        },
        fields=['name', 'status']
    )

    sales_invoice = sales_invoices[0] if sales_invoices else None
    delivery_note = delivery_notes[0] if delivery_notes else None

    si_status = sales_invoice['status'] if sales_invoice else 'Not Available'
    dn_status = delivery_note['status'] if delivery_note else 'Not Available'
    approved = sales_invoice['approved'] if sales_invoice else 0  # Default to 0 if not found

    sales_channel = None
    if sales_invoice:
        sales_channel = frappe.db.get_value('Sales Invoice', sales_invoice['name'], 'sales_channel')

    if sales_channel == 'Amazon':
        if not sales_invoice or not delivery_note:
            frappe.throw(_("For Amazon orders, both Sales Invoice and Delivery Note must be submitted and available."))

    elif sales_invoice and sales_channel != 'Amazon':
        if si_status != 'Paid':
            if approved != 1:
                frappe.throw(_("Sales Invoice '{}' must have a 'Paid' status to proceed, unless it is approved.").format(sales_invoice['name']))
            else:
                frappe.msgprint(_("Sales Invoice '{}' is not 'Paid' but has been approved.").format(sales_invoice['name']))

    if not sales_invoice and not delivery_note:
        frappe.throw(_("No submitted Sales Invoice or Delivery Note found for the serial number {}").format(serial_no))

    return {
        'serial_no': serial_no,
        'item_code': item_code,
        'sales_invoice': sales_invoice['name'] if sales_invoice else None,
        'si_status': si_status,
        'delivery_note': delivery_note['name'] if delivery_note else None,
        'dn_status': dn_status,
        'sales_channel': sales_channel,  
        'approved': approved  
    }
