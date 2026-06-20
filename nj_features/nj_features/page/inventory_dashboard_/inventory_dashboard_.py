import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_supplier_rfq_dashboard(supplier):
    if not supplier:
        frappe.throw(_("Please select a supplier."))

    if not frappe.db.exists("Supplier", supplier):
        frappe.throw(_("Supplier {0} does not exist.").format(frappe.bold(supplier)))

    if not frappe.has_permission("Request for Quotation", "read"):
        frappe.throw(_("Not permitted to read Request for Quotation."), frappe.PermissionError)

    rfq_rows = frappe.db.sql(
        """
        SELECT
            rfq.name AS rfq,
            rfq.transaction_date,
            rfq.status,
            rfq_item.item_codes,
            rfq_item.total_qty,
            COALESCE(njqca.submitted_count, 0) AS submitted_count,
            COALESCE(njqca.serial_nos, '') AS serial_nos,
            COALESCE(njqca.njqca_names, '') AS njqca_names
        FROM `tabRequest for Quotation` rfq
        INNER JOIN `tabRequest for Quotation Supplier` rfq_supplier
            ON rfq_supplier.parent = rfq.name
            AND rfq_supplier.supplier = %(supplier)s
        LEFT JOIN (
            SELECT
                parent,
                GROUP_CONCAT(DISTINCT item_code ORDER BY item_code SEPARATOR ', ') AS item_codes,
                SUM(qty) AS total_qty
            FROM `tabRequest for Quotation Item`
            GROUP BY parent
        ) rfq_item
            ON rfq_item.parent = rfq.name
        LEFT JOIN (
            SELECT
                rfq_id,
                COUNT(DISTINCT name) AS submitted_count,
                GROUP_CONCAT(DISTINCT serial_no ORDER BY serial_no SEPARATOR ', ') AS serial_nos,
                GROUP_CONCAT(DISTINCT name ORDER BY name SEPARATOR ', ') AS njqca_names
            FROM `tabNJQCA`
            WHERE
                docstatus = 1
                AND rfq_id IS NOT NULL
                AND rfq_id != ''
                AND serial_no IS NOT NULL
                AND serial_no != ''
            GROUP BY rfq_id
        ) njqca
            ON njqca.rfq_id = rfq.name
        WHERE rfq.docstatus < 2
        ORDER BY rfq.modified DESC
        """,
        {"supplier": supplier},
        as_dict=True,
    )

    total_qty = 0
    total_submitted = 0

    for row in rfq_rows:
        row.total_qty = flt(row.total_qty)
        row.submitted_count = flt(row.submitted_count)
        row.completion_percent = (
            flt((row.submitted_count / row.total_qty) * 100, 2) if row.total_qty else 0
        )
        total_qty += row.total_qty
        total_submitted += row.submitted_count

    return {
        "supplier": supplier,
        "total_rfqs": len(rfq_rows),
        "total_qty": total_qty,
        "total_submitted": total_submitted,
        "completion_percent": flt((total_submitted / total_qty) * 100, 2) if total_qty else 0,
        "rows": rfq_rows,
    }
