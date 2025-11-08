
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import cstr, validate_phone_number

from ecommerce_integrations.controllers.customer import EcommerceCustomer
from ecommerce_integrations.shopify.constants import (
	ADDRESS_ID_FIELD,
	CUSTOMER_ID_FIELD,
	MODULE_NAME,
	SETTING_DOCTYPE,
)

logger = frappe.logger('ShopifcustomerfromNJFeature', allow_site=True, file_count=1)
class ShopifyCustomer(EcommerceCustomer):
	def __init__(self, customer_id: str):
		self.setting = frappe.get_doc(SETTING_DOCTYPE)
		super().__init__(customer_id, CUSTOMER_ID_FIELD, MODULE_NAME)

	def sync_customer(self, customer: Dict[str, Any]) -> None:
		"""Create Customer in ERPNext using shopify's Customer dict."""

		customer_name = cstr(customer.get("first_name")) + " " + cstr(customer.get("last_name"))
		if len(customer_name.strip()) == 0:
			customer_name = customer.get("email")

		customer_group = self.setting.customer_group
		super().sync_customer(customer_name, customer_group)

		billing_address = customer.get("billing_address", {}) or customer.get("default_address")
		shipping_address = customer.get("shipping_address", {})

		if billing_address:
			self.create_customer_address(
				customer_name, billing_address, address_type="Billing", email=customer.get("email")
			)
		if shipping_address:
			self.create_customer_address(
				customer_name, shipping_address, address_type="Shipping", email=customer.get("email")
			)

		self.create_customer_contact(customer)

	def create_customer_address(
		self,
		customer_name,
		shopify_address: Dict[str, Any],
		address_type: str = "Billing",
		email: Optional[str] = None,
	) -> None:
		"""Create customer address(es) using Customer dict provided by shopify."""
		address_fields = _map_address_fields(shopify_address, customer_name, address_type, email)
		super().create_customer_address(address_fields)

	def update_existing_addresses(self, customer):
		billing_address = customer.get("billing_address", {}) or customer.get("default_address")
		shipping_address = customer.get("shipping_address", {})

		customer_name = cstr(customer.get("first_name")) + " " + cstr(customer.get("last_name"))
		email = customer.get("email")

		if billing_address:
			self._update_existing_address(customer_name, billing_address, "Billing", email)
		if shipping_address:
			self._update_existing_address(customer_name, shipping_address, "Shipping", email)

	def _update_existing_address(
		self,
		customer_name,
		shopify_address: Dict[str, Any],
		address_type: str = "Billing",
		email: Optional[str] = None,
	) -> None:
		"""Create new address only if it's different from existing addresses"""
		
		# Get all existing addresses of this type for the customer
		existing_addresses = self.get_all_customer_addresses(address_type)
		# logger.info(f"existing_addresses ===========90 {existing_addresses}")

		
		# Map new address fields
		new_address_fields = _map_address_fields(shopify_address, customer_name, address_type, email)
		# logger.info(f"new_address_fields ===========90 {new_address_fields}")
		
		# Check if this address already exists
		if self._address_already_exists(new_address_fields, existing_addresses):
			# Address already exists, no need to create new one
			return
		
		# Create new address (keeping original naming logic from _map_address_fields)
		super().create_customer_address(new_address_fields)

	def get_all_customer_addresses(self, address_type: str) -> list:
		"""Get all existing addresses of a specific type for this customer"""
		try:
			# Get customer document
			customer_doc = frappe.get_doc("Customer", self.customer_id)
			# logger.info(f"customer_doc ===========90 {customer_doc}")
			
			# Filter addresses by type
			addresses = []
			for link in customer_doc.get("customer_addresses", []):
				address_doc = frappe.get_doc("Address", link.address)
				
				if address_doc.address_type == address_type:
					addresses.append(address_doc)
			
			return addresses
		except:
			return []

	def _address_already_exists(self, new_address_fields: Dict, existing_addresses: list) -> bool:
		"""Check if an address with same details already exists"""
		for existing_address in existing_addresses:
			# Compare key address fields
			if (existing_address.address_line1 == new_address_fields.get("address_line1") and
				existing_address.address_line2 == new_address_fields.get("address_line2") and
				existing_address.city == new_address_fields.get("city") and
				existing_address.state == new_address_fields.get("state") and
				existing_address.pincode == new_address_fields.get("pincode") and
				existing_address.country == new_address_fields.get("country")):
				return True
		return False
		


	def create_customer_contact(self, shopify_customer: Dict[str, Any]) -> None:

		if not (shopify_customer.get("first_name") and shopify_customer.get("email")):
			return

		contact_fields = {
			"status": "Passive",
			"first_name": shopify_customer.get("first_name"),
			"last_name": shopify_customer.get("last_name"),
			"unsubscribed": not shopify_customer.get("accepts_marketing"),
		}

		if shopify_customer.get("email"):
			contact_fields["email_ids"] = [{"email_id": shopify_customer.get("email"), "is_primary": True}]

		phone_no = shopify_customer.get("phone") or shopify_customer.get("default_address", {}).get(
			"phone"
		)

		if validate_phone_number(phone_no, throw=False):
			contact_fields["phone_nos"] = [{"phone": phone_no, "is_primary_phone": True}]

		super().create_customer_contact(contact_fields)


