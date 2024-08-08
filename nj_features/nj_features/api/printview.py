import json
import frappe
from frappe.www.printview import *
from frappe.utils.jinja import is_rtl

@frappe.whitelist()
def printview():
    data = frappe.request.data
    data_json = data.decode('utf-8')
    data = json.loads(data_json)
    doc = frappe.get_doc(data.get('doctype'), data.get('docname'))
    
    letterhead = frappe.form_dict.letterhead or None
    settings = frappe.parse_json(frappe.form_dict.settings)
    meta = frappe.get_meta(doc.doctype)
    doc_print_format = frappe.db.get_value('NJ Settings', {'doc_type': data.get('doctype'), 'parameter': 'print_format'}, 'value')
    print_format = get_print_format_doc(doc_print_format, meta=meta)
    
    body = get_rendered_template(
        doc,
        print_format=print_format,
        meta=meta,
        trigger_print=True,
        no_letterhead=True,
        letterhead=letterhead,
        settings=settings,
    )
    print_style = get_print_style(frappe.form_dict.style, print_format)
    is_invalid_print = True
    return {
		"body": body,
		"print_style": print_style,
		"comment": frappe.session.user,
		"title": frappe.utils.strip_html(doc.get_title() or doc.name),
		"lang": frappe.local.lang,
		"layout_direction": "rtl" if is_rtl() else "ltr",
		"is_invalid_print": is_invalid_print,
		"doctype": frappe.form_dict.doctype,
		"name": frappe.form_dict.name,
		"key": frappe.form_dict.get("key")
	}
    
    # return get_html_and_style(doc=doc, print_format="Standard", no_letterhead=1)