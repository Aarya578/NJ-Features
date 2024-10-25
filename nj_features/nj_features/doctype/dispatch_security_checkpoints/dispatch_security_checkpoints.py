# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from frappe import _  # Add this line

class DispatchSecurityCheckpoints(Document):
    pass


@frappe.whitelist()
def scan_serial_no_data(serial_no):
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

    try:
        serial_no_doc = frappe.get_doc('Serial No', serial_no)
        
        item_code = serial_no_doc.item_code if serial_no_doc.item_code else 'Not Available'
    
        sales_invoices = frappe.db.sql(f"""SELECT name, status, approved 
                                                FROM `tabSales Invoice` 
                                                WHERE name = (
                                                    SELECT parent 
                                                    FROM `tabSales Invoice Item` 
                                                    WHERE docstatus = 1 
                                                    AND serial_no = '{serial_no}' ORDER BY creation DESC LIMIT 1
                                                )""", as_dict=True)
        
        delivery_notes = frappe.db.sql(f"""SELECT name, status
                                                FROM `tabDelivery Note` 
                                                WHERE name = (
                                                    SELECT parent 
                                                    FROM `tabDelivery Note Item` 
                                                    WHERE docstatus = 1 
                                                    AND serial_no = '{serial_no}' ORDER BY creation DESC LIMIT 1
                                                )""", as_dict=True)
        
        sales_invoice = sales_invoices[0].get('name') if sales_invoices else None
        delivery_note = delivery_notes[0].get('name') if delivery_notes else None
        si_status = sales_invoices[0].get('status') if sales_invoices else 'Not Available'
        dn_status = delivery_notes[0].get('status') if delivery_notes else 'Not Available'
        approved = sales_invoices[0].get('approved') if sales_invoices else 0

        sales_channel = None
        if sales_invoice:
            sales_channel = frappe.db.get_value('Sales Invoice', sales_invoice, 'sales_channel')
        if sales_channel == 'Amazon':
            if not sales_invoice and not delivery_note:
                frappe.msgprint(_("For Amazon orders, both Sales Invoice and Delivery Note must be submitted and available."))
                return {}
        
        elif sales_invoice and sales_channel != 'Amazon':
            if si_status != 'Paid' or approved == 1:
                frappe.msgprint(_("Sales Invoice '{}' must have a 'Paid' status to proceed, unless it is approved.").format(sales_invoice))
                return {}
            
        if not sales_invoice and not delivery_note :
            frappe.msgprint(_("`Sales Invoice` or `Delivery Note` must be created for the serial number <b>{}</b>").format(serial_no))
            return {}
        return {
            'serial_no': serial_no,
            'item_code': item_code,
            'sales_invoice': sales_invoice if sales_invoice else None,
            'si_status': si_status,
            'delivery_note': delivery_note if delivery_note else None,
            'dn_status': dn_status,
            'sales_channel': sales_channel,  
            'approved': approved  
        }

    except Exception as e:
        frappe.throw(e)