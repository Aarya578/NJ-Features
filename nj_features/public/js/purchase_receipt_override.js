console.log("purchase_receipt_override.js loaded");

frappe.ui.form.on("Purchase Receipt", {

    proof_image: function(frm) {
        console.log("PR proof_image changed", frm.doc.name, frm.doc.proof_image);

        if (!frm.doc.proof_image) {
            console.log("No proof image uploaded.");
            return;
        }

        // Must be saved first (needs a name)
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

        // Save the form first so proof_image is persisted, then run OCR
        frm.save().then(() => {
            _run_pr_invoice_scan(frm);
        });
    },

    after_save: function(frm) {
        console.log("PR after_save triggered", frm.doc.name, frm.doc.proof_image);

        // Only run if proof_image exists AND scan not already triggered by field change
        if (!frm.doc.proof_image) return;
        if (frm.__pr_invoice_scan_running) return;
        if (frm.__pr_scan_done_for === frm.doc.proof_image) return; // already ran for this image

        _run_pr_invoice_scan(frm);
    }
});


function _run_pr_invoice_scan(frm) {
    if (frm.__pr_invoice_scan_running) return;

    frm.__pr_invoice_scan_running = true;
    frm.__pr_scan_done_for = frm.doc.proof_image; // mark so after_save doesn't double-fire

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

            // Build result HTML
            let html = "<div>";
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

            // Refresh connections section so PI shows up
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