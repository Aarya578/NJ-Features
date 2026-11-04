"""Check how Serial Nos are distributed across status and department."""
import frappe

def check_serial_statuses():
    print("=" * 70)
    print(" SERIAL NO STATUS & LOCATION DISTRIBUTION")
    print("=" * 70)

    # 1. Distinct statuses in tabSerial No
    statuses = frappe.db.sql("""
        select ifnull(status, 'NULL') as status, count(*) as count
        from `tabSerial No`
        group by status
    """, as_dict=True)
    print("1. All Statuses in `tabSerial No`:")
    for s in statuses:
        st = str(s.status)
        print(f"   • {st:<20}: {s.count:>6} serial nos")

    # 2. What departments have Active Serial Nos?
    active_depts = frappe.db.sql("""
        select ifnull(department, 'NULL') as department, count(*) as count
        from `tabSerial No`
        where status = 'Active'
        group by department
        order by count desc
        limit 20
    """, as_dict=True)
    print("\n2. Departments with 'Active' Serial Nos:")
    for d in active_depts:
        dp = str(d.department)
        print(f"   • {dp:<35}: {d.count:>6} serial nos")

    # 3. What departments have Non-Delivered Serial Nos (Active, In Store, etc.)?
    other_depts = frappe.db.sql("""
        select ifnull(department, 'NULL') as department, ifnull(status, 'NULL') as status, count(*) as count
        from `tabSerial No`
        where status != 'Delivered' and status != 'Cancelled'
        group by department, status
        order by count desc
        limit 20
    """, as_dict=True)
    print("\n3. Top non-delivered serial nos by department and status:")
    for d in other_depts:
        dp = str(d.department)
        st = str(d.status)
        print(f"   • {dp:<30} | {st:<15}: {d.count:>6}")

    # 4. Check Chip Tech, Paint, FQC specifically
    print("\n4. Specific check for Chip Tech, Paint, FQC:")
    for dept in ['Chip Tech - NJ', 'Paint - NJ', 'FQC-NJ', 'Paint Inward - NJ', 'BR - NJ']:
        counts = frappe.db.sql("""
            select ifnull(status, 'NULL') as status, count(*) as count
            from `tabSerial No`
            where department = %s
            group by status
        """, (dept,), as_dict=True)
        print(f"   • {dept}: {counts if counts else 'No records in tabSerial No'}")
