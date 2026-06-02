# Copyright (c) 2024, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import frappe
from datetime import datetime
import pytz

@frappe.whitelist(allow_guest=True)
def current_date_time():
    try:
        timezone = pytz.timezone("Asia/Kolkata")
        now = datetime.now(timezone)
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M:%S")

        return {
            "current_date": current_date,
            "current_time": current_time
        }
    
    except Exception as e:
        return { "error": str(e) }