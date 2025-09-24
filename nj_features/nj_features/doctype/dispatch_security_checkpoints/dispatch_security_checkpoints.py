# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, nowdate, getdate

class DispatchSecurityCheckpoints(Document):
    pass
    def on_submit(self):
        self.update_send_email_DN()
        self.update_payment_recived()
        # self.update_send_email_SI()

    def update_send_email_DN(self):
        try:
            for row in self.dispatch_security_child_table:
                if row.delivery_note:
                    dn_doc = frappe.get_doc("Delivery Note", row.delivery_note)
                    # print("dn_doc=======================", dn_doc)
                    dn_doc.send_email = 1
                    dn_doc.save(ignore_permissions=True)
                    frappe.db.commit()

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Error in update_send_email_DN")
            frappe.throw(f"Error while updating Delivery Note send_email: {e}")
    def update_send_email_SI(self):
        try:
            for row in self.dispatch_security_child_table:
                if row.sales_invoice:
                    # Fetch the Delivery Note
                    si_doc = frappe.get_doc("Sales Invoice", row.sales_invoice)
                    si_doc.send_email = 1
                    si_doc.save(ignore_permissions=True)
                    frappe.db.commit()

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Error in update_send_email_SI")
            frappe.throw(f"Error while updating Sales Invoice send_email: {e}")

    def update_payment_recived(self):
        try:
            for row in self.dispatch_security_child_table:
                if row.sales_order:
                    so_doc = frappe.get_doc("Sales Order", row.sales_order)
                    # print("so_doc=======================", so_doc)

                    if so_doc.get("is_cod") and not so_doc.get("payment_received"):
                        # print("so_doc=======================", so_doc.get("is_cod"))
                        so_doc.payment_received = 1
                        so_doc.save(ignore_permissions=True)
                        frappe.db.commit()

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Error in update_payment_recived")
            frappe.throw(f"Error while updating Sales Order payment_received: {e}")


@frappe.whitelist()
def scan_serial_no_data_for_sales(serial_no):
    try:
        serial_no = serial_no.strip()
        serial_no_exists = frappe.db.exists('Serial No', serial_no)
        if not serial_no_exists:
            frappe.throw(f"Serial No: {serial_no} doesn't exist")
            return None

        delivery_note = None
        dn_status = None
        sales_invoice = None
        sales_order = None
        item_code = None
        si_status = None
        approved = None
        sales_channel = None
        is_cod = None
        serial_no_from_dn_query = """
            SELECT dn.name as delivery_note, dn.status as dn_status, 
                dni.against_sales_invoice AS sales_invoice, 
                dni.against_sales_order AS sales_order,
                so.is_cod AS so_is_cod, 
                dni.item_code, 
                si.status as si_status, si.approved, si.sales_channel
            FROM `tabDelivery Note Item` dni
            INNER JOIN `tabSales Invoice` si ON si.name = dni.against_sales_invoice
            INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
            INNER JOIN `tabSales Order` so ON so.name = dni.against_sales_order
            LEFT JOIN `tabPacked Item` pi ON dn.name = pi.parent
            WHERE (
                dni.serial_no = {0}
                OR dni.serial_no LIKE {1}
                OR dni.serial_no LIKE {2}
                OR dni.serial_no LIKE {3}
                OR pi.serial_no = {0}
                OR pi.serial_no LIKE {1}
                OR pi.serial_no LIKE {2}
                OR pi.serial_no LIKE {3}
            ) AND dn.docstatus = 1
            ORDER BY dn.creation DESC, dn.modified DESC
        """.format(
            frappe.db.escape(serial_no),
            frappe.db.escape("{}\n%".format(serial_no)),
            frappe.db.escape("%\n{}".format(serial_no)),
            frappe.db.escape("%\n{}\n%".format(serial_no)),
        )

        result = frappe.db.sql(serial_no_from_dn_query, as_dict=True)
        if not result:
            serial_no_from_dn_query = """
                SELECT 
                    si.name AS sales_invoice,
                    si.status AS si_status,
                    sii.delivery_note AS delivery_note,
                    dn.status AS dn_status,
                    sii.sales_order AS sales_order,
                    so.is_cod AS so_is_cod,
                    sii.item_code,
                    si.approved,
                    si.sales_channel
                FROM `tabSales Invoice Item` sii
                INNER JOIN `tabSales Invoice` si 
                    ON si.name = sii.parent
                LEFT JOIN `tabDelivery Note` dn
                    ON dn.name = sii.delivery_note
                LEFT JOIN `tabSales Order` so
                    ON so.name = sii.sales_order    
                LEFT JOIN `tabPacked Item` pi ON si.name = pi.parent    
                WHERE (
                    sii.serial_no = {0}
                    or sii.serial_no like {1}
                    or sii.serial_no like {2}
                    or sii.serial_no like {3}
                    or pi.serial_no = {0}
                    or pi.serial_no like {1}
                    or pi.serial_no like {2}
                    or pi.serial_no like {3}
                )
                AND si.docstatus = 1
                ORDER BY si.creation DESC, si.modified DESC;
            """.format(
                frappe.db.escape(serial_no),
                frappe.db.escape("{}\n%".format(serial_no)),
                frappe.db.escape("%\n{}".format(serial_no)),
                frappe.db.escape("%\n{}\n%".format(serial_no)),
            )

            result = frappe.db.sql(serial_no_from_dn_query, as_dict=True)

        if result:
            data = result[0]
            delivery_note = data.get('delivery_note')
            dn_status = data.get('dn_status')
            sales_invoice = data.get('sales_invoice')
            sales_order = data.get('sales_order')
            item_code = data.get('item_code')
            si_status = data.get('si_status')
            approved = data.get('approved')
            sales_channel = data.get('sales_channel')
            is_cod = data.get('so_is_cod')

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

        if delivery_note:
            delivery_note_creation = frappe.db.get_value('Delivery Note', delivery_note, 'creation')
            if delivery_note_creation:
                creation_date = getdate(delivery_note_creation)
                four_days_ago = add_days(nowdate(), -10)  # actually checks 10 days back
                if creation_date < getdate(four_days_ago):
                    frappe.throw("The latest Delivery Note was not created within the last 10 days.")

            customer_name = ""
            courier_name = ""
            tracking_id = ""
            email_id = ""
            dn_doc = frappe.get_doc("Delivery Note", delivery_note)
            customer_name = dn_doc.customer 
            courier_name = dn_doc.get("courier_service", "")
            tracking_id = dn_doc.get("tracking_id", "")
            if dn_doc.shipping_address_name:
                try:
                    address = frappe.get_doc("Address", dn_doc.shipping_address_name)
                    email_id = address.get("email_id", "")
                except frappe.DoesNotExistError:
                    pass

            return {
                'serial_no': serial_no,
                'item_code': item_code,
                'delivery_note': delivery_note,
                'sales_invoice': sales_invoice,
                'sales_order': sales_order,
                'si_status': si_status,
                'dn_status': dn_status,
                'sales_channel': sales_channel,
                'approved': approved,
                'customer_name': customer_name,
                'courier_name': courier_name,
                'tracking_id': tracking_id,
                'email_id': email_id,
                'is_cod': is_cod
            }

        return None

    except Exception as e:
        frappe.throw(e)

