import frappe
import base64
import json
import os
import io
import re
import requests as http_requests
from frappe.utils import today, flt


# ─────────────────────────────────────────
# PURCHASE INVOICE AUTO-FILL (existing flow)
# ─────────────────────────────────────────

@frappe.whitelist()
def extract_invoice_data(file_url):
    """
    Extract invoice fields for Purchase Invoice form.
    Fallback chain: OpenAI GPT-4o → Tesseract → Manual
    """
    file_path = _resolve_file_path(file_url)
    image_bytes, mime_type = _prepare_image(file_path, file_url)

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

    # Validate PR exists and is saved
    if not frappe.db.exists("Purchase Receipt", pr_name):
        frappe.throw(f"Purchase Receipt {pr_name} not found")

    pr = frappe.get_doc("Purchase Receipt", pr_name)

    if pr.docstatus == 2:
        frappe.throw("Cannot create PI for a cancelled Purchase Receipt")

    # Step 1 — OCR the image
    file_path = _resolve_file_path(file_url)
    image_bytes, mime_type = _prepare_image(file_path, file_url)

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
        po_name = item.purchase_order
        if not po_name:
            # Items without PO go into a default group
            po_name = "__no_po__"
        if po_name not in po_groups:
            po_groups[po_name] = []
        po_groups[po_name].append(item)

    # Step 3 — Create one PI per PO
    results = []
    for po_name, pr_items in po_groups.items():

        # Check if PI already exists for this PR + PO combination
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

        # Build PI items with smart qty/rate comparison
        pi_items, warnings = _build_pi_items(pr_items, po_name, pr_name)

        if not pi_items:
            results.append({
                "po": po_name,
                "pi": None,
                "status": "error",
                "message": "Could not build items for PI",
                "warnings": warnings
            })
            continue

        # Create the PI
        try:
            pi = _create_pi(pr, ocr_data, pi_items, po_name, file_url)
            has_mismatches = len(warnings) > 0

            # Auto-submit if no mismatches
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


def _build_pi_items(pr_items, po_name, pr_name):
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
            "purchase_receipt":   pr_name,
            "pr_detail":          pr_item.name,
        }

        pr_qty  = flt(pr_item.qty)
        pr_rate = flt(pr_item.rate)

        # Fetch PO item for comparison
        if pr_item.purchase_order_item:
            try:
                po_item = frappe.get_doc(
                    "Purchase Order Item",
                    pr_item.purchase_order_item
                )
                po_qty  = flt(po_item.qty)
                po_rate = flt(po_item.rate)

                # Qty comparison
                if pr_qty < po_qty:
                    warnings.append(
                        f"{pr_item.item_code}: Short delivery — "
                        f"received {pr_qty} of {po_qty} ordered. "
                        f"Remaining {po_qty - pr_qty} units still on PO."
                    )
                    pi_item["qty"] = pr_qty  # Bill only received qty

                elif pr_qty > po_qty:
                    warnings.append(
                        f"{pr_item.item_code}: Excess received — "
                        f"received {pr_qty} but PO qty is {po_qty}. "
                        f"PI created for PO qty {po_qty}."
                    )
                    pi_item["qty"] = po_qty  # Cap at PO qty

                else:
                    pi_item["qty"] = pr_qty  # Exact match

                # Rate comparison
                if po_rate > 0 and abs(pr_rate - po_rate) > 0.01:
                    warnings.append(
                        f"{pr_item.item_code}: Rate mismatch — "
                        f"PR rate ₹{pr_rate} vs PO rate ₹{po_rate}. "
                        f"PI created with PO rate."
                    )
                    pi_item["rate"] = po_rate  # Always use PO rate
                else:
                    pi_item["rate"] = po_rate if po_rate > 0 else pr_rate

            except Exception as e:
                # PO item not found — use PR values
                pi_item["qty"]  = pr_qty
                pi_item["rate"] = pr_rate
                warnings.append(
                    f"{pr_item.item_code}: Could not fetch PO item — "
                    f"using PR values."
                )
        else:
            pi_item["qty"]  = pr_qty
            pi_item["rate"] = pr_rate

        # Calculate amounts
        qty  = flt(pi_item["qty"])
        rate = flt(pi_item["rate"])
        amt  = qty * rate
        conv = flt(pi_item["conversion_factor"])

        pi_item["received_qty"]  = qty
        pi_item["stock_qty"]     = qty * conv
        pi_item["amount"]        = amt
        pi_item["base_rate"]     = rate
        pi_item["base_amount"]   = amt
        pi_item["net_rate"]      = rate
        pi_item["net_amount"]    = amt
        pi_item["base_net_rate"] = rate
        pi_item["base_net_amount"] = amt

        pi_items.append(pi_item)

    return pi_items, warnings


