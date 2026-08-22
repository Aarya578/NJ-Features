import re

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
            rfq.company,
            rfq.transaction_date,
            rfq.status,
            rfq_item.item_codes,
            rfq_item.required_date,
            rfq_item.total_items,
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
                MAX(schedule_date) AS required_date,
                COUNT(name) AS total_items,
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
    model_rows = get_rfq_model_rows(rfq)
    function_tested = frappe.db.sql(
        """
        SELECT COUNT(DISTINCT qi.name)
        FROM `tabNJQCA` njqca
        INNER JOIN `tabNJ Quality Inspection` qi
            ON qi.name = njqca.qi_name
        WHERE njqca.rfq_id = %(rfq)s
          AND njqca.docstatus = 1
          AND qi.docstatus = 1
        """,
        {"rfq": rfq},
    )[0][0]
    rfq_detail = rfq_rows[0] if rfq_rows else frappe._dict()
    currency = (
        frappe.get_cached_value("Company", rfq_detail.company, "default_currency")
        if rfq_detail.company
        else frappe.defaults.get_global_default("currency")
    )

    return {
        "supplier": supplier,
        "rfq": rfq_detail.rfq,
        "company": rfq_detail.company,
        "status": rfq_detail.status,
        "rfq_date": rfq_detail.transaction_date,
        "required_date": rfq_detail.required_date,
        "total_items": rfq_detail.total_items or 0,
        "currency": currency,
        "total_rfqs": len(rfq_rows),
        "total_qty": total_qty,
        "total_submitted": total_submitted,
        "function_tested": function_tested,
        "completion_percent": flt((total_submitted / total_qty) * 100, 2) if total_qty else 0,
        "rows": rfq_rows,
        "quality_rows": quality_rows,
        "model_rows": model_rows,
    }


def get_rfq_model_rows(rfq):
    rfq_items = frappe.get_all(
        "Request for Quotation Item",
        filters={"parent": rfq, "parenttype": "Request for Quotation"},
        fields=["name", "item_code", "qty"],
        order_by="idx asc",
    )
    rows = []
    deductions_by_group = get_deductions_by_item(rfq)
    submitted_njqca_items = set(frappe.get_all(
        "NJQCA",
        filters={"rfq_id": rfq, "docstatus": 1},
        pluck="item_code",
    ))

    for rfq_item in rfq_items:
        item = frappe.db.get_value(
            "Item",
            rfq_item.item_code,
            ["item_group", "variant_of"],
            as_dict=True,
        ) or frappe._dict()
        item_template = item.variant_of or rfq_item.item_code
        item_wizards = frappe.get_all(
            "Item Wizards",
            filters={"item_template": item_template},
            fields=["name", "brand", "model"],
            order_by="docstatus desc, modified desc",
            limit_page_length=1,
        )
        item_wizard = item_wizards[0] if item_wizards else frappe._dict()

        attribute_rows = frappe.get_all(
            "Item Variant Attribute",
            filters={"parent": rfq_item.item_code},
            fields=["attribute", "attribute_value"],
            order_by="idx asc",
        )
        attributes = {
            (row.attribute or "").strip().lower(): row.attribute_value or ""
            for row in attribute_rows
        }
        display_size = ""
        if item_wizard.name:
            display_size = frappe.db.get_value(
                "Items Attribute",
                {"parent": item_wizard.name, "item_attribute": "Display Size"},
                "attribute_value",
            ) or ""
        numeric_display = re.search(r"\d+(?:\.\d+)?", display_size)
        model = " ".join(
            value.strip()
            for value in [item_wizard.brand or "", item_wizard.model or ""]
            if value and value.strip()
        )
        qty = flt(rfq_item.qty)
        grade_a_rate = get_grade_a_rate(attribute_rows, item.item_group)
        deduction_per_unit = deductions_by_group.get(item.item_group, 0)
        final_rate = (
            flt(grade_a_rate) - flt(deduction_per_unit)
            if grade_a_rate is not None else None
        )

        rows.append({
            "rfq_item": rfq_item.name,
            "item_code": rfq_item.item_code,
            "type": item.item_group or "",
            "model": model,
            "processor": attributes.get("processor type1") or attributes.get("processor type") or "",
            "ram": attributes.get("ram capacity") or "",
            "ssd": attributes.get("storage capacity") or "",
            "screen": numeric_display.group(0) if numeric_display else "",
            "status": "Working" if rfq_item.item_code in submitted_njqca_items else "Not Working",
            "qty": qty,
            "grade_a_rate": grade_a_rate,
            "deduction_per_unit": deduction_per_unit,
            "final_rate": final_rate,
            "line_total": qty * final_rate if final_rate is not None else None,
        })

    return rows


