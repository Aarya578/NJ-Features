
"""Check department and warehouse names for JN vs non-JN."""
import frappe

def check_dept_names():
    print("=" * 70)
    print(" CHECKING DEPARTMENT AND WAREHOUSE NAMES")
    print("=" * 70)

    # 1. Check departments matching Chip, Paint, Inward, Packing, BR, L2
    depts = frappe.db.sql("""
        select name, department_name, ifnull(disabled, 0) as disabled
        from `tabDepartment`
        where name like '%Chip%' or name like '%Paint%' or name like '%Inward%' or name like '%Pack%' or name like '%BR%' or name like '%L2%'
        order by name
    """, as_dict=True)
    print("1. Matching Departments in `tabDepartment`:")
    for d in depts:
        print(f"   • {d.name:<30} | Name: '{d.department_name}' | Disabled: {d.disabled}")

    # 2. Check warehouses
    whs = frappe.db.sql("""
        select name, warehouse_name, department
        from `tabWarehouse`
        where name like '%Chip%' or name like '%Paint%' or name like '%Inward%' or name like '%Pack%'
        limit 10
    """, as_dict=True)
    print("\n2. Matching Warehouses in `tabWarehouse`:")
    for w in whs:
        print(f"   • {w.name:<25} | Dept: '{w.department}'")




