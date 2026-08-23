from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from nj_features.nj_features.doctype.rfq_customer_quotation_access.rfq_customer_quotation_access import (
    ensure_customer_quotation_links,
)


class TestRFQCustomerQuotationAccess(FrappeTestCase):
    @patch(
        "nj_features.nj_features.doctype.rfq_customer_quotation_access."
        "rfq_customer_quotation_access._get_reusable_access",
        return_value=None,
    )
    @patch(
        "nj_features.nj_features.doctype.rfq_customer_quotation_access."
        "rfq_customer_quotation_access._create_customer_quotation_access"
    )
    @patch.object(frappe.db, "set_value")
    def test_generates_a_separate_link_for_each_emailed_supplier(
        self,
        set_value,
        create_access,
        _get_reusable_access,
    ):
        create_access.side_effect = [
            {
                "access_name": "ACCESS-A",
                "quotation_url": "https://example.test/customer_quotation?token=token-a",
                "expires_on": "2026-08-13 12:00:00",
            },
            {
                "access_name": "ACCESS-B",
                "quotation_url": "https://example.test/customer_quotation?token=token-b",
                "expires_on": "2026-08-13 12:00:00",
            },
        ]
        source_doc = frappe._dict(
            name="TEST-RFQ",
            suppliers=[
                frappe._dict(
                    name="ROW-A",
                    idx=1,
                    supplier="Supplier A",
                    email_id="a@example.test",
                    send_email=1,
                    customer_quotation_link=None,
                    customer_quotation_access=None,
                    link_expires_on=None,
                ),
                frappe._dict(
                    name="ROW-B",
                    idx=2,
                    supplier="Supplier B",
                    email_id="b@example.test",
                    send_email=1,
                    customer_quotation_link=None,
                    customer_quotation_access=None,
                    link_expires_on=None,
                ),
                frappe._dict(
                    name="ROW-C",
                    idx=3,
                    supplier="Supplier C",
                    email_id="c@example.test",
                    send_email=0,
                    customer_quotation_link=None,
                    customer_quotation_access=None,
                    link_expires_on=None,
                ),
            ],
        )

        links = ensure_customer_quotation_links(source_doc, valid_days=7, one_time_use=1)

        self.assertEqual([link["access_name"] for link in links], ["ACCESS-A", "ACCESS-B"])
        self.assertEqual(create_access.call_count, 2)
        self.assertEqual(set_value.call_count, 3)
        create_access.assert_any_call("TEST-RFQ", "Supplier A", 7, 1)
        create_access.assert_any_call("TEST-RFQ", "Supplier B", 7, 1)