def _create_pi(pr, ocr_data, pi_items, po_name, file_url):
    """Create a new Purchase Invoice from PR data + OCR data"""

    pi = frappe.new_doc("Purchase Invoice")

    # Header from PR
    pi.supplier          = pr.supplier
    pi.company           = pr.company
    pi.currency          = pr.currency
    pi.buying_price_list = pr.buying_price_list
    pi.posting_date      = today()

    # Header from OCR
    pi.bill_no           = ocr_data.get("supplier_invoice_no") or ""
    pi.bill_date         = ocr_data.get("supplier_invoice_date") or today()
    pi.supplier_gst_no   = ocr_data.get("supplier_gstin") or ""
    pi.supplier_gstin    = ocr_data.get("supplier_gstin") or ""
    pi.gst_category      = ocr_data.get("gst_category") or "Registered Regular"
    pi.invoice_copy      = ocr_data.get("invoice_copy") or "Original for Recipient"
    pi.proof_image       = file_url

    # Tax settings from PR
    if pr.taxes_and_charges:
        pi.taxes_and_charges = pr.taxes_and_charges

    # Add items
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


# ─────────────────────────────────────────
# OPENAI GPT-4o EXTRACTOR
# ─────────────────────────────────────────

def _extract_with_openai(image_bytes, mime_type, api_key):
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    prompt = """You are an invoice data extractor for an Indian company called NewJaisa Technologies.
Extract the following fields and return ONLY a valid JSON object, nothing else:
{
  "supplier_invoice_no": "the invoice/bill number",
  "supplier_invoice_date": "date in YYYY-MM-DD format",
  "supplier_gstin": "supplier GST number (15 characters)",
  "grand_total": 0.0,
  "total_taxes_and_charges": 0.0,
  "gst_category": "one of: Registered Regular, Registered Composition, Unregistered, Overseas, Consumer, Deemed Export",
  "invoice_copy": "one of: Original for Recipient, Duplicate for Transporter, Duplicate for Supplier, Triplicate for Supplier",
  "purchase_order_no": "buyer's purchase order number (look for PO number, Buyer's Order No, PUR-ORD- reference)"
}
Rules:
- supplier_gstin = SELLER/SUPPLIER's GST number. Search the ENTIRE invoice including bottom, tables, footer areas
- A GST number pattern is: 2 digits + 5 letters + 4 digits + 1 letter + 1 alphanumeric + Z + 1 alphanumeric
- NEVER return these NewJaisa buyer GSTINs as supplier_gstin: 29AAGCN9792H1ZO, 29AACN9792H1ZO
- If you find multiple GSTINs, return the one that is NOT NewJaisa's
- supplier_invoice_date = INVOICE DATE only (not order date, not dispatch date)
- For dates like 25.02.2025 return 2025-02-25
- For dates like 30.11.2025 return 2025-11-30
- For dates like 15-Sep-25 return 2025-09-15
- For dates like 10-Jul-25 return 2025-07-10
- purchase_order_no = look for "Buyer's Order No", "PO Number", "PUR-ORD-" references on the invoice
- gst_category: if supplier has GSTIN use "Registered Regular", else "Unregistered"
- invoice_copy: look for "Original for Recipient" etc printed on invoice, default to "Original for Recipient"
- grand_total: the final payable amount including all taxes
- total_taxes_and_charges: total GST/tax amount only
- Use null if a field is not found
- Return only the JSON object, no markdown, no explanation"""

    response = http_requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-4o",
            "max_tokens": 1000,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_b64}",
                            "detail": "high"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        },
        timeout=30
    )

    if response.status_code != 200:
        raise Exception(f"OpenAI API error {response.status_code}: {response.text}")

    result_text = response.json()["choices"][0]["message"]["content"].strip()

    frappe.log_error(title="Invoice OCR Debug", message=result_text)

    if "```" in result_text:
        result_text = result_text.split("```")[1]
        if result_text.startswith("json"):
            result_text = result_text[4:]

    return json.loads(result_text.strip())


