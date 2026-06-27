import frappe
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

ACCOUNTS_ROLES = {"System Manager", "Accounts Manager", "Accounts User"}
SUBMIT_ROLES   = {"System Manager", "Accounts Manager", "Accounts User", "Employee"}


class CashExpenseRequest(Document):

    def before_insert(self):
        self.current_status = "Draft"

    def validate(self):
        self.fetch_department()
        self.validate_receipt()
        if self.employee:
            user_roles = set(frappe.get_roles(frappe.session.user))
            if not ACCOUNTS_ROLES.intersection(user_roles):
                self.check_employee_limit()

    def fetch_department(self):
        if self.employee:
            department = frappe.db.get_value("Employee", self.employee, "department")
            if department:
                self.department = department

    def validate_receipt(self):
        if self.amount and self.amount > 1000:
            if not self.receipt_upload and not self.multiple_receipts:
                frappe.throw("Receipt is mandatory for expenses above Rs.1000")

    def check_employee_limit(self):
        limit_doc = frappe.db.get_value(
            "Employee Expense Limit",
            {"employee": self.employee},
            ["name", "monthly_limit", "current_month_expense", "last_reset_date", "active"],
            as_dict=True
        )

        if not limit_doc:
            frappe.throw(
                f"Expense Limit not configured for employee <b>{self.employee}</b>. "
                "Please set it up before submitting."
            )

        if not limit_doc.get("active"):
            frappe.throw(
                f"Expense Limit for employee <b>{self.employee}</b> is Inactive. "
                "Please activate it before submitting."
            )

        _auto_reset_if_new_month(limit_doc)

        used          = limit_doc.get("current_month_expense") or 0
        monthly_limit = limit_doc.get("monthly_limit") or 0
        remaining     = monthly_limit - used

        if self.amount and self.amount > remaining:
            frappe.throw(
                f"Expense of Rs.{self.amount} exceeds monthly limit. "
                f"Remaining balance: Rs.{remaining}"
            )

    # =============================
    # ON SUBMIT (docstatus → 1)
    # Triggered by post_request()
    # =============================

    def on_submit(self):
        if not self.employee:
            return

        limit_name = frappe.db.get_value(
            "Employee Expense Limit",
            {"employee": self.employee}
        )

        if not limit_name:
            frappe.throw("Employee Expense Limit record missing")

        limit_doc = frappe.get_doc("Employee Expense Limit", limit_name)
        _auto_reset_if_new_month(limit_doc)
        limit_doc.current_month_expense = (limit_doc.current_month_expense or 0) + (self.amount or 0)
        limit_doc.save(ignore_permissions=True)

        self.create_journal_entry()
        self.db_set("current_status", "Posted")

    # =============================
    # CREATE JOURNAL ENTRY
    # =============================

    def create_journal_entry(self):
        if self.accounts_entry:
            return

        if not self.expense_category:
            frappe.throw("Expense Category is required")

        category = frappe.get_doc("Expense Category", self.expense_category)

        if not category.expense_account:
            frappe.throw("Expense Account not defined in Expense Category")

        if frappe.db.get_value("Account", category.expense_account, "is_group"):
            frappe.throw(
                f"{category.expense_account} is a Group Account. Please select a Ledger Account."
            )

        # Fetch company — try session default first, then from Employee record
        company = frappe.defaults.get_user_default("Company")
        if not company:
            company = frappe.db.get_value("Employee", self.employee, "company")
        if not company:
            frappe.throw("Default Company is not set. Please set a Default Company for your user or on the Employee record.")

        # Credit account: use the field on this document (auto-filled from Employee or manually set)
        credit_account = self.expense_credit_account

        if not credit_account:
            frappe.throw(
                "Expense Credit Account is not set. "
                "Please set it on this Cash Expense Request before posting.",
                title="Credit Account Missing"
            )

        if frappe.db.get_value("Account", credit_account, "is_group"):
            frappe.throw(
                f"The Expense Credit Account <b>{credit_account}</b> is a Group Account. "
                "Please select a Ledger (non-group) Account."
            )

        je = frappe.get_doc({
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "posting_date": nowdate(),
            "company": company,
            "accounts": [
                {
                    "account": category.expense_account,
                    "debit_in_account_currency": self.amount,
                    "cost_center": self.cost_center
                },
                {
                    "account": credit_account,
                    "credit_in_account_currency": self.amount
                }
            ]
        })

        je.insert(ignore_permissions=True)
        je.submit()
        self.db_set("accounts_entry", je.name)


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _auto_reset_if_new_month(limit_doc):
    today = getdate(nowdate())

    if isinstance(limit_doc, dict):
        last_reset_date = limit_doc.get("last_reset_date")
    else:
        last_reset_date = getattr(limit_doc, "last_reset_date", None)

    if last_reset_date:
        lr = getdate(last_reset_date)
        if lr.year == today.year and lr.month == today.month:
            return

    if isinstance(limit_doc, dict):
        doc = frappe.get_doc("Employee Expense Limit", limit_doc["name"])
    else:
        doc = limit_doc

    doc.current_month_expense = 0
    doc.last_reset_date       = nowdate()
    doc.save(ignore_permissions=True)

    if isinstance(limit_doc, dict):
        limit_doc["current_month_expense"] = 0
        limit_doc["last_reset_date"]       = nowdate()


