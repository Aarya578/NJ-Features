
frappe.provide("erpnext.buying");
{% include 'erpnext/public/js/controllers/buying.js' %};

frappe.ui.form.on('Purchase Order', {
    onload() { 
        $('.col-lg-2.layout-side-section').hide(); 


    },

    refresh: function(frm) {
        // No warranty updates on refresh - only after save
    },
    fetch_qnique_records: function (frm) {
        
        frappe.call({
            method: "nj_features.overrides.purchase_order.fetch_unique_records",
            args: {
                doc: frm.doc
            },
            freeze: true,
            freeze_message: "Fetching Unique Records...",
            callback: function (r) {
                if (!r.message) return;

                // Clear old table
                frm.clear_table("filtered_table");

                // Add new aggregated rows
                r.message.forEach(row => {
                    let child = frm.add_child("filtered_table");
                    child.item_code = row.item_code;
                    child.qty = row.qty;
                    child.rate = row.rate;
                    child.amount = row.amount;
                });

                frm.refresh_field("filtered_table");
            }
        });
    },

    fetch_warranty_days: function (frm) {
        
        frappe.call({

            method: 'nj_features.overrides.purchase_order.part_warrnty_days_after_save',
            args: {
                docname: frm.doc.name
            },
            callback: function (r) {
                if (r.message) {
                    if (r.message.error) {
                        frappe.msgprint({
                            title: __('Warranty Error'),
                            message: __(r.message.error),
                            indicator: 'red'
                        });
                    } else {
                        frappe.msgprint({
                            title: __('Warranty Updated'),
                            message: __(r.message.message),
                            indicator: 'green'
                        });
                        frm.reload_doc();
                    }
                }
            }
        });
    },
    
    has_warranty(frm) {
        if (frm.doc.has_warranty == 0 && frm.doc.docstatus == 0) {
            frm.set_value('warranty_days', 0);
        }
    },
    supplier(frm) {            
        if (!frm.doc.supplier) {
            frm.set_value('tax_withholding_category', '');
            return;
        }

        frappe.call({
            method: "nj_features.overrides.purchase_order.get_tax_without_holding",
            args: { supplier: frm.doc.supplier },
            callback(response) {
                const tax_category = response.message || '';

                frm.set_query('tax_withholding_category', () => {
                    return { filters: { name: tax_category } };
                });

                if (tax_category) {
                    frm.set_value('tax_withholding_category', tax_category);
                } else {
                    frm.set_value('tax_withholding_category', '');
                }

                frm.refresh_field('tax_withholding_category');
            }
        });
    },

    validate: function(frm) {
        let items = frm.doc.items.map(row => ({
            idx: row.idx,
            item_group: row.item_group
        }));

        frappe.call({
            method: "nj_features.overrides.purchase_order.get_item_group_cost_centers",
            args: { items: items },
            callback: function(r) {
                
                if (r.message) {
                    console.log("Cost centers:===", r.message);
                    
                    frm.doc.items.forEach(row => {
                        if (r.message[row.idx]) {
                            frappe.model.set_value(row.doctype, row.name, "cost_center", r.message[row.idx]);

                        }
                         frm.refresh_field('cost_center');
                    });
                }
            }
        });
        
        var postingDate = frm.doc.transaction_date;
        var numberOfDays = frm.doc.warranty_days;
        var warrantyDate = frappe.datetime.add_days(postingDate, numberOfDays);

        cur_frm.set_value('warrenty_till_date', warrantyDate)
        if (frm.doc.part_warranty) {
        // frappe.call({
        //     method: 'nj_features.overrides.purchase_order.part_warrnty_days_after_save',
        //     args: {
        //         doc: frm.doc // send full unsaved doc values
        //     },
        //     freeze: true,
        //     callback: function(r) {
        //         if (r.message.error){
        //             frappe.show_alert({
        //                 title: __("Warranty Update Failed"),
        //                 message: __(r.message.error),
        //                 indicator: 'red'
        //             });
        //             frappe.validated = false;
        //         }
        //         else if (r.message?.status === "updated") {
        //             frappe.show_alert({
        //                 message: r.message.message,
        //                 indicator: 'green'
        //             });
        //             // Use refresh instead of reload_doc for better performance
        //             frm.refresh();
        //         } else if (r.message?.status === "no_changes") {
        //             frappe.show_alert({
        //                 message: r.message.message,
        //                 indicator: 'blue'
        //             });
        //         }
        //     },
        //     error: function(xhr) {
        //         let responseJSON = xhr?.xhr?.responseJSON;
        //         let message = responseJSON?.message || "Error updating warranty table";
        //         frappe.msgprint({
        //             title: __("Warranty Update Failed"),
        //             message: __(message),
        //             indicator: 'red'
        //         });
        //     }
        // });

    }
    
    },


// after_save: function(frm) {
//         frappe.call({
//             method: 'nj_features.overrides.purchase_order.part_warrnty_days_after_save',
//             args: {
//                 doc: frm.doc // send full unsaved doc values
//             },
//             freeze: true,
//             callback: function(r) {
//                 if (r.message.error){
//                     frappe.show_alert({
//                         title: __("Warranty Update Failed"),
//                         message: __(r.message.error),
//                         indicator: 'red'
//                     });
//                     frappe.validated = false;
//                 }
//                 else if (r.message?.status === "updated") {
//                     frappe.show_alert({
//                         message: r.message.message,
//                         indicator: 'green'
//                     });
//                     // Use refresh instead of reload_doc for better performance
//                     frm.refresh();
//                 } else if (r.message?.status === "no_changes") {
//                     frappe.show_alert({
//                         message: r.message.message,
//                         indicator: 'blue'
//                     });
//                 }
//             },
//             error: function(xhr) {
//                 let responseJSON = xhr?.xhr?.responseJSON;
//                 let message = responseJSON?.message || "Error updating warranty table";
//                 frappe.msgprint({
//                     title: __("Warranty Update Failed"),
//                     message: __(message),
//                     indicator: 'red'
//                 });
//             }
//     });
// }



});

