console.log("purchase_receipt_override.js loaded");

// ─────────────────────────────────────────
// PURCHASE RECEIPT — MAIN FORM EVENTS
// ─────────────────────────────────────────

frappe.ui.form.on("Purchase Receipt", {

    onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        frm.refresh_field("items");
    },

    refresh: function(frm) {
        // Set UOM query on refresh for existing rows (show all UOMs)
        frm.set_query('uom', 'items', function(doc, cdt, cdn) {
            var r = locals[cdt][cdn];
            if (!r.item_code) return {};
            return {
                query: 'nj_features.overrides.purchase_receipt.get_item_uoms_for_query',
                filters: { item_code: r.item_code }
            };
        });

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

        if ((frm.doc.items || []).length) {
            frm.add_custom_button(__('Print All Items Barcode'), async function() {
                await nj_pr_print_all_items(frm);
            }).addClass('btn-primary');
        }
    },

    fetch_unique_records: function(frm) {
        frappe.call({
            method: "nj_features.overrides.purchase_receipt.fetch_unique_records",
            args: { doc: frm.doc },
            freeze: true,
            freeze_message: "Fetching Unique Records...",
            callback: function(r) {
                if (!r.message) return;
                frm.clear_table("filtered_table");
                r.message.forEach(row => {
                    let child = frm.add_child("filtered_table");
                    child.item_code = row.item_code;
                    child.qty = row.qty;
                    child.rate = row.rate;
                    child.amount = row.amount;
                    child.serial_no = row.serial_no;
                });
                frm.refresh_field("filtered_table");
            }
        });
    },

    return_items: function(frm) {
        frappe.call({
            method: "nj_features.overrides.purchase_receipt.uppeding_item_to_items",
            args: { doc: frm.doc },
            freeze: true,
            freeze_message: "Updating Return Items...",
            callback: function(r) {
                if (!r.message) return;

                frm.clear_table("items");

                r.message.forEach(row => {
                    let child = frm.add_child("items");
                    Object.keys(row).forEach(fieldname => {
                        child[fieldname] = row[fieldname];
                    });
                });

                frm.refresh_field("items");

                if (frm.cscript && frm.cscript.calculate_taxes_and_totals) {
                    frm.cscript.calculate_taxes_and_totals();
                }

                frm.dirty();
                frappe.show_alert({
                    message: __("Return items updated"),
                    indicator: "green"
                });
            }
        });
    },

    proof_image: function(frm) {
        console.log("PR proof_image changed", frm.doc.name, frm.doc.proof_image);

        if (!frm.doc.proof_image) {
            console.log("No proof image uploaded.");
            return;
        }

        if (frm.doc.__islocal) {
            frappe.msgprint({
                title: __("Save Required"),
                message: __("Please save the Purchase Receipt before uploading a proof image."),
                indicator: "orange"
            });
            return;
        }

        if (frm.__pr_invoice_scan_running) {
            console.log("PR invoice scan is already running.");
            return;
        }

        frm.save().then(() => {
            _run_pr_invoice_scan(frm);
        });
    },

    after_save: function(frm) {
        console.log("PR after_save triggered", frm.doc.name, frm.doc.proof_image);

        if (!frm.doc.proof_image) return;
        if (frm.__pr_invoice_scan_running) return;
        if (frm.__pr_scan_done_for === frm.doc.proof_image) return;

        _run_pr_invoice_scan(frm);
    }
});


// ─────────────────────────────────────────────────────────────────────────────
// FILTERED TABLE — keep amount in sync when qty/rate is edited manually
// ─────────────────────────────────────────────────────────────────────────────

frappe.ui.form.on("Filtered Table", {
    qty: function(frm, cdt, cdn) {
        nj_pr_recalc_filtered_amount(frm, cdt, cdn);
    },

    rate: function(frm, cdt, cdn) {
        nj_pr_recalc_filtered_amount(frm, cdt, cdn);
    }
});


// ─────────────────────────────────────────────────────────────────────────────
// PURCHASE RECEIPT ITEM — UOM FILTER + BARCODE PRINTING + MANUAL CONVERSION
// ─────────────────────────────────────────────────────────────────────────────

