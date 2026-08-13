# Copyright (c) 2026, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe


def validate_rfq_qty(doc, method=None):
    """
    Serial No "validate" hook (see hooks.py's doc_events). Function
    name kept as-is even though the check below is no longer
    qty-based -- renaming it would need another manual hooks.py edit
    on the server, and this is simpler to deploy as a drop-in
    replacement of the same file.

    RULE (changed from qty-count to BIOS-uniqueness): a given physical
    machine (bios_serial_no) should only ever have ONE Serial No
    against a given RFQ, no matter how many times it gets tested.
    Testing itself is never blocked by this -- retests, re-runs after
    a failed QI, etc. are all expected. Only a SECOND serial for the
    same (bios_serial_no, rfq_id) pair is blocked.

    In the normal flow this should rarely actually fire: NJQCA.py's
    _ensure_rfq_serial_no already checks for an existing serial by
    (bios_serialno, rfq_id) and REUSES it rather than attempting to
    create a duplicate in the first place. This hook exists as a
    backstop for any other path that creates a Serial No directly
    (manual Desk creation, a future script, anything that doesn't go
    through _ensure_rfq_serial_no's reuse check) -- the actual
    guarantee lives here, at the point closest to the real database
    write, same reasoning as the qty version this replaced.

    Not perfectly race-proof against two saves committing in the same
    instant (that would need SELECT ... FOR UPDATE row locking or a
    DB-level unique constraint on top of this), but that's an
    extremely narrow window for what is fundamentally a one-machine,
    one-serial rule rather than a shared numeric pool multiple
    sessions could plausibly race over at once.
    """
    if not doc.rfq_id or not doc.bios_serial_no:
        return

    existing = frappe.db.get_value(
        "Serial No",
        {
            "rfq_id": doc.rfq_id,
            "bios_serial_no": doc.bios_serial_no,
            "name": ["!=", doc.name or ""],
        },
        "name",
    )

    if existing:
        frappe.throw(
            f"BIOS <b>{doc.bios_serial_no}</b> already has Serial No "
            f"<b>{existing}</b> against RFQ <b>{doc.rfq_id}</b>. "
            f"Testing this machine again is fine -- a second Serial No "
            f"for the same machine against the same RFQ is not."
        )
