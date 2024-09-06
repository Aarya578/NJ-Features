frappe.ui.form.on('Daily Individual Report', {
    onload: function (frm) {
        if(!frm.doc.warehouse && frm.doc.docstatus == 0) {
            frappe.db.get_value('Employee', { 'user_id': frappe.session.user_email }, 'work_warehouse', function(r) {
                if (r.work_warehouse) {
                    frm.set_value('warehouse', r.work_warehouse)
                }
                else{
                    frappe.msgprint(__('Please set your Work Warehouse in Employee.'))
                }
            });
        }
        if (frm.is_new()) {
            if (frm.is_new()) {
                frm.set_df_property('data_import_report', 'cannot_add_rows', true);
                $('.col-lg-2.layout-side-section').hide();

                frappe.call({
                    method: 'nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.fetch_data_imports',
                    args: {},
                    callback: function (r) {
                        if (!r.exc) {
                            frm.clear_table('data_import_report');

                            r.message.forEach(function (row) {
                                frm.add_child('data_import_report', {
                                    'data_import': row.name,
                                    'data_import_status': row.status
                                });
                            });

                            frm.refresh_field('data_import_report');
                        }
                    }
                });

                frappe.call({
                    method: 'nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.get_serial_no_data',
                    args: {},
                    callback: function (r) {
                        if (!r.exc) {
                            frm.clear_table('work_warehouse_inventory');

                            r.message.forEach(function (row) {
                                // Ensure that item_code and serial_no are handled as arrays
                                let item_codes = Array.isArray(row.item_code) ? row.item_code : [row.item_code];
                                let serial_nos = Array.isArray(row.serial_no) ? row.serial_no : [row.serial_no];

                                let item_code_str = item_codes.join(', ');
                                let serial_no_str = serial_nos.join(', ');

                                frm.add_child('work_warehouse_inventory', {
                                    'item_code': item_code_str,
                                    'serial_no': serial_no_str,
                                    'user_activitty': 'Log In'
                                });
                            });

                            frm.refresh_field('work_warehouse_inventory');
                        }
                    }
                });
            }
        }
    },
    refresh: function (frm) {
        frm.fields_dict['work_warehouse_inventory'].grid.wrapper.on('change', 'input[data-fieldname="yes"]', function () {
            toggle_checkboxes(this);
        });

        frm.fields_dict['work_warehouse_inventory'].grid.wrapper.on('change', 'input[data-fieldname="no"]', function () {
            toggle_checkboxes(this);
        });
    }
});

function toggle_checkboxes(field) {
    let row = $(field).closest('.grid-row');
    let yes_field = row.find('input[data-fieldname="yes"]');
    let no_field = row.find('input[data-fieldname="no"]');

    if ($(field).is(':checked')) {
        if (field.dataset.fieldname === 'yes') {
            no_field.prop('checked', false).change();
        } else {
            yes_field.prop('checked', false).change();
        }
    }
}
