frappe.ui.form.on('Employee', {
    refresh(frm) {
        // Hide sidebar and specific fields
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        frm.set_df_property('company', 'hidden', 1);
    },
    validate(frm) {
        // Ensure validations run only when required
        frappe.validated = false;

        // Call to create user and warehouse
        frappe.call({
            method: 'nj_features.overrides.employee.create_user_and_warehouse',
            args: { 'self': frm.doc },
            callback: function(r) {
                if (r && r._server_messages) {
                    frappe.throw(r._server_messages);
                } else if (r && r.message) {
                    frappe.validated = true;
                    if (r.message.status) {
                        console.log("status", r.message.status);
                    } else {
                        Object.keys(r.message).forEach(row => {
                            frm.set_value(row, r.message[row]);
                            frm.refresh_field(row);
                        });
                    }
                }
            }
        });

        // Log role profile changes
        frappe.call({
            method: "nj_features.overrides.employee.role_profile_change_log",
            args: {
                user_id: frm.doc.user_id,
                cur_role_profile: frm.doc.role_profile,
                previous_role_profile: frm.doc.previous_role_profile
            },
            callback(r) {
                console.log('Role Profile Change Log:', r.message);
            }
        });
    },
    role_profile(frm) {
        // Fetch and set the previous role profile on role profile change
        frappe.call({
            method: "nj_features.overrides.employee.get_previous_role_profile",
            args: {
                docname: frm.doc.name
            },
            callback(r) {
                if (r.message) {
                    frm.set_value('previous_role_profile', r.message);
                }
            }
        });
    }
});
