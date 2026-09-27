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


def ensure_department_history_unique_constraint():
    """
    after_migrate hook. Adds a UNIQUE INDEX on (parent, departmant) to
    `tabDepartment History` -- the actual fix for the "Department Count
    History already has a row for X -- duplicate rows not allowed" bug.

    Before this, the only thing stopping a duplicate row was
    prevent_manual_department_history_edits, an application-level check
    that only inspects one document's own in-memory list at save time --
    it can't stop two independent writers (seed_department_count_history,
    _bump_department_count, nj_p1_features.overrides.serial_no.
    updating_department_history_table) from each separately concluding
    "no row exists yet" and both trying to create one. This index makes
    that scenario impossible at the database level, and pairs with all
    three writers now using an atomic INSERT ... ON DUPLICATE KEY UPDATE
    (see _atomic_department_history_write below) instead of the old
    check-then-append-then-save pattern, so there's no race window left
    for the index to even need to catch.

    frappe.db.add_unique no-ops if the index already exists, so this is
    safe to run on every migrate.

    Rows written BEFORE the atomic writers landed can still violate the
    constraint, and add_unique does not clean up after itself - it just raises
    IntegrityError and aborts the whole migrate. So dedupe first. Observed on
    production 2026-09-22: 3 duplicate pairs, each two rows with count=1 written
    seconds apart by the same user - one event, double-written, exactly the race
    described above.

    Merge rule is MAX, not SUM: these pairs are one event recorded twice, so
    summing would inflate the department pass count. A genuine second pass would
    have been an increment on the existing row, not a new row.
    """
    duplicates = frappe.db.sql("""
        SELECT parent, departmant, COUNT(*) AS n
        FROM `tabDepartment History`
        GROUP BY parent, departmant
        HAVING COUNT(*) > 1
    """, as_dict=True)

    if duplicates:
        # Keep the earliest row of each group, fold the others into it, delete
        # the rest. Done in SQL per group rather than through the ORM: these are
        # child rows of Serial No and re-saving the parent would re-trigger the
        # very writers that created the duplicates.
        for d in duplicates:
            rows = frappe.db.sql("""
                SELECT name,
                       COALESCE(`count`, 0) AS cnt,
                       COALESCE(`restrict`, 0) AS restrict_flag,
                       COALESCE(limit_count, 0) AS limit_count
                FROM `tabDepartment History`
                WHERE parent = %s AND departmant = %s
                ORDER BY creation, name
            """, (d["parent"], d["departmant"]), as_dict=True)

            keeper = rows[0]
            losers = [r["name"] for r in rows[1:]]

            frappe.db.sql("""
                UPDATE `tabDepartment History`
                SET `count` = %s, `restrict` = %s, limit_count = %s
                WHERE name = %s
            """, (
                max(r["cnt"] for r in rows),
                max(r["restrict_flag"] for r in rows),
                max(r["limit_count"] for r in rows),
                keeper["name"],
            ))

            frappe.db.sql(
                "DELETE FROM `tabDepartment History` WHERE name IN ({})".format(
                    ", ".join(["%s"] * len(losers))
                ),
                tuple(losers),
            )

        frappe.db.commit()
        frappe.log_error(
            "Removed {} duplicate Department History row(s) across {} "
            "(parent, departmant) group(s) before applying the unique "
            "index".format(
                sum(d["n"] - 1 for d in duplicates), len(duplicates)
            ),
            "ensure_department_history_unique_constraint",
        )

    frappe.db.add_unique("Department History", ["parent", "departmant"])


