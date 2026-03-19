frappe.ui.form.on('Cash Expense Request', {

    refresh: function(frm) {

        console.log("Cash Expense Request JS Loaded");

        if (frm.doc.employee) {
            fetch_budget(frm);
        }

        if (frm.doc.docstatus === 1 && !frm.__alert_shown) {

            frm.__alert_shown = true;

            frappe.show_alert({
                message: __("Expense Posted and Budget Updated"),
                indicator: "green"
            }, 5);
        }
    },


    employee: function(frm) {

        if (!frm.doc.employee) {
            frm.set_value("department", null);
            frm.set_value("cost_center", null);
            return;
        }

        frappe.call({
            method: "nj_features.nj_features.doctype.cash_expense_request.cash_expense_request.get_employee_department_and_cost_center",
            args: {
                employee: frm.doc.employee
            },
            callback: function(r) {
                if (r.message) {
                    frm.set_value("department", r.message.department || null);
                    frm.set_value("cost_center", r.message.cost_center || null);
                }
            }
        });

        fetch_budget(frm);
    },


    amount: function(frm) {

        if (!frm.doc.employee) {
            return;
        }

        fetch_budget(frm);
    },


    on_submit: function(frm) {

        frappe.msgprint({
            title: __("Success"),
            message: __("Expense submitted successfully and budget updated."),
            indicator: "green"
        });

        setTimeout(() => {
            frm.reload_doc();
        }, 800);
    }

});


function fetch_budget(frm){

    if(!frm.doc.employee){
        return;
    }

    frappe.call({

        method: "nj_features.nj_features.doctype.cash_expense_request.cash_expense_request.get_employee_budget",

        args: {
            employee: frm.doc.employee
        },

        callback: function(r){

            if(!r.message){
                return;
            }

            let monthly = r.message.monthly_limit || 0;
            let used = r.message.used || 0;
            let remaining = r.message.remaining || 0;

            frm.set_value("monthly_budget", monthly);
            frm.set_value("used_this_month", used);
            frm.set_value("remaining_budget", remaining);

            if(frm.doc.amount && frm.doc.amount > remaining){
                frm.set_value("budget_exceeded", 1);
            }
            else{
                frm.set_value("budget_exceeded", 0);
            }

        }

    });

}