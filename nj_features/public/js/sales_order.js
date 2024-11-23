// frappe.listview_settings['Sales Order'] = {
//     onload: function(listview) {
//         viewButton(listview);
//     },
//     refresh: function(listview) {
//         viewButton(listview);
//     },
// };

// function viewButton(listview) {
    
//     // Add Amazon Sync button
//     console.log("listview");
//     // if (!listview.page.custom_buttons_added) {
//         listview.page.set_secondary_action("Amazon Sync", function() {
//             openAmazonSyncForm();
//         }).addClass('btn-primary');
//     //     listview.page.custom_buttons_added = true; // Avoid adding the button multiple times
//     // }
// }


// function openAmazonSyncForm() {
//     // frappe.db.get_doc('Amazon SP API Settings', '966b8eb8c8').then((r) => {
//          console.log("================r==============================",r);
//         frappe.call({
//             method: 'ecommerce_integrations.amazon.doctype.amazon_sp_api_settings.amazon_sp_api_settings.schedule_get_order_details',
          
//             // args: {
//             //     // Pass any necessary arguments here
//             //     self: r
               
//             // },
//             callback: function(r) {
//                 if (r.message) {
//                     frappe.msgprint(__('Orders have been successfully synced with Amazon.'));
//                 }
//             }
            
//         });
//         console.log("inside the method")

//     // } )
// }



// 
// frappe.listview_settings['Sales Order'] = {
//     onload: function(listview) {
//         viewButton(listview);
//     },
//     refresh: function(listview) {
//         viewButton(listview);
//     },
// };

// function viewButton(listview) {
//     console.log("Adding Amazon Sync button");
//     if (!listview.page.custom_buttons_added) {
//         listview.page.set_secondary_action("Amazon Sync", function() {
//             openAmazonSyncForm(listview);
//         }).addClass('btn-primary');
//         listview.page.custom_buttons_added = true; // Avoid adding the button multiple times
//     }
// }

// function openAmazonSyncForm(listview) {
//     console.log("Amazon Sync button clicked");
//     frappe.call({
//         method: 'ecommerce_integrations.amazon.doctype.amazon_sp_api_settings.amazon_sp_api_settings.schedule_get_order_details',
//         callback: function(response) {
//             if (response.message === "Orders have been successfully synced with Amazon.") {
//                 frappe.msgprint(__('Orders have been successfully synced with Amazon.'));
//                 listview.refresh(); // Refresh the Sales Order list view to show updated orders
//             } else if (response.message === "No orders found.") {
//                 frappe.msgprint(__('No orders were found to sync.'));
//             } else {
//                 frappe.msgprint(__('There was an error syncing orders with Amazon: ') + response.message);
//             }
//         },
//         error: function(error) {
//             frappe.msgprint(__('There was an error syncing orders with Amazon.'));
//             console.error("Error during Amazon Sync:", error);
//         }
//     });
//     console.log("Inside the method");
// }
// 

frappe.ui.form.on('Sales Order', {
    setup: function(frm) {
        frm.make_purchase_order = function() {
            return;
        }
    },
    refresh: function(frm) {
        setTimeout(() => {
            frm.remove_custom_button('Delivery Note', 'Create');
            frm.page.remove_inner_button('Delivery Note', 'Create');
            $('.btn-group.dropdown-menu a:contains("Delivery Note")').parent().remove();
        }, 300);
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
    onload: function(listview) {
        viewButton(listview);
    },
    refresh: function(listview) {
        viewButton(listview);
    },
};

function viewButton(listview) {
    console.log("Adding Amazon Sync button");
    if (!listview.page.custom_buttons_added) {
        listview.page.set_secondary_action("Amazon Order Sync", function() {
            openAmazonSyncForm(listview);
        }).addClass('btn-primary');
        listview.page.custom_buttons_added = true; // Avoid adding the button multiple times
    }
}

// function openAmazonSyncForm(listview) {
//     console.log("Amazon Sync button clicked");
//     frappe.call({
//         method: 'ecommerce_integrations.amazon.doctype.amazon_sp_api_settings.amazon_sp_api_settings.schedule_get_order_details',
//         callback: function(response) {
//             if (response.message) {
//                 frappe.msgprint(__(response.message));
//                 listview.refresh(); // Refresh the Sales Order list view to show updated orders
//             } else {
//                 frappe.msgprint(__('No orders were synced.'));
//             }
//         },
//         error: function(error) {
//             frappe.msgprint(__('There was an error syncing orders with Amazon.'));
//             console.error("Error during Amazon Sync:", error);
//         }
//     });
//     console.log("Inside the method");
// }
function openAmazonSyncForm() {
    frappe.call({
        method: 'ecommerce_integrations.amazon.doctype.amazon_sp_api_settings.amazon_sp_api_settings.schedule_get_order_details',
        callback: function(response) {
            console.log("Response from backend:", response);
            if (response.message) {
                if (response.message.status === 'success') {
                    frappe.msgprint(__(response.message.message));
                    // Refresh the list view to show the newly synced orders
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

