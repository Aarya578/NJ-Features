frappe.ui.form.on('Sales Invoice', {
    refresh: function(frm) {   
        // remove "Update Items" button from UI
        frm.remove_custom_button('Update Items');     
        // Ensure the button is shown even if update_stock == 1
		var from_delivery_note = frm.doc.items.some(item => item.delivery_note ? true : false);

		if (!from_delivery_note && !frm.doc.is_delivered_by_supplier) {
			frm.add_custom_button(__('Delivery Note'),
            () => frm.cscript['Make Delivery Note'](), __('Create'));
		}
        // Custom E-Invoicing functionality override
        // setup_custom_einvoice_actions(frm);

        // Run on refresh as well; onload can fire before taxes are fully populated.
        if (Number(frm.doc.docstatus || 0) === 0 && Number(frm.doc.is_debit_note || 0) === 0) {
            update_gst_tax_type_from_nj_settings(frm);
        }
    },
     onload(frm) {
        if (Number(frm.doc.docstatus || 0) === 0 && Number(frm.doc.is_debit_note || 0) === 0) {
            update_gst_tax_type_from_nj_settings(frm);
        }
    }
    ,

    // onload: function(frm) {   
    //     if (!frm.doc.__islocal) return;
    //     frappe.call({
    //         method: "nj_features.overrides.sales_invoice.due_date_validation",
    //         args: { doc: frm.doc },
    //         callback: function(r) {             
    //             if (r.message && r.message.due_date) {
    //                 frm.set_value("due_date", r.message.due_date);
    //             }
    //         }        update_gst_tax_type_from_nj_settings(frm);

    //     });
    
    // },

    // onload: function(frm) {
    //     let items = frm.doc.items.map(row => ({
    //         idx: row.idx,
    //         item_group: row.item_group
    //     }));

    //     frappe.call({
    //         method: "nj_features.overrides.sales_invoice.get_item_group_cost_centers",
    //         args: { items: items },
    //         callback: function(r) {
                
    //             if (r.message) {
    //                 frm.doc.items.forEach(row => {
    //                     if (r.message[row.idx]) {
    //                         frappe.model.set_value(row.doctype, row.name, "cost_center", r.message[row.idx]);

    //                     }
    //                      frm.refresh_field('cost_center');
    //                 });
    //             }
    //         }
    //     });
    // },
    validate:  function(frm) {
        apply_allocated(frm);
        //  frm.call({
        //     method: "nj_features.overrides.sales_invoice.approve_validation",
        //     doc: frm.doc,  // automatically sends doc
        // });
        setup_custom_einvoice_actions(frm);

        
    //     if (!frm.doc.invoice_no && !frm.doc.transporter_id && !frm.doc.transporter_names && !frm.doc.email) {
    //         frappe.call({
    //             method: "nj_features.overrides.sales_invoice.fetching_transporter_details",
    //             args: {
    //                 docname: frm.doc.name
    //             },
    //             callback: function (r) {
    //                 if (r.message && r.message.status === "success") {
    //                     // Update fields manually
    //                     frm.set_value("invoice_no", r.message.invoice_no);
    //                     frm.set_value("transporter_id", r.message.transporter_id);
    //                     frm.set_value("transporter_names", r.message.transporter_names);
    //                     frm.set_value("email", r.message.email);

    //                     frappe.msgprint("Transporter details updated from Delivery Note.");
    //                 }
    //             }
    //         });
    //     } else {
    //         console.log("Transporter details already present. Skipping update.");
    //     }
    // frappe.call({
    //         method: "nj_features.overrides.sales_invoice.due_date_validation",
    //         args: {
    //             doc: frm.doc
    //         },
    //         callback: function(r) {
    //             console.log("r.message==================================", r.message);
                
    //             if (r.message) {
    //                 frm.set_value("payment_schedule", r.message.payment_schedule);
    //                 frm.refresh_field("payment_schedule");
    //             }
    //         }
    //     });


    },
    before_save(frm) {
        apply_allocated(frm);
    },

    grand_total(frm) {
        apply_allocated(frm);
    }
    
});
// function update_gst_tax_type_from_nj_settings(frm) {
//     console.log("updating============================");

