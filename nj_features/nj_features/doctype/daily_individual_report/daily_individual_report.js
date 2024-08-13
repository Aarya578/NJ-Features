frappe.ui.form.on('Daily Individual Report', {
    onload: function(frm) {
        frm.set_df_property('data_import_report', 'cannot_add_rows', true);
        // frm.set_df_property('work_warehouse_inventory', 'cannot_add_rows', true);
        $('.col-lg-2.layout-side-section').hide();   

        // Fetch and populate Data Import Report
        frappe.call({
            method: 'nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.fetch_data_imports',
            args: {},
            callback: function(r) {
                if (!r.exc) {
                    // Clear existing rows in the child table
                    frm.clear_table('data_import_report');

                    // Populate the child table with the fetched data
                    r.message.forEach(function(row) {
                        frm.add_child('data_import_report', {
                            'data_import': row.name,
                            'data_import_status': row.status
                        });
                    });

                    // Refresh the child table to display the new rows
                    frm.refresh_field('data_import_report');
                }
            }
        });

        // Fetch and populate Work Warehouse Inventory
        frappe.call({
            method: 'nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.get_serial_no_data',
            args: {},
            callback: function(r) {
                if (!r.exc) {
                    // Clear existing rows in the child table
                    frm.clear_table('work_warehouse_inventory');

                    r.message.forEach(function(row) {
                        // Ensure that item_code and serial_no are handled as arrays
                        let item_codes = Array.isArray(row.item_code) ? row.item_code : [row.item_code];
                        let serial_nos = Array.isArray(row.serial_no) ? row.serial_no : [row.serial_no];
            
                        // Join the array elements into a comma-separated string
                        let item_code_str = item_codes.join(', ');
                        let serial_no_str = serial_nos.join(', ');
            
                        // Add the concatenated strings to the child table
                        frm.add_child('work_warehouse_inventory', {
                            'item': item_code_str,
                            'serial_no': serial_no_str
                        });
                    });

                    // Refresh the child table to display the new rows
                    frm.refresh_field('work_warehouse_inventory');
                }
            }
        });
    },
    refresh: function(frm) {
        // Add event listeners to the child table fields
        frm.fields_dict['work_warehouse_inventory'].grid.wrapper.on('change', 'input[data-fieldname="yes"]', function() {
            toggle_checkboxes(this);
        });

        frm.fields_dict['work_warehouse_inventory'].grid.wrapper.on('change', 'input[data-fieldname="no"]', function() {
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
