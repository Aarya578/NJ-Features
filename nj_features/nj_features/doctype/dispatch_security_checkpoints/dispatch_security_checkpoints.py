# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

class DispatchSecurityCheckpoints(Document):
    pass

@frappe.whitelist()
def scan_serial_no_data_for_sales(serial_no):
    try:
        serial_no = serial_no.strip()
        serial_no_exists = frappe.db.exists('Serial No', serial_no)
        if not serial_no_exists:
            frappe.throw(f"Serial No: {serial_no} doesn't exist")
            return None
        
        result = frappe.db.sql(f"""
            SELECT dn.name as delivery_note, dn.status as dn_status, dni.serial_no, 
                dni.against_sales_invoice AS sales_invoice, dni.against_sales_order AS sales_order, 
                dni.item_code, si.status as si_status, si.approved, si.sales_channel
            FROM `tabDelivery Note Item` dni
            INNER JOIN `tabSales Invoice` si ON si.name = dni.against_sales_invoice
            INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            WHERE dni.serial_no = %s AND dn.docstatus = 1
        """, (serial_no,), as_dict=True)

        if result:
            delivery_note_data = result[0]

            delivery_note = delivery_note_data.get('delivery_note')
            dn_status = delivery_note_data.get('dn_status')
            sales_invoice = delivery_note_data.get('sales_invoice')
            sales_order = delivery_note_data.get('sales_order')
            item_code = delivery_note_data.get('item_code')
            si_status = delivery_note_data.get('si_status')
            approved = delivery_note_data.get('approved')
            sales_channel = delivery_note_data.get('sales_channel')

            if sales_invoice:
                if sales_channel == 'Amazon' and (not sales_invoice or not delivery_note):
                    frappe.msgprint(_("For Amazon orders, both Sales Invoice and Delivery Note must be submitted and available."))
                    return None
                elif sales_channel != 'Amazon' and si_status != 'Paid' and approved == 0:
                    frappe.msgprint(_("Sales Invoice '{}' must have a 'Paid' status to proceed and it is approved.").format(sales_invoice))
                    return None
                elif sales_channel != 'Amazon' and si_status == 'Paid' and approved == 0:
                    frappe.msgprint(_("Sales Invoice '{}' must be approved to proceed.").format(sales_invoice))
                    return None
            else:
                frappe.throw(_("No matching sales invoice found for serial number <b>{}</b>").format(serial_no))
                return None
        else:
            frappe.throw(_("No matching delivery note or sales invoice found for serial number <b>{}</b>").format(serial_no))
            return None

        return {
            'serial_no': serial_no,
            'item_code': item_code,
            'delivery_note': delivery_note,
            'sales_invoice': sales_invoice,
            'sales_order': sales_order,
            'si_status': si_status,
            'dn_status': dn_status,
            'sales_channel': sales_channel,
            'approved': approved
        }

    except Exception as e:
        frappe.throw(e)

@frappe.whitelist()
def scan_serial_no_data_for_return(serial_no):
    try:
        serial_no = serial_no.strip()
        serial_no_exists = frappe.db.exists('Serial No', serial_no)
        if not serial_no_exists:
            frappe.throw(f"Serial No: {serial_no} doesn't exist")
            return None

        return_data = frappe.db.sql(f"""SELECT ch.parent as PR, ch.purchase_invoice as PI, 
                            pr.status as PR_Status, pi.status as PI_Status, ch.item_code
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
            'item_code': return_data[0].get('item_code'),
            'purchase_receipt': return_data[0].get('PR'),
            'purchase_invoice': return_data[0].get('PI'),
            'pr_status': return_data[0].get('PR_Status'),
            'pi_status': return_data[0].get('PI_Status')
        }
    
    except Exception as e:
        frappe.throw(e)