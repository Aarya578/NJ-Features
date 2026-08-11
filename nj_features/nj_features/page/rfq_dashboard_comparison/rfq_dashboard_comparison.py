import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, nowdate, strip_html


@frappe.whitelist()
def get_rfq_summary(rfq):
    if not rfq:
        frappe.throw(_("Please select an RFQ."))

    if not frappe.has_permission("Request for Quotation", "read", rfq):
        frappe.throw(
            _("Not permitted to read Request for Quotation {0}.").format(
                frappe.bold(rfq)
            ),
            frappe.PermissionError,
        )

    rfq_doc = frappe.db.get_value(
        "Request for Quotation",
        rfq,
        ["name", "transaction_date", "company"],
        as_dict=True,
    )
    if not rfq_doc:
        frappe.throw(_("Request for Quotation {0} does not exist.").format(frappe.bold(rfq)))

    totals = frappe.db.sql(
        """
        SELECT
            MAX(schedule_date) AS required_date,
            COUNT(name) AS total_items,
            COALESCE(SUM(qty), 0) AS total_qty_required,
            COALESCE(SUM(rate), 0) AS total_rate
        FROM `tabRequest for Quotation Item`
        WHERE parent = %(rfq)s
          AND parenttype = 'Request for Quotation'
        """,
        {"rfq": rfq},
        as_dict=True,
    )[0]

    currency = None
    if rfq_doc.company:
        currency = frappe.get_cached_value("Company", rfq_doc.company, "default_currency")
    currency = currency or frappe.defaults.get_global_default("currency")

    items = frappe.get_all(
        "Request for Quotation Item",
        filters={
            "parent": rfq,
            "parenttype": "Request for Quotation",
        },
        fields=["name", "item_code", "description", "qty"],
        order_by="idx asc",
    )

    for item in items:
        item.description = strip_html(item.description or "")
        item.qty = flt(item.qty)

    purchase_orders = []
    purchase_order_rows = frappe.db.sql(
        """
        SELECT po.name AS purchase_order, po.supplier, po.creation, po.status,
            po.docstatus, po.currency, poi.item_code, poi.qty, poi.rate
        FROM `tabPurchase Order` po
        LEFT JOIN `tabPurchase Order Item` poi
            ON poi.parent = po.name AND poi.parenttype = 'Purchase Order'
        WHERE po.rfq_name = %(rfq)s
        ORDER BY po.creation DESC, po.name DESC, poi.idx ASC
        """,
        {"rfq": rfq},
        as_dict=True,
    )
    purchase_orders_by_name = {}
    readable_purchase_orders = set()
    for row in purchase_order_rows:
        purchase_order = row.purchase_order
        if purchase_order not in readable_purchase_orders:
            if not frappe.has_permission("Purchase Order", "read", purchase_order):
                continue
            readable_purchase_orders.add(purchase_order)

        if purchase_order not in purchase_orders_by_name:
            purchase_order_data = {
                "name": purchase_order,
                "supplier": row.supplier,
                "creation": row.creation,
                "status": row.status,
                "docstatus": row.docstatus,
                "currency": row.currency or currency,
                "items": [],
            }
            purchase_orders_by_name[purchase_order] = purchase_order_data
            purchase_orders.append(purchase_order_data)

        if row.item_code:
            purchase_orders_by_name[purchase_order]["items"].append({
                "item_code": row.item_code,
                "qty": flt(row.qty),
                "rate": flt(row.rate),
            })

    supplier_quotation_rows = frappe.db.sql(
        """
        SELECT
            sq.name AS supplier_quotation,
            sq.supplier,
            sq.transaction_date,
            sq.lead_date,
            sq.currency,
            sqi.item_code,
            sqi.request_for_quotation_item,
            sqi.rate,
            sqi.available_qty,
            sqi.availability
        FROM `tabSupplier Quotation` sq
        INNER JOIN `tabSupplier Quotation Item` sqi
            ON sqi.parent = sq.name
            AND sqi.parenttype = 'Supplier Quotation'
        WHERE sq.docstatus < 2
          AND sqi.request_for_quotation = %(rfq)s
        ORDER BY sq.creation ASC, sq.name ASC, sqi.idx ASC
        """,
        {"rfq": rfq},
        as_dict=True,
    )

    suppliers = []
    suppliers_by_quotation = {}
    readable_quotations = set()

    for row in supplier_quotation_rows:
        quotation = row.supplier_quotation
        if quotation not in readable_quotations:
            if not frappe.has_permission("Supplier Quotation", "read", quotation):
                continue
            readable_quotations.add(quotation)

        if quotation not in suppliers_by_quotation:
            lead_days = None
            if row.transaction_date and row.lead_date:
                lead_days = date_diff(row.lead_date, row.transaction_date)

            supplier_data = {
                "supplier_quotation": quotation,
                "supplier": row.supplier,
                "currency": row.currency or currency,
                "lead_days": lead_days,
                "items": [],
            }
            suppliers_by_quotation[quotation] = supplier_data
            suppliers.append(supplier_data)

        suppliers_by_quotation[quotation]["items"].append({
            "item_code": row.item_code,
            "request_for_quotation_item": row.request_for_quotation_item,
            "rate": flt(row.rate),
            "available_qty": flt(row.available_qty),
            "availability": row.availability or "",
        })

    return {
        "rfq": rfq_doc.name,
        "rfq_date": rfq_doc.transaction_date,
        "required_date": totals.required_date,
        "total_items": totals.total_items or 0,
        "total_qty_required": flt(totals.total_qty_required),
        "total_rate": flt(totals.total_rate),
        "currency": currency,
        "items": items,
        "suppliers": suppliers,
        "purchase_orders": purchase_orders,
    }