frappe.ui.form.on("Purchase Order Warrenty for Specific Parts", {
    purchase_order_warrenty_for_specific_parts_add: function(frm, cdt, cdn) {
        var child = locals[cdt][cdn];
        frappe.model.set_value(cdt, cdn, 'warranty_days', frm.doc.warranty_days);
    }
});

const purchaseOrderValidation = erpnext.buying.PurchaseOrderController.extend({
    close_purchase_order: function(){
        frappe.call({
            method: 'nj_features.overrides.purchase_order.check_billed_and_closed_amount',
            args: {'purchase_order': cur_frm.doc.name, 'po_grand_total': cur_frm.doc.grand_total},
            callback: function(r) {
                let closedAmount = r.message.total_closed_amount ?? 0.0
                let billedAmount = r.message.total_billed_amount ?? 0.0
                let toleranceAmount = r.message.tolerance_amount
                let diffAmount = closedAmount - billedAmount
                if (closedAmount == 0 && billedAmount == 0) {
                    console.log("No, closedAmount is ",closedAmount," and billedAmount is ", billedAmount);
                    frappe.throw("PO cannot be closed because both 'Closed Amount' and 'Billed Amount' are 0.0. Instead you can cancel the PO.");
                }// (diffAmount + toleranceAmount) >= -1 &&  - Removed
                if ((diffAmount + toleranceAmount) <= 1) {
                    console.log("Yes, Closed Amount: ", closedAmount + toleranceAmount ," <= Billed Amount: ", billedAmount);
                    erpnext.buying.PurchaseOrderController.prototype.close_purchase_order.call(me);
                } else {
                    console.log("No",closedAmount + toleranceAmount ," <> ", billedAmount);
                    frappe.throw("PO cannot be closed because 'Closed Amount: " + closedAmount + 
                    "' > 'Billed Amount: " + billedAmount + "'.");
                }
            }
        });
    }
});

$.extend(cur_frm.cscript, new purchaseOrderValidation({frm: cur_frm}));

frappe.provide("frappe.model");

$.extend(frappe.model, {
    nj_open_mapped_doc: function(opts) {
        
        if (opts.frm && opts.frm.doc.__unsaved) {
            frappe.throw(
                __(
                    "You have unsaved changes in this form. Please save before you continue."
                )
            );
        } else if (!opts.source_name && opts.frm) {
            opts.source_name = opts.frm.doc.name;
        } else if (!opts.frm && !opts.source_name) {
            opts.source_name = null;
        }

        return frappe.call({
            type: "POST",
            method: "nj_features.overrides.purchase_order.make_purchase_receipt",
            args: {
                method: opts.method,
                source_name: opts.source_name,
                sir_name: opts.args.sir_name || null,
                args: opts.args,
            },
            freeze: true,
            freeze_message: opts.freeze_message || "",
            callback: function(r) {
                if (!r.exc) {
                    frappe.model.sync(r.message);
                    if (opts.run_link_triggers) {
                        frappe.get_doc(
                            r.message.doctype,
                            r.message.name
                        ).__run_link_triggers = true;
                    }
                    frappe.set_route("Form", r.message.doctype, r.message.name);
                }
            }
        });
    }
});