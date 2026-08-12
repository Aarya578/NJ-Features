# Copyright (c) 2026, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe


def validate_rfq_qty(doc, method=None):
    """
    Serial No "validate" hook (see hooks.py's doc_events -- one new
    entry added there, nothing else touched).

    Blocks a Serial No from being saved if it would push the count of
    Serial Nos against its (rfq_id, item_code) combination past that
    RFQ Item line's qty.

    Runs for EVERY Serial No save, including the one inside
    create_serial_no_based_on_rfq (njqca.py) -- right before that
    document actually commits. This is the point closest to the real
    write, unlike the app-side qty checks (Flutter's RfqItemSelectScreen,
    NJQCA.exe's own fallback lookup), which happen once at RFQ
    selection time and can go stale over the length of a full test
    session (confirmed from real session logs: 4+ minutes between
    item_code resolution and the actual Serial No write, with no
    re-check in between) -- including the case of two technicians
    both starting sessions against the same RFQ line before either
    one's Serial No has actually been created yet.

    Not perfectly race-proof against two saves committing in the same
    instant (that would need SELECT ... FOR UPDATE row locking or a
    DB-level unique constraint on top of this), but it closes the
    multi-minute app-side gap down to a single-transaction window,
    which is the realistic risk here rather than millisecond-exact
    simultaneous submits.
    """
    if not doc.rfq_id or not doc.item_code:
        return

    qty = frappe.db.get_value(
        "Request for Quotation Item",
        {"parent": doc.rfq_id, "item_code": doc.item_code},
        "qty",
    )
    if qty is None:
        # item_code isn't actually a line on this RFQ -- not this
        # hook's job to validate that mismatch, leave it alone.
        return

    existing_count = frappe.db.count(
        "Serial No",
        filters={
            "rfq_id": doc.rfq_id,
            "item_code": doc.item_code,
            "name": ["!=", doc.name or ""],
        },
    )

    if existing_count >= qty:
        frappe.throw(
            f"RFQ <b>{doc.rfq_id}</b> quota for item <b>{doc.item_code}</b> "
            f"is already fully used ({existing_count} of {qty}). "
            f"Cannot create another Serial No against it."
        )
