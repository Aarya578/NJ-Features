import frappe
import base64
import json
import os
import io
import re
import requests as http_requests
from frappe.utils import today, flt

# ─────────────────────────────────────────
# FILE RESOLUTION HELPERS
# ─────────────────────────────────────────

def _resolve_file_path(file_url):
    """
    Convert an ERPNext file URL to an absolute disk path.
    Handles:
      /files/abc.png          → site/public/files/abc.png
      /private/files/abc.png  → site/private/files/abc.png
    Falls back to File doctype lookup.
    """
    if not file_url:
        raise ValueError("No file URL provided")

    site_path = frappe.get_site_path()

    # Public files: /files/...
    if file_url.startswith("/files/"):
        candidate = os.path.join(site_path, "public", file_url.lstrip("/"))
        if os.path.exists(candidate):
            return candidate

    # Private files: /private/files/...
    if file_url.startswith("/private/files/"):
        candidate = os.path.join(site_path, file_url.lstrip("/"))
        if os.path.exists(candidate):
            return candidate

    # Fallback: look up via File doctype
    file_docs = frappe.get_all(
        "File",
        filters={"file_url": file_url},
        fields=["name"],
        limit=1
    )
    if file_docs:
        f = frappe.get_doc("File", file_docs[0].name)
        full_path = f.get_full_path()
        if os.path.exists(full_path):
            return full_path

    raise ValueError(f"Cannot resolve file path for URL: {file_url}")


def _prepare_image(file_path, file_url):
    """
    Read image bytes from disk and determine MIME type.
    Converts PDFs (first page) to JPEG using pdf2image if available.
    Returns (image_bytes, mime_type)
    """
    ext = os.path.splitext(file_path)[1].lower()

    mime_map = {
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png":  "image/png",
        ".gif":  "image/gif",
        ".webp": "image/webp",
    }

    if ext in mime_map:
        with open(file_path, "rb") as f:
            return f.read(), mime_map[ext]

    if ext == ".pdf":
        try:
            from pdf2image import convert_from_path
            pages = convert_from_path(file_path, first_page=1, last_page=1, dpi=200)
            if pages:
                buf = io.BytesIO()
                pages[0].save(buf, format="JPEG")
                return buf.getvalue(), "image/jpeg"
        except Exception as e:
            frappe.log_error(title="Invoice OCR: PDF conversion failed", message=str(e))
        raise ValueError("PDF conversion failed and no fallback available")

    # Last resort: read raw bytes and guess jpeg
    with open(file_path, "rb") as f:
        return f.read(), "image/jpeg"


# ─────────────────────────────────────────
# OCR BACKENDS
# ─────────────────────────────────────────

def _extract_with_openai(image_bytes, mime_type, openai_key):
    """
    Send image to OpenAI GPT-4o vision and extract invoice fields.
    Returns a dict with invoice fields.
    """
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    prompt = """You are an invoice data extraction assistant.
Extract the following fields from this invoice image and return ONLY valid JSON with these exact keys:
{
  "supplier_invoice_no": "string or null",
  "supplier_invoice_date": "YYYY-MM-DD or null",
  "supplier_gstin": "string or null",
  "grand_total": number or null,
  "total_taxes_and_charges": number or null,
  "purchase_order_no": "string or null",
  "gst_category": "string or null",
  "invoice_copy": "string or null"
}
Return ONLY the JSON object, no explanation, no markdown."""

    payload = {
        "model": "gpt-4o",
        "max_tokens": 500,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{b64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
    }

    response = http_requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=30
    )

    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if present
    content = re.sub(r"^```[a-z]*\n?", "", content)
    content = re.sub(r"\n?```$", "", content)

    return json.loads(content)


def _extract_with_tesseract(image_bytes):
    """
    Fallback OCR using pytesseract.
    Does basic regex extraction of common invoice fields.
    """
    try:
        import pytesseract
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(image)

        result = {
            "supplier_invoice_no": None,
            "supplier_invoice_date": None,
            "supplier_gstin": None,
            "grand_total": None,
            "total_taxes_and_charges": None,
            "purchase_order_no": None,
            "gst_category": None,
            "invoice_copy": None,
        }

        # GSTIN: 15-char alphanumeric
        gstin_match = re.search(r'\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b', text)
        if gstin_match:
            result["supplier_gstin"] = gstin_match.group()

        # Invoice number
        inv_match = re.search(r'(?:invoice\s*(?:no|number|#)[:\s]*)([\w\-\/]+)', text, re.IGNORECASE)
        if inv_match:
            result["supplier_invoice_no"] = inv_match.group(1).strip()

        # Date: DD/MM/YYYY or YYYY-MM-DD
        date_match = re.search(r'\b(\d{2})[\/\-](\d{2})[\/\-](\d{4})\b', text)
        if date_match:
            d, m, y = date_match.group(1), date_match.group(2), date_match.group(3)
            result["supplier_invoice_date"] = f"{y}-{m}-{d}"

        # Grand total
        total_match = re.search(r'(?:grand\s*total|total\s*amount)[:\s₹]*([\d,]+\.?\d*)', text, re.IGNORECASE)
        if total_match:
            result["grand_total"] = float(total_match.group(1).replace(",", ""))

        return result

    except Exception as e:
        frappe.log_error(title="Invoice OCR: Tesseract error", message=str(e))
        return {}


