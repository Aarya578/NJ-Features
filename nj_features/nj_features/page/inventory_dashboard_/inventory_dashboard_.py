import re
from urllib.parse import quote

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
        FROM `tabNJ Quality Inspection` qi
        WHERE qi.docstatus = 1
          AND (
              qi.rfq_id = %(rfq)s
              OR qi.name IN (
                  SELECT DISTINCT qi_name
                  FROM `tabNJQCA`
                  WHERE rfq_id = %(rfq)s
                    AND docstatus = 1
                    AND IFNULL(qi_name, '') != ''
              )
          )
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
        "serial_qc_rows": get_rfq_serial_qc_rows(rfq),
    }


def get_rfq_serial_qc_rows(rfq):
    """Return serial-level QC inspection rows for all submitted QIs under this RFQ."""
    qis = frappe.db.sql(
        """
        SELECT DISTINCT
            qi.name,
            qi.barcode,
            qi.bios_serial_number,
            qi.brand,
            qi.model,
            qi.item_wizard,
            qi.item_code,
            qi.inspection_type,
            qi.creation
        FROM `tabNJ Quality Inspection` qi
        WHERE qi.docstatus = 1
          AND (
              qi.rfq_id = %(rfq)s
              OR qi.name IN (
                  SELECT DISTINCT qi_name
                  FROM `tabNJQCA`
                  WHERE rfq_id = %(rfq)s
                    AND docstatus = 1
                    AND IFNULL(qi_name, '') != ''
              )
          )
        ORDER BY qi.creation DESC
        """,
        {"rfq": rfq},
        as_dict=True,
    )

    if not qis:
        return []

    qi_names = [q.name for q in qis]

    readings = frappe.db.sql(
        """
        SELECT
            parent AS qi_name,
            item_group,
            grade,
            difference_rate,
            is_available
        FROM `tabNj Quality Readings`
        WHERE parent IN %(qi_names)s
        ORDER BY parent, idx ASC
        """,
        {"qi_names": tuple(qi_names)},
        as_dict=True,
    )

    readings_by_qi = {}
    for r in readings:
        readings_by_qi.setdefault(r.qi_name, []).append(r)

    # 19 item groups mapping from Image 2
    item_group_keys = {
        "body a": "body_a",
        "body d base cover": "body_d_base_cover",
        "camera": "camera",
        "speaker": "speaker",
        "hinges": "hinges",
        "fan": "fan",
        "touchpad button": "touchpad_button",
        "wifi card": "wifi_card",
        "power button": "power_button",
        "motherboard": "motherboard",
        "software configuration": "software_configuration",
        "body b": "body_b",
        "laptop storage": "laptop_storage",
        "display": "display",
        "battery": "battery",
        "laptop ram": "laptop_ram",
        "body c touchpad": "body_c_touchpad",
        "body d": "body_d",
        "keyboard": "keyboard",
    }

    rows = []
    severity = {"D": 4, "C": 3, "B": 2, "A": 1, "—": 0}

    for qi in qis:
        serial_no = qi.barcode or qi.bios_serial_number or qi.name

        brand = qi.brand or ""
        model_name = qi.model or ""

        # If brand or model_name is missing, check item_wizard
        if (not brand or not model_name) and qi.item_wizard:
            iw = frappe.db.get_value("Item Wizards", qi.item_wizard, ["brand", "model"], as_dict=True) or {}
            brand = brand or iw.get("brand") or ""
            model_name = model_name or iw.get("model") or ""

        # If still missing, check item_template from item_code
        if (not brand or not model_name) and qi.item_code:
            item_data = frappe.db.get_value("Item", qi.item_code, ["item_name", "variant_of"], as_dict=True) or {}
            template = item_data.get("variant_of") or qi.item_code
            wizards = frappe.get_all(
                "Item Wizards",
                filters={"item_template": template},
                fields=["brand", "model"],
                order_by="docstatus desc, modified desc",
                limit_page_length=1,
            )
            if wizards:
                brand = brand or wizards[0].get("brand") or ""
                model_name = model_name or wizards[0].get("model") or ""

        model = " ".join(v.strip() for v in [brand, model_name] if v and v.strip())
        if not model and qi.item_code:
            model = frappe.db.get_value("Item", qi.item_code, "item_name") or qi.item_code

        qc_date = frappe.utils.format_date(qi.creation, "dd MMM") if qi.creation else "—"

        row_grades = {field: "—" for field in item_group_keys.values()}
        deduction = 0

        qi_readings = readings_by_qi.get(qi.name, [])
        for r in qi_readings:
            ig_raw = (r.item_group or "").strip().lower()
            field = item_group_keys.get(ig_raw)
            raw_grade = (r.grade or "").strip().upper()

            # Clean grade to single letter: "Grade A" -> "A", "Grade B" -> "B", etc.
            grade_clean = "—"
            if "GRADE D" in raw_grade or raw_grade == "D":
                grade_clean = "D"
            elif "GRADE C" in raw_grade or raw_grade == "C":
                grade_clean = "C"
            elif "GRADE B" in raw_grade or raw_grade == "B":
                grade_clean = "B"
            elif "GRADE A" in raw_grade or raw_grade == "A":
                grade_clean = "A"

            if field:
                current = row_grades[field]
                if severity.get(grade_clean, 0) > severity.get(current, 0):
                    row_grades[field] = grade_clean

            # Sum difference_rate for Grade D defects on this QI
            if grade_clean == "D":
                deduction += flt(r.difference_rate)

        row_dict = {
            "serial_no": serial_no,
            "qi_name": qi.name,
            "model": model,
            "qc_date": qc_date,
            "inspection_type": qi.inspection_type or "—",
            "deduction": deduction,
        }
        row_dict.update(row_grades)
        rows.append(row_dict)

    return rows


