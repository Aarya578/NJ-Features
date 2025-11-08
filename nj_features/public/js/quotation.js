frappe.ui.form.on('Quotation', {
    customer_address: function(frm) {
        fetch_email(frm);
    },

    after_save: function(frm) {
        fetch_email(frm);
    },
    onload_post_render: function(frm) {
        check_and_hide_sales_order_button(frm);

    },
    
    refresh: function(frm) {
        check_and_hide_sales_order_button(frm);

        if (frm.doc.docstatus === 1) {

            // Remove ERPNext default SO button
            frm.remove_custom_button("Sales Order", "Create");

            // Add custom button
            frm.add_custom_button("Sales Order", function () {
                frappe.call({
                    method: "nj_features.overrides.quotation.bypass_so_permission",
                    args: { quotation_name: frm.doc.name },
                    freeze: true,
                    freeze_message: "Creating Sales Order...",
                    callback: function (r) {
                        if (r.message) {
                            frappe.msgprint(`Sales Order <b>${r.message}</b> created`);
                            frappe.set_route("Form", "Sales Order", r.message);
                        }
                    }
                });
            }, "Create");
        }
    },
    
    customer_reply: function(frm) {
        check_and_hide_sales_order_button(frm);
    },

    //  validate: function(frm) {
    //     frappe.call({
    //         method: "nj_features.overrides.quotation.fetch_email_from_shipping_address",
    //         args: {
    //             doc_name: frm.doc.name
    //         },
    //         async: false,
    //         callback: function(r) {
    //             if (r.message) {
    //                 console.log("Email fetched:", r.message);
    //                 frm.set_value("email", r.message);
    //                 frm.refresh_field("email");
    //             }
    //         }
    //     });
    // }
});

function check_and_hide_sales_order_button(frm) {
    if (frm.doc.customer_reply === 'Dis Agree') {
        setTimeout(() => {
            $('span.menu-item-label:contains("Sales Order")').closest('li').hide();       
            frm.remove_custom_button('Sales Order', 'Create');   
            $('.inner-group-button .dropdown-menu li a:contains("Sales Order")').closest('li').hide();
        }, 500);
    } else if (frm.doc.customer_reply === 'Agree') {
        setTimeout(() => {
            $('span.menu-item-label:contains("Sales Order")').closest('li').show();
            $('.inner-group-button .dropdown-menu li a:contains("Sales Order")').closest('li').show();
        }, 500);
    }
}
function fetch_email(frm) {
    if (!frm.doc.name || frm.is_new() || !frm.doc.customer_address) return;

    frappe.call({
        method: "nj_features.overrides.quotation.fetch_email_from_shipping_address",
        args: {
            doc_name: frm.doc.name
        },
        callback: function(r) {
            if (r.message) {
                frm.set_value("email", r.message);
                frm.refresh_field("email");
                console.log("Email updated:", r.message);
            }
        }
    });
}