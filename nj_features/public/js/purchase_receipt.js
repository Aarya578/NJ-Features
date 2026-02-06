frappe.ui.form.on('Purchase Receipt', {
    onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        if (frm.doc.docstatus == 0) {
            var user_email = frappe.session.user
            frappe.db.get_value('Employee', {'user_id': user_email, 'status': 'Active'}, 'work_warehouse').then(function(r) {

                if (r.message && r.message.work_warehouse) {

                    frm.set_value('set_warehouse', r.message.work_warehouse)

                    frm.doc.items.forEach(function(item) {
                        frappe.db.get_list('NJ Settings', {
                            filters: {'doc_type':'Warehouse', 'module':'NJ Features'},
                            fields: ['parameter', 'value']
                        }).then(function(result) {
                            result.forEach(function(setting) {

                                if (setting.parameter === item.item_group) {
                                    item.warehouse = setting.value;
                                }
                            });
                        });

                    });
                } else {
                    frappe.throw("Work Warehouse is not set for <b>User: "+user_email+"</b>. Please mail us at <strong><a href='mailto:itsupport@newjaisa.com'>itsupport@newjaisa.com</a></strong> to create an employee.")
                }
            });
        }
        frm.refresh_field("items")


        // let items = frm.doc.items.map(row => ({
        //     idx: row.idx,
        //     item_group: row.item_group
        // }));

        // frappe.call({
        //     method: "nj_features.overrides.purchase_receipt.get_item_group_cost_centers",
        //     args: { items: items },
        //     callback: function(r) {

        //         if (r.message) {
        //             console.log("Cost centers:===", r.message);

        //             frm.doc.items.forEach(row => {
        //                 if (r.message[row.idx]) {
        //                     frappe.model.set_value(row.doctype, row.name, "cost_center", r.message[row.idx]);

        //                 }
        //                  frm.refresh_field('cost_center');
        //             });
        //         }
        //     }
        // });
    },

    fetch_unique_records: function (frm) {
        
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

    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {

            frm.add_custom_button(__('Print QR Code'), function() {
                var docname = encodeURIComponent(frm.doc.name);
                var format = "Purchase Receipt Barcode";
                var print_trigger = 1;

                window.open(frappe.urllib.get_full_url("/printview?" +
                    "doctype=" + encodeURIComponent("Purchase Receipt") +
                    "&name=" + docname +
                    "&trigger_print=" + print_trigger +
                    "&format=" + format +
                    "&no_letterhead=0" +
                    "&_lang=" + (frappe.boot.lang || "en")));
            }).addClass('btn-primary');

        } else {
            frm.remove_custom_button('Print Barcode');
        }

        // ============================
        // ✅ NEW: Print All Items Button
        // ============================
        if ((frm.doc.items || []).length) {
            frm.add_custom_button(__('Print All Items Barcode'), async function() {
                await nj_pr_print_all_items(frm);
            }).addClass('btn-primary');
        }
    }
});

// Barcode printing
frappe.ui.form.on('Purchase Receipt Item', {
    // serial_no: function(frm, cdt, cdn) {
    //     var child_doc = locals[cdt][cdn];
    //     if (child_doc.serial_no && child_doc.serial_no.startsWith("NJ-")) {
    //         frappe.msgprint("Manually entered serial numbers cannot start with 'NJ-'");
    //         return;
    //     }
    // },
    print: function(frm, cdt, cdn) {

        var child_doc = locals[cdt][cdn];

        if(frm.doc.docstatus == 0){
            frappe.call({
                method: 'nj_features.nj_features.api.qr_code.print_barcode',
                args: {
                    doc: child_doc
                },
                callback: function(r) {

                    if (r.message.serial_no) {
                        frappe.model.set_value(cdt, cdn, 'serial_no', r.message.serial_no);
                    }
                    if (r.message.truncated_item_code) {
                        frappe.model.set_value(cdt, cdn, 'truncated_item_code', r.message.truncated_item_code);
                    }
                    if (r.message.decoded_item_code) {
                        frappe.model.set_value(cdt, cdn, 'decoded_item_code', r.message.decoded_item_code);
                    }
                }
            });
        }

        if((child_doc.qr_code_mapping || child_doc.truncated_item_code) && frm.doc.docstatus == 1) {
            let objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
                                        "doctype=" + encodeURIComponent("Purchase Receipt Item") +
                                        "&name=" + encodeURIComponent(child_doc.name) +
                                        "&trigger_print=1" +
                                        "&format=" + "PR Item Barcode" +
                                        "&qr_code_name=" + child_doc.decoded_item_code +
                                        "&no_letterhead=1" +
                                        "&_lang=en"
                                    ));
        }
    }
});