@frappe.whitelist()
def generate_purchase_orders(rfq, verdict):
    if not rfq:
        frappe.throw(_("Please select an RFQ."))

    if not frappe.has_permission("Request for Quotation", "read", rfq):
        frappe.throw(_("Not permitted to read this RFQ."), frappe.PermissionError)
    if not frappe.has_permission("Purchase Order", "create"):
        frappe.throw(_("Not permitted to create Purchase Orders."), frappe.PermissionError)
    if not frappe.has_permission("Purchase Order", "submit"):
        frappe.throw(_("Not permitted to submit Purchase Orders."), frappe.PermissionError)

    verdict = frappe.parse_json(verdict)
    if not isinstance(verdict, list) or not verdict:
        frappe.throw(_("The Verdict does not contain any quantities to purchase."))

    rfq_doc = frappe.get_doc("Request for Quotation", rfq)
    if rfq_doc.docstatus == 2:
        frappe.throw(_("Cannot create Purchase Orders from a cancelled RFQ."))

    rfq_items = {row.name: row for row in rfq_doc.items}
    grouped_by_supplier = {}

    for allocation in verdict:
        rfq_item_name = allocation.get("rfq_item")
        quotation_name = allocation.get("supplier_quotation")
        qty = flt(allocation.get("qty"))

        if qty <= 0:
            continue
        if rfq_item_name not in rfq_items:
            frappe.throw(_("A Verdict item does not belong to RFQ {0}.").format(frappe.bold(rfq)))
        if not quotation_name:
            frappe.throw(_("Supplier Quotation is missing from a Verdict allocation."))
        if not frappe.has_permission("Supplier Quotation", "read", quotation_name):
            frappe.throw(
                _("Not permitted to read Supplier Quotation {0}.").format(
                    frappe.bold(quotation_name)
                ),
                frappe.PermissionError,
            )

        quotation = frappe.get_doc("Supplier Quotation", quotation_name)
        if quotation.docstatus == 2:
            frappe.throw(
                _("Supplier Quotation {0} is cancelled.").format(frappe.bold(quotation_name))
            )
        if quotation.company != rfq_doc.company:
            frappe.throw(
                _("Supplier Quotation {0} belongs to another company.").format(
                    frappe.bold(quotation_name)
                )
            )

        quotation_item = next(
            (
                row for row in quotation.items
                if row.request_for_quotation == rfq
                and row.request_for_quotation_item == rfq_item_name
            ),
            None,
        )
        if not quotation_item:
            frappe.throw(
                _("Supplier Quotation {0} is not linked to the selected RFQ item.").format(
                    frappe.bold(quotation_name)
                )
            )

        supplier_group = grouped_by_supplier.setdefault(quotation.supplier, {
            "supplier": quotation.supplier,
            "quotations": {},
            "items": {},
        })
        supplier_group["quotations"][quotation.name] = quotation

        item_key = (rfq_item_name, quotation.name)
        if item_key not in supplier_group["items"]:
            supplier_group["items"][item_key] = {
                "rfq_item": rfq_items[rfq_item_name],
                "quotation_item": quotation_item,
                "quotation": quotation,
                "qty": 0,
            }
        supplier_group["items"][item_key]["qty"] += qty

    if not grouped_by_supplier:
        frappe.throw(_("The Verdict does not contain any positive quantities to purchase."))

    created = []
    skipped = []
    for supplier, supplier_group in grouped_by_supplier.items():
        active_po = frappe.db.sql(
            """
            SELECT name, status
            FROM `tabPurchase Order`
            WHERE rfq_name = %(rfq)s
              AND supplier = %(supplier)s
              AND docstatus = 1
              AND status NOT IN ('Completed', 'Cancelled')
            ORDER BY creation DESC
            LIMIT 1
            """,
            {"rfq": rfq, "supplier": supplier},
            as_dict=True,
        )
        if active_po:
            skipped.append({
                "supplier": supplier,
                "purchase_order": active_po[0].name,
                "status": active_po[0].status,
            })
            continue

        purchase_order = make_purchase_order_from_verdict(rfq_doc, supplier_group)
        purchase_order.insert()
        purchase_order.submit()
        created.append({
            "supplier": supplier,
            "purchase_order": purchase_order.name,
            "status": purchase_order.status,
        })

    return {"created": created, "skipped": skipped}


