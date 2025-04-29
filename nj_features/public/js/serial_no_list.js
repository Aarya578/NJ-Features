frappe.listview_settings['Serial No'] = {
    onload: function(listview) {
        listview.page.add_inner_button(__('Update Inventory'), function() {
            
            const dialog = new frappe.ui.Dialog({
                title: __('Work Warehouse Inventory'),
                fields: [
                    {fieldtype:'Section Break'},
                    {
                        fieldname: "work_warehouse_inventory",
                        fieldtype: "Table",
                        in_place_edit: true,
                        fields: [
                            {
                                label: __('Item Code'),
                                fieldname: 'item_code',
                                fieldtype: 'Link',
                                reqd: 1,
                                options: 'Item',
                                in_list_view: 1,
                                read_only: 1,
                                columns: 3
                            },
                            {
                                label: __('Serial No'),
                                fieldname: 'serial_no',
                                fieldtype: 'Link',
                                options: 'Serial No',
                                in_list_view: 1,
                                columns: 2
                            },
                            {
                                label: __('Warehouse'),
                                fieldname: 'warehouse',
                                fieldtype: 'Link',
                                options: 'Warehouse',
                                in_list_view: 1,
                                columns: 2
                            },
                            {
                                label: __('Yes'),
                                fieldname: 'yes',
                                fieldtype: 'Check',
                                default: 1,
                                in_list_view: 1,
                                columns: 1
                            },
                            {
                                label: __('No'),
                                fieldname: 'no',
                                fieldtype: 'Check',
                                default: 0,
                                in_list_view: 1,
                                columns: 1
                            },
                            {
                                label: __('User Activity'),
                                fieldname: 'user_activity',
                                fieldtype: 'Select',
                                options: '\nLog In\nLog Out',
                                default: 'Log Out',
                                read_only: 1
                            },
                            {
                                label: __('Reason'),
                                fieldname: 'reason',
                                fieldtype: 'Text Editor',
                                in_list_view: 1,
                                columns: 2
                            }
                        ]
                    }
                ],
                size: 'extra-large',
                primary_action_label: __('Submit'),
               
                primary_action: function() {
                    const values = dialog.get_values();
                    if (values) {
                        let showPopup = false;
                        let missingReasonRows = [];
                
                        // Uncheck 'Yes' if 'No' is checked
                        values.work_warehouse_inventory.forEach((row) => {
                            if (row.no) { row.yes = false; }
                        });
                
                        dialog.get_field('work_warehouse_inventory').grid.refresh();
                
                        // Check for missing reasons in rows where 'No' is checked
                        values.work_warehouse_inventory.forEach((row, index) => {
                            if (row.no && !row.reason) {
                                showPopup = true;
                                missingReasonRows.push(index + 1);
                            }
                        });
                
                        // Display a popup if reasons are missing
                        if (showPopup) {
                            frappe.msgprint({
                                title: __('Missing Fields'),
                                indicator: 'red',
                                message: __('Reason is mandatory when No is checked in row(s): {0}', [missingReasonRows.join(', ')])
                            });
                        } else {

                            frappe.call({
                                method: 'nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.get_emp_warehouses',
                                callback: function (r) {
                                    // Fetch the warehouse from the logged-in user's Employee record
                                    if (r.message) {
                                        console.log("r,message", r.message);
                                        frappe.call({
                                            method: 'frappe.client.save',
                                            args: {
                                                doc: {
                                                    doctype: 'Daily Individual Report',
                                                    work_warehouse_inventory: values.work_warehouse_inventory,
                                                    warehouse: r.message,
                                                    created_by: frappe.session.user
                                                }
                                            },
                                            callback: function(r) {
                                                if (!r.exc) {
                                                    frappe.call({
                                                        method: 'frappe.client.submit',
                                                        args: { doc: r.message },
                                                        callback: function(r) {
                                                            if (!r.exc) {
                                                                frappe.msgprint(__('Report submitted successfully.'));
                                                                dialog.hide();
                                                            }
                                                        }
                                                    });
                                                }
                                            }
                                        });
                                    } else {
                                        frappe.msgprint(__('Please set your Work Warehouse in Employee.'));
                                    }
                                }
                            })
                            
                        }
                    }
                }
            });

            // Fetch serial number data and populate the dialog's table
            frappe.call({
                method: 'nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.get_serial_no_data',
                callback: function (r) {
                    if (!r.exc) {
                        // Clear existing table data
                        dialog.fields_dict.work_warehouse_inventory.df.data = [];
                        dialog.fields_dict.work_warehouse_inventory.refresh();

                        // Add fetched rows to the dialog's table
                        r.message.forEach(function (row) {
                            dialog.fields_dict.work_warehouse_inventory.df.data.push({
                                item_code: row.item_code,
                                serial_no: row.serial_no,
                                warehouse: row.warehouse,
                                yes: 1,
                                no: 0,
                                user_activity: 'Log Out'
                            });
                        });

                        dialog.fields_dict.work_warehouse_inventory.grid.refresh();
                        
                        dialog.fields_dict.work_warehouse_inventory.$wrapper.on('change', 'input[data-fieldname="yes"]', function () {
                            toggle_checkboxes(this);
                        });

                        dialog.fields_dict.work_warehouse_inventory.$wrapper.on('change', 'input[data-fieldname="no"]', function () {
                            toggle_checkboxes(this);
                        });                    
                    }
                }
            });
            dialog.show();
            
        }).addClass('btn-primary');
    },
}

// function toggle_checkboxes(field) {
//     let row = $(field).closest('.grid-row');
//     let yes_field = row.find('input[data-fieldname="yes"]');
//     let no_field = row.find('input[data-fieldname="no"]');

//     if ($(field).is(':checked')) {
//         if (field.dataset.fieldname === 'yes') {
//             no_field.prop('checked', false).change();
//         } else {
//             yes_field.prop('checked', false).change();
//         }
//     }
// }

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
    } else {
        if (!yes_field.is(':checked') && !no_field.is(':checked')) {
            if (field.dataset.fieldname === 'yes') {
                no_field.prop('checked', true).change();
            } else {
                yes_field.prop('checked', true).change();
            }
        }
    }
}
