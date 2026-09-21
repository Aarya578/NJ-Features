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


def seed_department_count_history(doc, method=None):
    """
    Serial No "validate" hook. Seeds the first Department Count History
    row (child table field department_history) the moment this Serial
    No first has a resolvable department -- i.e. as soon as its
    `warehouse` points at a Warehouse with a Department set.

    Deliberately does NOT read the `department` field on Serial No:
    that field is only ever set once, at creation time (from the QC
    operator's own department at that moment), and is never updated
    again by any later stock movement -- confirmed against real UAT
    data, where a serial's `department` still read its original value
    days after the serial had physically moved through two more
    departments. Warehouse -> Department is the only reliable "current
    department" signal.

    Checks for an existing row matching the CURRENT department by name,
    rather than whether the table is empty -- a user can pre-add a row
    for a department the serial hasn't visited yet (see
    prevent_manual_department_history_edits), which would otherwise make
    an already-non-empty table look "already seeded" and skip seeding
    the serial's actual starting department entirely. Once a row for the
    current department exists, this never touches it again -- every
    later department change is counted by
    nj_features.overrides.stock_entry.update_department_count_history
    on the Stock Entry that actually moves the serial.

    Restrict/Limit Count no longer live on this row -- they are
    department-wide settings on the Department doctype itself (see
    nj_features.overrides.stock_entry.get_department_restriction_violation).

    A pre-existing serial with real history predating this feature only
    ever gets a single row seeded here, for whatever department it
    currently happens to be in -- there is no reconstruction of the
    departments it passed through earlier (no backfill job exists for
    that). Count tracking is accurate from this point forward only.
    """
    if not doc.warehouse:
        return

    department = frappe.db.get_value("Warehouse", doc.warehouse, "department")
    if not department:
        return

    existing = next(
        (
            row for row in (doc.get("department_history") or [])
            if (row.departmant or "").strip() == department
        ),
        None,
    )
    if existing:
        return

    row = doc.append("department_history", {})
    row.departmant = department
    row.count = 1


def prevent_manual_department_history_edits(doc, method=None):
    """
    Serial No "validate" hook. Department Count History (department_
    history) is entirely server-managed -- seeded on creation, bumped on
    real stock movement. A normal user-initiated save may only:

      - add a brand-new row (a Department not already tracked) with
        Count left at 0, to pre-track a department the serial hasn't
        actually visited yet.

    It may never delete a row, rename an existing row's Department, add
    two rows for the same Department, or set/change a Count by hand --
    Count is only ever written by seed_department_count_history,
    _bump_department_count, or the backfill batch, all of which bypass
    this check entirely (see below), so any Count difference reaching
    here is necessarily a manual edit.

    MUST run before seed_department_count_history in hooks.py's Serial
    No validate list: this compares the doc as the client submitted it
    against what was in the DB before this save, so it needs to run
    before any of our OWN hooks mutate department_history in this same
    validate cycle -- otherwise seed_department_count_history's own
    legitimate row seed (for a department not yet tracked) would look
    identical to a user having manually added a row, and get wrongly
    blocked.

    Our OTHER code that legitimately rewrites this table --
    _bump_department_count and run_department_count_history_backfill_
    batch in nj_features.overrides.stock_entry -- never reaches this
    check at all: the former sets flags.ignore_validate before saving,
    and the latter writes via raw SQL, bypassing Document validation
    entirely.
    """
    if doc.is_new():
        return

    before = doc.get_doc_before_save()
    if not before:
        return

    old_by_dept = {
        (row.departmant or "").strip(): row
        for row in (before.get("department_history") or [])
    }

    seen_depts = set()
    matched_old_depts = set()

    for row in doc.get("department_history") or []:
        dept = (row.departmant or "").strip()
        if not dept:
            frappe.throw("Every Department Count History row must have a Department set.")

        if dept in seen_depts:
            frappe.throw(
                f"Department Count History already has a row for <b>{dept}</b> -- "
                f"duplicate rows for the same Department are not allowed."
            )
        seen_depts.add(dept)

        old_row = old_by_dept.get(dept)
        if old_row:
            matched_old_depts.add(dept)
            if (row.count or 0) != (old_row.count or 0):
                frappe.throw(
                    "Count cannot be added, removed, or edited manually on "
                    "Department Count History. This table is maintained "
                    "automatically as the serial moves between departments."
                )
        elif (row.count or 0) != 0:
            frappe.throw(
                f"A new Department Count History row for <b>{dept}</b> must "
                f"start with Count = 0 -- Count is maintained automatically as "
                f"the serial moves between departments."
            )

    if set(old_by_dept.keys()) - matched_old_depts:
        frappe.throw(
            "Department Count History rows cannot be deleted, and an existing "
            "row's Department cannot be changed -- a new row can only be "
            "added for a Department not yet tracked."
        )


@frappe.whitelist()
def format_component_audit_entry(serial_no, item_group, component, field_changed, old_value, new_value, reason):
    """
    Format and return a single UI audit log entry for Serial No Component changes.
    Uses Frappe session user and server formatted date/time.
    """
    from frappe.utils import now_datetime, formatdate, format_time

    now = now_datetime()
    formatted_date = formatdate(now, "dd-MM-yyyy")
    formatted_time = format_time(now, "HH:mm:ss")
    user = frappe.session.user

    entry = (
        "--------------------------------------------------\n"
        f"Date: {formatted_date}\n"
        f"Time: {formatted_time}\n"
        f"User: {user}\n"
        f"Serial No: {serial_no or ''}\n"
        f"Item Group: {item_group or ''}\n"
        f"Component: {component or ''}\n"
        f"Field: {field_changed or ''}\n"
        f"Old Value: {old_value or ''}\n"
        f"New Value: {new_value or ''}\n"
        f"Reason: {(reason or '').strip()}\n"
        "--------------------------------------------------"
    )
    return entry

