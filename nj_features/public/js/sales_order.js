frappe.ui.form.on('Sales Order', {
    refresh: function(frm) {
        if (frm.doc.status !== 'Closed' && frm.doc.status !== 'On Hold' && frm.doc.docstatus === 1) {
            frm.add_custom_button('Initiate Refund', function() {
                frappe.call({
                    method: 'nj_lib.nj_lib.doctype.nj_refund.nj_refund.create_refund_record_from_so',
                    args: {
                        sales_order: frm.doc.name
                    },
                    callback: function(r) {
                        if (r.message) {
                            frappe.msgprint(r.message);
                        }
                    }
                });
            });
        } 
        // frm.add_custom_button(__('Critical Log'), function() {
        //     // Show loading indicator
        //     frappe.show_alert({
        //         message: __('Generating AWB Number...'),
        //         indicator: 'blue'
        //     });
        //     frappe.call({
        //         method: 'nj_features.overrides.sales_order.send_consignement_data',
        //         args: {
        //             doc: JSON.stringify(frm.doc)
        //         },
        //         callback: function(response) {
        //             frm.reload_doc();
        //             frappe.show_alert({
        //                 message: __('AWB Number generated successfully!'),
        //                 indicator: 'green'
        //             });
        //         }
        //     });
            
            
          
        // }).addClass('btn-primary');
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Critical Log'), function() {
                // Show loading indicator
                frappe.show_alert({
                    message: __('Generating AWB Number...'),
                    indicator: 'blue'
                });

                frappe.call({
                    method: 'nj_features.overrides.sales_order.send_consignement_data',
                    args: {
                        doc: JSON.stringify(frm.doc)
                    },
                    callback: function(response) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __('AWB Number generated successfully!'),
                            indicator: 'green'
                        });
                    }
                });
            }).addClass('btn-primary');
        }
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Shiprocket'), function() {
                // Show loading indicator
                frappe.show_alert({
                    message: __('Generating AWB Number...'),
                    indicator: 'blue'
                });
                frappe.call({
                    method: 'nj_features.overrides.sales_order.shiprocket_awb_number',
                    args: {
                        doc: JSON.stringify(frm.doc)
                    },
                    callback: function(response) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __('AWB Number generated successfully!'),
                            indicator: 'green'
                        });
                    }
                });
                
                
            
            }).addClass('btn-primary');
        }
    },
    validate: function(frm) {
        console.log("Inside validate function =================");
        
        // Log data for debugging
        console.log("Doc before update:", frm.doc);
        
        frappe.call({
            method: 'nj_features.overrides.sales_order.update_item_details',
            args: {
                self: frm.doc
            },
            callback: function(r) {
                console.log("Server response:", r);          
                if (r.message) {
                    if (r.message.weight !== null && r.message.weight !== undefined) {
                        frm.set_value('weight', r.message.weight);
                        frm.refresh_field("weight");
                    }            
                    if (r.message.height) {
                        frm.set_value('height', r.message.height);
                        frm.refresh_field("height");
                    }             
                    if (r.message.length) {
                        frm.set_value('length', r.message.length);
                        frm.refresh_field("length");
                    }               
                    if (r.message.breadth) {
                        frm.set_value('breadth', r.message.breadth);
                        frm.refresh_field("breadth");
                    }           

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
    },
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