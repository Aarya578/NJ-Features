# Copyright (c) 2026, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now, generate_hash


def _iter_department_crossings(doc):
    """
    Shared by block_restricted_department_moves (before_submit) and
    update_department_count_history (on_submit) -- walks a Material
    Transfer Stock Entry's items and yields each distinct (serial_no,
    t_department) pair that represents a genuine cross-department move
    (s_warehouse != t_warehouse, and their departments differ). Same
    department reshuffles and rows missing a serial/warehouse are
    skipped. Deduped per call so the same pair is never yielded twice
    for one submission.
    """
    if (doc.get("stock_entry_type") or doc.get("purpose")) != "Material Transfer":
        return

    dept_cache = {}

    def department_of(warehouse):
        if warehouse not in dept_cache:
            dept_cache[warehouse] = frappe.db.get_value("Warehouse", warehouse, "department")
        return dept_cache[warehouse]

    seen = set()

    for row in doc.get("items", []):
        s_warehouse = row.get("s_warehouse")
        t_warehouse = row.get("t_warehouse")
        if not s_warehouse or not t_warehouse or not row.get("serial_no"):
            continue

        s_department = department_of(s_warehouse)
        t_department = department_of(t_warehouse)
        if not t_department or s_department == t_department:
            continue

        for serial_no in row.get("serial_no").split("\n"):
            serial_no = serial_no.strip()
            if not serial_no:
                continue

            key = (serial_no, t_department)
            if key in seen:
                continue
            seen.add(key)

            yield serial_no, t_department


def get_department_restriction_violation(serial_no, department):
    """
    Returns an error message string if moving `serial_no` into `department`
    would violate that row's Restrict/Limit Count, else None.

    Reads the serial's EXISTING department_history row for `department` --
    first-time entry into a department is never blocked, since no row (and
    therefore no limit) can exist yet for a department this serial hasn't
    been counted into before. Restrict/Limit Count are per (serial,
    department) overrides, not a department-wide setting -- someone has to
    have deliberately flagged that specific row after an earlier visit.

    Threshold: count is allowed to REACH limit_count; the move that would
    push it past that (count already >= limit_count) is what gets blocked.
    """
    row = frappe.db.get_value(
        "Department History",
        {
            "parent": serial_no,
            "parenttype": "Serial No",
            "parentfield": "department_history",
            "departmant": department,
        },
        ["restrict", "limit_count", "count"],
        as_dict=True,
    )

    if not row or not row.restrict or not row.limit_count:
        return None

    if (row.count or 0) >= row.limit_count:
        return (
            f"Serial No <b>{serial_no}</b> has reached its movement limit "
            f"(<b>{row.limit_count}</b>) for department <b>{department}</b> "
            f"and is restricted from moving there again."
        )

    return None


def block_restricted_department_moves(doc, method=None):
    """
    Stock Entry "before_submit" hook. Blocks the submission outright (via
    frappe.throw, surfaced to the user as a popup) if any transferred
    serial would cross into a department it's Restricted from and has
    already reached its Limit Count for -- see
    get_department_restriction_violation().

    Stock Movement / NJ Audit / Auto Stock Entry / MPC / NJQCA already get
    this same check earlier, during validate_serial_no_and_department()
    in nj_features.nj_features.doctype.stock_movement.stock_movement --
    that call happens BEFORE those flows even create their underlying
    Stock Entry, via nj_lib.utils.stock_entry.stock_entry_using_nj_lib().
    This hook exists to also catch a Stock Entry created and submitted
    directly (not through that helper), which is the one path that skips
    validate_serial_no_and_department entirely (see nj_lib's
    validate_direct_stock_entry_on_submit docstring). Running here too
    for the nj_lib-routed flows is harmless -- the state they already
    passed can't have changed in the few moments since.
    """
    error_messages = []

    for serial_no, t_department in _iter_department_crossings(doc):
        violation = get_department_restriction_violation(serial_no, t_department)
        if violation:
            error_messages.append(violation)

    if error_messages:
        frappe.throw("<br>".join(error_messages))


