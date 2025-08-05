import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	cint,
	comma_and,
	flt,
	formatdate,
	getdate,
	time_diff_in_seconds,
	to_timedelta,
)
from erpnext.manufacturing.doctype.workstation.workstation import Workstation

class CustomeWorkstation(Workstation):
    def validate(self):
        self.validate_workstation()