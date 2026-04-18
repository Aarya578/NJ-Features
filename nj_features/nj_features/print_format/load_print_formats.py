import os
import frappe


def load():
    base = os.path.dirname(__file__)

    formats = [
        ("NJ Sales Invoice", "nj_sales_invoice.html"),
        ("NJ GST E INVOICE", "nj_gst_e_invoice.html"),
    ]

    for name, filename in formats:
        path = os.path.join(base, filename)
        with open(path) as f:
            html = f.read()

        pf = frappe.get_doc("Print Format", name)
        pf.html = html
        pf.save()
        frappe.db.commit()
        print(f"Loaded: {name}")


def dump():
    base = os.path.dirname(__file__)

    formats = [
        ("NJ Sales Invoice", "nj_sales_invoice.html"),
        ("NJ GST E INVOICE", "nj_gst_e_invoice.html"),
    ]

    for name, filename in formats:
        pf = frappe.get_doc("Print Format", name)
        path = os.path.join(base, filename)
        with open(path, "w") as f:
            f.write(pf.html or "")
        print(f"Dumped: {name} → {path}")