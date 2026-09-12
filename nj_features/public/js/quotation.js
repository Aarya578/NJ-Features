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

    before_submit: function(frm) {
        return handle_customer_quotation_before_submit(frm);
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

async function handle_customer_quotation_before_submit(frm) {
    if (!frm.fields_dict.customer_quotation) {
        frappe.validated = false;
        frappe.msgprint(__("Field Customer Quotation (customer_quotation) was not found."));
        return;
    }

    if (frm.doc.customer_quotation) {
        frappe.validated = true;
        return;
    }

    frappe.validated = false;
    const generated = await show_customer_quotation_link_dialog(frm);
    if (generated) {
        frappe.msgprint(__("Customer quotation link generated. Click Submit again to submit the Quotation."));
    }
}

function show_customer_quotation_link_dialog(frm) {
    return new Promise((resolve) => {
        let generated = false;
        const dialog = new frappe.ui.Dialog({
            title: __("Generate Customer Quotation Link"),
            fields: [
                {
                    fieldname: "valid_days",
                    label: __("Valid For Days"),
                    fieldtype: "Int",
                    default: 7,
                    reqd: 1
                },
                {
                    fieldname: "one_time_use",
                    label: __("One Time Use"),
                    fieldtype: "Check",
                    default: 0
                }
            ],
            primary_action_label: __("Generate Link"),
            async primary_action(values) {
                if (values.valid_days < 1) {
                    frappe.msgprint(__("Valid For Days must be at least 1."));
                    return;
                }

                const primaryButton = dialog.get_primary_btn();
                primaryButton.prop("disabled", true);
                try {
                    const response = await frappe.call({
                        method:
                            "nj_features.nj_features.doctype.quotation_customer_access.quotation_customer_access.generate_quotation_customer_link",
                        args: {
                            source_quotation: frm.doc.name,
                            valid_days: values.valid_days,
                            one_time_use: values.one_time_use
                        },
                        freeze: true,
                        freeze_message: __("Generating customer quotation link...")
                    });

                    const result = response.message || {};
                    if (!result.quotation_url) {
                        primaryButton.prop("disabled", false);
                        return;
                    }

                    await frm.set_value("customer_quotation", result.quotation_url);
                    generated = true;
                    resolve(true);
                    dialog.hide();
                } catch (error) {
                    primaryButton.prop("disabled", false);
                }
            }
        });

        dialog.onhide = () => {
            if (!generated) resolve(false);
        };
        dialog.show();
    });
}

function check_and_hide_sales_order_button(frm) {

    // Case 1: Dis Agree
    if (frm.doc.customer_replay === "Dis Agree") {

        frappe.db.get_value("NJ Settings", { parameter: "quotation_value" }, "value")
            .then(res => {
                let setting_value = res?.message?.value || 0;
                console.log("setting value =", setting_value);

                // If value = 1 → skip hiding
                if (setting_value == 1) {
                    return;
                }

                // If value = 0 → hide Sales Order
                setTimeout(() => {
                    $('span.menu-item-label:contains("Sales Order")').closest('li').hide();
                    frm.remove_custom_button('Sales Order', 'Create');
                    $('.inner-group-button .dropdown-menu li a:contains("Sales Order")').closest('li').hide();
                }, 500);
            });

    } 
    // Case 2: Agree → always show
    else if (frm.doc.customer_replay === "Agree") {

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