//     // 🔒 Skip if document is submitted
//     if (Number(frm.doc.docstatus || 0) === 1) {
//         return;
//     }

//     if (!frm.doc.taxes || !frm.doc.taxes.length) return;

//     frappe.db.get_value(
//         "NJ Settings",
//         { parameter: "taxe_account_heads" },
//         "value"
//     ).then(r => {
//         const csv = r?.message?.value;
//         console.log("message=========", r.message);

//         if (!csv) return;

//         const normalize = (value) => (value || "")
//             .toString()
//             .trim()
//             .toLowerCase();

//         const account_heads = csv
//             .split(',')
//             .map(v => normalize(v))
//             .filter(Boolean);

//         let updated_any = false;

//         frm.doc.taxes.forEach(tax => {
//             const tax_account_head = normalize(tax.account_head);
//             const matched = account_heads.some(setting_head =>
//                 tax_account_head === setting_head || tax_account_head.startsWith(`${setting_head} - `)
//             );

//             if (
//                 tax_account_head &&
//                 matched &&
//                 tax.charge_type !== "On Net Total"
//             ) {
//                 const net_total = Number(frm.doc.net_total || 0);
//                 const current_rate = Number(tax.rate || 0);
//                 const current_tax_amount = Number(tax.tax_amount || 0);

//                 // If tax came as "Actual" with amount but no rate (common in SO->SI mapping),
//                 // derive a percentage before switching to "On Net Total" so recalculation works.
//                 if (current_rate === 0 && current_tax_amount > 0 && net_total > 0) {
//                     const derived_rate = Number(((current_tax_amount / net_total) * 100).toFixed(6));
//                     frappe.model.set_value(
//                         tax.doctype,
//                         tax.name,
//                         "rate",
//                         derived_rate
//                     );
//                 }

//                 frappe.model.set_value(
//                     tax.doctype,
//                     tax.name,
//                     "charge_type",
//                     "On Net Total"
//                 );
//                 updated_any = true;
//             }
//         });

//         // Recalculate only if any row was changed
//         if (updated_any) {
//             frm.cscript.calculate_taxes_and_totals();
//         }
//     });
// }
frappe.ui.form.on('Sales Invoice Advance', {
    advances_add(frm, cdt, cdn) {
        set_row_allocated(frm, cdt, cdn);
    },

    reference_name(frm, cdt, cdn) {
        // wait for ERP to fetch values, then override once
        setTimeout(() => {
            set_row_allocated(frm, cdt, cdn);
        }, 500);
    }
});

function apply_allocated(frm) {
    const gt = flt(frm.doc.grand_total);
    let remaining = gt;

    // Prevent server-side validate from recalculating advances and overriding manual allocation.
    if (Object.prototype.hasOwnProperty.call(frm.doc, "allocate_advances_automatically")) {
        frm.doc.allocate_advances_automatically = 0;
    }

    (frm.doc.advances || []).forEach(row => {
        const max_alloc = flt(row.advance_amount || 0);
        const next_alloc = Math.max(0, Math.min(max_alloc, remaining));

        if (flt(row.allocated_amount) !== next_alloc) {
            frappe.model.set_value(row.doctype, row.name, 'allocated_amount', next_alloc);
        }

        remaining = Math.max(0, remaining - next_alloc);
    });

    frm.refresh_field("advances");
}

