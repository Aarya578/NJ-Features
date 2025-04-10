frappe.ui.form.on('Sales Order', {
    onload_post_render: function(frm) {
        frm.remove_custom_button('Delivery Note', 'Create');
        $('span.menu-item-label[data-label="Create%20%3E%20Delivery%20Note"]').closest('li').hide();
    },

    amazon_order_id: function(frm) {
        $(frm.fields_dict.amazon_order_id.input).on('blur', function() {
            validateAmazonOrderID(frm);
        });
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