def _atomic_department_history_write(serial_no, department, increment):
    """
    Atomically ensure `serial_no` has exactly one Department History row
    for `department`. Used by seed_department_count_history (increment=
    False: create with count=1 if missing, never touch an existing row)
    and by _bump_department_count / nj_p1_features.overrides.serial_no.
    updating_department_history_table (increment=True: create with
    count=1 if missing, else count += 1).

    A single INSERT ... ON DUPLICATE KEY UPDATE (or INSERT IGNORE for the
    no-touch case) rather than the old "load the doc, check department_
    history in Python, append if missing, save" pattern -- that pattern
    has a genuine TOCTOU race: two callers can both load a doc that has
    no row yet, both append one, both save, and the second save's
    incoming payload just legitimately has one new row same as the
    first's, so nothing catches it. This is why the DB-level unique
    index (see ensure_department_history_unique_constraint) matters as
    much as this atomic write does -- together they make a duplicate
    structurally impossible rather than just usually-avoided.

    Deliberately writes via raw SQL instead of doc.append() + doc.save()
    on the parent Serial No -- appending to doc.department_history and
    saving would work for a hook that runs after the Serial No's own
    save has fully completed (on_update), but seed_department_count_
    history used to run on validate, and Frappe's own child-table sync
    (which runs later in that same save, comparing the DB against
    whatever's in the in-memory list) would have deleted a row this
    function inserted mid-validate right back out again, since it
    wouldn't be part of that in-memory list. Writing directly and never
    touching doc.department_history sidesteps that entirely, which is
    also why seed_department_count_history is now an on_update hook
    instead of validate -- see hooks.py.
    """
    if not serial_no or not department:
        return
    if not frappe.db.exists("Serial No", serial_no):
        return

    next_idx = frappe.db.count("Department History", {"parent": serial_no}) + 1
    values = {
        "name": frappe.generate_hash(length=10),
        "parent": serial_no,
        "dept": department,
        "idx": next_idx,
        "user": frappe.session.user or "Administrator",
    }

    if increment:
        frappe.db.sql(
            """
            INSERT INTO `tabDepartment History`
                (name, parent, parenttype, parentfield, departmant, count, idx,
                 creation, modified, owner, modified_by)
            VALUES
                (%(name)s, %(parent)s, 'Serial No', 'department_history', %(dept)s, 1, %(idx)s,
                 NOW(), NOW(), %(user)s, %(user)s)
            ON DUPLICATE KEY UPDATE count = count + 1, modified = NOW(), modified_by = %(user)s
            """,
            values,
        )
    else:
        frappe.db.sql(
            """
            INSERT IGNORE INTO `tabDepartment History`
                (name, parent, parenttype, parentfield, departmant, count, idx,
                 creation, modified, owner, modified_by)
            VALUES
                (%(name)s, %(parent)s, 'Serial No', 'department_history', %(dept)s, 1, %(idx)s,
                 NOW(), NOW(), %(user)s, %(user)s)
            """,
            values,
        )


def seed_department_count_history(doc, method=None):
    """
    Serial No "on_update" hook (moved from "validate" -- see
    _atomic_department_history_write's docstring for why). Seeds the
    first Department Count History row the moment this Serial No first
    has a resolvable department -- i.e. as soon as its `warehouse`
    points at a Warehouse with a Department set.

    Deliberately does NOT read the `department` field on Serial No:
    that field is only meaningfully in sync because of CustomSerialNo.
    db_update()'s direct write in nj_p1_features, a raw frappe.db.
    set_value() that bypasses the normal Document/hook lifecycle
    entirely -- relying on it here as well as in nj_p1_features.
    overrides.serial_no.updating_department_history_table (which reads
    that same field) meant two independent writers were resolving
    "current department" two different ways, one of them fed by a
    write that isn't part of the same transaction/validation path as
    everything else. Warehouse -> Department via a live lookup is the
    one canonical signal every writer should use instead.

    Never touches an existing row for the current department -- every
    later department change is counted by nj_features.overrides.
    stock_entry.update_department_count_history on the Stock Entry that
    actually moves the serial.

    Restrict/Limit Count no longer live on this row -- they are
    department-wide settings on the Department doctype itself (see
    nj_features.overrides.stock_entry.get_department_restriction_violation).
    """
    if not doc.warehouse:
        return

    department = frappe.db.get_value("Warehouse", doc.warehouse, "department")
    if not department:
        return

    _atomic_department_history_write(doc.name, department, increment=False)


def prevent_manual_department_history_edits(doc, method=None):
    """
    Serial No "validate" hook. Department Count History (department_
    history) is entirely server-managed -- seeded on creation, bumped on
    real stock movement. A normal user-initiated save may only:

      - add a brand-new row (a Department not already tracked) with
        Count left at 0, to pre-track a department the serial hasn't
        actually visited yet.

    It may never delete a row, rename an existing row's Department, add
    two rows for the same Department, or set/change a Count by hand.

    All of our OWN code that legitimately writes this table --
    seed_department_count_history, _bump_department_count, and
    nj_p1_features.overrides.serial_no.updating_department_history_table
    -- writes via _atomic_department_history_write (raw SQL), never
    through doc.append() + doc.save(), so none of it ever reaches this
    check at all. Any Count/duplicate-row issue this catches is
    therefore necessarily a manual edit via the Desk form, not a race
    between our own writers (that race is now prevented at the DB level
    -- see ensure_department_history_unique_constraint).
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