function set_row_allocated(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const gt = flt(frm.doc.grand_total);
    const next_alloc = Math.max(0, Math.min(flt(row.advance_amount || 0), gt));

    if (flt(row.allocated_amount) !== next_alloc) {
        frappe.model.set_value(cdt, cdn, 'allocated_amount', next_alloc);
    }
}
function update_gst_tax_type_from_nj_settings(frm) {
    console.log("Updating GST tax types...");

    // 🔒 Skip if submitted
    if (Number(frm.doc.docstatus || 0) === 1) return;

    if (!frm.doc.taxes || !frm.doc.taxes.length) return;

    frappe.db.get_value(
        "NJ Settings",
        { parameter: "taxe_account_heads" },
        "value"
    ).then(r => {

        const csv = r?.message?.value;
        if (!csv) return;

        const normalize = (val) => (val || "").toString().trim().toLowerCase();

        const account_heads = csv
            .split(',')
            .map(v => normalize(v))
            .filter(Boolean);

        let updated_any = false;

        frm.doc.taxes.forEach(tax => {

            const tax_account_head = normalize(tax.account_head);

            // Check if tax belongs to configured heads
            const matched = account_heads.some(setting_head =>
                tax_account_head === setting_head ||
                tax_account_head.startsWith(`${setting_head} -`)
            );

            if (!matched) return;

            // ✅ FIX 1: Always set correct GST rate (NO reverse calculation)
            let correct_rate = 0;

            if (tax_account_head.includes("sgst")) {
                correct_rate = 9;
            } else if (tax_account_head.includes("cgst")) {
                correct_rate = 9;
            } else if (tax_account_head.includes("igst")) {
                correct_rate = 18;
            }

            // Skip if no GST match
            if (!correct_rate) return;

            // ✅ FIX 2: Set rate only if different
            if (Number(tax.rate) !== correct_rate) {
                frappe.model.set_value(
                    tax.doctype,
                    tax.name,
                    "rate",
                    correct_rate
                );
                updated_any = true;
            }

            // ✅ FIX 3: Force correct charge type
            if (tax.charge_type !== "On Net Total") {
                frappe.model.set_value(
                    tax.doctype,
                    tax.name,
                    "charge_type",
                    "On Net Total"
                );
                updated_any = true;
            }

            // ✅ FIX 4: Clear wrong actual amount (important)
            if (tax.charge_type === "Actual") {
                frappe.model.set_value(
                    tax.doctype,
                    tax.name,
                    "tax_amount",
                    0
                );
            }
        });

        // ✅ Recalculate once
        if (updated_any) {
            frm.cscript.calculate_taxes_and_totals();
        }
    });
}
function setup_custom_einvoice_actions(frm) {

    if (frm.doc.docstatus == 2) return;    
    frappe.call({
        method: 'nj_features.overrides.sales_invoice.validate_eligibility',
        args: { doc: frm.doc },
        callback: function(res) {
            const invoice_eligible = res.message;
            if (!invoice_eligible) return;

            const { doctype, irn, irn_cancelled, ewaybill, eway_bill_cancelled, name, qrcode_image, __unsaved } = frm.doc;

            // Remove existing E-Invoicing buttons if any
            frm.remove_custom_button(__('Generate IRN'), __('E Invoicing'));
            frm.remove_custom_button(__('Cancel IRN'), __('E Invoicing'));
            frm.remove_custom_button(__('Generate E-Way Bill'), __('E Invoicing'));
            frm.remove_custom_button(__('Cancel E-Way Bill'), __('E Invoicing'));
            frm.remove_custom_button(__('Generate QRCode'), __('E Invoicing'));

            // Helper function to add custom buttons
            const add_custom_button = (label, action) => {
                frm.add_custom_button(label, action, __('E Invoicing'));
            };

            // Helper function to show E-Way Bill button after IRN click
            const show_eway_bill_after_irn = () => {
                setTimeout(() => {
                    // Remove Generate IRN button
                    frm.remove_custom_button(__('Generate IRN'), __('E Invoicing'));
                    
                    // Add E-Way Bill button
                    add_eway_bill_button();
                    
                    // Show other buttons based on current document state
                    if (frm.doc.irn && !frm.doc.irn_cancelled && !frm.doc.ewaybill) {
                        add_cancel_irn_button();
                    }
                    
                    if (frm.doc.irn && !frm.doc.irn_cancelled) {
                        add_qrcode_button();
                    }
                    
                    if (frm.doc.irn && frm.doc.ewaybill && !frm.doc.irn_cancelled && !frm.doc.eway_bill_cancelled) {
                        add_cancel_eway_bill_button();
                    }
                }, 100);
            };

            // E-Way Bill Button Function
            const add_eway_bill_button = () => {                
                const action = () => {
                    const d = new frappe.ui.Dialog({
                        title: __('Generate E-Way Bill'),
                        size: "large",
                        fields: get_custom_ewaybill_fields(frm), // Use custom function
                        primary_action: function() {
                            const data = d.get_values();
                            
                            // Add your custom validation logic here
                            console.log('Custom logic: Before generating E-Way Bill', data);
                            
                            // Check if IRN field has value to determine which method to call
                            const irn_value = frm.doc.irn || '';
                            const has_irn = irn_value.trim() !== '';
                            
                            // Determine method and args based on IRN presence
                            let method_to_call, call_args;
                            
                            if (has_irn) {
                                // If IRN exists, use the standard ERPNext method
                                
                                method_to_call = 'erpnext.regional.india.e_invoice.utils.generate_eway_bill';
                                call_args = {
                                    doctype,
                                    docname: name,
                                    irn: irn_value,
                                    ...data
                                };
                                console.log('Using standard ERPNext method - IRN exists:', irn_value);
                            } else {
                                // If IRN is empty, use the custom method
                                
                                method_to_call = 'nj_features.overrides.sales_invoice.generate_eway_bill';
                                call_args = {
                                    doctype,
                                    docname: name,
                                    irn: irn_value, // Pass empty IRN
                                    ...data
                                };
                                console.log('Using custom method - IRN is empty');
                            }
                            
                            frappe.call({
                                method: method_to_call,
                                args: call_args,
                                freeze: true,
                                callback: () => {
                                    // Add your custom logic here after generating E-Way Bill
                                    console.log('Custom logic: After generating E-Way Bill');
                                    
                                    frappe.show_alert({
                                        message: __('E-Way Bill Generated successfully'),
                                        indicator: 'green'
                                    }, 7);
                                    frm.reload_doc();
                                    d.hide();
                                },
                                error: () => {
                                    frappe.show_alert({
                                        message: __('E-Way Bill was not Generated'),
                                        indicator: 'red'
                                    }, 7);
                                    d.hide();
                                }
                            });
                        },
                        primary_action_label: __('Submit')
                    });
                    
                    // Custom transporter field change handler
                    d.fields_dict.transporter.df.onchange = function () {
                        const transporter = d.fields_dict.transporter.value;
                        if (transporter) {
                            frappe.db.get_value('Supplier', transporter, ['gst_transporter_id', 'supplier_name'])
                                .then(({ message }) => {
                                    d.set_value('gst_transporter_id', message.gst_transporter_id);
                                    d.set_value('transporter_name', message.supplier_name);
                                });
                        } else {
                            d.set_value('gst_transporter_id', '');
                            d.set_value('transporter_name', '');
                        }
                    };
                    
                    // Custom driver field change handler
                    d.fields_dict.driver.df.onchange = function () {
                        const driver = d.fields_dict.driver.value;
                        if (driver) {
                            frappe.db.get_value('Driver', driver, ['full_name'])
                                .then(({ message }) => {
                                    d.set_value('driver_name', message.full_name);
                                });
                        } else {
                            d.set_value('driver_name', '');
                        }
                    };
                    
                    d.show();
                };
                add_custom_button(__("Generate E-Way Bill"), action);
            };
            // const add_eway_bill_button = () => {
            //     console.log("Adding E-Way Bill button=======================================================");
                
            //     const action = () => {
            //         const d = new frappe.ui.Dialog({
            //             title: __('Generate E-Way Bill'),
            //             size: "large",
            //             fields: get_custom_ewaybill_fields(frm), // Use custom function
            //             primary_action: function() {
            //                 const data = d.get_values();
                            
            //                 // Add your custom validation logic here
            //                 console.log('Custom logic: Before generating E-Way Bill', data);
                            
            //                 frappe.call({
            //                     method: 'nj_features.overrides.sales_invoice.generate_eway_bill',
            //                     args: {
            //                         doctype,
            //                         docname: name,
            //                         irn: frm.doc.irn || '', // Use current IRN from doc
            //                         ...data
            //                     },
            //                     freeze: true,
            //                     callback: () => {
            //                         // Add your custom logic here after generating E-Way Bill
            //                         console.log('Custom logic: After generating E-Way Bill');
                                    
            //                         frappe.show_alert({
            //                             message: __('E-Way Bill Generated successfully'),
            //                             indicator: 'green'
            //                         }, 7);
            //                         frm.reload_doc();
            //                         d.hide();
            //                     },
            //                     error: () => {
            //                         frappe.show_alert({
            //                             message: __('E-Way Bill was not Generated'),
            //                             indicator: 'red'
            //                         }, 7);
            //                         d.hide();
            //                     }
            //                 });
            //             },
            //             primary_action_label: __('Submit')
            //         });
                    
            //         // Custom transporter field change handler
            //         d.fields_dict.transporter.df.onchange = function () {
            //             const transporter = d.fields_dict.transporter.value;
            //             if (transporter) {
            //                 frappe.db.get_value('Supplier', transporter, ['gst_transporter_id', 'supplier_name'])
            //                     .then(({ message }) => {
            //                         d.set_value('gst_transporter_id', message.gst_transporter_id);
            //                         d.set_value('transporter_name', message.supplier_name);
            //                     });
            //             } else {
            //                 d.set_value('gst_transporter_id', '');
            //                 d.set_value('transporter_name', '');
            //             }
            //         };
                    
            //         // Custom driver field change handler
            //         d.fields_dict.driver.df.onchange = function () {
            //             const driver = d.fields_dict.driver.value;
            //             if (driver) {
            //                 frappe.db.get_value('Driver', driver, ['full_name'])
            //                     .then(({ message }) => {
            //                         d.set_value('driver_name', message.full_name);
            //                     });
            //             } else {
            //                 d.set_value('driver_name', '');
            //             }
            //         };
                    
            //         d.show();
            //     };
            //     add_custom_button(__("Generate E-Way Bill"), action);
            // };

            // Cancel IRN Button Function
            const add_cancel_irn_button = () => {
                const fields = [
                    {
                        "label": "Reason",
                        "fieldname": "reason",
                        "fieldtype": "Select",
                        "reqd": 1,
                        "default": "1-Duplicate",
                        "options": ["1-Duplicate", "2-Data Entry Error", "3-Order Cancelled", "4-Other"]
                    },
                    {
                        "label": "Remark",
                        "fieldname": "remark",
                        "fieldtype": "Data",
                        "reqd": 1
                    }
                ];
                
                const action = () => {
                    const d = new frappe.ui.Dialog({
                        title: __("Cancel IRN"),
                        fields: fields,
                        primary_action: function() {
                            const data = d.get_values();
                            
                            // Add your custom validation logic here
                            console.log('Custom logic: Before cancelling IRN', data);
                            
                            frappe.call({
                                method: 'erpnext.regional.india.e_invoice.utils.cancel_irn',
                                args: {
                                    doctype,
                                    docname: name,
                                    irn: irn,
                                    reason: data.reason.split('-')[0],
                                    remark: data.remark
                                },
                                freeze: true,
                                callback: () => {
                                    // Add your custom logic here after cancelling IRN
                                    console.log('Custom logic: After cancelling IRN');
                                    frm.reload_doc();
                                    d.hide();
                                },
                                error: () => d.hide()
                            });
                        },
                        primary_action_label: __('Submit')
                    });
                    d.show();
                };
                add_custom_button(__("Cancel IRN"), action);
            };

            // Cancel E-Way Bill Button Function
            const add_cancel_eway_bill_button = () => {
                const action = () => {
                    // Add your custom logic here before cancelling E-Way Bill
                    console.log('Custom logic: Before cancelling E-Way Bill');
                    
                    frappe.confirm(
                        __("Have you cancelled e-way bill on the portal?"),
                        () => {
                            frappe.call({
                                method: "erpnext.regional.india.e_invoice.utils.cancel_eway_bill",
                                args: { doctype, docname: name },
                                freeze: true,
                                callback: () => {
                                    // Add your custom logic here after cancelling E-Way Bill
                                    console.log('Custom logic: After cancelling E-Way Bill');
                                    frm.reload_doc();
                                },
                            });
                        },
                        () => {
                            frappe.show_alert(
                                {
                                    message: __(
                                        "Please cancel e-way bill on the portal first."
                                    ),
                                    indicator: "orange",
                                },
                                5
                            );
                        }
                    );
                };
                add_custom_button(__("Cancel E-Way Bill"), action);
            };

            // Generate QRCode Button Function
            const add_qrcode_button = () => {
                let is_qrcode_attached = false;
                if (qrcode_image && frm.attachments) {
                    let attachments = frm.attachments.get_attachments();
                    if (attachments.length != 0) {
                        for (let i = 0; i < attachments.length; i++) {
                            if (attachments[i].file_url == qrcode_image) {
                                is_qrcode_attached = true;
                                break;
                            }
                        }
                    }
                }
                
                if (!is_qrcode_attached) {
                    const action = () => {
                        if (frm.doc.__unsaved) {
                            frappe.throw(__('Please save the document to generate QRCode.'));
                        }
                        
                        // Add your custom logic here before generating QRCode
                        console.log('Custom logic: Before generating QRCode');
                        
                        const dialog = frappe.msgprint({
                            title: __("Generate QRCode"),
                            message: __("Generate and attach QR Code using IRN?"),
                            primary_action: {
                                action: function() {
                                    frappe.call({
                                        method: 'erpnext.regional.india.e_invoice.utils.generate_qrcode',
                                        args: { doctype, docname: name },
                                        freeze: true,
                                        callback: () => {
                                            // Add your custom logic here after generating QRCode
                                            console.log('Custom logic: After generating QRCode');
                                            frm.reload_doc();
                                            dialog.hide();
                                        },
                                        error: () => dialog.hide()
                                    });
                                }
                            },
                            primary_action_label: __('Yes')
                        });
                        dialog.show();
                    };
                    add_custom_button(__("Generate QRCode"), action);
                }
            };

            // Check if IRN button was already clicked (use a custom flag)
            const irn_button_clicked = frm.doc.__irn_button_clicked || false;

            // INITIALLY: Show only Generate IRN button if no IRN exists and button wasn't clicked
            if (!irn && !__unsaved && !irn_button_clicked) {
                
                const action = () => {
                    if (frm.doc.__unsaved) {
                        frappe.throw(__('Please save the document to generate IRN.'));
                    }
                    
                    // Mark that IRN button was clicked
                    frm.doc.__irn_button_clicked = true;
                    
                    // Add your custom logic here before generating IRN
                    console.log('Custom logic: Before generating IRN');
                    
                    frappe.call({
                        method: 'erpnext.regional.india.e_invoice.utils.get_einvoice',
                        args: { doctype, docname: name },
                        freeze: true,
                        callback: (res) => {
                            const einvoice = res.message;
                            
                            // Add your custom logic here after getting einvoice
                            console.log('Custom logic: After getting einvoice', einvoice);
                            
                            show_einvoice_preview(frm, einvoice);
                            
                            // Show E-Way Bill button after IRN generation attempt (success)
                            show_eway_bill_after_irn();
                        },
                        error: (err) => {
                            // Even if IRN generation fails, show E-Way Bill button
                            console.log('IRN generation failed, but showing E-Way Bill button');
                            show_eway_bill_after_irn();
                        }
                    });
                };
                add_custom_button(__("Generate IRN"), action);
            }
            
            // AFTER IRN BUTTON CLICK: Show E-Way Bill and other buttons
            else {
                // Show E-Way Bill button if no ewaybill exists
                if (!ewaybill) {
                    add_eway_bill_button();
                }

                // Show other buttons based on current state
                if (irn && !irn_cancelled && !ewaybill) {
                    add_cancel_irn_button();
                }

                // Show Cancel E-Way Bill button if conditions are met
                if (irn && ewaybill && !irn_cancelled && !eway_bill_cancelled) {
                    add_cancel_eway_bill_button();
                }

                // Show QRCode button if IRN exists
                if (irn && !irn_cancelled) {
                    add_qrcode_button();
                }
            }
        }
    });
}