def _check_accounts_role():
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not ACCOUNTS_ROLES.intersection(user_roles):
        frappe.throw("Only Accounts team can perform this action.", frappe.PermissionError)


# ============================================================
# API — FETCH EMPLOYEE DEPARTMENT
# ============================================================

@frappe.whitelist()
def get_employee_department_and_cost_center(employee):
    if not employee:
        return {}
    department = frappe.db.get_value("Employee", employee, "department")
    return {"department": department or None, "cost_center": None}


# ============================================================
# API — FETCH LIVE BUDGET FOR UI
# ============================================================

@frappe.whitelist()
def get_employee_budget(employee):
    if not employee:
        return {}

    limit = frappe.db.get_value(
        "Employee Expense Limit",
        {"employee": employee},
        ["name", "monthly_limit", "current_month_expense", "last_reset_date", "active"],
        as_dict=True
    )

    if not limit:
        return {"not_found": True}

    if not limit.get("active"):
        return {"inactive": True}

    _auto_reset_if_new_month(limit)

    monthly   = limit.get("monthly_limit") or 0
    used      = limit.get("current_month_expense") or 0
    remaining = monthly - used

    return {"monthly_limit": monthly, "used": used, "remaining": remaining}


# ============================================================
# API — FETCH EMPLOYEE CREDIT ACCOUNT FOR UI
# ============================================================

@frappe.whitelist()
def get_employee_credit_account(employee):
    if not employee:
        return {}
    account = frappe.db.get_value("Employee", employee, "expense_credit_account")
    return {"credit_account": account or None}


# ============================================================
# ACTION — SUBMIT (Draft → Submitted)
# Employee + Accounts
# ============================================================

@frappe.whitelist()
def submit_request(docname):
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not SUBMIT_ROLES.intersection(user_roles):
        frappe.throw("You do not have permission to submit this request.", frappe.PermissionError)

    doc = frappe.get_doc("Cash Expense Request", docname)

    if doc.current_status != "Draft":
        frappe.throw(f"Cannot submit. Current status is {doc.current_status}.")

    doc.current_status = "Submitted"
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return "Submitted"


# ============================================================
# ACTION — REJECT (Submitted → Rejected)
# Accounts only
# ============================================================

@frappe.whitelist()
def reject_request(docname, reason=""):
    _check_accounts_role()

    doc = frappe.get_doc("Cash Expense Request", docname)

    if doc.current_status != "Submitted":
        frappe.throw(f"Cannot reject. Current status is {doc.current_status}.")

    doc.current_status = "Rejected"
    doc.save(ignore_permissions=True)

    if reason:
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Comment",
            "reference_doctype": "Cash Expense Request",
            "reference_name": docname,
            "content": f"<b>Rejected:</b> {reason}"
        }).insert(ignore_permissions=True)

    frappe.db.commit()
    return "Rejected"


# ============================================================
# ACTION — POST (Submitted → Posted)
# Creates JE via on_submit. Accounts only.
# Pre-checks expense_credit_account on the doc itself
# (auto-filled from Employee or manually set on the form).
# ============================================================

@frappe.whitelist()
def post_request(docname):
    _check_accounts_role()

    doc = frappe.get_doc("Cash Expense Request", docname)

    if doc.current_status != "Submitted":
        frappe.throw(f"Cannot post. Current status is {doc.current_status}.")

    # Pre-check: expense_credit_account must be set on the document itself.
    # Return structured response so JS shows a targeted message instead of raw throw.
    if not doc.expense_credit_account:
        return {"missing_credit_account": True}

    doc.approved_by   = frappe.session.user
    doc.approval_date = nowdate()
    doc.flags.ignore_permissions = True
    doc.submit()
    frappe.db.commit()

    return "Posted"


# ============================================================
# ACTION — RESUBMIT (Rejected → Submitted)
# Employee + Accounts
# ============================================================

@frappe.whitelist()
def resubmit_request(docname):
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not SUBMIT_ROLES.intersection(user_roles):
        frappe.throw("You do not have permission to resubmit.", frappe.PermissionError)

    doc = frappe.get_doc("Cash Expense Request", docname)

    if doc.current_status != "Rejected":
        frappe.throw(f"Cannot resubmit. Current status is {doc.current_status}.")

    doc.current_status = "Submitted"
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return "Submitted"


# ============================================================
# MANUAL / SCHEDULER BULK RESET
# ============================================================

@frappe.whitelist()
def reset_employee_expenses():
    today = nowdate()
    employees = frappe.get_all("Employee Expense Limit", fields=["name"])
    for emp in employees:
        doc = frappe.get_doc("Employee Expense Limit", emp.name)
        doc.current_month_expense = 0
        doc.last_reset_date       = today
        doc.save(ignore_permissions=True)
    return f"All employee expense usage reset on {today}"