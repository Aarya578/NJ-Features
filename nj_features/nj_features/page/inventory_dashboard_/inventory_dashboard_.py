import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_supplier_rfqs(supplier):
    if not supplier:
        frappe.throw(_("Please select a supplier."))

    if not frappe.db.exists("Supplier", supplier):
        frappe.throw(_("Supplier {0} does not exist.").format(frappe.bold(supplier)))

    if not frappe.has_permission("Request for Quotation", "read"):
        frappe.throw(_("Not permitted to read Request for Quotation."), frappe.PermissionError)

    return frappe.db.sql(
        """
        SELECT
            rfq.name,
            rfq.status
        FROM `tabRequest for Quotation` rfq
        INNER JOIN `tabRequest for Quotation Supplier` rfq_supplier
            ON rfq_supplier.parent = rfq.name
            AND rfq_supplier.supplier = %(supplier)s
        WHERE rfq.docstatus < 2
        ORDER BY rfq.modified DESC
        """,
        {"supplier": supplier},
        as_dict=True,
    )


@frappe.whitelist()
def get_supplier_rfq_dashboard(supplier, rfq):
    if not rfq:
        frappe.throw(_("Please select an RFQ."))

    if not is_supplier_rfq(supplier, rfq):
        frappe.throw(_("RFQ {0} was not found for supplier {1}.").format(
            frappe.bold(rfq),
            frappe.bold(supplier),
        ))

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
            WHERE parent = %(rfq)s
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
                AND rfq_id = %(rfq)s
            GROUP BY rfq_id
        ) njqca
            ON njqca.rfq_id = rfq.name
        WHERE
            rfq.docstatus < 2
            AND rfq.name = %(rfq)s
        ORDER BY rfq.modified DESC
        """,
        {"supplier": supplier, "rfq": rfq},
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

    quality_rows = get_supplier_quality_summary(rfq)

    return {
        "supplier": supplier,
        "total_rfqs": len(rfq_rows),
        "total_qty": total_qty,
        "total_submitted": total_submitted,
        "completion_percent": flt((total_submitted / total_qty) * 100, 2) if total_qty else 0,
        "rows": rfq_rows,
        "quality_rows": quality_rows,
    }


def is_supplier_rfq(supplier, rfq):
    return frappe.db.exists(
        "Request for Quotation Supplier",
        {
            "parent": rfq,
            "supplier": supplier,
        },
    )


def get_supplier_quality_summary(rfq):
    return frappe.db.sql(
        """
        SELECT
            nq.manufacturer_model,
            nj.item_group,
            nj.grade,
            COUNT(DISTINCT nqi.barcode) AS item_group_count,
            GROUP_CONCAT(DISTINCT nqi.barcode ORDER BY nqi.barcode SEPARATOR ', ') AS serial_nos,
            GROUP_CONCAT(DISTINCT processor.processor_type ORDER BY processor.processor_type SEPARATOR ', ') AS processor_type,
            GROUP_CONCAT(DISTINCT ram.ram_capacity ORDER BY ram.ram_capacity SEPARATOR ', ') AS ram_capacity,
            GROUP_CONCAT(DISTINCT storage.storage_capacity ORDER BY storage.storage_capacity SEPARATOR ', ') AS storage_capacity
        FROM `tabNJQCA` nq
        INNER JOIN `tabNJ Quality Inspection` nqi
            ON nqi.name = nq.qi_name
        INNER JOIN `tabNj Quality Readings` nj
            ON nj.parent = nqi.name
        LEFT JOIN `tabNJQCA PROCESSOR` processor
            ON processor.parent = nq.name
            AND IFNULL(processor.processor_type, '') != ''
        LEFT JOIN `tabNJQCA Laptop Ram` ram
            ON ram.parent = nq.name
            AND IFNULL(ram.ram_capacity, '') != ''
        LEFT JOIN `tabNJQCA Laptop Storage` storage
            ON storage.parent = nq.name
            AND IFNULL(storage.storage_capacity, '') != ''
        WHERE
            nq.docstatus = 1
            AND nq.rfq_id = %(rfq)s
            AND IFNULL(nq.qi_name, '') != ''
            AND IFNULL(nq.manufacturer_model, '') != ''
            AND IFNULL(nqi.barcode, '') != ''
            AND UPPER(nj.grade) IN ('GRADE B', 'GRADE C', 'GRADE D')
        GROUP BY nq.manufacturer_model, nj.item_group, nj.grade
        ORDER BY nq.manufacturer_model, item_group_count DESC, nj.item_group, nj.grade
        """,
        {"rfq": rfq},
        as_dict=True,
    )