def _build_model_row(item_code, qty, deductions_by_group, submitted_item_codes, rfq_item_name=""):
    item = frappe.db.get_value(
        "Item",
        item_code,
        ["item_group", "variant_of"],
        as_dict=True,
    ) or frappe._dict()
    item_template = item.variant_of or item_code
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
        filters={"parent": item_code},
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
    qty = flt(qty)
    grade_a_rate = get_grade_a_rate(attribute_rows, item.item_group)
    deduction_per_unit = deductions_by_group.get(item.item_group, 0)
    final_rate = (
        flt(grade_a_rate) - flt(deduction_per_unit)
        if grade_a_rate is not None else None
    )

    return {
        "rfq_item": rfq_item_name or "",
        "item_code": item_code,
        "type": item.item_group or "",
        "model": model,
        "processor": attributes.get("processor type1") or attributes.get("processor type") or "",
        "ram": attributes.get("ram capacity") or "",
        "ssd": attributes.get("storage capacity") or "",
        "screen": numeric_display.group(0) if numeric_display else "",
        "segment": attributes.get("segment") or "",
        "status": "Working" if item_code in submitted_item_codes else "Not Working",
        "qty": qty,
        "grade_a_rate": grade_a_rate,
        "deduction_per_unit": deduction_per_unit,
        "final_rate": final_rate,
        "line_total": qty * final_rate if final_rate is not None else None,
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

    # Items inspected via submitted NJQCA
    submitted_njqca_items = set(frappe.get_all(
        "NJQCA",
        filters={"rfq_id": rfq, "docstatus": 1},
        pluck="item_code",
    ))

    # Items inspected via submitted Quality Inspections directly under this RFQ
    submitted_qi_items = set(frappe.get_all(
        "NJ Quality Inspection",
        filters={"rfq_id": rfq, "docstatus": 1},
        pluck="item_code",
    ))
    submitted_item_codes = submitted_njqca_items | submitted_qi_items

    rfq_item_codes = set()
    for rfq_item in rfq_items:
        if rfq_item.item_code:
            rfq_item_codes.add(rfq_item.item_code)
        rows.append(_build_model_row(
            item_code=rfq_item.item_code,
            qty=rfq_item.qty,
            deductions_by_group=deductions_by_group,
            submitted_item_codes=submitted_item_codes,
            rfq_item_name=rfq_item.name,
        ))

    # Extra lines for submitted QIs (Manual QIs) with different item_code / model not in original RFQ items
    extra_qi_items = frappe.db.sql(
        """
        SELECT
            qi.item_code,
            COUNT(DISTINCT qi.name) AS qi_count
        FROM `tabNJ Quality Inspection` qi
        WHERE qi.docstatus = 1
          AND (
              qi.rfq_id = %(rfq)s
              OR qi.name IN (
                  SELECT DISTINCT qi_name
                  FROM `tabNJQCA`
                  WHERE rfq_id = %(rfq)s
                    AND docstatus = 1
                    AND IFNULL(qi_name, '') != ''
              )
          )
          AND qi.item_code IS NOT NULL
          AND qi.item_code != ''
        GROUP BY qi.item_code
        """,
        {"rfq": rfq},
        as_dict=True,
    )

    for extra in extra_qi_items:
        item_code = extra.item_code
        if item_code in rfq_item_codes:
            continue
        rows.append(_build_model_row(
            item_code=item_code,
            qty=extra.qi_count,
            deductions_by_group=deductions_by_group,
            submitted_item_codes=submitted_item_codes,
            rfq_item_name="",
        ))

    return rows


def get_deductions_by_item(rfq):
    """Return the average Grade D deduction for each RFQ item group.

    Every submitted inspection linked to this RFQ (via submitted NJQCA or directly
    having rfq_id) contributes its Grade D difference rates. The sum is averaged
    across the distinct serial numbers that have at least one Grade D reading in that item group.
    """
    rows = frappe.db.sql(
        """
        SELECT
            COALESCE(NULLIF(TRIM(njqca.item_group), ''), NULLIF(TRIM(qi.item_group), ''), NULLIF(TRIM(item.item_group), '')) AS item_group,
            COUNT(DISTINCT CASE
                WHEN LOWER(TRIM(COALESCE(reading.grade, ''))) = 'grade d'
                THEN NULLIF(TRIM(COALESCE(njqca.serial_no, qi.barcode, qi.name)), '')
            END) AS serial_count,
            SUM(
                CASE
                    WHEN LOWER(TRIM(COALESCE(reading.grade, ''))) = 'grade d'
                    THEN COALESCE(reading.difference_rate, 0)
                    ELSE 0
                END
            ) AS total_difference_rate
        FROM `tabNJ Quality Inspection` qi
        LEFT JOIN `tabNJQCA` njqca
            ON njqca.qi_name = qi.name
            AND njqca.docstatus = 1
        LEFT JOIN `tabItem` item
            ON item.name = qi.item_code
        LEFT JOIN `tabNj Quality Readings` reading
            ON reading.parent = qi.name
        WHERE qi.docstatus = 1
          AND (
              qi.rfq_id = %(rfq)s
              OR qi.name IN (
                  SELECT DISTINCT qi_name
                  FROM `tabNJQCA`
                  WHERE rfq_id = %(rfq)s
                    AND docstatus = 1
                    AND IFNULL(qi_name, '') != ''
              )
          )
          AND (
              (njqca.item_group IS NOT NULL AND njqca.item_group != '')
              OR (qi.item_group IS NOT NULL AND qi.item_group != '')
              OR (item.item_group IS NOT NULL AND item.item_group != '')
          )
        GROUP BY COALESCE(NULLIF(TRIM(njqca.item_group), ''), NULLIF(TRIM(qi.item_group), ''), NULLIF(TRIM(item.item_group), ''))
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


@frappe.whitelist()
def create_or_update_serial_no_doc(
    serial_no, item_code=None, rfq=None, item_wizard=None, department=None, warehouse=None
):
    """
    Creates or updates a Serial No document in `tabSerial No` so Link field validation
    in NJ Quality Inspection (and any child references) passes without error.
    """
    if not serial_no:
        return None

    company = (
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or "NewJaisa"
    )

    user = frappe.session.user
    emp = (
        frappe.db.get_value(
            "Employee",
            {"user_id": user, "status": "Active"},
            ["name", "department", "work_warehouse"],
            as_dict=True,
        )
        or frappe.db.get_value(
            "Employee",
            {"user_id": user},
            ["name", "department", "work_warehouse"],
            as_dict=True,
        )
        or {}
    )

    if not department:
        department = emp.get("department") or ""
    if not warehouse:
        warehouse = emp.get("work_warehouse") or "Stores - NJ"

    iw_data = {}
    if item_wizard:
        iw_data = frappe.db.get_value(
            "Item Wizards",
            item_wizard,
            ["name", "item_group", "brand", "model"],
            as_dict=True,
        ) or {}
    elif item_code:
        try:
            iw_data = get_item_wizard_for_item(item_code) or {}
        except Exception:
            pass

    item_name = frappe.db.get_value("Item", item_code, "item_name") if item_code else None
    item_group = (
        iw_data.get("item_group")
        or (frappe.db.get_value("Item", item_code, "item_group") if item_code else None)
    )

    if frappe.db.exists("Serial No", serial_no):
        sn_doc = frappe.get_doc("Serial No", serial_no)
        updated = False
        if item_code and not sn_doc.item_code:
            sn_doc.item_code = item_code
            sn_doc.item_name = item_name or item_code
            updated = True
        if rfq and not sn_doc.rfq_id:
            sn_doc.rfq_id = rfq
            updated = True
        if iw_data.get("name") and not sn_doc.item_wizard:
            sn_doc.item_wizard = iw_data.get("name")
            updated = True
        if iw_data.get("brand") and not sn_doc.brand:
            sn_doc.brand = iw_data.get("brand")
            updated = True
        if iw_data.get("model") and not sn_doc.model:
            sn_doc.model = iw_data.get("model")
            updated = True
        if item_group and not sn_doc.item_group:
            sn_doc.item_group = item_group
            updated = True
        if department and not sn_doc.department:
            sn_doc.department = department
            updated = True
        if warehouse:
            sn_doc.warehouse = warehouse
            sn_doc.parent_warehouse = warehouse
            sn_doc.via_stock_ledger = True
            sn_doc.flags.via_stock_ledger = True
            sn_doc.status = "Active"
            updated = True
        if updated:
            sn_doc.via_stock_ledger = True
            sn_doc.flags.via_stock_ledger = True
            sn_doc.status = "Active"
            sn_doc.flags.ignore_permissions = True
            sn_doc.flags.ignore_mandatory = True
            sn_doc.save()
        frappe.db.set_value(
            "Serial No",
            serial_no,
            {
                "warehouse": warehouse,
                "parent_warehouse": warehouse,
                "status": "Active",
            },
            update_modified=False,
        )
        frappe.db.commit()
        return sn_doc

    sn_doc = frappe.new_doc("Serial No")
    sn_doc.name = serial_no
    sn_doc.serial_no = serial_no
    if item_code:
        sn_doc.item_code = item_code
        sn_doc.item_name = item_name or item_code
    sn_doc.company = company
    sn_doc.via_stock_ledger = True
    sn_doc.flags.via_stock_ledger = True
    sn_doc.status = "Active"
    sn_doc.item_source = "NJ Quality Inspection"
    if rfq:
        sn_doc.rfq_id = rfq
    if iw_data.get("name"):
        sn_doc.item_wizard = iw_data.get("name")
    if item_group:
        sn_doc.item_group = item_group
    if iw_data.get("brand"):
        sn_doc.brand = iw_data.get("brand")
    if iw_data.get("model"):
        sn_doc.model = iw_data.get("model")
    if warehouse:
        sn_doc.warehouse = warehouse
        sn_doc.parent_warehouse = warehouse
    if department:
        sn_doc.department = department

    sn_doc.flags.ignore_permissions = True
    sn_doc.flags.ignore_mandatory = True
    sn_doc.insert()
    frappe.db.set_value(
        "Serial No",
        serial_no,
        {
            "warehouse": warehouse,
            "parent_warehouse": warehouse,
            "status": "Active",
        },
        update_modified=False,
    )
    frappe.db.commit()
    return sn_doc


@frappe.whitelist()
def generate_ext_serial_no(rfq=None, item_code=None):
    import random
    from nj_features.nj_features.api.qr_code import create_serial_no

    # If item_code not provided, try to find an item from the RFQ
    if not item_code and rfq:
        rfq_items = frappe.get_all(
            "Request for Quotation Item",
            filters={"parent": rfq, "parenttype": "Request for Quotation"},
            fields=["item_code"],
            order_by="idx asc",
            limit=1,
        )
        if rfq_items and rfq_items[0].item_code:
            item_code = rfq_items[0].item_code

    if not item_code:
        frappe.throw(_("Please select an Item Code first."))

    serial_no = create_serial_no(item_code=item_code, rfq=True)
    if not serial_no:
        prefix = "EXT-LP-"
        for _ in range(10):
            candidate = prefix + str(random.randint(100000, 999999))
            if not frappe.db.exists("Serial No", candidate):
                serial_no = candidate
                break

    if not serial_no:
        frappe.throw(_("Unable to generate unique external serial number."))

    # Create the Serial No document in `tabSerial No` immediately
    create_or_update_serial_no_doc(serial_no, item_code=item_code, rfq=rfq)

    return {"serial_no": serial_no, "item_code": item_code}


@frappe.whitelist()
def get_item_wizard_for_item(item_code):
    if not item_code:
        frappe.throw(_("Please select an Item Code."))

    # Query matching requirements:
    # select it.name, it.item_group, it.brand, it.model from `tabItem` as i
    # inner join `tabItem Wizards` as it on (it.item_template = i.variant_of or it.item_template = i.name)
    # where i.name = %(item_code)s
    wizards = frappe.db.sql(
        """
        SELECT
            it.name,
            it.item_group,
            it.brand,
            it.model
        FROM `tabItem` as i
        INNER JOIN `tabItem Wizards` as it
            ON (it.item_template = i.variant_of OR it.item_template = i.name)
        WHERE i.name = %(item_code)s
        ORDER BY it.docstatus DESC, it.modified DESC
        LIMIT 1
        """,
        {"item_code": item_code},
        as_dict=True,
    )
    if wizards and wizards[0].name:
        return wizards[0]

    # Secondary lookup via NPD get_latest_item_wizard
    try:
        from nj_lib.utils.common_utils import get_latest_item_wizard
        iw_name = get_latest_item_wizard(item_code=item_code, ignore=False)
        if iw_name:
            iw_data = frappe.db.get_value(
                "Item Wizards",
                iw_name,
                ["name", "item_group", "brand", "model"],
                as_dict=True,
            )
            if iw_data:
                return iw_data
    except Exception:
        pass

    frappe.throw(_("Item Wizard not found for Item: {0}").format(item_code))


@frappe.whitelist()
def get_manual_qi_context(item_code=None, item_wizard=None, ext_serial_no=None, rfq=None):
    user = frappe.session.user
    emp = frappe.db.get_value(
        "Employee",
        {"user_id": user, "status": "Active"},
        ["name", "department", "work_warehouse"],
        as_dict=True,
    )
    if not emp:
        emp = frappe.db.get_value(
            "Employee",
            {"user_id": user},
            ["name", "department", "work_warehouse"],
            as_dict=True,
        ) or {}

    iw_data = {}
    if item_wizard:
        iw_data = frappe.db.get_value(
            "Item Wizards",
            item_wizard,
            ["name", "item_group", "brand", "model"],
            as_dict=True,
        ) or {}
    elif item_code:
        iw_data = get_item_wizard_for_item(item_code) or {}

    department = emp.get("department") or ""
    work_warehouse = emp.get("work_warehouse") or "Stores - NJ"

    if ext_serial_no:
        create_or_update_serial_no_doc(
            ext_serial_no,
            item_code=item_code,
            rfq=rfq,
            item_wizard=item_wizard or iw_data.get("name"),
            department=department,
            warehouse=work_warehouse,
        )

    return {
        "department": department,
        "work_warehouse": work_warehouse,
        "item_group": iw_data.get("item_group") or "",
        "brand": iw_data.get("brand") or "",
        "model": iw_data.get("model") or "",
    }


@frappe.whitelist()
def create_manual_qi(
    supplier=None,
    rfq=None,
    item_code=None,
    item_wizard=None,
    inspection_type=None,
    ext_serial_no=None,
    item_template=None,
    processor=None,
    ram=None,
    storage=None,
):
    """Create a draft QI for a generated RFQ serial and return its NJPulse URL."""
    required = {
        "Supplier": supplier,
        "Request for Quotation": rfq,
        "Item Code": item_code,
        "Item Wizard": item_wizard,
        "Inspection Type": inspection_type,
        "EXT Serial No": ext_serial_no,
    }
    missing = [label for label, value in required.items() if not value]
    if missing:
        frappe.throw(_("Missing required values: {0}").format(", ".join(missing)))

    if not is_supplier_rfq(supplier, rfq):
        frappe.throw(_("RFQ {0} does not belong to supplier {1}.").format(
            frappe.bold(rfq), frappe.bold(supplier)
        ))

    rfq_item_exists = frappe.db.exists(
        "Request for Quotation Item",
        {
            "parent": rfq,
            "parenttype": "Request for Quotation",
            "item_code": item_code,
        },
    )
    if rfq_item_exists:
        expected_wizard = get_item_wizard_for_item(item_code)
        if expected_wizard.get("name") != item_wizard:
            frappe.throw(_("Item Wizard does not match the selected Item Code."))
    else:
        from nj_p1_features.nj_p1_features.api.nj_qi_api import resolve_manual_qi_item

        resolved_item = resolve_manual_qi_item(
            item_template=item_template,
            processor=processor,
            ram=ram,
            storage=storage,
        )
        if (
            resolved_item.get("item_code") != item_code
            or resolved_item.get("item_wizard") != item_wizard
        ):
            frappe.throw(_("The updated Item Code or Item Wizard is no longer valid."))

    if not frappe.db.exists("Inspection Type", inspection_type):
        frappe.throw(_("Inspection Type {0} does not exist.").format(
            frappe.bold(inspection_type)
        ))

    serial_data = frappe.db.get_value(
        "Serial No",
        ext_serial_no,
        ["item_code", "rfq_id"],
        as_dict=True,
    )
    if not serial_data:
        frappe.throw(_("Please generate the EXT Serial No before creating QI."))
    if serial_data.get("item_code") and serial_data.get("item_code") != item_code:
        frappe.throw(_("EXT Serial No belongs to a different Item Code."))
    if serial_data.get("rfq_id") and serial_data.get("rfq_id") != rfq:
        frappe.throw(_("EXT Serial No belongs to a different RFQ."))

    context = get_manual_qi_context(
        item_code=item_code,
        item_wizard=item_wizard,
        ext_serial_no=ext_serial_no,
        rfq=rfq,
    )

    existing_qi = frappe.db.get_value(
        "NJ Quality Inspection",
        {
            "barcode": ext_serial_no,
            "inspection_type": inspection_type,
            "docstatus": 0,
        },
        "name",
        order_by="creation desc",
    )

    if existing_qi:
        qi_name = existing_qi
        reused = True
    else:
        from nj_features.nj_features.doctype.njqca.njqca import (
            fill_nj_quality_reading_from_serial_or_itm_wizard,
            get_itm_code_on_barcode,
        )

        qi_doc = frappe.new_doc("NJ Quality Inspection")
        qi_doc.inspection_type = inspection_type
        qi_doc.barcode = ext_serial_no
        qi_doc.bios_serial_number = ext_serial_no
        qi_doc.inspected_by = frappe.session.user
        qi_doc.item_code = item_code
        qi_doc.item_wizard = item_wizard
        qi_doc.rfq_id = rfq
        qi_doc.item_group = context.get("item_group")
        qi_doc.brand = context.get("brand")
        qi_doc.model = context.get("model")
        qi_doc.department = context.get("department")
        qi_doc.warehouse = context.get("work_warehouse")

        qi_doc = get_itm_code_on_barcode(qi_doc)
        if isinstance(qi_doc, dict) and qi_doc.get("disable_save"):
            frappe.throw(_("QI cannot be created because the Serial No has no warehouse."))

        qi_doc = fill_nj_quality_reading_from_serial_or_itm_wizard(
            qi_doc,
            inspection_type,
            is_defective="0",
            re_check="0",
        )
        qi_doc.save(ignore_permissions=True)
        qi_name = qi_doc.name
        reused = False

    base_url = frappe.db.get_value(
        "NJ Settings",
        {"parameter": "njpluse_url_for_qi"},
        "value",
    )
    if not base_url:
        frappe.throw(_("NJPulse URL is not configured in NJ Settings."))

    frappe.db.commit()
    njpulse_url = "{0}/qi/{1}/0".format(
        base_url.rstrip("/"),
        quote(qi_name, safe=""),
    )
    return {
        "qi_name": qi_name,
        "njpulse_url": njpulse_url,
        "reused": reused,
    }


def before_insert_nj_quality_inspection(doc, method=None):
    """
    Hook called before inserting a new NJ Quality Inspection.
    If it is an external serial number (starts with EXT- or has rfq_id),
    ensure the Serial No record is created in `tabSerial No` so Link validation passes.
    """
    if doc.rfq_id and doc.barcode and (str(doc.barcode).startswith("EXT-") or not frappe.db.exists("Serial No", doc.barcode)):
        create_or_update_serial_no_doc(
            doc.barcode,
            item_code=doc.item_code,
            rfq=doc.rfq_id,
            item_wizard=doc.item_wizard,
            department=doc.department,
            warehouse=doc.warehouse,
        )