def update_department_count_history(doc, method=None):
    """
    Stock Entry "on_submit" hook. Bumps each transferred serial's
    Department Count History (Serial No.department_history) the moment
    a real stock transfer crosses from one Department's warehouse into
    another's.

    Hooked on Stock Entry rather than Stock Movement / NJ Audit / a
    direct manual transfer individually: every one of those flows ends
    up submitting a real Stock Entry document, so this is the one point
    every department-crossing move in the system actually converges on.
    Instrumenting each of those call sites separately would double-count
    -- Stock Movement's own time_stamp_update() and nj_lib's
    validate_direct_stock_entry_on_submit() both already run against the
    SAME underlying Stock Entry submission for a Stock-Movement-driven
    transfer.

    Deliberately does not read/write Serial No.department -- see
    nj_features.overrides.serial_no.seed_department_count_history for
    why that field can't be trusted as a "current department" signal.
    Department is resolved fresh from the warehouse on each row instead.
    """
    for serial_no, t_department in _iter_department_crossings(doc):
        _bump_department_count(serial_no, t_department)


def _bump_department_count(serial_no, department):
    if not frappe.db.exists("Serial No", serial_no):
        return

    serial_doc = frappe.get_doc("Serial No", serial_no)

    existing_row = next(
        (row for row in serial_doc.department_history if (row.departmant or "").strip() == department),
        None,
    )

    if existing_row:
        existing_row.count = (existing_row.count or 0) + 1
        serial_doc.department_history.remove(existing_row)
        serial_doc.department_history.insert(0, existing_row)
    else:
        new_row = serial_doc.append("department_history", {})
        new_row.departmant = department
        new_row.count = 1
        serial_doc.department_history.remove(new_row)
        serial_doc.department_history.insert(0, new_row)

    for idx, row in enumerate(serial_doc.department_history, start=1):
        row.idx = idx

    serial_doc.flags.ignore_validate = True
    serial_doc.flags.ignore_on_update = True
    serial_doc.save(ignore_permissions=True, ignore_version=True)