def _is_valid_result(result):
    """Check if OCR result has at least one meaningful field"""
    if not result:
        return False
    meaningful = ["supplier_invoice_no", "supplier_invoice_date", "supplier_gstin", "grand_total"]
    return any(result.get(k) for k in meaningful)


# ─────────────────────────────────────────
# PURCHASE INVOICE AUTO-FILL (existing flow)
# ─────────────────────────────────────────

@frappe.whitelist()
def extract_invoice_data(file_url):
    """
    Extract invoice fields for Purchase Invoice form.
    Fallback chain: OpenAI GPT-4o → Tesseract → Manual
    """
    try:
        file_path = _resolve_file_path(file_url)
        image_bytes, mime_type = _prepare_image(file_path, file_url)
    except Exception as e:
        frappe.log_error(title="Invoice OCR: Error resolving file", message=str(e))
        return {
            "supplier_invoice_no": None,
            "supplier_invoice_date": None,
            "supplier_gstin": None,
            "grand_total": None,
            "total_taxes_and_charges": None,
            "_source": "manual",
            "_error": "Could not resolve file path."
        }

    openai_key = frappe.conf.get("openai_api_key")
    if openai_key:
        try:
            result = _extract_with_openai(image_bytes, mime_type, openai_key)
            if _is_valid_result(result):
                result["_source"] = "openai"
                po_number = result.get("purchase_order_no")
                if po_number:
                    result["po_items"] = _get_items_from_po(po_number)
                else:
                    result["po_items"] = []
                return result
        except Exception as e:
            frappe.log_error(
                title="Invoice OCR: OpenAI failed, falling back to Tesseract",
                message=str(e)
            )

    try:
        result = _extract_with_tesseract(image_bytes)
        if _is_valid_result(result):
            result["_source"] = "tesseract"
            result["po_items"] = []
            return result
    except Exception as e:
        frappe.log_error(
            title="Invoice OCR: Tesseract also failed",
            message=str(e)
        )

    return {
        "supplier_invoice_no": None,
        "supplier_invoice_date": None,
        "supplier_gstin": None,
        "grand_total": None,
        "total_taxes_and_charges": None,
        "_source": "manual",
        "_error": "Could not extract data automatically. Please fill manually."
    }


# ─────────────────────────────────────────
# PURCHASE RECEIPT → AUTO-CREATE PI
# ─────────────────────────────────────────