def _map_address_fields(shopify_address, customer_name, address_type, email):
    """ returns dict with shopify address fields mapped to equivalent ERPNext fields """

    address1 = shopify_address.get("address1") or "Address 1"
    address2 = shopify_address.get("address2") or ""

    # If address1 is too long (>100 chars), split into address_line1 and address_line2
    if len(address1) > 90:
        words = address1.split()
        line1, line2 = "", []

        for word in words:
            # Build line1 until 100 chars
            if len((line1 + " " + word).strip()) <= 90:
                line1 = (line1 + " " + word).strip()
            else:
                line2.append(word)

        address1 = line1
        leftover = " ".join(line2)

        # Merge leftover with existing address2 (if any)
        if address2:
            address2 = f"{leftover}, {address2}"
        else:
            address2 = leftover

    # If still no address2, fallback with city + zip
    if not address2:
        address2 = ", ".join(filter(None, [
            shopify_address.get("zip"),
            shopify_address.get("city"),
        ]))

    address_fields = {
        "address_title":customer_name,
        "address_type": address_type,
        ADDRESS_ID_FIELD: shopify_address.get("id"),
        "address_line1": address1,
        "address_line2": address2.strip() if address2 else None,
        "city": shopify_address.get("city"),
        "state": shopify_address.get("province"),
        "pincode": shopify_address.get("zip"),
        "country": shopify_address.get("country"),
        "email_id": email,
        "gstin": shopify_address.get("company")
    }

    phone = shopify_address.get("phone")
    if validate_phone_number(phone, throw=False):
        address_fields["phone"] = phone

    return address_fields

# def _map_address_fields(shopify_address, customer_name, address_type, email):
# 	""" returns dict with shopify address fields mapped to equivalent ERPNext fields"""

# 	# Compose address_line2 dynamically if address2 is missing
# 	if shopify_address.get("address2"):
# 		address_line2 = shopify_address.get("address2")
# 	else:
# 		address_line2 = ", ".join(filter(None, [
# 			shopify_address.get("zip"),
# 			shopify_address.get("city"),
# 			shopify_address.get("province"),
# 			shopify_address.get("country")
# 		]))

# 	address_fields = {
# 		"address_title": customer_name,
# 		"address_type": address_type,
# 		ADDRESS_ID_FIELD: shopify_address.get("id"),
# 		"address_line1": shopify_address.get("address1") or "Address 1",
# 		"address_line2": address_line2,
# 		"city": shopify_address.get("city"),
# 		"state": shopify_address.get("province"),
# 		"pincode": shopify_address.get("zip"),
# 		"country": shopify_address.get("country"),
# 		"email_id": email,
# 		# "gstin": shopify_address.get("company")
# 	}

# 	phone = shopify_address.get("phone")
# 	if validate_phone_number(phone, throw=False):
# 		address_fields["phone"] = phone

# 	return address_fields

# def _map_address_fields(shopify_address, customer_name, address_type, email):
# 	""" returns dict with shopify address fields mapped to equivalent ERPNext fields"""
# 	address_fields = {
# 		"address_title": customer_name,  # Keep original naming logic
# 		"address_type": address_type,
# 		ADDRESS_ID_FIELD: shopify_address.get("id"),
# 		"address_line1": shopify_address.get("address1") or "Address 1",
# 		"address_line2": shopify_address.get("address2"),
# 		"city": shopify_address.get("city"),
# 		"state": shopify_address.get("province"),
# 		"pincode": shopify_address.get("zip"),
# 		"country": shopify_address.get("country"),
# 		"email_id": email,
# 		"gstin":shopify_address.get("company")
# 	}
# 	# logger.info(f"existing_addresses ===========90 {address_fields}")
# 	# logger.debug(f"existing_addresses ===========90 {address_fields}")

# 	phone = shopify_address.get("phone")
# 	if validate_phone_number(phone, throw=False):
# 		address_fields["phone"] = phone

# 	return address_fields
