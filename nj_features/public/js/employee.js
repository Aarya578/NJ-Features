frappe.ui.form.on('Employee', {
    refresh(frm) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        frm.set_df_property('company', 'hidden', 1);
    },
    before_save(frm) {
        // Prevent form submission initially
        frappe.validated = false;

        // Perform server-side call
        frappe.call({
            method: 'nj_features.nj_features.doctype.employee.create_user_and_warehouse',
            args: {'self': frm.doc},
            callback: function(r) {
                // if (!r.message.work_warehouse){
                //     frappe.msgprint(__("Please create Department 's Employee Work Warehouse Group i.e: INW-Work-Warehouse - NJ"));
                // }
                if (r.message.error) {
                    // Handle server error
                    console.log("Server Error:", r.message.error);
                    var error_message = "Server Error: " + r.message.error;
                    frm.comment_box.set_input(error_message);
                    frm.comment_box.submit();
                    frappe.validated = false;
                } else if (r.message['Error while creating User']) {
                    // Handle user creation error
                    console.log("Error while creating User:", r.message['Error while creating User']);
                    var error_message = "Error: " + r.message['Error while creating User'];
                    frm.comment_box.set_input(error_message);
                    frm.comment_box.submit();
                    frappe.validated = false;
                } else if (r.message.user ) {
                    // Handle successful response
                    console.log("Success:", r);
                    frm.set_value('user_id', r.message.user);
                    frm.set_value('employee_asset_warehouse', r.message.employee_asset_warehouse);
                    if (!frm.doc.work_warehouse) {
                        frm.set_value('work_warehouse', r.message.work_warehouse);
                    }
                    frm.refresh_field('user_id');
                    frm.refresh_field('employee_asset_warehouse');
                    frm.refresh_field('work_warehouse');
                    // Allow form to save
                    frappe.validated = true;
                }else if (r.message.user_status){
                    console.log("User status is ",r.message);
                    frappe.validated = true;
                }
                 else {
                    console.log("Unexpected response:", r);
                    frappe.validated = false;
                }
            }
        });

        // Prevent form submission initially
        return false;
    }
});
