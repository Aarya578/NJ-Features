frappe.ui.form.on('Employee Expense Limit', {

    refresh: function(frm) {

        // Show a usage summary banner on saved records
        if (!frm.is_new() && frm.doc.monthly_limit) {
            let used      = frm.doc.current_month_expense || 0;
            let monthly   = frm.doc.monthly_limit || 0;
            let remaining = monthly - used;
            let pct       = monthly > 0 ? Math.round((used / monthly) * 100) : 0;
            let color     = pct >= 90 ? "red" : pct >= 70 ? "orange" : "green";

            frm.dashboard.add_comment(
                `<b>This Month:</b> &nbsp;
                 Used <b>&#8377;${used.toLocaleString("en-IN")}</b> of
                 <b>&#8377;${monthly.toLocaleString("en-IN")}</b> &nbsp;|&nbsp;
                 Remaining <span style="color:${color}"><b>&#8377;${remaining.toLocaleString("en-IN")}</b></span>
                 &nbsp;(${pct}% used)`,
                color, true
            );
        }

        // Quick Reset button for Accounts Manager / System Manager
        if (!frm.is_new() && frappe.user.has_role(["Accounts Manager", "System Manager"])) {
            frm.add_custom_button(__("Reset This Month"), function() {
                frappe.confirm(
                    __("Reset <b>{0}</b>'s current month expense to zero?", [frm.doc.employee]),
                    function() {
                        frm.set_value("current_month_expense", 0);
                        frm.set_value("last_reset_date", frappe.datetime.get_today());
                        frm.save().then(() => {
                            frappe.show_alert({ message: __("Reset successful"), indicator: "green" }, 4);
                        });
                    }
                );
            }, __("Actions"));
        }
    },

    employee: function(frm) {
        if (!frm.doc.employee) return;

        // Auto-fill cost center from employee's department if blank
        frappe.db.get_value("Employee", frm.doc.employee, "department", function(r) {
            if (r && r.department && !frm.doc.cost_center) {
                frappe.db.get_value("Department", r.department, "payroll_cost_center", function(d) {
                    if (d && d.payroll_cost_center) {
                        frm.set_value("cost_center", d.payroll_cost_center);
                    }
                });
            }
        });
    }

});