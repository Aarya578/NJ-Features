frappe.provide("erpnext.buying");
{% include 'erpnext/public/js/controllers/buying.js' %};

frappe.ui.form.on('Purchase Order', {
    onload() { 
        $('.col-lg-2.layout-side-section').hide(); 
    },

    refresh: function(frm) {

        // Restrict NPD Approval and Is Sample fields
        frappe.call({
            method: "frappe.client.get_value",
            args: {
                doctype: "User",
                filters: {
                    name: frappe.session.user
                },
                fieldname: "role_profile_name"
            },
            callback: function(r) {

                if (!r.message) {
                    return;
                }

                let role_profile = (r.message && r.message.role_profile_name) || "";

                let is_npd_manager = (
                    role_profile === "NPD Manager"
                );

                frm.set_df_property(
                    "npd_approval_",
                    "read_only",
                    !is_npd_manager
                );

                frm.set_df_property(
                    "is_sample",
                    "read_only",
                    !is_npd_manager
                );

                frm.refresh_field("npd_approval_");
                frm.refresh_field("is_sample");
            }
        });


        // Existing UOM query
        frm.set_query('uom', 'items', function(doc, cdt, cdn) {
            var r = locals[cdt][cdn];
            if (!r.item_code) return {};
            return {
                query: 'nj_features.overrides.purchase_order.get_item_uoms_for_query',
                filters: { item_code: r.item_code }
            };
        });
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

                frm.clear_table("filtered_table");

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

        cur_frm.set_value('warrenty_till_date', warrantyDate);
    }
});


// ─────────────────────────────────────────────────────────────────────────────
// PURCHASE ORDER ITEM — UOM FILTER + MANUAL CONVERSION OVERRIDE
// ─────────────────────────────────────────────────────────────────────────────

frappe.ui.form.on("Purchase Order Item", {

    item_code: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (!row.item_code) return;

        // Set per-row UOM query dynamically (show all UOMs)
        frm.set_query('uom', 'items', function(doc, cdt, cdn) {
            var r = locals[cdt][cdn];
            if (!r.item_code) return {};
            return {
                query: 'nj_features.overrides.purchase_order.get_item_uoms_for_query',
                filters: { item_code: r.item_code }
            };
        });
    },

    uom: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (row.manual_conversion_override) return;
        if (!row.uom || !row.item_code) return;

        var selected_uom = row.uom;

        nj_po_set_conversion_factor(frm, cdt, cdn, row, selected_uom);
    },

    manual_conversion_override: function(frm, cdt, cdn) {
        nj_po_toggle_conversion_editability(frm, cdt, cdn);
    },

    qty: function(frm, cdt, cdn) {
        nj_po_recalc_stock_qty(frm, cdt, cdn);
    },

    conversion_factor: function(frm, cdt, cdn) {
        nj_po_recalc_stock_qty(frm, cdt, cdn);
    }
});

function nj_po_toggle_conversion_editability(frm, cdt, cdn) {
    var row = locals[cdt][cdn];
    var is_override = !!row.manual_conversion_override;

    frm.fields_dict["items"].grid.update_docfield_property(
        "conversion_factor", "read_only", is_override ? 0 : 1
    );
    frm.fields_dict["items"].grid.refresh();

    if (!is_override) {
        if (row.item_code && row.uom) {
            frappe.call({
                method: "erpnext.stock.get_item_details.get_conversion_factor",
                args: { item_code: row.item_code, uom: row.uom },
                callback: function(r) {
                    if (r && r.message) {
                        frappe.model.set_value(cdt, cdn, "conversion_factor", r.message.conversion_factor || 1);
                    }
                }
            });
        }
    }
}

function nj_po_recalc_stock_qty(frm, cdt, cdn) {
    var row = locals[cdt][cdn];
    if (row.manual_conversion_override && flt(row.conversion_factor) > 0) {
        var stock_qty = flt(row.qty) * flt(row.conversion_factor);
        frappe.model.set_value(cdt, cdn, "stock_qty", stock_qty);
    }
}

// ─────────────────────────────────────────────────────────────────────────────


function nj_po_apply_uom_and_cf(frm, cdt, cdn, row, selected_uom, cf) {
    frappe.model.set_value(cdt, cdn, 'uom', selected_uom);
    frappe.model.set_value(cdt, cdn, 'conversion_factor', cf);
    frappe.model.set_value(cdt, cdn, 'stock_qty', flt(row.qty || 0) * cf);
}

function nj_po_set_conversion_factor(frm, cdt, cdn, row, selected_uom) {
    frappe.call({
        method: 'nj_features.overrides.purchase_order.get_item_uoms',
        args: { item_code: row.item_code },
        callback: function(r) {
            var uoms = r.message || [];
            var match = uoms.find(u => u.uom === selected_uom);
            if (match) {
                var cf = flt(match.conversion_factor, 9);
                console.log('PO UOM:', selected_uom, '| CF:', cf, '| source=item mapping');
                nj_po_apply_uom_and_cf(frm, cdt, cdn, row, selected_uom, cf);
                return;
            }

            frappe.call({
                method: 'erpnext.stock.get_item_details.get_conversion_factor',
                args: { item_code: row.item_code, uom: selected_uom },
                callback: function(res) {
                    var conversion_factor = res && res.message ? flt(res.message.conversion_factor, 9) : 0;

                    if (conversion_factor > 0) {
                        console.log('PO UOM:', selected_uom, '| CF:', conversion_factor, '| source=erpnext fallback');
                        nj_po_apply_uom_and_cf(frm, cdt, cdn, row, selected_uom, conversion_factor);
                        return;
                    }

                    frappe.show_alert({
                        message: __('Selected UOM is not mapped for this item. Enable Manual Conversion Override and enter the conversion factor.'),
                        indicator: 'orange'
                    }, 7);
                }
            });
        }
    });
}

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
                }
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