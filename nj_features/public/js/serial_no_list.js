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
                                    read_only: 1
                                },
                                {
                                    label: __('Serial No'),
                                    fieldname: 'serial_no',
                                    fieldtype: 'Link',
                                    options: 'Serial No',
                                    in_list_view: 1
                                },
                                {
                                    label: __('Yes'),
                                    fieldname: 'yes',
                                    fieldtype: 'Check',
                                    default: 1,
                                    in_list_view: 1,
                                },
                                {
                                    label: __('No'),
                                    fieldname: 'no',
                                    fieldtype: 'Check',
                                    default: 0,
                                    in_list_view: 1,
                                },
                                {
                                    label: __('User Activity'),
                                    fieldname: 'user_actvity',
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
                                }
                            ]
                        }
                ],
                size: 'extra-large',
                primary_action_label: __('Submit'),
                primary_action: function() {
                    const values = dialog.get_values();
                    if (values) {
                        frappe.call({
                            method: 'frappe.client.insert',
                            args: {
                                doc: {
                                    doctype: 'Daily Individual Report',
                                }
                            },
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

            dialog.show();
            
        }).addClass('btn-primary');
    }
}
