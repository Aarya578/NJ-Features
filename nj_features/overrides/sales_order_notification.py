import frappe
from frappe.utils import formatdate, flt, getdate

EMAIL_TEMPLATE_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0; background-color: #f4f6f8; }
    .container { max-width: 600px; margin: 20px auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }

    /* NewJaisa brand header — deep navy/blue with white logo, matching newjaisa.com */
    .header { background: #12294D; color: #ffffff; padding: 28px 30px; text-align: center; }
    .header img { height: 34px; margin-bottom: 14px; }
    .header h1 { margin: 0; font-size: 21px; font-weight: 600; letter-spacing: 0.2px; }
    .header p { margin: 6px 0 0; font-size: 13px; color: #A9C1E0; }

    .content { padding: 30px; }
    .highlight-card { background: #EDF3FB; border-left: 4px solid #12294D; padding: 18px 20px; border-radius: 4px; margin: 20px 0; }
    .highlight-card table { width: 100%; border-collapse: collapse; }
    .highlight-card td { padding: 6px 0; font-size: 15px; }
    .highlight-card td.label { color: #555; width: 45%; }
    .highlight-card td.value { font-weight: 600; color: #111; }

    /* NewJaisa green — matches the site's "in stock" / offer badges */
    .eta-badge { display: inline-block; background: #1F9D55; color: #ffffff; font-weight: bold; padding: 4px 10px; border-radius: 4px; font-size: 14px; }

    .trust-table { width: 100%; margin: 22px 0; border-collapse: separate; border-spacing: 6px; }
    .trust-pill { background: #F4F8FC; border: 1px solid #E0E9F5; border-radius: 6px; padding: 10px 8px; font-size: 12px; color: #12294D; font-weight: 600; text-align: center; }

    .footer { background: #12294D; padding: 22px 30px; text-align: center; font-size: 13px; color: #A9C1E0; }
    .footer a { color: #ffffff; text-decoration: none; font-weight: 600; }
    .footer .copyright { margin-top: 12px; font-size: 11px; color: #6E86AC; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <img src="https://newjaisa.com/cdn/shop/files/logo-ligth_2ea4e552-0c35-4d85-9af0-67f7e4a5ad0b.svg?v=1721221860" alt="NewJaisa" />
      <h1>Your Order Update</h1>
      <p>Certified Refurbished · Quality Tested · Trusted by Thousands</p>
    </div>
    <div class="content">
      <p>Dear <strong>{{ customer_name }}</strong>,</p>
      <p>Thank you for choosing <strong>NewJaisa</strong>! Your order is currently being processed and prepared by our engineering and quality team.</p>

      <div class="highlight-card">
        <table>
          <tr>
            <td class="label">Order Number:</td>
            <td class="value">{{ sales_order_name }}</td>
          </tr>
          <tr>
            <td class="label">Order Date:</td>
            <td class="value">{{ order_date }}</td>
          </tr>
          <tr>
            <td class="label">Item:</td>
            <td class="value">{{ item_name }}</td>
          </tr>
          <tr>
            <td class="label">Configuration:</td>
            <td class="value">{{ item_configuration }}</td>
          </tr>
          <tr>
            <td class="label">Quantity:</td>
            <td class="value">{{ quantity }}</td>
          </tr>
          <tr>
            <td class="label">Order Value:</td>
            <td class="value">₹{{ order_amount }}</td>
          </tr>
          <tr>
            <td class="label">Payment Mode:</td>
            <td class="value">{{ payment_mode }}</td>
          </tr>
          <tr>
            <td class="label">Current Status:</td>
            <td class="value">{{ order_status }}</td>
          </tr>
          <tr>
            <td class="label">Estimated Delivery:</td>
            <td class="value"><span class="eta-badge">📅 {{ estimated_delivery_date }}</span></td>
          </tr>
        </table>
      </div>

      <div class="highlight-card" style="border-left-color:#1F9D55; background:#EEF8F1;">
        <table>
          <tr>
            <td class="label">Shipping To:</td>
            <td class="value">{{ shipping_name }}</td>
          </tr>
          <tr>
            <td class="label">Address:</td>
            <td class="value">{{ shipping_address }}</td>
          </tr>
          <tr>
            <td class="label">Contact No.:</td>
            <td class="value">{{ shipping_phone }}</td>
          </tr>
        </table>
      </div>

      <p>Every device at NewJaisa undergoes rigorous <strong>50+ point quality testing</strong>, thorough sanitization, and secure packaging to ensure it reaches you in peak condition.</p>

      <table class="trust-table">
        <tr>
          <td class="trust-pill">✅ 6+6 Month Warranty</td>
          <td class="trust-pill">🚚 Pan India Delivery</td>
        </tr>
        <tr>
          <td class="trust-pill">↩️ 14 Days Easy Return</td>
          <td class="trust-pill">🛡️ Free QuickHeal Security</td>
        </tr>
      </table>

      <p style="margin-top:24px; font-weight:600; color:#12294D;">What happens next?</p>
      <table style="width:100%; border-collapse:collapse; margin-bottom:10px;">
        <tr>
          <td style="padding:6px 0; width:26px; color:#1F9D55;">✔</td>
          <td style="padding:6px 0; font-size:14.5px;">Order confirmed and payment verified</td>
        </tr>
        <tr>
          <td style="padding:6px 0; width:26px; color:#1F9D55;">✔</td>
          <td style="padding:6px 0; font-size:14.5px;">Device picked and undergoing 50+ point QC</td>
        </tr>
        <tr>
          <td style="padding:6px 0; width:26px; color:#999;">○</td>
          <td style="padding:6px 0; font-size:14.5px; color:#777;">Packaging and dispatch</td>
        </tr>
        <tr>
          <td style="padding:6px 0; width:26px; color:#999;">○</td>
          <td style="padding:6px 0; font-size:14.5px; color:#777;">Out for delivery — tracking link shared via SMS/email</td>
        </tr>
      </table>

      <p>We will notify you with the shipment tracking details as soon as your package is dispatched.</p>
      <p>If you have any questions, simply reply to this email or reach us at <a href="mailto:support@newjaisa.com">support@newjaisa.com</a>.</p>
    </div>
    <div class="footer">
      <p>Need help? <a href="mailto:support@newjaisa.com">support@newjaisa.com</a> · +91-8088403455</p>
      <p class="copyright">© NewJaisa Technologies Limited | <a href="https://newjaisa.com">newjaisa.com</a></p>
    </div>
  </div>
</body>
</html>"""


def get_customer_email(doc):
    """Resolve recipient email from Sales Order."""
    if doc.contact_email:
        return doc.contact_email.strip()

    if doc.contact_person:
        email = frappe.db.get_value("Contact", doc.contact_person, "email_id")
        if email:
            return email.strip()

    if doc.customer:
        contact_name = frappe.db.sql("""
            SELECT parent FROM `tabDynamic Link`
            WHERE link_doctype = 'Customer' AND link_name = %s AND parenttype = 'Contact'
            LIMIT 1
        """, doc.customer)
        if contact_name:
            email = frappe.db.get_value("Contact", contact_name[0][0], "email_id")
            if email:
                return email.strip()

    return None


def send_sales_order_confirmation_email(so_name):
    """Send branded order confirmation email with Estimated Delivery Date upon SO submission."""
    try:
        doc = frappe.get_doc("Sales Order", so_name)
        if doc.docstatus != 1:
            return

        recipient_email = get_customer_email(doc)
        if not recipient_email:
            frappe.logger().info(f"No recipient email found for Sales Order {so_name}. Skipping email.")
            return

        # Main item details
        items = doc.items or []
        main_item = None
        total_qty = 0
        for it in items:
            total_qty += flt(it.qty)
            if not main_item and it.item_code not in ("Additional 6 Months warranty", "ADDITIONAL WARRANTY 1 YEAR", "Folding Laptop Stand"):
                main_item = it

        if not main_item and items:
            main_item = items[0]

        item_name = main_item.item_name if main_item else (items[0].item_code if items else "Refurbished Device")
        item_config = main_item.description if main_item and main_item.description else item_name

        # Clean ETA date
        eta_date_str = str(doc.delivery_date) if doc.delivery_date else str(getdate())
        formatted_eta = formatdate(eta_date_str, "dd MMMM yyyy")

        # Order date
        order_date_str = str(doc.transaction_date or doc.creation)[:10]
        formatted_order_date = formatdate(order_date_str, "dd MMMM yyyy")

        # Shipping details
        shipping_name = doc.contact_display or doc.customer_name or doc.customer
        shipping_address = (doc.shipping_address or doc.address_display or "").replace("\n", ", ")
        shipping_phone = doc.contact_phone or doc.contact_mobile or "N/A"

        # Payment mode
        payment_mode = "COD" if doc.is_cod else ("Prepaid / Online" if doc.payment_received else "Online Payment")

        context = {
            "customer_name": doc.customer_name or doc.customer,
            "sales_order_name": doc.name,
            "order_date": formatted_order_date,
            "item_name": item_name,
            "item_configuration": item_config,
            "quantity": int(total_qty) if total_qty.is_integer() else total_qty,
            "order_amount": f"{doc.grand_total:,.2f}" if doc.grand_total else "0.00",
            "payment_mode": payment_mode,
            "order_status": doc.status or "In Production",
            "estimated_delivery_date": formatted_eta,
            "shipping_name": shipping_name,
            "shipping_address": shipping_address or "As per customer profile",
            "shipping_phone": shipping_phone
        }

        rendered_html = frappe.render_template(EMAIL_TEMPLATE_HTML, context)

        frappe.sendmail(
            recipients=[recipient_email],
            sender="support@newjaisa.com",
            subject=f"Order Update: Estimated Delivery Date for Order #{doc.name}",
            message=rendered_html,
            reference_doctype="Sales Order",
            reference_name=doc.name,
            now=True
        )

        frappe.logger().info(f"Successfully sent ETA confirmation email to {recipient_email} for SO {doc.name}")

    except Exception as e:
        frappe.log_error(title=f"Error sending ETA confirmation email for {so_name}", message=frappe.get_traceback())
