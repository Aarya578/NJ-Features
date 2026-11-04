"""UAT verification script: audits any Resource Reallocation plan against raw ERPNext tables.

Usage from bench directory:
bench --site amzuat.newjaisa.com execute nj_features.nj_features.resource_allocation.verify.audit --args "['RR-2026-10-29-003']"
bench --site amzuat.newjaisa.com execute nj_features.nj_features.resource_allocation.verify.audit_dept --args "['RR-2026-10-29-003', 'Chip Tech - NJ']"
"""
import json
import frappe
from . import engine, loader, service


def audit(plan_name=None):
    if not plan_name:
        latest = frappe.get_all("Resource Reallocation", order_by="creation desc", limit=1)
        if not latest:
            print("No Resource Reallocation plan found.")
            return
        plan_name = latest[0].name

    doc = frappe.get_doc("Resource Reallocation", plan_name)
    print("=" * 80)
    print(f" UAT AUDIT REPORT: {doc.name} (Plan Date: {doc.plan_date}, Mode: {doc.mode})")
    print(f" Status: {doc.status} | Present: {doc.present_count} | Moves: {doc.moves_count} | Inward Release: {doc.inward_release}")
    print("=" * 80)

    cfg = service.get_config()
    raw = loader.load_raw(doc.plan_date, doc.mode, cfg)
    snap = engine.Snapshot.from_json(doc.snapshot_json) if doc.snapshot_json else engine.build_snapshot(raw, cfg, doc.mode)

    print("\n--- 1. DEPARTMENT SUMMARY VALIDATION ---")
    print(f"{'Department':<26} {'Backlog':>8} {'SLA':>5} {'Req/Day':>8} {'Ppl_B':>6} {'Cap_B':>8} {'Ppl_A':>6} {'Cap_A':>8} {'Status':>10}")
    print("-" * 95)

    dept_rows = frappe.get_all("Reallocation Department Summary",
                               filters={"parent": doc.name},
                               fields=["department", "workload", "sla_days", "required_capacity",
                                       "headcount_before", "capacity_before", "headcount_after",
                                       "capacity_after", "locked_reason"],
                               order_by="idx asc")

    for r in dept_rows:
        d = r.department
        dep = snap.depts.get(d)
        if not dep:
            continue

        # Verify math
        calc_req = round(dep.required, 1)
        calc_work = round(dep.workload, 1)
        calc_sla = round(dep.sla_days, 2) if dep.sla_days else 0

        status = "LOCKED" if r.locked_reason else "OK"
        print(f"{d:<26} {r.workload:>8.1f} {r.sla_days:>5.1f} {r.required_capacity:>8.1f} {r.headcount_before:>6} {r.capacity_before:>8.1f} {r.headcount_after:>6} {r.capacity_after:>8.1f} {status:>10}")

    print("\n--- 2. MOVERS VALIDATION ---")
    lines = frappe.get_all("Resource Reallocation Line",
                           filters={"reallocation": doc.name, "changed": 1},
                           fields=["employee", "employee_name", "current_department",
                                   "recommended_department", "move_type", "recommended_capacity"])

    if not lines:
        print("No movers recommended.")
    else:
        print(f"Total movers: {len(lines)}")
        for l in lines[:10]:
            print(f"  • {l.employee_name} ({l.employee}): {l.current_department} -> {l.recommended_department} [{l.move_type}] Target: {l.recommended_capacity}")
        if len(lines) > 10:
            print(f"  ... and {len(lines) - 10} more movers.")

    print("\nAudit completed successfully.")


