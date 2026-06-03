import frappe
from frappe.model.document import Document
from frappe.utils import nowdate

# Roles that are allowed to create / edit / delete this doctype
ACCOUNTS_ROLES = {"System Manager", "Accounts Manager", "Accounts User"}


class EmployeeExpenseLimit(Document):

    def before_insert(self):
        self._check_accounts_role()
        if not self.last_reset_date:
            self.last_reset_date = nowdate()

    def validate(self):
        self._check_accounts_role()
        self.validate_duplicate()
        self.validate_limit()

    def on_trash(self):
        self._check_accounts_role()

    # ─────────────────────────────────────────────
    # ROLE GUARD
    # ─────────────────────────────────────────────

    def _check_accounts_role(self):
        """
        Hard server-side guard. Throws even if someone bypasses
        the DocType permission table (e.g. via API or console).
        System Manager is always allowed through.
        """
        user_roles = set(frappe.get_roles(frappe.session.user))
        if not ACCOUNTS_ROLES.intersection(user_roles):
            frappe.throw(
                "Only the Accounts team can create or modify Employee Expense Limits.",
                frappe.PermissionError
            )

    # ─────────────────────────────────────────────
    # DUPLICATE GUARD
    # ─────────────────────────────────────────────

    def validate_duplicate(self):
        existing = frappe.db.get_value(
            "Employee Expense Limit",
            {
                "employee": self.employee,
                "name": ["!=", self.name or ""],
                "active": 1
            },
            "name"
        )
        if existing:
            frappe.throw(
                f"An active Expense Limit already exists for employee "
                f"<b>{self.employee}</b>: "
                f"<a href='/app/employee-expense-limit/{existing}'>{existing}</a>"
            )

    # ─────────────────────────────────────────────
    # LIMIT VALUE GUARD
    # ─────────────────────────────────────────────

    def validate_limit(self):
        if self.monthly_limit and self.monthly_limit <= 0:
            frappe.throw("Monthly Limit must be greater than zero")