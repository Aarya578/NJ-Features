import frappe
from frappe.model.document import Document


class CashExpenseRequest(Document):

    # =============================
    # VALIDATE BEFORE SAVE
    # =============================

    def validate(self):

        self.fetch_department()
        self.validate_receipt()
        self.check_employee_limit()


    # =============================
    # AUTO FETCH DEPARTMENT
    # =============================

    def fetch_department(self):

        if self.employee:

            department = frappe.db.get_value(
                "Employee",
                self.employee,
                "department"
            )

            if department:
                self.department = department


    # =============================
    # RECEIPT VALIDATION
    # =============================

    def validate_receipt(self):

        if self.amount and self.amount > 1000:

            if not self.receipt_upload and not self.multiple_receipts:
                frappe.throw("Receipt is mandatory for expenses above ₹1000")


    # =============================
    # BUDGET VALIDATION
    # =============================

    def check_employee_limit(self):

        if not self.employee:
            frappe.throw("Employee is required")

        limit_doc = frappe.db.get_value(
            "Employee Expense Limit",
            {"employee": self.employee},
            ["name", "monthly_limit", "current_month_expense"],
            as_dict=True
        )

        if not limit_doc:
            frappe.throw("Expense limit not set for this employee")

        used = limit_doc.current_month_expense or 0
        monthly_limit = limit_doc.monthly_limit or 0

        remaining = monthly_limit - used

        if self.amount and self.amount > remaining:

            frappe.throw(
                f"Expense exceeds monthly limit. Remaining balance: ₹{remaining}"
            )


    # =============================
    # UPDATE LIMIT AFTER SUBMIT
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

        limit_doc = frappe.get_doc(
            "Employee Expense Limit",
            limit_name
        )

        current_usage = limit_doc.current_month_expense or 0

        limit_doc.current_month_expense = current_usage + (self.amount or 0)

        limit_doc.save(ignore_permissions=True)

        # CREATE ACCOUNTING ENTRY
        self.create_journal_entry()

        frappe.db.commit()


    # =============================
    # CREATE JOURNAL ENTRY
    # =============================

    def create_journal_entry(self):

        # prevent duplicate entries
        if self.accounts_entry:
            return

        if not self.expense_category:
            frappe.throw("Expense Category is required to create Journal Entry")

        category = frappe.get_doc(
            "Expense Category",
            self.expense_category
        )

        if not category.expense_account:
            frappe.throw("Expense Account not defined in Expense Category")

        company = frappe.defaults.get_user_default("Company")

        # Decide credit account
        if self.mode == "Cash":
            credit_account = "Cash - NJ"
        else:
            credit_account = "Employee Payable - NJ"

        je = frappe.get_doc({
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "posting_date": frappe.utils.today(),
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

        # link JE back to request
        self.accounts_entry = je.name



# ======================================
# API → FETCH LIVE BUDGET FOR UI
# ======================================

@frappe.whitelist()
def get_employee_budget(employee):

    if not employee:
        return {}

    limit = frappe.db.get_value(
        "Employee Expense Limit",
        {"employee": employee},
        ["monthly_limit", "current_month_expense"],
        as_dict=True
    )

    if not limit:
        return {}

    monthly = limit.monthly_limit or 0
    used = limit.current_month_expense or 0

    remaining = monthly - used

    return {
        "monthly_limit": monthly,
        "used": used,
        "remaining": remaining
    }


# ======================================
# MONTHLY RESET FUNCTION
# ======================================

@frappe.whitelist()
def reset_employee_expenses():

    employees = frappe.get_all(
        "Employee Expense Limit",
        fields=["name"]
    )

    for emp in employees:

        doc = frappe.get_doc(
            "Employee Expense Limit",
            emp.name
        )

        doc.current_month_expense = 0
        doc.save(ignore_permissions=True)

    frappe.db.commit()

    return "All employee expense usage reset successfully"