// =====================================================
// ✅ NEW FUNCTIONS (do not interfere with existing code)
// =====================================================

async function nj_pr_print_all_items(frm) {
    const rows = frm.doc.items || [];
    if (!rows.length) {
        frappe.msgprint("No item rows found.");
        return;
    }

    // Filter: only rows having item_code/component
    const target_rows = rows.filter(r => (r.item_code || r.component));

    // Popup blockers: open all windows immediately inside click
    // We'll fill URLs after generation.
    const print_windows = [];

    frappe.show_progress("Printing", 0, target_rows.length, "Preparing...");

    try {
        // 1) In Draft: generate mapping / serials first
        if (frm.doc.docstatus === 0) {

            frm.disable_save();

            for (let i = 0; i < target_rows.length; i++) {
                const row = target_rows[i];

                frappe.show_progress("Printing", i + 1, target_rows.length, `Generating for row #${row.idx || (i+1)}...`);

                const msg = await nj_pr_call_print_barcode(row);

                // Update row fields using model.set_value (safer)
                if (msg && msg.serial_no) {
                    await frappe.model.set_value(row.doctype, row.name, 'serial_no', msg.serial_no);
                }
                if (msg && msg.truncated_item_code) {
                    await frappe.model.set_value(row.doctype, row.name, 'truncated_item_code', msg.truncated_item_code);
                }
                if (msg && msg.decoded_item_code) {
                    await frappe.model.set_value(row.doctype, row.name, 'decoded_item_code', msg.decoded_item_code);
                }

                // refresh table
                frm.refresh_field("items");

                // Pre-open windows only for rows that are printable
                const printable = (row.qr_code_mapping || row.truncated_item_code || row.decoded_item_code);
                if (printable) {
                    const w = window.open("about:blank");
                    if (w) print_windows.push({ w, row });
                }
            }

            frm.enable_save();

            // Optional but highly recommended: save draft so child row data is persisted
            // If you DON'T want autosave, comment below 2 lines.
            await frm.save();
        } else {
            // 2) In Submitted: directly open windows for printable rows
            for (let i = 0; i < target_rows.length; i++) {
                const row = target_rows[i];
                const printable = (row.qr_code_mapping || row.truncated_item_code || row.decoded_item_code);
                if (printable) {
                    const w = window.open("about:blank");
                    if (w) print_windows.push({ w, row });
                }
            }
        }

        // 3) Assign URLs to opened windows (avoids popup block)
        for (const pw of print_windows) {
            const row = pw.row;

            const qr_name = row.decoded_item_code || row.qr_code_mapping || row.truncated_item_code || "";

            const url = frappe.urllib.get_full_url("/printview?" +
                "doctype=" + encodeURIComponent("Purchase Receipt Item") +
                "&name=" + encodeURIComponent(row.name) +
                "&trigger_print=1" +
                "&format=" + encodeURIComponent("PR Item Barcode") +
                "&qr_code_name=" + encodeURIComponent(qr_name) +
                "&no_letterhead=1" +
                "&_lang=en"
            );

            if (pw.w) pw.w.location = url;
        }

        frappe.msgprint(`Done. Printed ${print_windows.length} item rows. If nothing opened, allow popups for this site.`);

    } catch (e) {
        console.error(e);
        frm.enable_save();
        frappe.msgprint({
            title: "Print All Failed",
            message: (e && e.message) ? e.message : e,
            indicator: "red"
        });
    } finally {
        frappe.hide_progress();
        frm.enable_save();
    }
}

function nj_pr_call_print_barcode(child_row) {
    return new Promise((resolve, reject) => {
        frappe.call({
            method: 'nj_features.nj_features.api.qr_code.print_barcode',
            args: { doc: child_row },
            callback: function(r) {
                resolve((r && r.message) ? r.message : {});
            },
            error: function(err) {
                reject(err);
            }
        });
    });
}
