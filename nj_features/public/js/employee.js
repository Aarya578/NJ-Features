frappe.ui.form.on('Employee', {
    refresh(frm) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        frm.set_df_property('company', 'hidden', 1);
        
        frm.set_query('work_warehouse', function() {
            return { filters: { warehouse_owner: frm.doc.user_id?frm.doc.user_id:frm.doc.prefered_email } };
        });

        frm.set_query('department', function() {
            return { filters: { disabled: 0 } };
        });

        frm.set_query('reports_to', function() {
            return { filters: { status: "Active" } };
        });

        frm.set_query('employee_asset_warehouse', function() {
            return { filters: { warehouse_owner: frm.doc.user_id?frm.doc.user_id:frm.doc.prefered_email, disabled: 0, warehouse_type: "Employee Personal Warehouse" } };
        });
    },

    after_save: function(frm) {
        if (frm.doc.department && frm.doc.role_profile && frm.doc.date_of_joining) {
            frappe.call({
                method: "nj_features.overrides.employee.update_employee_experience",
                args: { docname: frm.doc.name, date_of_joining: frm.doc.date_of_joining },
                callback: function(response) {
                    if (!response.exc) {
                        frappe.call({
                            method: "nj_features.overrides.employee.fetch_and_update_ramp_level",
                            args: {
                                docname: frm.doc.name,
                                department: frm.doc.department,
                                role_profile: frm.doc.role_profile
                            },
                            callback: function(r) {
                                if (!r.exc) {
                                    frappe.msgprint(__('Employee details updated successfully.'));
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                }
            });
        }
        frappe.call({
            method: "nj_features.overrides.employee.update_work_warehouse",
            args:{
                doc: frm.doc
            },
            callback: function(r) {
                console.log("update_work_warehouse", r);
            }
        })
    },

    validate(frm) {
        console.log("Inside validate function =================");
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
                user_id: frm.doc.prefered_email, // Ensure this field exists in your form
                cur_role_profile: frm.doc.role_profile,
                previous_role_profile: frm.doc.previous_role_profile || null,
                ramp_level: frm.doc.ramp_level || null,
                previous_ramp: frm.doc.previous_ramp || null
            }
        });     
    },

    role_profile(frm) {
        if (frm.doc.role_profile) {

            frappe.call({
                method: "nj_features.overrides.employee.get_previous_role_profile",
                args: { docname: frm.doc.name },
                callback(r) {
                    if (r.message) {
                        frm.set_value('previous_role_profile', r.message);
                    }
                }
            });
            
            frappe.call({
                method: "nj_features.overrides.employee.get_ramp_level",
                args: {
                    role_profile: frm.doc.role_profile,
                    // total_days: calculate_total_days(frm.doc.date_of_joining), 
                    total_days: frm.doc.calculated_days
                },
                callback: function (response) {
                    if (response.message) {
                        frm.set_value('ramp_level', response.message); // Update the field in the form
                    }
                }
            });    
        }
    },

    department(frm) {
        if (!frm.doc.department) {
            frm.set_query('role_profile', function() {
                return { filters: { name: "" } };
            });
            frm.set_value('role_profile', '');
            return;
        }
        if (frm.doc.department) {
            frappe.call({
                method: "nj_features.overrides.employee.get_role_profiles",
                args: { department: frm.doc.department },
                callback(response) {
                    let role_profiles = response.message || [];
    
                    frm.set_query('role_profile', function() {
                        return {
                            filters: [['Role Profile', 'name', 'in', role_profiles]]
                        };
                    });
    
                    if (role_profiles.length === 1) {
                        frm.set_value('role_profile', role_profiles[0]);
                    } else {
                        frm.set_value('role_profile', ''); 
                    }
    
                    frm.refresh_field('role_profile');  // Ensure UI updates
                }
            });
        }
    },

    before_save(frm) {
        console.log("Inside before_save function =================");
        frappe.call({
            method: "nj_features.overrides.employee.get_previous_department",
            args: { docname: frm.doc.name },
            callback(r) {
                if (r.message) {
                    frm.set_value('previous_department', r.message);
                }
            }
        });

        if (!frm.doc.department) return;

        frappe.call({
            method: "nj_features.overrides.employee.get_role_profiles",
            args: { department: frm.doc.department },
            callback(response) {
                let role_profiles = response.message || [];

                frm.set_query('role_profile', function() {
                    return {
                        filters: [['Role Profile', 'name', 'in', role_profiles]]
                    };
                });

                if (!role_profiles.includes(frm.doc.role_profile)) {
                    frappe.msgprint({
                        title: __('Invalid Role Profile'),
                        message: __('The role profile <b>{0}</b> is not allowed for the department <b>{1},Please Contact MIS Team</b>.', 
                            [frm.doc.role_profile, frm.doc.department]),
                        indicator: 'red'
                    });
                    frappe.validated = false;
                }
            }
        });
    }        
});
