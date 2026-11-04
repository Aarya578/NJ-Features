"""Check SLAs and weights between JN and non-JN."""
import frappe

def check_slas():
    print("=" * 70)
    print(" CHECKING SLAS AND WEIGHTS ON BOTH DEPT VARIANTS")
    print("=" * 70)

    for base in ['Chip Tech', 'Paint', 'L2', 'BR', 'Packing & Dispatch', 'Inward']:
        non_jn = f"{base} - NJ"
        jn = f"JN {base} - NJ"
        
        d_non = frappe.db.get_value("Department", non_jn, ["department_sla", "max_aging_days"], as_dict=True) or {}
        d_jn = frappe.db.get_value("Department", jn, ["department_sla", "max_aging_days"], as_dict=True) or {}
        
        sn_non = frappe.db.count("Serial No", {"department": non_jn, "status": "Active"})
        sn_jn = frappe.db.count("Serial No", {"department": jn, "status": "Active"})
        
        emp_non = frappe.db.count("Employee", {"department": non_jn, "status": "Active"})
        emp_jn = frappe.db.count("Employee", {"department": jn, "status": "Active"})

        print(f"\n[{base}]")
        print(f"  Non-JN ('{non_jn}'): SLA={d_non.get('department_sla')}, Aging={d_non.get('max_aging_days')} | Serials={sn_non} | Emps={emp_non}")
        print(f"  JN     ('{jn}'): SLA={d_jn.get('department_sla')}, Aging={d_jn.get('max_aging_days')} | Serials={sn_jn} | Emps={emp_jn}")
