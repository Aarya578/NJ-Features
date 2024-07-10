import json
import frappe
from frappe import _
from frappe.model.document import Document
from nj_features.nj_features.doctype.njqca.njqca import get_info_from_serial_no, fetch_model_description, brand_model_validation, get_part_mapping, after_save_njqca, get_model
    
@frappe.whitelist()
def process_njqca_data():
    
    data = frappe.request.data         # Byte
    data_json = data.decode('utf-8')   # Str
    data = json.loads(data_json)       # JSON
    
    pass
