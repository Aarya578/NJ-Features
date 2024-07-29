frappe.ui.form.on('Employee', {
    refresh(frm) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        frm.set_df_property('company', 'hidden', 1);
    },
    before_save(frm) {

        frappe.call({
            method: 'nj_features.nj_features.doctype.employee.create_user_and_warehouse',
            args: {'self': frm.doc},
            callback: function(r) {
                if (r.message.error) {

                    var error_message = "Server Error: " + r.message.error;
                    frm.comment_box.set_input(error_message);
                    frm.comment_box.submit();
                    frappe.validated = false;
                    return

                } else if (r.message.work_warehouse) {
                    if (!frm.doc.user_id) {
                        frm.set_value('user_id', r.message.work_warehouse);
                        frm.refresh_field('user_id');
                    }
                
                    if (!frm.doc.work_warehouse) {
                        frm.set_value('work_warehouse', r.message.work_warehouse);
                        frm.refresh_field('work_warehouse');
                    }
                
                    frm.set_value('employee_asset_warehouse', r.message.employee_asset_warehouse);
                    frm.refresh_field('employee_asset_warehouse');
                    frappe.validated = true;

                } else if (r.message.user_status){
                    frappe.validated = true;
                } else {
                    frappe.validated = false;
                    return false;
                }
            }
        });
    }
});