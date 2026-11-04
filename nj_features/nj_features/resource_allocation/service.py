"""Frappe-side orchestration: compute, recompute after edits, re-optimise, apply."""
import copy

import frappe
from frappe import _

from . import engine, loader

LINE = "Resource Reallocation Line"


def get_config():
    """Engine defaults, overridable per site:
    bench --site <site> set-config -p resource_reallocation '{"min_staff_per_dept": 2}'"""
    cfg = copy.deepcopy(engine.DEFAULT_CONFIG)
    cfg.update(frappe.conf.get("resource_reallocation") or {})
    return cfg


def _before(snap):
    return {n: e.dept for n, e in snap.emps.items() if e.present}


def _lines(doc, fields=None):
    return frappe.get_all(LINE, filters={"reallocation": doc.name},
                          fields=fields or ["name", "employee", "recommended_department",
                                            "is_override", "move_type", "present"])


def compute(doc):
    cfg = get_config()
    raw = loader.load_raw(doc.plan_date, doc.mode, cfg)
    if doc.mode == "Today" and len(raw.get("checkins", [])) == 0:
        frappe.msgprint(
            _("No biometric check-in punches found for {0}. In 'Today' mode, employees without an IN punch are marked Absent.<br><br><b>To plan with full active staff, switch Mode to 'Tomorrow'.</b>").format(doc.plan_date),
            title=_("No Attendance Punches Found"),
            indicator="orange"
        )
    snap = engine.build_snapshot(raw, cfg, doc.mode)
    assign, reasons = engine.optimise(snap, cfg)
    _write(doc, snap, assign, reasons, {})


def reoptimise(doc):
    """Keep every manual change pinned, re-run the optimiser for everyone else."""
    snap = engine.Snapshot.from_json(doc.snapshot_json)
    overrides = {l.employee: l.recommended_department for l in _lines(doc) if l.is_override}
    assign, reasons = engine.optimise(snap, get_config(), overrides)
    _write(doc, snap, assign, reasons, overrides)


def recompute(doc):
    """Re-evaluate figures for the plan exactly as it now stands (no optimisation)."""
    snap = engine.Snapshot.from_json(doc.snapshot_json)
    lines = _lines(doc)
    assign = {l.employee: l.recommended_department for l in lines
              if l.present and l.employee in snap.emps}
    reasons = {l.employee: l.move_type for l in lines}
    drows = engine.department_rows(snap, _before(snap), assign)
    rows = {r["employee"]: r for r in engine.line_rows(snap, assign, reasons, drows)}
    keep = ("recommended_role", "recommended_capacity", "recommended_dept_backlog_days",
            "recommended_dept_sla", "current_dept_backlog_days", "current_dept_sla", "changed")
    for l in lines:
        r = rows.get(l.employee)
        if r:
            frappe.db.set_value(LINE, l.name, {k: r[k] for k in keep}, update_modified=False)
    _set_parent(doc, snap, assign, drows)
    doc.save(ignore_permissions=True)


def _write(doc, snap, assign, reasons, overrides):
    drows = engine.department_rows(snap, _before(snap), assign)
    frappe.db.sql(f"delete from `tab{LINE}` where reallocation = %s", doc.name)
    for r in engine.line_rows(snap, assign, reasons, drows):
        line = frappe.get_doc(dict(doctype=LINE, reallocation=doc.name,
                                   is_override=int(r["employee"] in overrides), **r))
        line.flags.from_engine = True
        line.insert(ignore_permissions=True)
    _set_parent(doc, snap, assign, drows)
    doc.snapshot_json = snap.to_json()
    doc.status = "Computed"
    doc.save(ignore_permissions=True)


def _set_parent(doc, snap, assign, drows):
    doc.set("departments", [])
    for r in drows:
        doc.append("departments", r)
    lines = _lines(doc, ["present", "changed", "move_type"])
    doc.present_count = sum(1 for l in lines if l.present)
    doc.moves_count = sum(1 for l in lines if l.changed)
    doc.untrained_moves = sum(1 for l in lines if l.changed and l.move_type == "Untrained move")
    doc.inward_available = int(snap.inward_units)
    doc.inward_release = engine.inward_release(snap, assign)


def apply(doc):
    """On submit: write department, previous department and role profile.
    The ERP's own Employee hooks then recalculate days in role, ramp and target."""
    applied, skipped = [], []
    for l in frappe.get_all(LINE, filters={"reallocation": doc.name, "changed": 1, "present": 1},
                            fields=["employee", "employee_name", "current_department",
                                    "recommended_department", "recommended_role"]):
        emp = frappe.get_doc("Employee", l.employee)
        if emp.department != l.current_department:
            skipped.append(f"{l.employee_name}: department changed to {emp.department} since compute")
            continue
        try:
            emp.previous_department = l.current_department
            emp.department = l.recommended_department
            if l.recommended_role:
                emp.previous_role_profile = emp.role_profile
                emp.role_profile = l.recommended_role
            emp.save(ignore_permissions=True)

            if emp.get("work_warehouse"):
                frappe.db.sql("""
                    UPDATE `tabWarehouse`
                    SET department = %s, previous_department = %s
                    WHERE name = %s
                """, (emp.department, emp.previous_department, emp.work_warehouse))

            applied.append(f"{l.employee_name}: {l.current_department} → {l.recommended_department} ({l.recommended_role or 'same role'})")
        except Exception as e:
            if hasattr(frappe.local, "message_log") and frappe.local.message_log:
                frappe.local.message_log.pop()
            skipped.append(f"{l.employee_name}: {str(e)}")
    doc.db_set("status", "Applied")
    msg = _("Applied {0} moves.").format(len(applied)) + "<br>" + "<br>".join(applied)
    if skipped:
        msg += "<br><br><b>" + _("Skipped") + "</b><br>" + "<br>".join(skipped)
    doc.add_comment("Info", msg)