def run_department_count_history_backfill_batch(batch_size=1500):
    """
    Scheduled "hourly" job. Reconstructs Department Count History for a
    bounded batch of in-stock serials that predate this feature, then
    marks each one department_history_backfilled so the next hourly run
    picks up where this one left off -- self-completing over many short
    runs instead of one long operation. Safe to run anytime, including
    business hours: touches at most `batch_size` serials per run, each
    write scoped to exactly (parent=<that serial>, parenttype='Serial
    No', parentfield='department_history') -- never any other doctype,
    field, or serial's rows. Once the queue (in-stock AND not yet
    flagged) is empty, each run is a fast no-op.

    A brand-new serial never enters this queue -- seed_department_count_
    history (Serial No.validate, in nj_features.overrides.serial_no)
    flags it done immediately on creation, since it has no real history
    predating this feature to reconstruct in the first place. This job
    exists only for serials that were already moving through the
    warehouse before this feature shipped.

    Reconstruction logic matches update_department_count_history exactly
    (see its docstring for why department is always resolved fresh from
    the warehouse, never from the stale Serial No.department field):
    replays the serial's real Stock Ledger Entry history, using each
    transfer's positive-qty (entering) leg joined against Warehouse.
    department, collapsing consecutive entries into the same department
    into one stay so only genuine crossings count as a "pass through".

    Any Restrict / Limit Count already set manually on an existing row
    is preserved across the rebuild by department name -- this only
    replaces the reconstructed shape (departmant, count, ordering),
    never a row's restriction configuration.

    Skips (defers to a later run, does NOT mark done) any serial with a
    Stock Ledger Entry in the last RECENT_ACTIVITY_BUFFER_MINUTES -- a
    real live transfer for that exact serial could be committing its
    ledger entry in between this job's read and its write, and since
    this job marks a serial done as soon as it processes it, a
    collision here would never get a chance to self-correct. There's no
    urgency to this job, so deferring a serial that's mid-movement by
    one more hourly cycle costs nothing and closes that window.
    """
    RECENT_ACTIVITY_BUFFER_MINUTES = 10

    # Plain SQL rather than frappe.get_all(filters=...) -- the "is"/"set"
    # filter operator was found to silently match ZERO rows against a
    # real, non-empty warehouse column on one site's Frappe version (while
    # correctly matching on another), with no error raised either way.
    # Explicit IS NOT NULL / != '' has no such version-dependent ambiguity.
    serial_names = frappe.db.sql_list(
        """
        SELECT sn.name
        FROM `tabSerial No` sn
        WHERE sn.warehouse IS NOT NULL AND sn.warehouse != ''
          AND sn.department_history_backfilled = 0
          AND sn.name NOT IN (
              SELECT DISTINCT serial_no FROM `tabStock Ledger Entry`
              WHERE serial_no IS NOT NULL AND serial_no != ''
                AND creation > DATE_SUB(NOW(), INTERVAL %s MINUTE)
          )
        LIMIT %s
        """,
        (RECENT_ACTIVITY_BUFFER_MINUTES, batch_size),
    )

    if not serial_names:
        return

    current_time = now()
    processed = 0

    for serial_no in serial_names:
        ledger_rows = frappe.db.sql(
            """
            SELECT w.department
            FROM `tabStock Ledger Entry` sle
            LEFT JOIN `tabWarehouse` w ON w.name = sle.warehouse
            WHERE sle.serial_no = %s AND sle.is_cancelled = 0 AND sle.actual_qty > 0
            ORDER BY sle.posting_date, sle.posting_time, sle.creation
            """,
            serial_no,
        )

        sequence = []
        for (department,) in ledger_rows:
            department = (department or "").strip()
            if department and (not sequence or sequence[-1] != department):
                sequence.append(department)

        if sequence:
            preserved = {
                r.departmant: (r.restrict, r.limit_count)
                for r in frappe.db.sql(
                    """
                    SELECT departmant, `restrict`, limit_count FROM `tabDepartment History`
                    WHERE parent = %s AND parenttype = 'Serial No' AND parentfield = 'department_history'
                      AND (`restrict` = 1 OR limit_count > 0)
                    """,
                    serial_no,
                    as_dict=True,
                )
            }

            history = []
            for department in sequence:
                existing = next((h for h in history if h["departmant"] == department), None)
                if existing:
                    existing["count"] += 1
                    history.remove(existing)
                    history.insert(0, existing)
                else:
                    history.insert(0, {"departmant": department, "count": 1})

            frappe.db.sql(
                """
                DELETE FROM `tabDepartment History`
                WHERE parent = %s AND parenttype = 'Serial No' AND parentfield = 'department_history'
                """,
                serial_no,
            )

            for idx, h in enumerate(history, start=1):
                restrict, limit_count = preserved.get(h["departmant"], (0, 0))
                frappe.db.sql(
                    """
                    INSERT INTO `tabDepartment History`
                        (name, parent, parenttype, parentfield, idx, departmant, count,
                         `restrict`, limit_count, docstatus, owner, creation, modified, modified_by)
                    VALUES (%s, %s, 'Serial No', 'department_history', %s, %s, %s,
                            %s, %s, 0, 'Administrator', %s, %s, 'Administrator')
                    """,
                    (
                        generate_hash(length=10), serial_no, idx, h["departmant"], h["count"],
                        restrict, limit_count, current_time, current_time,
                    ),
                )

        frappe.db.set_value("Serial No", serial_no, "department_history_backfilled", 1, update_modified=False)
        processed += 1

    frappe.db.commit()
    frappe.logger().info(
        f"[department_count_history backfill] processed {processed} serials this run"
    )
