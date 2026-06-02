# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class DocAttachment(Document):
    @staticmethod
    def clear_old_logs(days=None):
        days = days or 1800
        table_name = "tabDoc Attachment"
        
        frappe.db.sql(f"""
            DELETE FROM `{table_name}`
            WHERE creation < NOW() - INTERVAL {days} DAY
        """)