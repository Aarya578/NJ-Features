import frappe
import json
@frappe.whitelist()
def stockaccess(doc):
    # print("doc======",doc)
    if isinstance(doc, str):
        doc = json.loads(doc)
    user_roles = tuple(frappe.get_roles(frappe.session.user))
    
    print("user_roles==========",user_roles)
    sql="""SELECT permission_1,permission_2,permission_3,permission_4 from `tabCustom DocPerm` where parent='stock entry' and role IN %s;
    """
    permisssions=frappe.db.sql(sql,(user_roles,),as_dict=True)
    print("=================permisssions=======",permisssions)
    response = {}
    response['stock_entry_type_query'] = []

    # Extract permission values from the first row of permissions list
    if permisssions :
        permission_row = permisssions[0]
        for key, value in permission_row.items():
            if value and value != '0':
                response['stock_entry_type_query'].append(value)
    else:
        response['stock_entry_type_query']=[]
    print("===============response==========",response)
    return response
    

    

    




























# # print("*****************",doc)
    # response={}
    # if 'Repack' in user_roles:
    #     print("inside condition=====")
    #     response['stock_entry_type_query'] = ['Repack']
    #     print("response====",response)
    #     return response

    # if 'Material Transfer' in user_roles:
    #     response['stock_entry_type_query'] = ['Material Transfer']
    #     print("response=>>>>>=====stock movement",response)
    #     return response
    # if 'Material Receipt' in user_roles:
    #     response['stock_entry_type_query'] = ['Material Receipt']
    #     print("response====",response)

    #     return response
    # if 'Material Issue' in user_roles:
    #     response['stock_entry_type_query'] = ['Material Issue']
    #     return response
        
    # else:
    #     response['stock_entry_type_query'] = []
    #     response['stock_entry_type'] = ''
    #     response['_read_only'] = True
    #     return response