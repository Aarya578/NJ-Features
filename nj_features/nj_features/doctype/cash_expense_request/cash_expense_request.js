frappe.ui.form.on('Cash Expense Request', {

    refresh: function(frm) {
        console.log("Cash Expense Request JS Loaded");

        if (frm.doc.employee) {
            fetch_budget(frm);
        }

        if (frm.doc.docstatus === 1 && !frm.__alert_shown) {
            frm.__alert_shown = true;
            frappe.show_alert({
                message: __("Expense Posted and Journal Entry created"),
                indicator: "green"
            }, 5);
        }

        setup_action_buttons(frm);
    },

    employee: function(frm) {
        if (!frm.doc.employee) {
            frm.set_value("department", null);
            frm.set_value("cost_center", null);
            frm.set_value("monthly_budget", 0);
            frm.set_value("used_this_month", 0);
            frm.set_value("remaining_budget", 0);
            frm.set_value("budget_exceeded", 0);
            frm.__limit_dialog_shown = null;
            return;
        }

        frappe.call({
            method: "nj_features.nj_features.doctype.cash_expense_request.cash_expense_request.get_employee_department_and_cost_center",
            args: { employee: frm.doc.employee },
            callback: function(r) {
                if (r.message) {
                    frm.set_value("department", r.message.department || null);
                }
            }
        });

        fetch_budget(frm);
    },

    amount: function(frm) {
        if (!frm.doc.employee) return;
        fetch_budget(frm);
    }

});


// ─────────────────────────────────────────────────────────────
//  ACTION BUTTONS
//
//  Employee flow:
//    Draft     → [Submit for Approval]
//    Rejected  → [Resubmit]
//
//  Accounts flow:
//    Submitted → [Submit & Create Journal Entry] + [Reject]
//    Rejected  → [Resubmit]
// ─────────────────────────────────────────────────────────────

function setup_action_buttons(frm) {

    if (frm.is_new()) return;

    const status      = frm.doc.current_status;
    const is_accounts = frappe.user.has_role("Accounts Manager") || frappe.user.has_role("Accounts User");
    const is_employee = frappe.user.has_role("Employee");
    const can_submit  = is_accounts || is_employee;
    const MODULE      = "nj_features.nj_features.doctype.cash_expense_request.cash_expense_request";

    // ── Draft → Submit for Approval (Employee + Accounts) ────
    if (status === "Draft" && can_submit && frm.doc.docstatus === 0) {
        frm.add_custom_button(__("Submit for Approval"), function() {
            frappe.confirm(
                __("Submit this expense request for approval?"),
                function() {
                    frappe.call({
                        method: MODULE + ".submit_request",
                        args: { docname: frm.doc.name },
                        callback: function(r) {
                            if (r.message) {
                                frappe.show_alert({ message: __("Submitted for Approval"), indicator: "blue" }, 4);
                                frm.reload_doc();
                            }
                        }
                    });
                }
            );
        }).addClass("btn-primary");
    }

    // ── Submitted → Submit & Create JE + Reject (Accounts only) ──
    if (status === "Submitted" && is_accounts && frm.doc.docstatus === 0) {

        // Primary action — post and create JE
        frm.add_custom_button(__("Submit & Create Journal Entry"), function() {
            frappe.confirm(
                __("Submit this expense and create the Journal Entry? This cannot be undone."),
                function() {
                    frappe.call({
                        method: MODULE + ".post_request",
                        args: { docname: frm.doc.name },
                        callback: function(r) {
                            if (r.message) {
                                frappe.show_alert({ message: __("Posted. Journal Entry created."), indicator: "green" }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                }
            );
        }).addClass("btn-primary");

        // Reject alongside
        frm.add_custom_button(__("Reject"), function() {
            frappe.prompt(
                { fieldtype: "Small Text", fieldname: "reason", label: "Rejection Reason", reqd: 1 },
                function(values) {
                    frappe.call({
                        method: MODULE + ".reject_request",
                        args: { docname: frm.doc.name, reason: values.reason },
                        callback: function(r) {
                            if (r.message) {
                                frappe.show_alert({ message: __("Expense Rejected"), indicator: "red" }, 4);
                                frm.reload_doc();
                            }
                        }
                    });
                },
                __("Reject Expense"), __("Reject")
            );
        }).addClass("btn-danger");
    }

    // ── Rejected → Resubmit (Employee + Accounts) ────────────
    if (status === "Rejected" && can_submit && frm.doc.docstatus === 0) {
        frm.add_custom_button(__("Resubmit"), function() {
            frappe.confirm(
                __("Resubmit this expense request?"),
                function() {
                    frappe.call({
                        method: MODULE + ".resubmit_request",
                        args: { docname: frm.doc.name },
                        callback: function(r) {
                            if (r.message) {
                                frappe.show_alert({ message: __("Resubmitted for Approval"), indicator: "blue" }, 4);
                                frm.reload_doc();
                            }
                        }
                    });
                }
            );
        }).addClass("btn-primary");
    }
}


// ─────────────────────────────────────────────────────────────
//  FETCH BUDGET
// ─────────────────────────────────────────────────────────────

function fetch_budget(frm) {
    if (!frm.doc.employee) return;

    frappe.call({
        method: "nj_features.nj_features.doctype.cash_expense_request.cash_expense_request.get_employee_budget",
        args: { employee: frm.doc.employee },
        callback: function(r) {
            if (!r.message) return;

            if (r.message.not_found) {
                if (frm.__limit_dialog_shown === frm.doc.employee) return;
                frm.__limit_dialog_shown = frm.doc.employee;

                if (frappe.user.has_role("Accounts Manager") || frappe.user.has_role("Accounts User") || frappe.user.has_role("System Manager")) {
                    frappe.confirm(
                        __("Expense Limit is not set for employee <b>{0}</b>.<br><br>Do you want to create one now?",
                            [frm.doc.employee]),
                        function() {
                            frappe.new_doc("Employee Expense Limit", { employee: frm.doc.employee });
                        },
                        function() {
                            frappe.show_alert({ message: __("Please set an Expense Limit before submitting."), indicator: "orange" }, 5);
                        }
                    );
                } else {
                    frappe.show_alert({
                        message: __("Expense Limit not set for this employee. Please contact the Accounts team."),
                        indicator: "orange"
                    }, 6);
                }
                return;
            }

            if (r.message.inactive) {
                frappe.show_alert({ message: __("Expense Limit for this employee is Inactive. Contact Accounts to activate it."), indicator: "red" }, 6);
                frm.set_value("monthly_budget",   0);
                frm.set_value("used_this_month",  0);
                frm.set_value("remaining_budget", 0);
                frm.set_value("budget_exceeded",  0);
                return;
            }

            let monthly   = r.message.monthly_limit || 0;
            let used      = r.message.used          || 0;
            let remaining = r.message.remaining     || 0;

            frm.set_value("monthly_budget",   monthly);
            frm.set_value("used_this_month",  used);
            frm.set_value("remaining_budget", remaining);

            if (frm.doc.amount && frm.doc.amount > remaining) {
                frm.set_value("budget_exceeded", 1);
                frappe.show_alert({ message: __("Amount exceeds remaining budget of \u20b9{0}", [remaining]), indicator: "red" }, 4);
            } else {
                frm.set_value("budget_exceeded", 0);
            }
        }
    });
}