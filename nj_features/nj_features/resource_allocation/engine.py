"""
Resource reallocation engine (v2) - pure Python, no Frappe imports, so it can
be unit-tested outside the ERP. The Frappe side lives in loader.py / service.py.

Rules (as agreed with Vishesh, 28-Oct-2026)
-------------------------------------------
Workload
  * Every Active Serial No in a department is work. Its weight comes from the
    department's Weightage table: a part weighted 0.3 adds 0.3 to the person's
    productivity count, so a person can do ~3x as many of it as laptops.
    No Weightage table -> laptops/desktops count 1, parts count 1 only in
    component-flow departments.

SLA target (not "1 day")
  * The backlog a department should hold = capacity x SLA days.
    e.g. Paint, SLA 3 days, 10 people at 7/day -> right-sized backlog = 210.
  * SLA per item group comes from Department > Part Level SLA; fallback is
    Department SLA, then Max Aging Days. Values >= sla_placeholder_days
    (500, 6000 ...) are placeholders: such a department is "locked" - nobody
    is moved in or out of it, and it is flagged in the summary.
  * Required daily capacity  R = sum(qty x weight / SLA) per item group.
    Load vs SLA = R / C. Above 100% the department will breach its SLA.

Allocation
  * Everyone starts where they are. People only move into departments that
    are over SLA (R > C), highest load-vs-SLA first.
  * A donor department must still meet its own SLA after giving the person
    (C_src - c >= R_src) and keep at least min_staff_per_dept people.
  * Who moves, in order: people whose permanent (parent) department is the
    destination; then people with experience there (ramp target from their
    Employee Experience days); then, only if no trained person can be
    found for that department, untrained people at the department's Level-1
    target.
  * Each person moves at most once. Manual overrides are pinned.
  * Finally, idle trained capacity is moved into the entry department
    (Core IQC) so it can absorb units released from Inward, and the release
    quantity = C_entry x SLA_entry - backlog_entry, capped at Inward stock.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field

EPS = 1e-9
NO_CAPACITY_DAYS = 999.0

DEFAULT_CONFIG = {
    "entry_dept": "Core IQC Reconfig - NJ",
    "inward_dept": "JN Inward - NJ",
    "inward_depts": ["JN Inward - NJ", "Inward  - NJ"],
    "unit_depts": [
        "Core IQC Reconfig - NJ", "Core IQC BDT - NJ", "BG - Core IQC - NJ",
        "Core IQC Dismantle - NJ", "Chip Tech - NJ", "BR - NJ", "Paint Inward - NJ",
        "Paint - NJ", "BG - Paint IPQC  - NJ", "Stores - NJ", "L2 - NJ",
        "L2 MDT - NJ", "L2 BDT - NJ", "L2 QC Reject - NJ",
        "BG - Reliability Testing - NJ", "FQC-NJ", "Inventory Optimization - NJ",
        "BG - Adaptor QC - NJ", "Packing & Dispatch - NJ",
    ],
    "part_depts": ["SIQC  - NJ", "BG - DR - NJ", "BG - KBD - NJ", "BTY - NJ", "Adapter - NJ"],
    "unit_item_groups": ["Laptops", "Chromebooks", "Chromeboxes", "Desktops",
                         "Full Set Desktops", "AIO", "MacBooks"],
    # Roles never moved and never counted (line managers, TLs, trainers ... carry
    # line-level targets like 240 / 330 that are not personal productivity).
    "exclude_role_patterns": [r"\bML\b", r"\bTL\b", r"incharge", r"Trainer",
                              r"Runner", r"Racking", r"Stock Movement"],
    "min_staff_per_dept": 1,
    "sla_placeholder_days": 100,
    "allow_untrained": True,
    "fill_entry_from_inward": True,
    "max_moves": 100,
}


def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def ramp_target(rows, days):
    """rows = [(from_days, to_days, target)] from the Role Profile ramp table."""
    rows = sorted(rows)
    if not rows:
        return 0.0
    for f, t, tgt in rows:
        if f <= days <= t:
            return tgt
    return rows[-1][2] if days > rows[-1][1] else rows[0][2]


def _excluded(role, cfg):
    return any(re.search(p, role or "", re.I) for p in cfg["exclude_role_patterns"])


# --------------------------------------------------------------------------
# Snapshot - everything the optimiser needs, frozen at compute time so that
# "recompute" after manual edits uses the same backlog numbers.
# --------------------------------------------------------------------------
@dataclass
class Emp:
    name: str
    emp_id: str
    full_name: str
    dept: str
    parent_dept: str | None
    prev_dept: str | None
    role: str | None
    ramp_level: str | None
    present: bool = True
    caps: dict = field(default_factory=dict)  # dept -> [capacity, role, days]


@dataclass
class Dept:
    name: str
    workload: float = 0.0   # weighted units sitting in the department
    required: float = 0.0   # weighted units/day needed to hold backlog at SLA
    unmanaged: float = 0.0  # workload whose item group has no usable SLA
    locked: str = ""        # reason the department is excluded from moves
    main_role: str | None = None
    trainee_cap: float = 0.0
    configured_sla: float | None = None

    @property
    def sla_days(self):
        if self.required > EPS:
            return self.workload / self.required
        return self.configured_sla


@dataclass
class Snapshot:
    mode: str
    entry_dept: str
    entry_sla: float | None
    inward_units: float
    emps: dict
    depts: dict

    def to_json(self):
        return json.dumps({
            "mode": self.mode, "entry_dept": self.entry_dept, "entry_sla": self.entry_sla,
            "inward_units": self.inward_units,
            "emps": {k: asdict(v) for k, v in self.emps.items()},
            "depts": {k: asdict(v) for k, v in self.depts.items()},
        })

    @classmethod
    def from_json(cls, s):
        d = json.loads(s)
        return cls(d["mode"], d["entry_dept"], d["entry_sla"], d["inward_units"],
                   {k: Emp(**v) for k, v in d["emps"].items()},
                   {k: Dept(**v) for k, v in d["depts"].items()})


def build_snapshot(raw, cfg, mode):
    """raw: ramps[(role,from,to,target)], weights[(dept,group,value)],
    part_slas[(dept,group,sla)], depts[{name,department_sla,max_aging_days}],
    backlog[(dept,group,qty)], employees[{...}], experience[(emp,dept,role,days)],
    checkins[employee ids with an IN punch]."""
    pool = list(cfg["unit_depts"]) + list(cfg["part_depts"])
    part_depts = set(cfg["part_depts"])
    unit_groups = set(cfg["unit_item_groups"])
    ph = cfg["sla_placeholder_days"]

    ramps = defaultdict(list)
    for role, f, t, tgt in raw["ramps"]:
        ramps[role].append((_num(f), _num(t), _num(tgt)))
    weights = defaultdict(dict)
    for d, g, v in raw["weights"]:
        weights[d][g] = _num(v)
    part_sla = defaultdict(dict)
    for d, g, s in raw["part_slas"]:
        part_sla[d][g] = _num(s)
    dinfo = {r["name"]: r for r in raw["depts"]}

    def dept_level_sla(d):
        info = dinfo.get(d) or {}
        for k in ("department_sla", "sla", "max_aging_days"):
            v = _num(info.get(k))
            if 0 < v < ph:
                return v
        return None

    def default_sla(d):
        s = dept_level_sla(d)
        if s:
            return s
        for s in part_sla[d].values():
            if 0 < s < ph:
                return s
        return None

    def sla_for(d, g):
        s = part_sla[d].get(g)
        if s and 0 < s < ph:
            return s
        return dept_level_sla(d)

    def weight_for(d, g):
        if weights.get(d):
            return weights[d].get(g, 0.0)
        return 1.0 if g in unit_groups else 0.0

    depts = {d: Dept(d, configured_sla=default_sla(d)) for d in pool}
    inward_set = set(cfg.get("inward_depts") or [cfg.get("inward_dept", "JN Inward - NJ")])
    inward_units = 0.0
    for d, g, n in raw["backlog"]:
        n = _num(n)
        if d in inward_set:
            if g in unit_groups:
                inward_units += n
            continue
        if d not in depts:
            continue
        w = weight_for(d, g)
        if w <= 0:
            continue
        work = n * w
        dep = depts[d]
        dep.workload += work
        s = sla_for(d, g)
        if s:
            dep.required += work / s
        else:
            dep.unmanaged += work

    for d, dep in depts.items():
        has_sla = dept_level_sla(d) or any(0 < s < ph for s in part_sla[d].values())
        if d not in dinfo:
            dep.locked = "Department missing or disabled"
        elif not has_sla:
            dep.locked = "No usable SLA (blank or placeholder)"

    emps = {}
    for e in raw["employees"]:
        d = e["department"]
        if d not in depts or _excluded(e.get("role_profile"), cfg):
            continue
        tgt = _num(e.get("target"))
        if tgt <= 0:  # no personal target -> support role, leave alone
            continue
        emp = Emp(e["name"], e.get("emp_id") or "", e.get("employee_name") or e["name"], d,
                  e.get("parent_department"), e.get("previous_department"),
                  e.get("role_profile"), e.get("ramp_level"))
        emp.caps[d] = [tgt, e.get("role_profile"), None]
        emps[emp.name] = emp

    for parent, d, role, days in raw["experience"]:
        emp = emps.get(parent)
        if not emp or d not in depts or d == emp.dept or _excluded(role, cfg):
            continue
        cap = ramp_target(ramps.get(role, []), _num(days))
        if cap > 0 and (d not in emp.caps or cap > emp.caps[d][0]):
            emp.caps[d] = [cap, role, _num(days)]

    roles = defaultdict(list)
    for emp in emps.values():
        roles[emp.dept].append(emp.role)
    for d, rs in roles.items():
        main = max(sorted(set(rs), key=str), key=rs.count)
        depts[d].main_role = main
        depts[d].trainee_cap = ramp_target(ramps.get(main, []), 0)

    checked = set(raw.get("checkins") or [])
    for emp in emps.values():
        emp.present = (mode == "Tomorrow") or (f"EMP-{emp.emp_id}" in checked) or (emp.name in checked)

    entry = cfg["entry_dept"]
    entry_sla = sla_for(entry, "Laptops") if entry in depts else None
    return Snapshot(mode, entry, entry_sla, inward_units, emps, depts)


# --------------------------------------------------------------------------
# Optimiser
# --------------------------------------------------------------------------
def capacity(snap, emp, d):
    """(daily target in dept d, role to give them there, trained?)"""
    if d in emp.caps:
        c, r, _ = emp.caps[d]
        return c, r, True
    dep = snap.depts.get(d)
    if dep and dep.trainee_cap > 0:
        return dep.trainee_cap, dep.main_role, False
    return 0.0, None, False


def evaluate(snap, assign):
    C = {d: 0.0 for d in snap.depts}
    H = {d: 0 for d in snap.depts}
    for n, d in assign.items():
        C[d] = C.get(d, 0.0) + capacity(snap, snap.emps[n], d)[0]
        H[d] = H.get(d, 0) + 1
    return C, H


def _load(R, C):
    return R / C if C > EPS else (math.inf if R > EPS else 0.0)


def optimise(snap, cfg, overrides=None):
    present = sorted(n for n, e in snap.emps.items() if e.present)
    assign = {n: snap.emps[n].dept for n in present}
    reasons = {}
    moved = set()
    for n, d in (overrides or {}).items():
        if n in assign and d in snap.depts:
            assign[n] = d
            moved.add(n)
            reasons[n] = "Manual override"

    C, H = evaluate(snap, assign)
    R = {d: dep.required for d, dep in snap.depts.items()}
    cap_at = lambda n, d: capacity(snap, snap.emps[n], d)[0]

    def can_give(n, src):
        if snap.depts[src].locked or H[src] - 1 < cfg["min_staff_per_dept"]:
            return False
        return C[src] - cap_at(n, src) >= R[src] - EPS

    def best(dst, trained_only):
        best_key, best_n = None, None
        for n in present:
            if n in moved:
                continue
            src = assign[n]
            if src == dst or not can_give(n, src):
                continue
            emp = snap.emps[n]
            c, _, trained = capacity(snap, emp, dst)
            if c <= 0 or (trained_only and not trained):
                continue
            key = (0 if emp.parent_dept == dst else 1,   # permanent dept first
                   -c,                                    # biggest help
                   cap_at(n, src),                        # smallest loss to donor
                   0 if emp.prev_dept == dst else 1,
                   n)
            if best_key is None or key < best_key:
                best_key, best_n = key, n
        return best_n

    def move(n, dst, reason):
        src = assign[n]
        C[src] -= cap_at(n, src)
        C[dst] += cap_at(n, dst)
        H[src] -= 1
        H[dst] += 1
        assign[n] = dst
        moved.add(n)
        reasons[n] = reason

    def reason_for(n, dst):
        emp = snap.emps[n]
        if emp.parent_dept == dst:
            return "Return to parent dept"
        return "Trained move" if capacity(snap, emp, dst)[2] else "Untrained move"

    nmoves = 0
    while nmoves < cfg["max_moves"]:
        deficits = [d for d, dep in snap.depts.items() if not dep.locked and R[d] > C[d] + EPS]
        deficits.sort(key=lambda d: (-_load(R[d], C[d]), -R[d], d))
        done = False
        for dst in deficits:
            n = best(dst, True) or (best(dst, False) if cfg["allow_untrained"] else None)
            if n:
                move(n, dst, reason_for(n, dst))
                nmoves += 1
                done = True
                break
        if not done:
            break

    entry = snap.entry_dept
    if (cfg["fill_entry_from_inward"] and entry in snap.depts and not snap.depts[entry].locked
            and snap.entry_sla and snap.inward_units > 0):
        target = (snap.depts[entry].workload + snap.inward_units) / snap.entry_sla
        while nmoves < cfg["max_moves"] and C[entry] < target - EPS:
            n = best(entry, True)
            if not n:
                break
            move(n, entry, "Fill from Inward")
            nmoves += 1

    return assign, reasons


def inward_release(snap, assign):
    C, _ = evaluate(snap, assign) 
    dep = snap.depts.get(snap.entry_dept)
    if not dep or not snap.entry_sla:
        return 0
    need = C[snap.entry_dept] * snap.entry_sla - dep.workload
    return int(max(0, min(snap.inward_units, round(need))))



# --------------------------------------------------------------------------
# Output rows (field names match the doctypes)
# --------------------------------------------------------------------------
def _days(W, C):
    if W <= EPS:
        return 0.0
    return round(W / C, 2) if C > EPS else NO_CAPACITY_DAYS


def department_rows(snap, before, after):
    Cb, Hb = evaluate(snap, before)
    Ca, Ha = evaluate(snap, after)
    rows = []
    for d in sorted(snap.depts):
        dep = snap.depts[d]
        lb, la = _load(dep.required, Cb[d]), _load(dep.required, Ca[d])
        rows.append({
            "department": d,
            "sla_days": round(dep.sla_days, 2) if dep.sla_days else 0,
            "workload": round(dep.workload, 1),
            "required_capacity": round(dep.required, 1),
            "headcount_before": Hb[d], "capacity_before": round(Cb[d], 1),
            "backlog_days_before": _days(dep.workload, Cb[d]),
            "load_vs_sla_before": round(min(lb, 99.99) * 100, 1),
            "headcount_after": Ha[d], "capacity_after": round(Ca[d], 1),
            "backlog_days_after": _days(dep.workload, Ca[d]),
            "load_vs_sla_after": round(min(la, 99.99) * 100, 1),
            "gap_after": round(dep.required - Ca[d], 1),
            "locked_reason": dep.locked,
        })
    rows.sort(key=lambda r: -r["load_vs_sla_before"])
    return rows


def line_rows(snap, assign, reasons, drows):
    by = {r["department"]: r for r in drows}
    out = []
    for n, emp in snap.emps.items():
        rec = assign.get(n, emp.dept)
        c_cur, _, _ = capacity(snap, emp, emp.dept)
        c_rec, r_rec, _ = capacity(snap, emp, rec)
        changed = rec != emp.dept
        if not emp.present:
            mt = "Absent"
        else:
            mt = reasons.get(n) or ("Stay" if not changed else "Manual override")
        out.append({
            "employee": n, "employee_name": emp.full_name, "present": int(emp.present),
            "ramp_level": emp.ramp_level, "parent_department": emp.parent_dept,
            "current_department": emp.dept, "current_role": emp.role,
            "current_capacity": round(c_cur, 1),
            "current_dept_backlog_days": by[emp.dept]["backlog_days_before"],
            "current_dept_sla": by[emp.dept]["sla_days"],
            "recommended_department": rec,
            "recommended_role": r_rec if changed else emp.role,
            "recommended_capacity": round(c_rec, 1),
            "recommended_dept_backlog_days": by[rec]["backlog_days_after"],
            "recommended_dept_sla": by[rec]["sla_days"],
            "move_type": mt, "changed": int(changed),
        })
    out.sort(key=lambda r: (r["recommended_department"], r["employee_name"]))
    return out