def get_deductions_by_item(rfq):
    """Return the average Grade D deduction for each RFQ item group.

    Every submitted inspection linked through a submitted NJQCA contributes its
    Grade D difference rates. The sum is averaged across the distinct serial
    numbers that have at least one Grade D reading in that item group.
    """
    rows = frappe.db.sql(
        """
        SELECT
            njqca.item_group,
            COUNT(DISTINCT CASE
                WHEN LOWER(TRIM(COALESCE(reading.grade, ''))) = 'grade d'
                THEN NULLIF(TRIM(COALESCE(njqca.serial_no, qi.barcode)), '')
            END) AS serial_count,
            SUM(
                CASE
                    WHEN LOWER(TRIM(COALESCE(reading.grade, ''))) = 'grade d'
                    THEN COALESCE(reading.difference_rate, 0)
                    ELSE 0
                END
            ) AS total_difference_rate
        FROM `tabNJQCA` njqca
        INNER JOIN `tabNJ Quality Inspection` qi
            ON qi.name = njqca.qi_name
            AND qi.docstatus = 1
        LEFT JOIN `tabNj Quality Readings` reading
            ON reading.parent = qi.name
        WHERE njqca.rfq_id = %(rfq)s
          AND njqca.docstatus = 1
          AND njqca.item_group IS NOT NULL
          AND njqca.item_group != ''
        GROUP BY njqca.item_group
        """,
        {"rfq": rfq},
        as_dict=True,
    )

    return {
        row.item_group: flt(row.total_difference_rate) / row.serial_count
        if row.serial_count else 0
        for row in rows
    }


def get_grade_a_rate(attribute_rows, item_group):
    normalized_group = (item_group or "").strip().lower()
    if "desktop" in normalized_group:
        price_field = "desktop_value"
    elif "laptop" in normalized_group:
        price_field = "laptop_value"
    else:
        return None

    total = 0
    for attribute in attribute_rows:
        attribute_name = (attribute.attribute or "").strip()
        attribute_value = (attribute.attribute_value or "").strip()
        if not attribute_name or not attribute_value:
            continue

        price = frappe.db.sql(
            """
            SELECT `{price_field}` AS price
            FROM `tabItem Attribute Value`
            WHERE LOWER(TRIM(parent)) = LOWER(TRIM(%(attribute)s))
              AND LOWER(TRIM(attribute_value)) = LOWER(TRIM(%(attribute_value)s))
            LIMIT 1
            """.format(price_field=price_field),
            {"attribute": attribute_name, "attribute_value": attribute_value},
            as_dict=True,
        )
        if price:
            total += flt(price[0].price)

    return total


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


@frappe.whitelist()
def create_rfq_price_estimation_engine(supplier, rfq):
    if not supplier:
        frappe.throw(_("Please select a supplier."))

    if not rfq:
        frappe.throw(_("Please select an RFQ."))

    if not is_supplier_rfq(supplier, rfq):
        frappe.throw(_("RFQ {0} was not found for supplier {1}.").format(
            frappe.bold(rfq),
            frappe.bold(supplier),
        ))

    rfq_creation = frappe.db.get_value("Request for Quotation", rfq, "creation")
    serial_rows = get_rfq_serial_qi_status_rows(rfq)

    doc = frappe.get_doc({
        "doctype": "RFQ Price Estimation Engine",
        "supplier": supplier,
        "rfq": rfq,
        "system_count": len(serial_rows),
        "rfq_creation": rfq_creation,
        "serial_no_qi_status": serial_rows,
    })
    doc.insert()

    return {
        "name": doc.name,
        "route": "/app/rfq-price-estimation-engine/{0}".format(doc.name),
    }


def get_rfq_serial_qi_status_rows(rfq):
    serial_rows = frappe.db.sql(
        """
        SELECT DISTINCT
            nq.serial_no,
            nq.qi_name AS njqca_qi_name
        FROM `tabNJQCA` nq
        WHERE
            nq.docstatus = 1
            AND nq.rfq_id = %(rfq)s
            AND IFNULL(nq.serial_no, '') != ''
        ORDER BY nq.serial_no
        """,
        {"rfq": rfq},
        as_dict=True,
    )

    rows = []
    for serial_row in serial_rows:
        serial_no = serial_row.serial_no
        qi = get_latest_qi_for_serial(serial_no)

        rows.append({
            "serial_no": serial_no,
            "qi_status": get_docstatus_label(qi.docstatus) if qi else "",
            "est_value": qi.preferred_purchase_price if qi else 0,
            "item_code": qi.item_code if qi else frappe.db.get_value("Serial No", serial_no, "item_code"),
        })

    return rows


def get_latest_qi_for_serial(serial_no):
    qi_rows = frappe.db.sql(
        """
        SELECT
            name,
            docstatus,
            preferred_purchase_price,
            item_code
        FROM `tabNJ Quality Inspection`
        WHERE barcode = %(serial_no)s
        ORDER BY creation DESC
        LIMIT 1
        """,
        {"serial_no": serial_no},
        as_dict=True,
    )
    return qi_rows[0] if qi_rows else None


def get_docstatus_label(docstatus):
    docstatus = int(docstatus or 0)
    if docstatus == 1:
        return "Submitted"
    if docstatus == 2:
        return "Cancelled"
    return "Draft"
