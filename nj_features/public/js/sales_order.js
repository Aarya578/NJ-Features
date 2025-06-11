frappe.ui.form.on('Sales Order', {
    refresh: function(frm) {
        if (frm.doc.status !== 'Closed' && frm.doc.status !== 'On Hold' && frm.doc.docstatus === 1) {
            frm.add_custom_button('Initiate Refund', function() {
                frappe.call({
                    method: 'nj_lib.nj_lib.doctype.nj_refund.nj_refund.create_refund_record_from_so',
                    args: { sales_order: frm.doc.name },
                    callback: function(r) {
                        if (r.message) { frappe.msgprint(r.message); }
                    }
                });
            });
        } 
       
        if (frm.doc.docstatus === 1) {
            var critical_btn = frm.add_custom_button(__('Critical Log'), function() {
                frappe.show_alert({
                    message: __('Generating AWB Number...'),
                    indicator: 'blue'
                });
                frappe.call({
                    method: 'nj_features.overrides.sales_order.send_consignement_data',
                    args: { doc: JSON.stringify(frm.doc) },
                    callback: function(response) {
                        if (response.message) {
                            frappe.call({
                                method: 'frappe.client.set_value',
                                args: {
                                    doctype: 'Sales Order',
                                    name: frm.doc.name,
                                    fieldname: 'courier_service',
                                    value: 'CriticaLog'
                                },
                                callback: function(set_value_response) {
                                    frm.reload_doc();
                                    frappe.show_alert({
                                        message: __('AWB Number generated successfully!'),
                                        indicator: 'green'
                                    });
                                }
                            });
                        }
                    }
                });
            });
            critical_btn.addClass('btn-primary');
            var shiprocket_btn = frm.add_custom_button(__('Shiprocket'), function() {
                frappe.show_alert({
                    message: __('Generating AWB Number...'),
                    indicator: 'blue'
                });
                
                frappe.call({
                    method: 'nj_features.overrides.sales_order.shiprocket_awb_number',
                    args: { doc: JSON.stringify(frm.doc) },
                    callback: function(response) {
                        if (response.message) {
                            // Removed the automatic setting of 'Shiprocket Manifest'
                            // The courier_service will now be set by the Python method
                            frm.reload_doc();
                            frappe.show_alert({
                                message: __('AWB Number generated successfully!'),
                                indicator: 'green'
                            });
                        }
                    }
                });
            });

            shiprocket_btn.addClass('btn-primary');
            // var shiprocket_btn = frm.add_custom_button(__('Shiprocket'), function() {
            //     frappe.show_alert({
            //         message: __('Generating AWB Number...'),
            //         indicator: 'blue'
            //     });
            //     frappe.call({
            //         method: 'nj_features.overrides.sales_order.shiprocket_awb_number',
            //         args: { doc: JSON.stringify(frm.doc) },
            //         callback: function(response) {
            //             if (response.message) {
            //                 frappe.call({
            //                     method: 'frappe.client.set_value',
            //                     args: {
            //                         doctype: 'Sales Order',
            //                         name: frm.doc.name,
            //                         fieldname: 'courier_service',
            //                         value: 'Shiprocket Manifest'
            //                     },
            //                     callback: function(set_value_response) {
            //                         frm.reload_doc();
            //                         frappe.show_alert({
            //                             message: __('AWB Number generated successfully!'),
            //                             indicator: 'green'
            //                         });
            //                     }
            //                 });
            //             }
            //         }
            //     });
            // });
            // shiprocket_btn.addClass('btn-primary'); // Different color to distinguish
        }
    },
    validate: function(frm) {
    frappe.call({
        method: 'nj_features.overrides.sales_order.update_item_details',
        args: { self: frm.doc },
        callback: function(r) {
            if (r.message) {
                // Weight
                if (r.message.weight !== null && r.message.weight !== undefined) {
                    frm.set_value('weight', r.message.weight);
                }

                // Height
                if (r.message.height) {
                    frm.set_value('height', r.message.height);
                } else {
                    frm.set_value('height', null);  // Reset if not returned
                }

                // Length
                if (r.message.length) {
                    frm.set_value('length', r.message.length);
                } else {
                    frm.set_value('length', null);
                }

                // Breadth
                if (r.message.breadth) {
                    frm.set_value('breadth', r.message.breadth);
                } else {
                    frm.set_value('breadth', null);
                }

                frm.refresh_fields(['weight', 'height', 'length', 'breadth']);
            }
        }
    });


    },

    onload_post_render: function(frm) {
        frm.remove_custom_button('Delivery Note', 'Create');
        $('span.menu-item-label[data-label="Create%20%3E%20Delivery%20Note"]').closest('li').hide();
    },

    amazon_order_id: function(frm) {
        $(frm.fields_dict.amazon_order_id.input).on('blur', function() {
            validateAmazonOrderID(frm);
        });
    },

    after_save: function(frm) {
        if (!frm.doc.supplier_address_name || frm.doc.supplier_address_name === '' || frm.doc.supplier_address_name === undefined) {
            frm.set_value('shipping_address_name', frm.doc.customer_address);
            frm.refresh_field('shipping_address_name');
        }
    }
});

function validateAmazonOrderID(frm) {
    if (frm.doc.amazon_order_id && frm.doc.amazon_order_id.length < 16) {
        frappe.msgprint(__('Amazon Order ID must be at least 16 characters long.'));
        frm.set_value('amazon_order_id', '');
    }
}

frappe.listview_settings['Sales Order'] = {
    refresh: function(listview) {
        viewButton(listview);
    }
};

function viewButton(listview) {
    if (!listview.page.custom_buttons_added) {
        listview.page.set_secondary_action("Amazon Order Sync", function() {
            openAmazonSyncForm(listview);
        }).addClass('btn-primary');
        listview.page.custom_buttons_added = true; // Avoid adding the button multiple times
    }
}

function openAmazonSyncForm() {
    frappe.call({
        method: 'ecommerce_integrations.amazon.doctype.amazon_sp_api_settings.amazon_sp_api_settings.schedule_get_order_details',
        callback: function(response) {
            if (response.message) {
                if (response.message.status === 'success') {
                    frappe.msgprint(__(response.message.message));
                    frappe.views.list_view.refresh();
                } else {
                    frappe.msgprint({
                        title: __('Error'),
                        indicator: 'red',
                        message: __(response.message.message)
                    });
                }
            } else {
                frappe.msgprint({
                    title: __('Error'),
                    indicator: 'red',
                    message: __('There was an error syncing orders with Amazon.')
                });
            }
        }
    });
}