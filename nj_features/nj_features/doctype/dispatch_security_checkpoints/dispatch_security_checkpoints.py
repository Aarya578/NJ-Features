# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from frappe import _  # Add this line

class DispatchSecurityCheckpoints(Document):
    pass


@frappe.whitelist()
def scan_serial_no_data_for_sales(serial_no):
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
                                                    AND serial_no = '{serial_no}' ORDER BY creation DESC LIMIT 1)
                                                """, as_dict=True)
        
        delivery_notes = frappe.db.sql(f"""SELECT name, status
                                                FROM `tabDelivery Note` 
                                                WHERE name = (
                                                    SELECT parent 
                                                    FROM `tabDelivery Note Item` 
                                                    WHERE docstatus = 1 
                                                    AND serial_no = '{serial_no}' ORDER BY creation DESC LIMIT 1)
                                                """, as_dict=True)
        
        sales_invoice = sales_invoices[0].get('name') if sales_invoices else None
        delivery_note = delivery_notes[0].get('name') if delivery_notes else None
        si_status = sales_invoices[0].get('status') if sales_invoices else 'Not Available'
        dn_status = delivery_notes[0].get('status') if delivery_notes else 'Not Available'
        approved = sales_invoices[0].get('approved') if sales_invoices else 0

        sales_channel = None
        if sales_invoice:
            sales_channel = frappe.db.get_value('Sales Invoice', sales_invoice, 'sales_channel')
        else:
            frappe.msgprint(_("Sales Invoice not found for serial number <b>{}</b>").format(serial_no))
            return None
        if sales_channel == 'Amazon':
            if not sales_invoice and not delivery_note:
                frappe.msgprint(_("For Amazon orders, both Sales Invoice and Delivery Note must be submitted and available."))
                return None
        
        elif sales_invoice and sales_channel != 'Amazon':
            if si_status != 'Paid' or approved == 1:
                frappe.msgprint(_("Sales Invoice '{}' must have a 'Paid' status to proceed, unless it is approved.").format(sales_invoice))
                return None
            
        if not sales_invoice and not delivery_note :
            frappe.msgprint(_("`Sales Invoice` or `Delivery Note` must be created for the serial number <b>{}</b>").format(serial_no))
            return None
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


@frappe.whitelist()
def scan_serial_no_data_for_return(serial_no):
    try:
        serial_no_doc = frappe.get_doc('Serial No', serial_no)
        item_code = serial_no_doc.item_code if serial_no_doc.item_code else 'Not Available'

        return_data = frappe.db.sql(f"""SELECT ch.parent as PR, ch.purchase_invoice as PI, 
                            pr.status as PR_Status, pi.status as PI_Status
                            FROM `tabPurchase Receipt Item` ch
                            LEFT JOIN `tabPurchase Receipt` pr on pr.name = ch.parent
                            LEFT JOIN `tabPurchase Invoice` pi on pi.name = ch.purchase_invoice
                            WHERE ch.serial_no = '{serial_no}' AND pr.is_return = 1 
                            AND ch.purchase_invoice is not null or ch.purchase_invoice != ''
                            ORDER BY ch.creation DESC, ch.modified DESC limit 1
                            """, as_dict=True)
            
        if not return_data:
            frappe.msgprint(_("No PR or PI data found for serial number <b>{}</b>").format(serial_no))
            return None
        if not return_data[0].get('PR') and not return_data[0].get('PI'):
            frappe.msgprint(_("No PR or PI data found for serial number <b>{}</b>").format(serial_no))
            return None

        if not return_data[0].get('PR_Status') and not return_data[0].get('PI_Status'):
            frappe.msgprint(_("Please check the status of PR or PI found for serial number <b>{}</b>").format(serial_no))
            return None

        return {
            'serial_no': serial_no,
            'item_code': item_code,
            'purchase_receipt': return_data[0].get('PR'),
            'purchase_invoice': return_data[0].get('PI'),
            'pr_status': return_data[0].get('PR_Status'),
            'pi_status': return_data[0].get('PI_Status')
        }
    except Exception as e:
        frappe.throw(e)