frappe.ui.form.on('Purchase Receipt Item', {

    item_code: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (!row.item_code) return;

        // Set per-row UOM query dynamically (show all UOMs)
        frm.set_query('uom', 'items', function(doc, cdt, cdn) {
            var r = locals[cdt][cdn];
            if (!r.item_code) return {};
            return {
                query: 'nj_features.overrides.purchase_receipt.get_item_uoms_for_query',
                filters: { item_code: r.item_code }
            };
        });
    },

    uom: function(frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (row.manual_conversion_override) return;
        if (!row.uom || !row.item_code) return;

        var selected_uom = row.uom;

        nj_pr_set_conversion_factor(frm, cdt, cdn, row, selected_uom);
    },

    // ── Existing: barcode printing ────────────────────────────────────────────
    print: function(frm, cdt, cdn) {
        var child_doc = locals[cdt][cdn];

        if (frm.doc.docstatus == 0) {
            frappe.call({
                method: 'nj_features.nj_features.api.qr_code.print_barcode',
                args: { doc: child_doc },
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

        if ((child_doc.qr_code_mapping || child_doc.truncated_item_code) && frm.doc.docstatus == 1) {
            window.open(frappe.urllib.get_full_url("/printview?" +
                "doctype=" + encodeURIComponent("Purchase Receipt Item") +
                "&name=" + encodeURIComponent(child_doc.name) +
                "&trigger_print=1" +
                "&format=" + "PR Item Barcode" +
                "&qr_code_name=" + child_doc.decoded_item_code +
                "&no_letterhead=1" +
                "&_lang=en"
            ));
        }
    },

    // ── Manual conversion override ────────────────────────────────────────────
    manual_conversion_override: function(frm, cdt, cdn) {
        nj_pr_toggle_conversion_editability(frm, cdt, cdn);
    },

    qty: function(frm, cdt, cdn) {
        nj_pr_recalc_stock_qty(frm, cdt, cdn);
    },

    conversion_factor: function(frm, cdt, cdn) {
        nj_pr_recalc_stock_qty(frm, cdt, cdn);
    }
    // ─────────────────────────────────────────────────────────────────────────
});


function nj_pr_apply_uom_and_cf(frm, cdt, cdn, row, selected_uom, cf) {
    frappe.model.set_value(cdt, cdn, 'uom', selected_uom);
    frappe.model.set_value(cdt, cdn, 'conversion_factor', cf);
    frappe.model.set_value(cdt, cdn, 'stock_qty', flt(row.qty || 0) * cf);
}

function nj_pr_recalc_filtered_amount(frm, cdt, cdn) {
    var row = locals[cdt][cdn];
    frappe.model.set_value(cdt, cdn, "amount", flt(row.qty || 0) * flt(row.rate || 0));
    frm.refresh_field("filtered_table");
}

function nj_pr_set_conversion_factor(frm, cdt, cdn, row, selected_uom) {
    frappe.call({
        method: 'nj_features.overrides.purchase_receipt.get_item_uoms',
        args: { item_code: row.item_code },
        callback: function(r) {
            var uoms = r.message || [];
            var match = uoms.find(u => u.uom === selected_uom);
            if (match) {
                var cf = flt(match.conversion_factor, 9);
                console.log('PR UOM:', selected_uom, '| CF:', cf, '| source=item mapping');
                nj_pr_apply_uom_and_cf(frm, cdt, cdn, row, selected_uom, cf);
                return;
            }

            frappe.call({
                method: 'erpnext.stock.get_item_details.get_conversion_factor',
                args: { item_code: row.item_code, uom: selected_uom },
                callback: function(res) {
                    var conversion_factor = res && res.message ? flt(res.message.conversion_factor, 9) : 0;

                    if (conversion_factor > 0) {
                        console.log('PR UOM:', selected_uom, '| CF:', conversion_factor, '| source=erpnext fallback');
                        nj_pr_apply_uom_and_cf(frm, cdt, cdn, row, selected_uom, conversion_factor);
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

// ─────────────────────────────────────────
// OCR — RUN PR INVOICE SCAN
// ─────────────────────────────────────────

function _run_pr_invoice_scan(frm) {
    if (frm.__pr_invoice_scan_running) return;

    frm.__pr_invoice_scan_running = true;
    frm.__pr_scan_done_for = frm.doc.proof_image;

    console.log("Running PR invoice scan for", frm.doc.name, frm.doc.proof_image);

    frappe.call({
        method: "nj_features.nj_features.api.invoice_ocr.process_pr_invoice_scan",
        args: {
            pr_name: frm.doc.name,
            file_url: frm.doc.proof_image
        },
        freeze: true,
        freeze_message: __("Reading invoice and creating Purchase Invoice..."),
        callback: function(r) {
            console.log("PR OCR success", r);
            frm.__pr_invoice_scan_running = false;

            const res = r.message;
            if (!res) {
                frappe.msgprint(__("No response received from server."));
                return;
            }

            if (!res.success) {
                frappe.msgprint({
                    title: __("OCR / PI Creation Failed"),
                    message: res.error || __("Could not process invoice automatically."),
                    indicator: "red"
                });
                return;
            }

            let html = "<div>";
            let hasNewPI = false;

            if (res.pi_list && res.pi_list.length) {
                res.pi_list.forEach(row => {
                    const piLink = row.pi
                        ? `<a href="/app/purchase-invoice/${row.pi}" target="_blank">${row.pi}</a>`
                        : "-";

                    html += `<p>
                        <b>PO:</b> ${row.po || "-"}<br>
                        <b>PI:</b> ${piLink}<br>
                        <b>Status:</b> ${row.status || "-"}<br>
                        <b>Message:</b> ${row.message || "-"}<br>`;

                    if (row.warnings && row.warnings.length) {
                        html += "<b>Warnings:</b><ul>";
                        row.warnings.forEach(w => {
                            html += `<li style="color:orange">${w}</li>`;
                        });
                        html += "</ul>";
                    }

                    html += "</p><hr>";

                    if (row.pi && row.status !== "exists") {
                        hasNewPI = true;
                        setTimeout(() => {
                            window.open(`/app/purchase-invoice/${row.pi}`, "_blank");
                        }, 800);
                    }
                });
            } else {
                html += "<p>No Purchase Invoices were created.</p>";
            }
            html += "</div>";

            frappe.msgprint({
                title: __("Purchase Invoice Processing Result"),
                message: html,
                indicator: res.pi_list && res.pi_list.length ? "green" : "orange"
            });

            frm.reload_doc();
        },
        error: function(r) {
            console.log("PR OCR error", r);
            frm.__pr_invoice_scan_running = false;
            frappe.msgprint({
                title: __("OCR / PI Creation Failed"),
                message: __("Could not process invoice automatically. Please create PI manually."),
                indicator: "red"
            });
        }
    });
}


// ─────────────────────────────────────────────────────────────────────────────
// MANUAL CONVERSION OVERRIDE — PR helpers
// ─────────────────────────────────────────────────────────────────────────────

function nj_pr_toggle_conversion_editability(frm, cdt, cdn) {
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

function nj_pr_recalc_stock_qty(frm, cdt, cdn) {
    var row = locals[cdt][cdn];
    if (row.manual_conversion_override && flt(row.conversion_factor) > 0) {
        var stock_qty = flt(row.qty) * flt(row.conversion_factor);
        frappe.model.set_value(cdt, cdn, "stock_qty", stock_qty);
    }
}

// ─────────────────────────────────────────────────────────────────────────────


// ─────────────────────────────────────────
// PRINT ALL ITEMS BARCODE
// ─────────────────────────────────────────

async function nj_pr_print_all_items(frm) {
    const rows = frm.doc.items || [];
    if (!rows.length) {
        frappe.msgprint("No item rows found.");
        return;
    }

    const target_rows = rows.filter(r => (r.item_code || r.component));
    const print_windows = [];

    frappe.show_progress("Printing", 0, target_rows.length, "Preparing...");

    try {
        if (frm.doc.docstatus === 0) {
            frm.disable_save();

            for (let i = 0; i < target_rows.length; i++) {
                const row = target_rows[i];
                frappe.show_progress("Printing", i + 1, target_rows.length, `Generating for row #${row.idx || (i + 1)}...`);

                const msg = await nj_pr_call_print_barcode(row);

                if (msg && msg.serial_no) {
                    await frappe.model.set_value(row.doctype, row.name, 'serial_no', msg.serial_no);
                }
                if (msg && msg.truncated_item_code) {
                    await frappe.model.set_value(row.doctype, row.name, 'truncated_item_code', msg.truncated_item_code);
                }
                if (msg && msg.decoded_item_code) {
                    await frappe.model.set_value(row.doctype, row.name, 'decoded_item_code', msg.decoded_item_code);
                }

                frm.refresh_field("items");

                const printable = (row.qr_code_mapping || row.truncated_item_code || row.decoded_item_code);
                if (printable) {
                    const w = window.open("about:blank");
                    if (w) print_windows.push({ w, row });
                }
            }

            frm.enable_save();
            await frm.save();

        } else {
            for (let i = 0; i < target_rows.length; i++) {
                const row = target_rows[i];
                const printable = (row.qr_code_mapping || row.truncated_item_code || row.decoded_item_code);
                if (printable) {
                    const w = window.open("about:blank");
                    if (w) print_windows.push({ w, row });
                }
            }
        }

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
