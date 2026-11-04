"""Check employee departments."""
import frappe

def check_emp_depts():
    print("=" * 70)
    print(" EMPLOYEE DEPARTMENTS CHECK")
    print("=" * 70)

    emps = frappe.db.sql("""
        select department, count(*) as count
        from `tabEmployee`
        where status = 'Active' and (department like '%Chip%' or department like '%Paint%' or department like '%Pack%' or department like '%BR%' or department like '%L2%')
        group by department
        order by count desc
    """, as_dict=True)
    for e in emps:
        print(f"   • {e.department:<30}: {e.count:>3} employees")