@frappe.whitelist()
def process_pr_invoice_scan(pr_name, file_url):
    """
    Called when proof_image is uploaded on a saved Purchase Receipt.
    1. OCR the image
    2. For each unique PO in PR items, create one PI
    3. Compare PR qty vs PO qty for smart alerts
    4. Auto-submit PI if no mismatches
    5. Return list of created PIs with any warnings
    """

    if not frappe.db.exists("Purchase Receipt", pr_name):
        frappe.throw(f"Purchase Receipt {pr_name} not found")

    pr = frappe.get_doc("Purchase Receipt", pr_name)

    if pr.docstatus == 2:
        frappe.throw("Cannot create PI for a cancelled Purchase Receipt")

    # Step 1 — OCR the image
    try:
        file_path = _resolve_file_path(file_url)
        image_bytes, mime_type = _prepare_image(file_path, file_url)
    except Exception as e:
        frappe.log_error(title="PR OCR: Error resolving file", message=str(e))
        return {
            "success": False,
            "error": "Could not resolve file path.",
            "pi_list": []
        }

    ocr_data = {}
    openai_key = frappe.conf.get("openai_api_key")
    if openai_key:
        try:
            ocr_data = _extract_with_openai(image_bytes, mime_type, openai_key)
        except Exception as e:
            frappe.log_error(title="PR OCR: OpenAI failed", message=str(e))

    if not ocr_data:
        try:
            ocr_data = _extract_with_tesseract(image_bytes)
        except Exception as e:
            frappe.log_error(title="PR OCR: Tesseract failed", message=str(e))

    if not ocr_data:
        return {
            "success": False,
            "error": "Could not read invoice image. Please create PI manually.",
            "pi_list": []
        }

    # Step 2 — Group PR items by PO
    po_groups = {}
    for item in pr.items:
        po_name = item.purchase_order or "__no_po__"
        if po_name not in po_groups:
            po_groups[po_name] = []
        po_groups[po_name].append(item)

    # Step 3 — Create one PI per PO
    results = []
    for po_name, pr_items in po_groups.items():

        existing_pi = _check_existing_pi(pr_name, po_name)
        if existing_pi:
            results.append({
                "po": po_name,
                "pi": existing_pi,
                "status": "exists",
                "message": f"PI {existing_pi} already exists for this PR",
                "warnings": []
            })
            continue

        pi_items, warnings = _build_pi_items(pr_items, po_name, pr_name, pr.docstatus)

        if not pi_items:
            results.append({
                "po": po_name,
                "pi": None,
                "status": "error",
                "message": "Could not build items for PI",
                "warnings": warnings
            })
            continue

        try:
            pi = _create_pi(pr, ocr_data, pi_items, po_name, file_url)
            has_mismatches = len(warnings) > 0

            if not has_mismatches:
                try:
                    pi.submit()
                    status = "submitted"
                    message = f"PI {pi.name} created and submitted"
                except Exception as e:
                    status = "draft"
                    message = f"PI {pi.name} created as Draft (submit failed: {str(e)})"
                    warnings.append(f"Auto-submit failed: {str(e)}")
            else:
                status = "draft"
                message = f"PI {pi.name} created as Draft — review warnings"

            results.append({
                "po": po_name,
                "pi": pi.name,
                "status": status,
                "message": message,
                "warnings": warnings
            })

        except Exception as e:
            frappe.log_error(
                title=f"PR OCR: Failed to create PI for PO {po_name}",
                message=str(e)
            )
            results.append({
                "po": po_name,
                "pi": None,
                "status": "error",
                "message": f"Failed to create PI: {str(e)}",
                "warnings": warnings
            })

    return {
        "success": True,
        "ocr_data": ocr_data,
        "pi_list": results
    }


# ─────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────

def _check_existing_pi(pr_name, po_name):
    """Check if a PI already exists for this PR"""
    filters = {"purchase_receipt": pr_name, "docstatus": ["!=", 2]}
    if po_name != "__no_po__":
        filters["purchase_order"] = po_name

    existing = frappe.get_all(
        "Purchase Invoice Item",
        filters=filters,
        fields=["parent"],
        limit=1
    )
    return existing[0].parent if existing else None


def _build_pi_items(pr_items, po_name, pr_name, pr_docstatus=0):
    """
    Build PI items from PR items with smart qty/rate comparison.
    Returns (items_list, warnings_list)
    """
    pi_items = []
    warnings = []

    for pr_item in pr_items:
        pi_item = {
            "item_code":          pr_item.item_code,
            "item_name":          pr_item.item_name,
            "description":        pr_item.description or pr_item.item_name,
            "gst_hsn_code":       pr_item.gst_hsn_code or "",
            "uom":                pr_item.uom,
            "stock_uom":          pr_item.stock_uom,
            "conversion_factor":  flt(pr_item.conversion_factor) or 1,
            "warehouse":          pr_item.warehouse,
            "expense_account":    pr_item.expense_account,
            "purchase_order":     pr_item.purchase_order,
            "po_detail":          pr_item.purchase_order_item,
        }
        # Only link PR if it is submitted — ERPNext validates PR must be submitted
        if pr_docstatus == 1:
            pi_item["purchase_receipt"] = pr_name
            pi_item["pr_detail"]        = pr_item.name

        pr_qty  = flt(pr_item.qty)
        pr_rate = flt(pr_item.rate)

        if pr_item.purchase_order_item:
            try:
                po_item = frappe.get_doc("Purchase Order Item", pr_item.purchase_order_item)
                po_qty  = flt(po_item.qty)
                po_rate = flt(po_item.rate)

                if pr_qty < po_qty:
                    warnings.append(
                        f"{pr_item.item_code}: Short delivery — "
                        f"received {pr_qty} of {po_qty} ordered. "
                        f"Remaining {po_qty - pr_qty} units still on PO."
                    )
                    pi_item["qty"] = pr_qty
                elif pr_qty > po_qty:
                    warnings.append(
                        f"{pr_item.item_code}: Excess received — "
                        f"received {pr_qty} but PO qty is {po_qty}. "
                        f"PI created for PO qty {po_qty}."
                    )
                    pi_item["qty"] = po_qty
                else:
                    pi_item["qty"] = pr_qty

                if po_rate > 0 and abs(pr_rate - po_rate) > 0.01:
                    warnings.append(
                        f"{pr_item.item_code}: Rate mismatch — "
                        f"PR rate ₹{pr_rate} vs PO rate ₹{po_rate}. "
                        f"PI created with PO rate."
                    )
                    pi_item["rate"] = po_rate
                else:
                    pi_item["rate"] = po_rate if po_rate > 0 else pr_rate

            except Exception as e:
                pi_item["qty"]  = pr_qty
                pi_item["rate"] = pr_rate
                warnings.append(f"{pr_item.item_code}: Could not fetch PO item — using PR values.")
        else:
            pi_item["qty"]  = pr_qty
            pi_item["rate"] = pr_rate

        qty  = flt(pi_item["qty"])
        rate = flt(pi_item["rate"])
        amt  = qty * rate
        conv = flt(pi_item["conversion_factor"])

        pi_item["received_qty"]    = qty
        pi_item["stock_qty"]       = qty * conv
        pi_item["amount"]          = amt
        pi_item["base_rate"]       = rate
        pi_item["base_amount"]     = amt
        pi_item["net_rate"]        = rate
        pi_item["net_amount"]      = amt
        pi_item["base_net_rate"]   = rate
        pi_item["base_net_amount"] = amt

        pi_items.append(pi_item)

    return pi_items, warnings



