from datetime import datetime
import requests
import frappe
from frappe import _
from frappe import get_list
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.document import Document
from frappe.utils import add_days, today
from ecommerce_integrations.amazon.doctype.amazon_sp_api_settings.amazon_sp_api_settings import AmazonSPAPISettings
from ecommerce_integrations.amazon.doctype.amazon_sp_api_settings import amazon_sp_api_settings
from frappe.desk.form.linked_with import get_linked_doctypes
from frappe.desk.form.linked_with import get_linked_docs
class Amazonoverride(Document):
    @frappe.whitelist()
    def get_order_details(self):
                from  nj_features.doctypes.amazon_sales_order.amazon_repository import (
                        get_orders,
                )

                if self.is_active == 1:
                        job_name = f"Get Amazon Orders - {self.name}"

                        #if frappe.db.get_all("RQ Job", {"job_name": job_name, "status": ["in", ["queued", "started"]]}):
                         #       return frappe.msgprint(_("The order details are currently being fetched in the background."))

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

def enable_auto_amazon_sync():
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

# from __future__ import annotations
# from ecommerce_integrations.amazon.doctype.amazon_sp_api_settings.amazon_repository import AmazonRepository
# import time

# class overrideamazon:
#     def create_sales_order(self, order) -> str | None:
#                 def create_customer(order) -> str:
#                         order_customer_name = ""
#                         buyer_info = order.get("BuyerInfo")

#                         if buyer_info and buyer_info.get("BuyerEmail"):
#                                 order_customer_name = buyer_info.get("BuyerEmail")
#                         else:
#                                 order_customer_name = f"Buyer - {order.get('AmazonOrderId')}"

#                         existing_customer_name = frappe.db.get_value(
#                                 "Customer", filters={"name": order_customer_name}, fieldname="name"
#                         )

#                         if existing_customer_name:
#                                 filters = [
#                                         ["Dynamic Link", "link_doctype", "=", "Customer"],
#                                         ["Dynamic Link", "link_name", "=", existing_customer_name],
#                                         ["Dynamic Link", "parenttype", "=", "Contact"],
#                                 ]

#                                 existing_contacts = frappe.get_list("Contact", filters)

#                                 if not existing_contacts:
#                                         new_contact = frappe.new_doc("Contact")
#                                         new_contact.first_name = order_customer_name
#                                         new_contact.append(
#                                                 "links", {"link_doctype": "Customer", "link_name": existing_customer_name},
#                                         )
#                                         new_contact.insert()

#                                 return existing_customer_name
#                         else:
#                                 new_customer = frappe.new_doc("Customer")
#                                 new_customer.customer_name = order_customer_name
#                                 new_customer.customer_group = self.amz_setting.customer_group
#                                 new_customer.territory = self.amz_setting.territory
#                                 new_customer.customer_type = self.amz_setting.customer_type
#                                 new_customer.save()

#                                 new_contact = frappe.new_doc("Contact")
#                                 new_contact.first_name = order_customer_name
#                                 new_contact.append("links", {"link_doctype": "Customer", "link_name": new_customer.name})

#                                 new_contact.insert()

#                                 return new_customer.name

#                 def create_address(order, customer_name) -> str | None:
#                         shipping_address = order.get("ShippingAddress")
#                         order_customer_name = ""
#                         buyer_info = order.get("BuyerInfo")

#                         if buyer_info and buyer_info.get("BuyerEmail"):
#                                 order_customer_name = buyer_info.get("BuyerEmail")
#                         else:
#                                 order_customer_name = f"Buyer - {order.get('AmazonOrderId')}"


#                         if not shipping_address:
#                                 # return
#                                 make_address = frappe.new_doc("Address")
#                                 make_address.address_line1 = order_customer_name
#                                 make_address.city = "to be updated"
#                                 make_address.state = "to be updated"
#                                 make_address.pincode = "to be updated"

#                                 filters = [
#                                         ["Dynamic Link", "link_doctype", "=", "Customer"],
#                                         ["Dynamic Link", "link_name", "=", customer_name],
#                                         ["Dynamic Link", "parenttype", "=", "Address"],
#                                 ]
#                                 existing_address = frappe.get_list("Address", filters)

#                                 for address in existing_address:
#                                         address_doc = frappe.get_doc("Address", address["name"])
#                                         if (
#                                                 address_doc.address_line1 == make_address.address_line1
#                                                 and address_doc.pincode == make_address.pincode
#                                         ):
#                                                 return address

