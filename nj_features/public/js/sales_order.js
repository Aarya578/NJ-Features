frappe.ui.form.on('Sales Order', {
    
    refresh: function(frm) {
        // frm.page.remove_inner_button('Sales Invoice', 'Create');
        if (frm.doc.status !== 'Closed' && frm.doc.status !== 'On Hold' && frm.doc.docstatus === 1) {
            frm.add_custom_button('Initiate Refund', function () {
                frappe.call({
                    method: 'nj_lib.nj_lib.doctype.nj_refund.nj_refund.create_refund_record_from_so',
                    args: { sales_order: frm.doc.name },
                    callback: function (r) {
                        if (r.message) frappe.msgprint(r.message);
                    }
                });
            });
            
        } 
    },
   
    // onload_post_render: function(frm) {
    //     frm.remove_custom_button('Sales Invoice', 'Create');
    //     $('span.menu-item-label[data-label="Create%20%3E%Sales%20Invoice"]').closest('li').hide();
    // },

    amazon_order_id: function(frm) {
        $(frm.fields_dict.amazon_order_id.input).on('blur', function() {
            validateAmazonOrderID(frm);
        });
    },

    after_save: function(frm) {

        // frm.call({
        //     method: "nj_features.overrides.sales_order.fetching_HSN_code", // update with actual path
        //     args: {
        //         doc: frm.doc
        //     },
        //     callback: function(r) {
        //         if (!r.exc) {
        //             frm.reload_doc();  // Refresh updated HSN or tax data
        //         }
        //     }
        // });
    //    frappe.call({
    //         method: "nj_features.overrides.sales_order.get_item_group_tax_and_hsn",
    //         args: {
    //             items: frm.doc.items
    //         },
    //         callback: function(r) {
    //             if (!r.exc && r.message) {
    //                 const hsn_map = r.message.hsn_map;
    //                 const taxes = r.message.taxes;

    //                 // Set HSN codes on each item row
    //                 (frm.doc.items || []).forEach(row => {
    //                     if (hsn_map[row.item_code]) {
    //                         frappe.model.set_value(row.doctype, row.name, "hsn_code", hsn_map[row.item_code]);
    //                     }
    //                 });

    //                 // Overwrite the taxes table
    //                 frm.clear_table("taxes");
    //                 taxes.forEach(tax => {
    //                     let tax_row = frm.add_child("taxes");
    //                     tax_row.charge_type = tax.charge_type || "On Net Total";
    //                     tax_row.account_head = tax.account_head;
    //                     tax_row.rate = tax.rate;
    //                     tax_row.description = tax.description;
    //                     tax_row.cost_center = tax.cost_center;
    //                 });

    //                 frm.refresh_field("items");
    //                 frm.refresh_field("taxes");

    //                 // Trigger recalculation
    //                 frm.events.apply_taxes(frm);
    //                 frm.events.set_unallocated_amount(frm);
    //             }
    //         }
    //     });

        if (!frm.doc.shipping_address_name && frm.doc.customer_address) {
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

frappe.require("/assets/nj_features/js/nj_features.js", function() {
    extend_listview_settings('Sales Order', {
        refresh: function(listview) {
            viewButton(listview);
        }
    });
});

function viewButton(listview) {
    if (!listview.page.custom_buttons_added) {
        listview.page.set_secondary_action("Amazon Order Sync", function() {
            openAmazonSyncForm();
        }).addClass('btn-primary');

        listview.page.custom_buttons_added = true;
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