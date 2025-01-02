frappe.provide("erpnext.buying");
{% include 'erpnext/public/js/controllers/buying.js' %};

frappe.ui.form.on('Purchase Order', {
    onload() { $('.col-lg-2.layout-side-section').hide(); },

    refresh: function(frm) {
        console.log('refreshing....');
        // if (frm.doc.docstatus == 1 && frm.doc.status != "Closed" && frm.doc.status != "On Hold") {
            
        //     // Override Purchase Receipt button
        //     frm.add_custom_button(__('SIR Purchase Receipt'), function() {

        //         frappe.call({
        //             method: 'nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_registry_in_warehouse',
        //             args: { po_number: frm.doc.name },
        //             callback: function(r) {
        //                 console.log('response', r.message);
        //                 if (r && r.message.length > 0) {
        //                     $.each(r.message, function(i, d) {
        //                         frappe.model.nj_open_mapped_doc({
        //                             method: "nj_features.overrides.purchase_order.make_purchase_receipt",
        //                             frm: cur_frm,
        //                             args: { sir_name: d.parent },
        //                             freeze_message: __("Creating PR from Registry ...")
        //                         });
        //                     });
        //                 }
        //             }
        //         });
        //     }, __('Create'));

        //     // Material to Supplier logic
        //     if (frm.doc.is_subcontracted === "Yes" && me.has_unsupplied_items()) {
        //         frm.page.remove_inner_button(__('Material to Supplier'), __('Transfer'));
        //         frm.add_custom_button(__('Material to Supplier'), function() {
        //             me.make_stock_entry();
        //         }, __("Transfer"));
        //     }
        // }
    },

    make_purchase_receipt: function(frm) {
        console.log('making purchase receipt...')
    },
    
    has_warranty(frm) {
        if (frm.doc.has_warranty == 0 && frm.doc.docstatus == 0) {
            frm.set_value('warranty_days', 0);
        }
    },

    validate: function(frm) {
        var postingDate = frm.doc.transaction_date;
        var numberOfDays = frm.doc.warranty_days;
        var warrantyDate = frappe.datetime.add_days(postingDate, numberOfDays);

        cur_frm.set_value('warrenty_till_date', warrantyDate)
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


frappe.ui.form.on("Purchase Order Warrenty for Specific Parts", {
    purchase_order_warrenty_for_specific_parts_add: function(frm, cdt, cdn) {
        var child = locals[cdt][cdn];
        frappe.model.set_value(cdt, cdn, 'warranty_days', frm.doc.warranty_days);
    }
})