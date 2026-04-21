
import json
import frappe
from frappe import _
from datetime import datetime, date
from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry


class CustomJournalEntry(JournalEntry):
    def validate(self):
        super().validate()
        # if self.voucher_type == "Journal Entry":
        #     if not self.utr_no:
        #         frappe.throw(_("UTR No is required"))
    def on_submit(self):
        pass
        # self.duplicate_jv_validation()


@frappe.whitelist()
def duplicate_jv_validation(doc , method = None):
    # print("doc==============inside teh function====",doc)
    ref_no = doc.cheque_no or doc.check_no  # handle both fields if needed
    # print("ref_no==================",ref_no)

    if not ref_no:
        return

    # Extract core reference (last part after '-')
    core_ref = ref_no.split("-")[-1].strip()

    # Check duplicate in submitted JE
    duplicate = frappe.db.sql("""
        SELECT name, cheque_no
        FROM `tabJournal Entry`
        WHERE docstatus = 1
        AND name != %s
        AND (
            cheque_no LIKE %s
            OR cheque_no LIKE %s
        )
    """, (
        doc.name,
        f"%{core_ref}%",
        f"%{ref_no}%"
    ), as_dict=1)

    if duplicate:
        frappe.throw(
            _("Cheque/Reference No '{0}' already used in Journal Entry {1}")
            .format(core_ref, duplicate[0].name)
        )