def make_purchase_order_from_verdict(rfq_doc, supplier_group):
    first_quotation = next(iter(supplier_group["quotations"].values()))
    today = getdate(nowdate())
    purchase_order = frappe.new_doc("Purchase Order")
    purchase_order.update({
        "supplier": supplier_group["supplier"],
        "company": rfq_doc.company,
        "transaction_date": today,
        "schedule_date": today,
        "warranty_days":30,
        "conversion_rate":1.2,
        "currency": first_quotation.currency,
        "conversion_rate": first_quotation.conversion_rate or 1,
        "buying_price_list": first_quotation.buying_price_list,
        "price_list_currency": first_quotation.price_list_currency,
        "plc_conversion_rate": first_quotation.plc_conversion_rate or 1,
        "supplier_address": first_quotation.supplier_address,
        "address_display": first_quotation.address_display,
        "contact_person": first_quotation.contact_person,
        "contact_display": first_quotation.contact_display,
        "contact_mobile": first_quotation.contact_mobile,
        "contact_email": first_quotation.contact_email,
        "rfq_name": rfq_doc.name,
        "ignore_pricing_rule": 1,
    })

    for item_data in supplier_group["items"].values():
        rfq_item = item_data["rfq_item"]
        quotation_item = item_data["quotation_item"]
        quotation = item_data["quotation"]
        schedule_date = getdate(rfq_item.schedule_date) if rfq_item.schedule_date else today
        if schedule_date < today:
            schedule_date = today

        purchase_order.append("items", {
            "item_code": rfq_item.item_code,
            "item_name": quotation_item.item_name or rfq_item.item_name,
            "description": quotation_item.description or rfq_item.description,
            "qty": flt(item_data["qty"]),
            "uom": quotation_item.uom or rfq_item.uom,
            "stock_uom": quotation_item.stock_uom or rfq_item.stock_uom,
            "conversion_factor": flt(quotation_item.conversion_factor or rfq_item.conversion_factor or 1),
            "rate": flt(quotation_item.rate),
            "schedule_date": schedule_date,
            "warehouse": quotation_item.warehouse or rfq_item.warehouse,
            "supplier_quotation": quotation.name,
            "supplier_quotation_item": quotation_item.name,
            "material_request": quotation_item.material_request,
            "material_request_item": quotation_item.material_request_item,
        })

    purchase_order.flags.ignore_pricing_rule = True
    purchase_order.run_method("set_missing_values")
    purchase_order.run_method("calculate_taxes_and_totals")
    return purchase_order
