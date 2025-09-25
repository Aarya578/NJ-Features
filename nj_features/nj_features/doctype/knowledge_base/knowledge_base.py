# Copyright (c) 2023, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
import json
from frappe.model.document import Document
import requests
import re
from frappe import _

import frappe
from frappe.utils.jinja import render_template
class KnowledgeBase(Document):
	pass

@frappe.whitelist()
def validate_links(doc):
    drive_link_pattern = r'^https:\/\/drive\.google\.com\/file\/d\/([\w-]+)\/view\?.*'
    attachment_fields = ['attach1', 'attach2', 'attach3', 'attach4']
    doc = json.loads(doc)

    for field in attachment_fields:
        link = doc.get(field)
        if link:
            match = re.match(drive_link_pattern, link)
            if not match:
                print(f"{field} is not a valid Google Drive link.")
                continue

            try:
                response = requests.get(link, allow_redirects=True)
                print(f"Response for {field}: {response.status_code}")
                if response.status_code == 401:
                    frappe.throw(_(f"{field} is a private Google Drive link. Please provide a public link."))

            except requests.RequestException:
                print(f"Failed to verify access for {field}.")

@frappe.whitelist()
def render_html_content_from_field(doctype, docname):
    try:
        doc = frappe.get_doc(doctype, docname)
        # Get the HTML template from NJ Settings
        html_template = frappe.db.get_value("NJ Settings", {"parameter": "html_template"}, "value")
        if not html_template:
            return "Template rendering failed: HTML template not found in NJ Settings"
        # Render the HTML content using Jinja
        rendered_html = render_template(html_template, {"doc": doc})
        # Save the rendered HTML to the html_content field
        doc.html_content = rendered_html
        doc.save(ignore_permissions=True)
        return rendered_html
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Render HTML Template Error")
        return f"Template rendering failed: {str(e)}"