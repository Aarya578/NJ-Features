frappe.ui.form.on('Sales Order', {
    refresh: function(frm) {
        if (frm.doc.status !== 'Closed' && frm.doc.status !== 'On Hold' && frm.doc.docstatus === 1) {
            frm.add_custom_button('Initiate Refund', function () {
                frappe.db.get_list('Sales Invoice Item', {
                filters: {
                    sales_order: frm.doc.name,
                    docstatus: 1  // Ensures it belongs to submitted Sales Invoice
                },
                fields: ['parent'],
                limit: 1
            }).then(res => {
                const sales_invoice = res.length ? res[0].parent : null;

                if (!sales_invoice) {
                    frappe.call({
                        method: 'nj_lib.nj_lib.doctype.nj_refund.nj_refund.create_refund_record_from_so',
                        args: { sales_order: frm.doc.name },
                        callback: function (r) {
                            if (r.message) frappe.msgprint(r.message);
                        }
                    });
                } else {
                    frappe.call({
                        method: 'nj_lib.nj_lib.doctype.nj_refund.nj_refund.get_return_delivery_notes',
                        args: { sales_order: frm.doc.name },
                        callback: function (r) {
                            if (r.message && r.message.length > 0) {
                                frappe.prompt(
                                    [
                                        {
                                            label: 'Select Return Delivery Note',
                                            fieldname: 'return_dn',
                                            fieldtype: 'Select',
                                            options: r.message,
                                            reqd: 1
                                        }
                                    ],
                                    function (values) {
                                        frappe.call({
                                            method: 'nj_lib.nj_lib.doctype.nj_refund.nj_refund.create_refund_record_from_so',
                                            args: {
                                                sales_order: frm.doc.name,
                                                return_dn: values.return_dn
                                            },
                                            callback: function (res2) {
                                                if (res2.message) {
                                                    frappe.msgprint(res2.message);
                                                }
                                            }
                                        });
                                    },
                                    'Select Return Delivery Note',
                                    'Proceed'
                                );
                            } else {
                                frappe.msgprint(__('No return Delivery Notes found for this Sales Order.'));
                            }
                        }
                    });
                }
            });

            });


        } 
       
        
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