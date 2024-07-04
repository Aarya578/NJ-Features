import frappe
import requests

@frappe.whitelist(allow_guest=True)
def current_date_time():
    try:
        # Fetch current date and time from World Time API for IST (Asia/Kolkata)
        response = requests.get("http://worldtimeapi.org/api/timezone/Asia/Kolkata")
        if response.status_code == 200:
            data = response.json()
            current_date = data['datetime'][:10]  # Extract date part
            current_time = data['datetime'][11:19]  

            return {
                "current_date": current_date,
                "current_time": current_time
            }
        else:
            return {
                "error": "Failed to fetch date and time from external source"
            }
    except Exception as e:
        return {
            "error": str(e)
        }
