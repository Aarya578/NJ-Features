"""Diagnostic to check how Chip Tech is loaded and calculated."""
import frappe
from . import engine, loader, service

def debug_chip_tech():
    print("=" * 70)
    print(" DEBUG CHIP TECH DEPARTMENT & SNAPSHOT")
    print("=" * 70)

    # 1. Raw DB row for Chip Tech - NJ
    row = frappe.db.sql("""
        select name, department_name, department_sla, max_aging_days
        from `tabDepartment`
        where name = 'Chip Tech - NJ'
    """, as_dict=True)
    print("1. DB tabDepartment for 'Chip Tech - NJ':", row)

    # Also check other columns with 'sla' in tabDepartment
    all_cols = [c[0] for c in frappe.db.sql("desc `tabDepartment`")]
    sla_cols = [c for c in all_cols if 'sla' in c.lower()]
    print("2. All SLA columns in `tabDepartment`:", sla_cols)
    if sla_cols:
        col_vals = frappe.db.sql(f"select {', '.join(sla_cols)} from `tabDepartment` where name='Chip Tech - NJ'", as_dict=True)
        print("   Values in Chip Tech - NJ:", col_vals)

    # 2. Test loader.py output
    cfg = service.get_config()
    raw = loader.load_raw("2026-10-31", "Tomorrow", cfg)
    dept_raw = [d for d in raw["depts"] if d["name"] == "Chip Tech - NJ"]
    print("3. loader.load_raw dept for 'Chip Tech - NJ':", dept_raw)

    # 3. Test engine.build_snapshot & department_rows
    snap = engine.build_snapshot(raw, cfg, "Tomorrow")
    ct_dept = snap.depts.get("Chip Tech - NJ")
    print("4. snap.depts['Chip Tech - NJ'] object:", ct_dept)
    if ct_dept:
        print("   configured_sla:", ct_dept.configured_sla)
        print("   workload:", ct_dept.workload)
        print("   required:", ct_dept.required)
        print("   sla_days property:", ct_dept.sla_days)

    rows = engine.department_rows(snap, {}, {})
    ct_row = [r for r in rows if r["department"] == "Chip Tech - NJ"]
    print("5. engine.department_rows output for 'Chip Tech - NJ':", ct_row)