@frappe.whitelist()
def scan_serial_no_data_for_return(pr_name):
    try:
        pr_name = pr_name.strip()
        if not frappe.db.exists('Purchase Receipt', pr_name):
            frappe.throw(f"Serial No or Purchase Receipt: {pr_name} doesn't exist")
            return None
        if pr_name:
            return_data = frappe.db.sql(f"""select Pr.name as PR, Pr.status as PR_Status , Pr.total as PR_Total, Pi.total as PI_Total,
                                            Pi.name as PI, Pi.status as PI_Status from `tabPurchase Receipt` Pr
                                            inner join `tabPurchase Invoice Item` PII 
                                            inner join `tabPurchase Invoice` Pi
                                            on PII.purchase_receipt = Pr.name and 
                                            Pi.name = PII.parent
                                            where Pr.name = 'PREC-RET-00222' and Pr.is_return = 1
                                """, as_dict=True)
        print(return_data)            
        if not return_data:
            frappe.msgprint(_("No PR or PI data found for <b>{}</b>").format(pr_name))
            return None
        if not return_data[0].get('PR') and not return_data[0].get('PI'):
            frappe.msgprint(_("No PR or PI data found for <b>{}</b>").format(pr_name))
            return None

        if not return_data[0].get('PR_Status') and not return_data[0].get('PI_Status'):
            frappe.msgprint(_("Please check the status of PR or PI for <b>{}</b>").format(pr_name))
            return None
        
        if not return_data[0].get('PR_Total') or return_data[0].get('PR_Total') >= 0 and return_data[0].get('PI_Total') != return_data[0].get('PR_Total'):
            frappe.msgprint(_("Please check the total amount of PR or PI found for<b>{}</b>").format(pr_name))
            return None
        return {
            'purchase_receipt': return_data[0].get('PR'),
            'purchase_invoice': return_data[0].get('PI'),
            'pr_status': return_data[0].get('PR_Status'),
            'pi_status': return_data[0].get('PI_Status')
        }
    
    except Exception as e:
        frappe.throw(e)

@frappe.whitelist()
def get_item_code_details_for_transfer(ste_number):
    ste_number = ste_number.strip()
    if not frappe.db.exists('Stock Entry', ste_number):
        frappe.throw(f"Stock Entry : {ste_number} doesn't exist")
        return None

    material_transfer_details = frappe.db.get_all("Stock Entry Detail",
        filters={'parent': ste_number},
        fields=['t_warehouse', 'qty', 'item_code', 's_warehouse', 'idx', 'serial_no','parent']
    )

    result = []

    for row in material_transfer_details:
        s_warehouse_lc = frappe.db.get_value("Warehouse", {'name': row['s_warehouse']}, ['location'])
        t_warehouse_lc = frappe.db.get_value("Warehouse", {'name': row['t_warehouse']}, ['location'])

        if s_warehouse_lc == t_warehouse_lc:
            result.append({
                'error': f'The source warehouse and target warehouse cannot have the same location at  row <br><b>{row["idx"]}  .{row["item_code"]} at {ste_number}</b>'
            })
        else:
            result.append(row)

    return result