# ─────────────────────────────────────────
# TESSERACT FALLBACK
# ─────────────────────────────────────────

def _extract_with_tesseract(image_bytes):
    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    raw_text = pytesseract.image_to_string(img, config='--psm 6')
    lines = raw_text.upper()

    result = {
        "supplier_invoice_no": None,
        "supplier_invoice_date": None,
        "supplier_gstin": None,
        "grand_total": None,
        "total_taxes_and_charges": None,
        "purchase_order_no": None
    }

    NEWJAISA_GSTINS = ["29AAGCN9792H1ZO", "29AACN9792H1ZO"]
    gstin_matches = re.findall(
        r'\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}\b', lines
    )
    for gstin in gstin_matches:
        if gstin not in NEWJAISA_GSTINS:
            result["supplier_gstin"] = gstin
            break

    inv_patterns = [
        r'(?:INVOICE\s*(?:NO|NUMBER|#)[:\s#]*)([\w\-/]+)',
        r'(?:BILL\s*(?:NO|NUMBER)[:\s#]*)([\w\-/]+)',
        r'(?:INV[:\s#]*)([\w\-/]+)',
    ]
    for pat in inv_patterns:
        m = re.search(pat, lines)
        if m:
            result["supplier_invoice_no"] = m.group(1).strip()
            break

    po_match = re.search(r'(PUR-ORD-[\w\-]+)', raw_text, re.IGNORECASE)
    if po_match:
        result["purchase_order_no"] = po_match.group(1).upper()

    date_patterns = [
        r'(?:INVOICE\s*DATE[:\s]*)(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})',
        r'(?:DATE[:\s]*)(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})',
        r'(?:DATE[:\s]*)(\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2})',
        r'\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})\b',
    ]
    for pat in date_patterns:
        m = re.search(pat, raw_text, re.IGNORECASE)
        if m:
            result["supplier_invoice_date"] = _normalize_date(m.group(1))
            break

    total_match = re.search(
        r'(?:GRAND\s*TOTAL|TOTAL\s*AMOUNT|NET\s*PAYABLE)[:\s\u20b9Rs.]*([0-9,]+(?:\.[0-9]{1,2})?)',
        lines
    )
    if total_match:
        try:
            result["grand_total"] = float(total_match.group(1).replace(',', ''))
        except ValueError:
            pass

    return result


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def _resolve_file_path(file_url):
    if file_url.startswith("/files/"):
        path = frappe.get_site_path("public", "files", file_url.split("/files/")[-1])
    elif file_url.startswith("/private/files/"):
        path = frappe.get_site_path("private", "files", file_url.split("/private/files/")[-1])
    else:
        frappe.throw(f"Unsupported file path: {file_url}")
    if not os.path.exists(path):
        frappe.throw(f"File not found: {path}")
    return path


def _prepare_image(file_path, file_url):
    ext = file_url.lower().rsplit(".", 1)[-1]
    with open(file_path, "rb") as f:
        file_data = f.read()

    if ext == "pdf":
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(file_data, first_page=1, last_page=1, dpi=250)
        buf = io.BytesIO()
        images[0].save(buf, format="PNG")
        return buf.getvalue(), "image/png"

    mime_map = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png",  "webp": "image/webp"
    }
    return file_data, mime_map.get(ext, "image/jpeg")


def _is_valid_result(result):
    if not result:
        return False
    meaningful = ["supplier_invoice_no", "supplier_invoice_date", "supplier_gstin"]
    return any(result.get(f) for f in meaningful)


def _normalize_date(date_str):
    parts = re.split(r'[\/\-\.]', date_str.strip())
    if len(parts) != 3:
        return None
    if len(parts[0]) == 4:
        return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
    else:
        return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"