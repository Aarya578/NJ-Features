frappe.ui.form.on('Employee', {
    refresh(frm) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        frm.set_df_property('company', 'hidden', 1);
    },
    before_save(frm) {
        console.log("frm", frm.doc);
        frappe.call({
            method: 'nj_features.nj_features.doctype.employee.create_user_and_warehouse',
            args: {'self': frm.doc},
            callback: function(r) {
                console.log("13 response");
                if (r.exception) {
                    console.log("exception");
                    var error_message = "Server Error: " + r.exception;
                    frm.comment_box.set_input(error_message);
                    frm.comment_box.submit();
                } 
                else if (r.message['Error while creating User']) {
                    console.log("else if in error",r.message);
                    var error_message = "Error: " + r.message['Error while creating User'];
                    frm.comment_box.set_input(error_message);
                    frm.comment_box.submit();
                } 
                else {
                    console.log('employee',r.message,"r.message.user_id");
                    frm.set_value('user_id', r.message.user_email);
                    frm.set_value('employee_asset_warehouse', r.message.emp_ware);
                    frm.set_value('work_warehouse', r.message.work_ware);
                    frm.refresh_field('user_id');
                    frm.refresh_field('employee_asset_warehouse');
                    frm.refresh_field('user_work_warehouseid');
                }
                // frm.refresh();

            }
        })
    }
})