#                                 make_address.append("links", {"link_doctype": "Customer", "link_name": customer_name})
#                                 make_address.address_type = "Shipping"
#                                 make_address.insert(ignore_permissions=True)
#                         else:
#                                 make_address = frappe.new_doc("Address")
#                                 make_address.address_line1 = shipping_address.get("AddressLine1", "Not Provided")
#                                 make_address.city = shipping_address.get("City", "Not Provided")
#                                 make_address.state = shipping_address.get("StateOrRegion").title()
#                                 make_address.pincode = shipping_address.get("PostalCode")

#                                 filters = [
#                                         ["Dynamic Link", "link_doctype", "=", "Customer"],
#                                         ["Dynamic Link", "link_name", "=", customer_name],
#                                         ["Dynamic Link", "parenttype", "=", "Address"],
#                                 ]
#                                 existing_address = frappe.get_list("Address", filters)

#                                 for address in existing_address:
#                                         address_doc = frappe.get_doc("Address", address["name"])
#                                         if (
#                                                 address_doc.address_line1 == make_address.address_line1
#                                                 and address_doc.pincode == make_address.pincode
#                                         ):
#                                                 return address

#                                 make_address.append("links", {"link_doctype": "Customer", "link_name": customer_name})
#                                 make_address.address_type = "Shipping"
#                                 make_address.insert(ignore_permissions=True)

#                 order_id = order.get("AmazonOrderId")
#                 so = frappe.db.get_value("Sales Order", filters={"amazon_order_id": order_id}, fieldname="name")

#                 if so:
#                         return so
#                 else:
#                         items = self.get_order_items(order_id)

#                         if not items:
#                                 return

#                         customer_name = create_customer(order)
#                         create_address(order, customer_name)

#                         delivery_date = dateutil.parser.parse(order.get("LatestShipDate")).strftime("%Y-%m-%d")
#                         transaction_date = dateutil.parser.parse(order.get("PurchaseDate")).strftime("%Y-%m-%d")

#                         so = frappe.new_doc("Sales Order")
#                         so.amazon_order_id = order_id
#                         so.naming_series = "SO-Amazon-"
#                         so.marketplace_id = order.get("MarketplaceId")
#                         so.customer = customer_name
#                         so.sale_type = "Amazon"
#                         so.delivery_date = delivery_date
#                         so.transaction_date = transaction_date
#                         so.company = self.amz_setting.company

#                         for item in items:
#                                 so.append("items", item)

#                         taxes_and_charges = self.amz_setting.taxes_charges

#                         if taxes_and_charges:
#                                 charges_and_fees = self.get_charges_and_fees(order_id)

#                                 for charge in charges_and_fees.get("charges"):
#                                         so.append("taxes", charge)

#                                 for fee in charges_and_fees.get("fees"):
#                                         so.append("taxes", fee)

#                         so.insert(ignore_permissions=True)
#                         # so.submit()

#                         return so.name

#     def create_sales_order(self, order) -> str | None:
#         print("\n\n\n  this is simple one \n\n\n")
#         return
# @frappe.whitelist()
# def tesing_one(doc, handler=""):
#     docum = frappe.get_doc("Sales Order", doc.name)
#     if docum.customer_address:
#         # crt_amzsl_inv(doc.name)
#         docum.insert(ignore_permissions=True)
#         # docum.submit()
#     else:
#         docum.insert(ignore_permissions=True)
#         # docum.submit()

@frappe.whitelist()
def get(doctype, docname):
	linked_doctypes = get_linked_doctypes(doctype=doctype)
	return get_linked_docs(doctype=doctype, name=docname, linkinfo=linked_doctypes)

@frappe.whitelist()
def on_submit(doc, handler=""):
    crt_amzsl_inv(doc.name)
    crt_amzdn(doc.name)
    amazon_shiped_status()
    # get_auth()
    # get_unshipped()

