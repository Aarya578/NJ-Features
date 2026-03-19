console.log("purchase_receipt_override.js loaded");

frappe.ui.form.on("Purchase Receipt", {
    after_save: function(frm) {
        console.log("PR after_save triggered", frm.doc.name, frm.doc.proof_image);

        if (!frm.doc.proof_image) return;
        if (frm.__pr_invoice_scan_running) return;

        frm.__pr_invoice_scan_running = true;

        frappe.call({
            method: "nj_features.nj_features.nj_features.api.invoice_ocr.process_pr_invoice_scan",
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

                let html = "";

                if (res.pi_list && res.pi_list.length) {
                    html += "<div>";
                    res.pi_list.forEach(row => {
                        html += `<p><b>PO:</b> ${row.po || "-"}<br>`;
                        html += `<b>PI:</b> ${row.pi || "-"}<br>`;
                        html += `<b>Status:</b> ${row.status || "-"}<br>`;
                        html += `<b>Message:</b> ${row.message || "-"}<br>`;

                        if (row.warnings && row.warnings.length) {
                            html += "<b>Warnings:</b><ul>";
                            row.warnings.forEach(w => {
                                html += `<li>${w}</li>`;
                            });
                            html += "</ul>";
                        }

                        html += "</p><hr>";
                    });
                    html += "</div>";
                }

                frappe.msgprint({
                    title: __("Purchase Invoice Processing Result"),
                    message: html || __("Processing completed."),
                    indicator: "green"
                });
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
});