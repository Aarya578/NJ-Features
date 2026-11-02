// Copyright (c) 2026, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Model Change', {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            frm.set_df_property('add', 'hidden', 1);
            frm.set_df_property('serial_no', 'read_only', 1);
            frm.set_df_property('model', 'read_only', 1);
        }

        // Prevent direct row addition inside grid; force using Serial No + Add button
        frm.set_df_property('current_sn_model', 'cannot_add_rows', frm.doc.docstatus !== 0);
        frm.set_df_property('updated_sn_model', 'cannot_add_rows', true);

        // Filter Serial No field to active serial numbers
        frm.set_query('serial_no', function() {
            return {
                filters: {
                    status: 'Active'
                }
            };
        });
    },

    model: function(frm) {
        if (!frm.doc.model) return;
        if (frm.doc.current_sn_model && frm.doc.current_sn_model.length > 0) {
            let existing_model = frm.doc.current_sn_model[0].model;
            if (frm.doc.model === existing_model) {
                frm.set_value('model', '');
                frappe.msgprint({
                    title: __('Invalid Model'),
                    indicator: 'red',
                    message: __('New Model cannot be the same as current Model <b>{0}</b>.', [existing_model])
                });
            }
        }
    },

    add: function(frm) {
        let serial_no = (frm.doc.serial_no || '').trim();
        if (!serial_no) {
            frappe.msgprint(__('Please select a Serial No first.'));
            return;
        }

        // Check duplicate in current_sn_model
        let is_duplicate = (frm.doc.current_sn_model || []).some(function(row) {
            return (row.serial_no || '').trim().toLowerCase() === serial_no.toLowerCase();
        });

        if (is_duplicate) {
            frappe.msgprint({
                title: __('Duplicate Serial No'),
                indicator: 'orange',
                message: __('Serial No <b>{0}</b> is already added to the table.', [serial_no])
            });
            return;
        }

        frappe.call({
            method: 'nj_features.nj_features.doctype.model_change.model_change.get_serial_no_details',
            args: {
                serial_no: serial_no
            },
            freeze: true,
            freeze_message: __('Validating Serial No...'),
            callback: function(r) {
                if (!r.message) return;

                let sn_data = r.message;
                let current_model = sn_data.model;

                if (!current_model) {
                    frappe.msgprint({
                        title: __('Model Missing'),
                        indicator: 'red',
                        message: __('Model is not set for Serial No <b>{0}</b>. Please check Serial No or contact NPD Team.', [serial_no])
                    });
                    return;
                }

                // Check model consistency across current_sn_model
                if (frm.doc.current_sn_model && frm.doc.current_sn_model.length > 0) {
                    let expected_model = frm.doc.current_sn_model[0].model;
                    if (current_model !== expected_model) {
                        frappe.msgprint({
                            title: __('Model Mismatch'),
                            indicator: 'red',
                            message: __('Please select same model serial no. Existing model is <b>{0}</b>, but selected Serial No <b>{1}</b> has model <b>{2}</b>.', [
                                expected_model,
                                serial_no,
                                current_model
                            ])
                        });
                        return;
                    }
                }

                // Check if target model was already selected and is same as current model
                if (frm.doc.model && frm.doc.model === current_model) {
                    frappe.msgprint({
                        title: __('Model Warning'),
                        indicator: 'orange',
                        message: __('Selected Serial No has model <b>{0}</b> which is same as the target Model in header. Please verify.', [current_model])
                    });
                }

                let row = frm.add_child('current_sn_model', {
                    serial_no: serial_no,
                    model: current_model
                });
                frm.refresh_field('current_sn_model');
                frm.set_value('serial_no', '');
            }
        });
    },

    validate: function(frm) {
        if (!frm.doc.current_sn_model || frm.doc.current_sn_model.length === 0) {
            frappe.throw(__('Please add at least one Serial No to the Current SN Model table.'));
        }

        if (!frm.doc.model) {
            frappe.throw(__('Please select the Model.'));
        }

        let existing_model = frm.doc.current_sn_model[0].model;
        if (frm.doc.model === existing_model) {
            frappe.throw(__('New Model cannot be the same as current Model <b>{0}</b>.', [existing_model]));
        }
    }
});