const get_custom_ewaybill_fields = (frm) => {
    
	return [
		{
			fieldname: "eway_part_a_section_break",
			fieldtype: "Section Break",
			label: "Part A",
		},
		{
			fieldname: "transporter",
			label: "Transporter",
			fieldtype: "Link",
			options: "Supplier",
			default: frm.doc.transporter_names,
		},
		{
			fieldname: "transporter_name",
			label: "Transporter Name",
			fieldtype: "Data",
			read_only: 1,
			default: frm.doc.transporter_names,
			depends_on: "transporter",
		},
		{
			fieldname: "part_a_column_break",
			fieldtype: "Column Break",
		},
		{
			fieldname: "gst_transporter_id",
			label: "GST Transporter ID",
			fieldtype: "Data",
			default: frm.doc.transporter_id,
		},
		{
			fieldname: "distance",
			label: "Distance (in km)",
			fieldtype: "Float",
			default: frm.doc.distance,
			description: 'Set as zero to auto calculate distance using pin codes',
		},
		{
			fieldname: "eway_part_b_section_break",
			fieldtype: "Section Break",
			label: "Part B",
		},
		{
			fieldname: "mode_of_transport",
			label: "Mode of Transport",
			fieldtype: "Select",
			options: `\nRoad\nAir\nRail\nShip`,
			default: frm.doc.mode_of_transport,
		},
		{
			fieldname: "gst_vehicle_type",
			label: "GST Vehicle Type",
			fieldtype: "Select",
			options: `Regular\nOver Dimensional Cargo (ODC)`,
			depends_on: 'eval:(doc.mode_of_transport === "Road")',
			default: frm.doc.gst_vehicle_type,
		},
		{
			fieldname: "vehicle_no",
			label: "Vehicle No",
			fieldtype: "Data",
			default: frm.doc.vehicle_no,
		},
		{
			fieldname: "part_b_column_break",
			fieldtype: "Column Break",
		},
		{
			fieldname: "lr_date",
			label: "Transport Receipt Date",
			fieldtype: "Date",
			default: frm.doc.lr_date,
		},
		{
			fieldname: "lr_no",
			label: "Transport Receipt No",
			fieldtype: "Data",
			default: frm.doc.invoice_no,
		},
		{
			fieldname: "driver",
			label: "Driver",
			fieldtype: "Link",
			options: "Driver",
			default: frm.doc.driver,
		},
		{
			fieldname: "driver_name",
			label: "Driver Name",
			fieldtype: "Data",
			fetch_from: "driver.full_name",
			read_only: 1,
			default: frm.doc.driver_name,
			depends_on: "driver",
		},
	];
};