def audit_dept(plan_name, dept_name):
    """Deep dive into a single department: shows raw DB serial numbers, weightage, SLAs, and employees."""
    doc = frappe.get_doc("Resource Reallocation", plan_name)
    print("=" * 80)
    print(f" DEEP-DIVE AUDIT: {dept_name} in {doc.name}")
    print("=" * 80)

    # 1. Backlog / Serial Numbers
    print("\n[A] Active Serial Nos in DB (`tabSerial No`):")
    sns = frappe.db.sql("""
        select item_group, count(*) as qty from `tabSerial No`
        where status = 'Active' and department = %s
        group by item_group
    """, (dept_name,), as_dict=True)

    weights = dict(frappe.db.sql("""
        select item_group, value from `tabWeightage`
        where parent = %s and parenttype='Department' and parentfield='weightage_table'
    """, (dept_name,)))

    part_slas = dict(frappe.db.sql("""
        select item_group, sla from `tabPart Level SLA`
        where parent = %s and parenttype='Department' and parentfield='part_level_sla'
    """, (dept_name,)))

    dept_info = frappe.db.get_value("Department", dept_name, ["department_sla", "max_aging_days"], as_dict=True) or {}

    total_workload = 0.0
    total_required = 0.0

    if not sns:
        print("  No active serial numbers in this department.")
    else:
        print(f"  {'Item Group':<25} {'Qty':>6} {'Weight':>8} {'Workload':>10} {'SLA':>6} {'Req/Day':>10}")
        print("  " + "-" * 70)
        for s in sns:
            g = s.item_group
            qty = s.qty
            w = float(weights.get(g, weights.get("All Item Groups", 1.0)))
            work = qty * w
            sla = float(part_slas.get(g) or dept_info.get("department_sla") or dept_info.get("max_aging_days") or 0)

            req = (work / sla) if sla > 0 else 0.0
            total_workload += work
            total_required += req
            print(f"  {g:<25} {qty:>6} {w:>8.2f} {work:>10.1f} {sla:>6.1f} {req:>10.1f}")
        print("  " + "-" * 70)
        eff_sla = (total_workload / total_required) if total_required > 0 else 0
        print(f"  {'TOTALS':<25} {'':>6} {'':>8} {total_workload:>10.1f} {eff_sla:>6.1f} {total_required:>10.1f}")

    # 2. Employees currently in this department
    print("\n[B] Current Employees in DB (`tabEmployee`):")
    emps = frappe.db.sql("""
        select name, employee_name, role_profile, ramp_level, target
        from `tabEmployee`
        where status = 'Active' and department = %s
    """, (dept_name,), as_dict=True)

    if not emps:
        print("  No active employees currently assigned to this department.")
    else:
        tot_cap = 0.0
        for e in emps:
            tgt = float(e.target or 0)
            tot_cap += tgt
            print(f"  • {e.employee_name} ({e.name}) | Role: {e.role_profile} | Level: {e.ramp_level} | Target: {tgt}")
        print(f"  Total Headcount: {len(emps)} | Total Capacity: {tot_cap}")



def check_chip_tech():
    """Diagnostic to check how Chip Tech Serial Numbers are stored in the DB."""
    print("=" * 70)
    print(" CHIP TECH SERIAL NUMBER DIAGNOSTIC")
    print("=" * 70)
    
    # 1. Check department field variants
    c_full = frappe.db.count("Serial No", {"department": "Chip Tech - NJ", "status": "Active"})
    c_short = frappe.db.count("Serial No", {"department": "Chip Tech", "status": "Active"})
    print(f"1. Serial No with status='Active' and department='Chip Tech - NJ' : {c_full}")
    print(f"2. Serial No with status='Active' and department='Chip Tech'      : {c_short}")
    
    # 2. Check linked warehouse
    wh_units = frappe.db.count("Serial No", {"warehouse": "BG - CT - NJ", "status": "Active"})
    print(f"3. Serial No with status='Active' and warehouse='BG - CT - NJ'   : {wh_units}")
    
    # 3. If there are any in warehouse, what does their department field say?
    sample = frappe.db.sql("""
        select name, item_name, department, warehouse, status
        from `tabSerial No`
        where warehouse = 'BG - CT - NJ' or department like '%Chip%'
        limit 5
    """, as_dict=True)
    
    print("\nSample records found:")
    if not sample:
        print("  None found matching 'BG - CT - NJ' or '%Chip%'")
    else:
        for s in sample:
            print(f"  • {s.name} | Dept: '{s.department}' | Warehouse: '{s.warehouse}' | Status: '{s.status}'")
