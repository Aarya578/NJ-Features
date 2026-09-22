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
    Returns a warning message string if moving `serial_no` into `department`
    would breach that Department's Restrict Department Count / Department
    Count Limit, else None. Callers surface this as a non-blocking popup
    (frappe.msgprint) -- the move itself is never prevented, see
    block_restricted_department_moves and
    nj_features.nj_features.doctype.stock_movement.stock_movement.
    validate_serial_no_and_department.

    Restrict Department Count and Department Count Limit are now
    department-wide settings (fields on the Department doctype itself, after
    Company) rather than per (serial, department) overrides on Serial No's
    department_history row -- every serial moving into a given department is
    subject to the same limit. The serial's own department_history row is
    only consulted for its Count, which is still tracked per (serial,
    department); a serial with no row yet for this department has a count of
    0 and never triggers a warning on first entry.

    Threshold: count is allowed to REACH the limit; the move that would push
    it past that (count already >= limit) is what triggers the warning.
    """
    dept = frappe.db.get_value(
        "Department",
        department,
        ["restrict_department_count", "department_count_limit"],
        as_dict=True,
    )

    if not dept or not dept.restrict_department_count or not dept.department_count_limit:
        return None

    count = frappe.db.get_value(
        "Department History",
        {
            "parent": serial_no,
            "parenttype": "Serial No",
            "parentfield": "department_history",
            "departmant": department,
        },
        "count",
    ) or 0

    if count >= dept.department_count_limit:
        return (
            f"Serial No <b>{serial_no}</b> is crossing the movement limit "
            f"(<b>{dept.department_count_limit}</b>) set for department "
            f"<b>{department}</b>."
        )

    return None


def block_restricted_department_moves(doc, method=None):
    """
    Stock Entry "before_submit" hook. Warns (via frappe.msgprint, surfaced
    to the user as a non-blocking popup) if any transferred serial would
    cross into a department it's Restricted from and has already reached
    its Limit Count for -- see get_department_restriction_violation().
    Submission proceeds regardless; this is informational only, not a
    gate.

    Stock Movement / NJ Audit / Auto Stock Entry / MPC / NJQCA already get
    this same check earlier, during validate_serial_no_and_department()
    in nj_features.nj_features.doctype.stock_movement.stock_movement --
    that call happens BEFORE those flows even create their underlying
    Stock Entry, via nj_lib.utils.stock_entry.stock_entry_using_nj_lib(),
    which sets doc.flags.department_restriction_warned once it has shown
    that warning so this hook doesn't show the identical warning a second
    time for the same submission. This hook exists to catch a Stock Entry
    created and submitted directly (not through that helper), which is
    the one path that skips validate_serial_no_and_department entirely
    (see nj_lib's validate_direct_stock_entry_on_submit docstring).
    """
    if doc.flags.get("department_restriction_warned"):
        return

    warning_messages = []

    for serial_no, t_department in _iter_department_crossings(doc):
        violation = get_department_restriction_violation(serial_no, t_department)
        if violation:
            warning_messages.append(violation)

    if warning_messages:
        frappe.msgprint(
            "<br>".join(warning_messages),
            title="Department Count Limit",
            indicator="orange",
        )


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
