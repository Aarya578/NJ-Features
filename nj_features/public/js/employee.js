frappe.ui.form.on('Employee', {
    refresh(frm) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        frm.set_df_property('company', 'hidden', 1);
        
    },
    validate(frm) {
        frappe.validated = false;
        frappe.call({
            method: 'nj_features.overrides.employee.create_user_and_warehouse',
            args: {'self': frm.doc},
            callback: function(r) {
                console.log("r",r);
                
                if (r && r._server_messages) {
                    frappe.throw(r._server_messages);
                } else if (r && r.message) {
                    frappe.validated = true;
                    if (r.message.status) {
                        console.log("status",r.message.status);
                    } else {
                        Object.keys(r.message).forEach(row => {
                            frm.set_value(row, r.message[row]);
                            frm.refresh_field(row);
                        });
                    }
                }
            }
        });
    }
});