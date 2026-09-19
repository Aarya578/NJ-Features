# Copyright (c) 2026, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe


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
