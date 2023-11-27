from datetime import datetime

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.document import Document
from frappe.utils import add_days, today
from ecommerce_integrations.amazon.doctype.amazon_sp_api_settings.amazon_sp_api_settings import AmazonSPAPISettings
from nj_features.doctypes.amazon_sales_order.amazon_repository import (
        get_orders,
        )

class Amazonoverride(Document):
        @frappe.whitelist()
        def set_default_fields_map(self):
                for field_map in [
                        {"amazon_field": "ASIN", "item_field": "item_code", "use_to_find_item_code": 1},
                        {"amazon_field": "SellerSKU", "item_field": None, "use_to_find_item_code": 0,},
                        {"amazon_field": "Title", "item_field": None, "use_to_find_item_code": 0,},
                ]:
                        self.append("amazon_fields_map", field_map)
        @frappe.whitelist()
        def get_order_details(self):
                from  nj_features.doctypes.amazon_sales_order.amazon_repository import (
                        get_orders,
                )

                if self.is_active == 1:
                        job_name = f"Get Amazon Orders - {self.name}"

                        frappe.enqueue(
                                job_name=job_name,
                                method=get_orders,
                                amz_setting_name=self.name,
                                created_after=self.after_date,
                                timeout=4000,
                                now=frappe.flags.in_test,
                        )

                        frappe.msgprint(_("Order details will be fetched in the background."))
                else:
                        frappe.msgprint(
                                _("Please enable the Amazon SP API Settings {0}.").format(frappe.bold(self.name))
                        )

def schedule_get_order_details():
        from nj_features.doctypes.amazon_sales_order.amazon_repository import (
                get_orders,
        )

        amz_settings = frappe.get_all(
                "Amazon SP API Settings",
                filters={"is_active": 1, "scheduler_status": 1},
                fields=["name", "after_date"],
        )

        for amz_setting in amz_settings:
                get_orders(amz_setting_name=amz_setting.name, created_after=amz_setting.after_date)

@frappe.whitelist()
def on_submit(doc, handler=""):
    crt_amzsl_inv(doc.name)
    crt_amzdn(doc.name)

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
        frappe.msgprint(frappe._("Sales invoice Submitted",si.name), indicator="green", alert=True)
        frappe.db.commit()
        return si.name
    else:
        pass

@frappe.whitelist()
def crt_amzdn(sales_order_name):
    so = frappe.get_doc("Sales Order", sales_order_name)
    if so.naming_series == "SO-Amazon-" and so.order_type == "Sales":
        dn = frappe.new_doc("Delivery Note")
        dn.update({
            "customer": so.customer,
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.add_days(frappe.utils.today(), 30),  # Adjust the due date as needed
            "items": []
        })
        for item in so.items:
            dn.append("items", {
                "item_code": item.item_code,
                "rate": item.rate,
                "qty": item.qty,
                "against_sales_order": sales_order_name
            })
        dn.insert(ignore_permissions=True)
        frappe.msgprint(frappe._("Delivery Note created "+dn.name ,dn.name), indicator="green", alert=True)
        frappe.db.commit()
        return dn.name
    else:
        pass