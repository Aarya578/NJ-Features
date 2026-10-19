frappe.ui.form.on('Sales Order', {
    
    refresh: function(frm) {
        // Show the current return block, rather than relying on old shortage logs.
        if (!frm.is_new() && frm.doc.docstatus === 1) {
            const order_name = frm.doc.name;
            frappe.call({
                method: 'nj_features.overrides.sales_order.get_sales_order_allocation_block_reason',
                args: { so_name: order_name },
                callback: function(r) {
                    if (frm.doc.name !== order_name) return;
                    if (frm._allocation_block_intro) {
                        frm._allocation_block_intro.remove();
                        frm._allocation_block_intro = null;
                    }
                    if (r.message) {
                        frm._allocation_block_intro = frm.dashboard.add_comment(
                            frappe.utils.escape_html(r.message), 'orange', true
                        );
                    }
                }
            });
        }

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
        // frappe.call({
        //     method: "nj_features.overrides.sales_order.1",
        //     args: { doc: cur_frm.doc },
        //     callback: function(r) {
        //         if (r.message) {                 
        //             cur_frm.set_value("sales_channel", r.message.sales_channel);
        //             frm.refresh_field("sales_channel");

        //         }
        //     }
        // });

        let update_features_table = frm.add_custom_button(__('Fetch Payment Id'), function() {
            frappe.show_alert({
                message: __('Fetching Payment Id...'),
                indicator: 'blue'
            });

            frappe.call({
                method: 'nj_features.overrides.sales_order.fetch_payment_id_from_shopify',
                args: { doc: frm.doc },   // pass entire doc so we get sales_order
                callback: function(response) {
                    if (response.message && response.message.payment_id) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __('Payment Id fetched successfully: ' + response.message.payment_id),
                            indicator: 'green'
                        });
                    }
                },
                error: function() {
                    frappe.msgprint(__('Failed to fetch Payment Id. Please check the Shopify response.'));
                }
            });
        });

        // Add styling to the button
        update_features_table.addClass('btn-primary');
        


        
    },

   
    onload_post_render: function(frm) {
        frm.remove_custom_button('Delivery Note', 'Create');
        $('span.menu-item-label[data-label="Create%20%3E%20Delivery%20Note"]').closest('li').hide();
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