def _normalize_gst_category(value):
    """
    Map whatever OCR returns to a valid ERPNext GST Category option.
    Valid: "", "Registered Regular", "Registered Composition",
           "Unregistered", "SEZ", "Overseas", "UIN Holders"
    """
    if not value:
        return "Registered Regular"
    v = value.strip().lower()
    if v in ("registered regular", "regular"):
        return "Registered Regular"
    if v in ("registered composition", "composition"):
        return "Registered Composition"
    if v in ("unregistered",):
        return "Unregistered"
    if v in ("sez",):
        return "SEZ"
    if v in ("overseas",):
        return "Overseas"
    if v in ("uin holders", "uin"):
        return "UIN Holders"
    return "Registered Regular"



def _normalize_invoice_copy(value):
    """
    Map whatever OCR returns to a valid ERPNext Invoice Copy option.
    Valid: "Original for Recipient", "Duplicate for Transporter",
           "Duplicate for Supplier", "Triplicate for Supplier"
    """
    if not value:
        return "Original for Recipient"
    v = value.strip().lower()
    if "original" in v:
        return "Original for Recipient"
    if "transporter" in v:
        return "Duplicate for Transporter"
    if "duplicate" in v and "supplier" in v:
        return "Duplicate for Supplier"
    if "triplicate" in v:
        return "Triplicate for Supplier"
    return "Original for Recipient"


def _create_pi(pr, ocr_data, pi_items, po_name, file_url):
    """Create a new Purchase Invoice from PR data + OCR data"""

    pi = frappe.new_doc("Purchase Invoice")

    pi.supplier          = pr.supplier
    pi.company           = pr.company
    pi.currency          = pr.currency
    pi.buying_price_list = pr.buying_price_list
    pi.posting_date      = today()

    pi.bill_no           = ocr_data.get("supplier_invoice_no") or ""
    pi.bill_date         = ocr_data.get("supplier_invoice_date") or today()
    pi.supplier_gst_no   = ocr_data.get("supplier_gstin") or ""
    pi.supplier_gstin    = ocr_data.get("supplier_gstin") or ""
    pi.gst_category      = _normalize_gst_category(ocr_data.get("gst_category"))
    pi.invoice_copy      = _normalize_invoice_copy(ocr_data.get("invoice_copy"))
    pi.proof_image       = file_url

    if pr.taxes_and_charges:
        pi.taxes_and_charges = pr.taxes_and_charges

    for item_data in pi_items:
        pi.append("items", item_data)

    pi.set_missing_values()
    pi.calculate_taxes_and_totals()
    pi.insert(ignore_permissions=True)

    return pi


# ─────────────────────────────────────────
# FETCH ITEMS FROM PO (for PI form flow)
# ─────────────────────────────────────────

def _get_items_from_po(po_number):
    """Fetch all items directly from a Purchase Order"""
    try:
        if not frappe.db.exists("Purchase Order", po_number):
            frappe.log_error(
                title="Invoice OCR: PO not found",
                message=f"Purchase Order {po_number} not found"
            )
            return []

        po = frappe.get_doc("Purchase Order", po_number)
        items = []

        for item in po.items:
            items.append({
                "item_code":           item.item_code,
                "item_name":           item.item_name,
                "description":         item.description or item.item_name,
                "qty":                 item.qty,
                "rate":                item.rate,
                "amount":              item.qty * item.rate,
                "uom":                 item.uom,
                "stock_uom":           item.stock_uom,
                "conversion_factor":   item.conversion_factor,
                "warehouse":           item.warehouse,
                "purchase_order":      po_number,
                "purchase_order_item": item.name,
                "hsn_code":            item.gst_hsn_code or None
            })

        return items

    except Exception as e:
        frappe.log_error(
            title="Invoice OCR: Error fetching PO items",
            message=str(e)
        )
        return []