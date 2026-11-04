"""Reads everything the engine needs straight from the ERP database."""
import frappe
from frappe.utils import getdate


def load_raw(plan_date, mode, cfg):
    pool = tuple(cfg["unit_depts"]) + tuple(cfg["part_depts"])
    inwards = tuple(cfg.get("inward_depts") or [cfg.get("inward_dept", "JN Inward - NJ")])
    with_inward = pool + inwards
    raw = {}
    raw["ramps"] = frappe.db.sql("""
        select parent, from_days, to_days, target from `tabTarget Kpi`
        where parenttype='Role Profile' and parentfield='ramp_table'""")
    raw["weights"] = frappe.db.sql("""
        select parent, item_group, value from `tabWeightage`
        where parenttype='Department' and parentfield='weightage_table' order by idx""")
    raw["part_slas"] = frappe.db.sql("""
        select parent, item_group, sla from `tabPart Level SLA`
        where parenttype='Department' and parentfield='part_level_sla'""")
    raw["depts"] = frappe.db.sql("""
        select name, sla, department_sla, max_aging_days from `tabDepartment`
        where name in %(d)s and ifnull(disabled, 0) = 0""", {"d": pool}, as_dict=True)
    unit_groups = tuple(cfg["unit_item_groups"])
    raw["backlog"] = frappe.db.sql("""
        select department, item_group, count(*) from `tabSerial No`
        where status = 'Active' and department in %(d)s
          and (
            item_group in %(u)s
            or item_code like '%%GRADE D%%'
            or ifnull(grade, '') = 'Grade D'
          )
        group by department, item_group""", {"d": with_inward, "u": unit_groups})
    raw["employees"] = frappe.db.sql("""
        select name, emp_id, employee_name, department, previous_department,
               parent_department, role_profile, ramp_level, target
        from `tabEmployee` where status = 'Active' and department in %(d)s""",
        {"d": pool}, as_dict=True)
    names = tuple(e.name for e in raw["employees"]) or ("",)
    raw["experience"] = frappe.db.sql("""
        select parent, department, role_profile, no_of_days from `tabEmployee Experience`
        where parenttype='Employee' and parentfield='employee_experience_table'
          and parent in %(n)s""", {"n": names})
    raw["checkins"] = []
    if mode == "Today":
        d = getdate(plan_date)
        # Checkin.employee holds 'EMP-' + Employee.emp_id (e.g. EMP-EMP020137),
        # not Employee.name. The Attendance doctype is not populated.
        raw["checkins"] = [r[0] for r in frappe.db.sql("""
            select distinct employee from `tabEmployee Checkin`
            where log_type = 'IN' and time between %s and %s""",
            (f"{d} 00:00:00", f"{d} 23:59:59"))]
    return raw
