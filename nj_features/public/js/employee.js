frappe.ui.form.on('Employee', {
    refresh(frm) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        frm.set_df_property('company', 'hidden', 1);
    },
    validate(frm) {
        frappe.call({
            method: 'nj_features.nj_features.doctype.employee.create_user_and_warehouse',
            args: {'self': frm.doc},
            callback: function(r) {
                if (r.exception) {
                    console.log("exception");
                    var error_message = "Server Error: " + r.exception;
                    frm.comment_box.set_input(error_message);
                    frm.comment_box.submit();
                    frappe.validated = false;
                } 
                else if (r.message['Error while creating User']) {
                    console.log("else if in error",r.message);
                    var error_message = "Error: " + r.message['Error while creating User'];
                    frm.comment_box.set_input(error_message);
                    frm.comment_box.submit();
                    frappe.validated = false;
                } 
                else {
                    console.log("else part", r);
                    frm.set_value('user_id', r.message.user);
                    frm.set_value('employee_asset_warehouse', r.message.employee_asset_warehouse);
                    if (!frm.doc.work_warehouse) {
                        frm.set_value('work_warehouse', r.message.work_warehouse);
                    }
                    frm.refresh_field('user_id');
                    frm.refresh_field('employee_asset_warehouse');
                    frm.refresh_field('work_warehouse');
                }
                frm.refresh();

            }
        })
        return frappe.validated;
    }
})