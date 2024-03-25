import frappe
import json
@frappe.whitelist()
def stockaccess(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)
    user_roles = frappe.get_roles(frappe.session.user)
    print("user_roles==========",user_roles)
    print("*****************",doc)
    response={}
    if 'Repack' in user_roles:
        print("inside condition=====")
        response['stock_entry_type_query'] = ['Material Receipt', 'Material Transfer', 'Repack']
        print("response====",response)
        return response

    elif 'Stock Movement' in user_roles:
        response['stock_entry_type_query'] = ['Material Receipt', 'Material Transfer']
        print("response=>>>>>=====stock movement",response)
        return response