@frappe.whitelist()
def crt_amzsl_inv(sales_order_name):
    so = frappe.get_doc("Sales Order", sales_order_name)
    if so.is_replacement_order == 1:
          replace_ord = frappe.get_doc("Sales Order", so.replacing_order)
          org_inv = get_si_name(so.replacing_order)
          si = frappe.new_doc("Sales Invoice")
          si.update({
            "customer": so.customer,
            "naming_series": 'SINV-',
            "sales_channel": 'Amazon',
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.add_days(frappe.utils.today(), 30),
            "items": []
        })
          for item in replace_ord.items:
            si.append("items", {
                "item_code": item.item_code,
                "rate": item.rate,
                "qty": item.qty,
                "sales_order": sales_order_name
            })
          si.insert(ignore_permissions=True)
          si.submit()
          frappe.msgprint(frappe._("Sales invoice created",si.name), indicator="green", alert=True)
          frappe.db.commit()
          create_credit_note(org_inv)
          frappe.msgprint(frappe._("Credit Note created for replaced order",si.name), indicator="green", alert=True)
          return si.name
    elif so.naming_series == "SO-Amazon-" and so.order_type == "Sales":
              si = frappe.new_doc("Sales Invoice")
              si.update({
            "customer": so.customer,
            "naming_series": 'SINV-',
            "sales_channel": 'Amazon',
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.add_days(frappe.utils.today(), 30),
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
                   frappe.msgprint(frappe._("Sales invoice created",si.name), indicator="green", alert=True)
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

# @frappe.whitelist()
# def crt_amzdn_credit(sales_order_name):
#     so = frappe.get_doc("Sales Order", sales_order_name)
#     if so.naming_series == "SO-Amazon-" and so.order_type == "Sales":
#         dn = frappe.new_doc("Delivery Note")
#         dn.update({
#             "customer": so.customer,
#             "posting_date": frappe.utils.today(),
#             "due_date": frappe.utils.add_days(frappe.utils.today(), 30),  # Adjust the due date as needed
#             "items": []
#         })
#         for item in so.items:
#             dn.append("items", {
#                 "item_code": item.item_code,
#                 "rate": item.rate,
#                 "qty": item.qty,
#                 "against_sales_order": sales_order_name
#             })
#         dn.insert(ignore_permissions=True)
#         frappe.msgprint(frappe._("Delivery Note created "+dn.name ,dn.name), indicator="green", alert=True)
#         frappe.db.commit()
#         return dn.name
#     else:
#         pass

@frappe.whitelist()
def get_si_name(sales_order):
      linked = get("Sales Order", sales_order)
      sales_invoice_list = linked.get("Sales Invoice", [])
      if sales_invoice_list:
           sales_invoice_name = sales_invoice_list[0]["name"]
           print("                    "+ sales_invoice_name+ "                    ")
           return sales_invoice_name
      else:
           return "No Payment Entry found."

@frappe.whitelist()
def create_credit_note(sales_invoice_name):
    # Load the Sales Invoice document
    sales_invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
    for item in sales_invoice.items:
        # Get the income account from the item
        income_account_item = sales_invoice.items[0]
        income_account = income_account_item.income_account
        cost_center = income_account_item.cost_center
    # Create a new GL Entry
    gl_entry = frappe.new_doc("GL Entry")
    gl_entry.posting_date = sales_invoice.posting_date
    gl_entry.account = income_account  # Replace with the actual GL account
    gl_entry.credit = sales_invoice.grand_total
    gl_entry.party_type = "Customer"
    gl_entry.voucher_type = "Sales Invoice"
    gl_entry.voucher_no = sales_invoice_name
    gl_entry.cost_center = cost_center
    gl_entry.party = sales_invoice.customer

    # Link the GL Entry to the Sales Invoice
    gl_entry.reference_doctype = "Sales Invoice"
    gl_entry.reference_docname = sales_invoice.name

    # Save and submit the GL Entry
    gl_entry.insert()
    gl_entry.submit()

@frappe.whitelist()
def get_unshipped():
    filters = {
        "shipment_status": ""
    }
    sales_orders = get_list("Sales Order", filters=filters, fields=["name","amazon_order_id"])
    # Extract the "amazon_order_id" field from each Sales Order
    amazon_order_ids = [so.get("amazon_order_id") for so in sales_orders]
    name_so = [so.get("amazon_order_id") for so in sales_orders]
    print(amazon_order_ids)
    return amazon_order_ids,


@frappe.whitelist()
def amazon_shiped_status():
       sales_orders = get_unshipped()
       auth = get_auth()
    #    make_api_call(auth,sales_orders)
       for orders in sales_orders:
            data_set = make_api_call(auth,orders)
            

@frappe.whitelist()
def get_auth():
    frappe_url = "https://api.amazon.com/auth/o2/token"
    request_body = {
        "grant_type": "refresh_token",
        "refresh_token": "Atzr|IwEBICRgnPf3b15sgN-qixY5sitAFspiHbpfvi--3LARNR-Znhg6EiZ9lbG90AHTetDKtIRMbheDzV--mTS9M4HyKBHgMgh3gynSd2Kxjum6G5TPmmhSK17QVKCeiMWSDA5-UK7S_DS4J0oS2m0RD6XCbv68nvuZ_i-BKibUnOOkBGaNwDkM7geuUOqorSI0pdIWdUqNPcwD4qcGhxqIHZrJcNyOWilxUyixoudW6yNZBuva7LBjIRrEVPdalJMKPzTagZyxrr7cgE3M8_0f6En3aK-cojRgdiazN1GSfG788AQ-Drj09GvulVFz8t0bwra1o9zP5LbL6j6fKpKjrFJkDX0T",
        "client_id": "amzn1.application-oa2-client.cb5ee70c9a324cad9a068d2790b4d4e6",
        "client_secret": "amzn1.oa2-cs.v1.7ba9671350aa77d8e02da71df208f7a35fcc866108e79f8711b3b550235cdbc7"
    }
    response = requests.post(frappe_url, json=request_body)
    response.raise_for_status()
    data = response.json()
    access_token = data.get('access_token')
    return access_token


# @frappe.whitelist()
# def make_api_call(auth,amz_ord):
#     base_url = "https://sellingpartnerapi-eu.amazon.com/orders/v0/orders/"
#     order_id = "4406-6662232-9001959"
#     url = base_url+order_id
#     headers = {
#         "x-amz-access-token": auth,
#     }

#     try:
#         response = requests.get(url, headers=headers)
#         response.raise_for_status()  # Raise an HTTPError for bad responses
#         data = response.json()
#         order_status = data.get("payload", {}).get("OrderStatus")
#         if order_status and order_status == "Shipped":
#              Buyer = "Buyer - "+ order_id+"-Shipping"
#              shipping_address = data.get("payload", {}).get("ShippingAddress")
#              if shipping_address:
#                 print("Order Status:", order_status)
#                 print("Shipping Address:", shipping_address)
#                 customer_address = frappe.get_doc("Address", "Buyer - 406-6662232-9001959-Shipping")
#                 print(customer_address)
#                 customer_address.city = "testing City"
#                 customer_address.insert()
#                 sales_order_name = frappe.get_value('Sales Order', {'amazon_order_id': "406-6662232-9001959"}, 'name')
#                 print(sales_order_name)
#                 sales_order_name.shipment_status = order_status
#              else:
#                 print("Shipping address not available for this shipped order.")
#         else:
#             pass
#     except requests.exceptions.RequestException as e:
#         frappe.msgprint(_("Error making API call: {0}").format(e))

def make_api_call(auth, order_id):
    base_url = "https://sellingpartnerapi-eu.amazon.com/orders/v0/orders/"
    order_id = "408-3640642-8125114"
    url = base_url + order_id
    headers = {
        "x-amz-access-token": auth,
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses
        data = response.json()
        order_status = data.get("payload", {}).get("OrderStatus")
        if order_status and order_status == "Shipped":
            buyer = ""
            shipping_address = data.get("payload", {}).get("ShippingAddress")
            if shipping_address:
                print("Order Status:", order_status)
                print("Shipping Address:", shipping_address)
                
                # Create or update customer address
                # customer_address = frappe.get_doc("Address", buyer)
                # customer_address.city = "testing City"
                # customer_address.insert()

                # Update sales order shipment status
                sales_order_name = frappe.get_value('Sales Order', {'amazon_order_id': order_id}, 'name')
                if sales_order_name:
                    sales_order = frappe.get_doc('Sales Order', sales_order_name)
                    sales_order.shipment_status = order_status
                    sales_order.save()
                    print("Updated Sales Order:", sales_order_name)
                else:
                    print("Sales Order not found for Amazon order ID:", order_id)
            else:
                print("Shipping address not available for this shipped order.")
        else:
            print("Order not shipped or order status not available.")
    except requests.exceptions.RequestException as e:
        frappe.msgprint(_("Error making API call: {0}").format(e))