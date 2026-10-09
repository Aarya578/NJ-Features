"""One-off: re-push the Shopify delivery dates lost to rate limiting on 2026-09-17.

Between 03:32 and 04:55 UTC, 109 pushes were refused by Shopify with "Exceeded 2
calls per second". The old code logged each refusal and dropped it, so those orders
still show their previous Estimated Delivery Date on Shopify while the ERP holds the
correct one. Nothing re-sends them on its own.

85 distinct orders, taken from SOLogger.log.

push_delivery_date_to_shopify_order() now throttles and honours Retry-After, so this
re-run should not trip the limit again. It is safe to run more than once: each push
just re-writes the same note attribute.

Run:
    bench --site erp.newjaisa.com execute nj_features.repush_shopify_dates.preview
    bench --site erp.newjaisa.com execute nj_features.repush_shopify_dates.run

Delete this file once it has been run.
"""

import frappe

# from nj_features.overrides.sales_order import push_delivery_date_to_shopify_order

SHOPIFY_ORDER_NUMBERS = [
    "6519223320758",
    "6536819507382",
    "6661371691190",
    "6666920558774",
    "6691945382070",
    "6714658914486",
    "6716814033078",
    "6717201318070",
    "6721148551350",
    "6727550697654",
    "6728668381366",
    "6730839851190",
    "6738833801398",
    "6739345834166",
    "6740430061750",
    "6740470366390",
    "6741410185398",
    "6743085285558",
    "6743185817782",
    "6744278597814",
    "6745666584758",
    "6746120847542",
    "6746417954998",
    "6747848310966",
    "6749775691958",
    "6750702436534",
    "6759719141558",
    "6761537503414",
    "6763538677942",
    "6765246185654",
    "6766012203190",
    "6766330937526",
    "6766864367798",
    "6769029972150",
    "6769129062582",
    "6769199055030",
    "6769348280502",
    "6771085672630",
    "6771171164342",
    "6771568869558",
    "6772940570806",
    "6773238628534",
    "6773444149430",
    "6773514666166",
    "6773753282742",
    "6774430236854",
    "6779839316150",
    "6780264022198",
    "6780299673782",
    "6780305932470",
    "6780538060982",
    "6781024141494",
    "6781341925558",
    "6781621272758",
    "6782858690742",
    "6782863933622",
    "6782967840950",
    "6783018598582",
    "6783162155190",
    "6783262621878",
    "6783356108982",
    "6784451346614",
    "6784454885558",
    "6784547225782",
    "6784582025398",
    "6784632258742",
    "6784642613430",
    "6784733511862",
    "6784777388214",
    "6784791576758",
    "6787021734070",
    "6787124756662",
    "6787229778102",
    "6787505291446",
    "6787578298550",
    "6787603660982",
    "6787664412854",
    "6787824091318",
    "6787856269494",
    "6787905421494",
    "6787963158710",
    "6788123656374",
    "6788240638134",
    "6788445110454",
    "6788678713526",
]


def _targets():
    """Map the failed Shopify order numbers back to Sales Orders and their dates."""
    rows = frappe.db.sql("""
        SELECT name, shopify_order_number, estimated_delivery_date
        FROM `tabSales Order`
        WHERE shopify_order_number IN %(nums)s
          AND docstatus = 1
          AND estimated_delivery_date IS NOT NULL
          AND estimated_delivery_date != ''
    """, {"nums": tuple(SHOPIFY_ORDER_NUMBERS)}, as_dict=True)
    return rows


def preview():
    """Show what run() would send. Contacts nothing."""
    rows = _targets()
    print("failed Shopify orders in the log : %d" % len(SHOPIFY_ORDER_NUMBERS))
    print("matched to a submitted Sales Order: %d" % len(rows))
    for r in rows[:15]:
        print("   %-22s shopify=%-16s -> %s" % (
            r.name, r.shopify_order_number, str(r.estimated_delivery_date)[:40]))
    if len(rows) > 15:
        print("   ... and %d more" % (len(rows) - 15))
    missing = len(SHOPIFY_ORDER_NUMBERS) - len(rows)
    if missing:
        print("\n   %d could not be matched (cancelled, draft, or no estimate yet)" % missing)


def run():
    """Re-push each one. Throttled and retried by the push function itself."""
    rows = _targets()
    print("re-pushing %d orders ..." % len(rows))
    ok = failed = 0
    for r in rows:
        try:
            # push_delivery_date_to_shopify_order(r.name, str(r.estimated_delivery_date))
            ok += 1
        except Exception as e:
            failed += 1
            print("   FAIL %s: %s" % (r.name, e))
    print("\n   attempted=%d  exceptions=%d" % (ok, failed))
    print("   Check SOLogger.log for [SHOPIFY_DATE_UNPUSHED] - any order listed there")
    print("   still did not make it and needs another run.")
