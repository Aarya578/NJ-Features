frappe.ui.form.on('Purchase Receipt', {

    after_save: function(frm) {
        // Trigger PI creation after PR is saved and has a proof_image
        const file_url = frm.doc.proof_image;
        if (!file_url) return;

        // Don't trigger for cancelled or amended docs
        if (frm.doc.docstatus === 2) return;

        // Check if PI already created for this PR (avoid duplicate)
        const already_processed = frm.doc.__already_processed_ocr;
        if (already_processed === frm.doc.proof_image) return;

        _create_pi_from_pr(frm);
    },

    proof_image: function(frm) {
        // Reset the processed flag when a new image is uploaded
        frm.doc.__already_processed_ocr = null;
    }
});


function _create_pi_from_pr(frm) {
    if (!frm.doc.name || frm.doc.name.startsWith('new-')) {
        frappe.msgprint({
            title: 'Save Required',
            message: 'Please save the Purchase Receipt first.',
            indicator: 'orange'
        });
        return;
    }

    const file_url = frm.doc.proof_image;
    if (!file_url) return;

    // Mark as processing to avoid duplicate calls
    frm.doc.__already_processed_ocr = file_url;

    frappe.show_progress(
        'Creating Purchase Invoice...',
        30, 100,
        'Reading invoice image and creating PI'
    );

    frappe.call({
        method: 'nj_features.nj_features.api.invoice_ocr.process_pr_invoice_scan',
        args: {
            pr_name: frm.doc.name,
            file_url: file_url
        },
        timeout: 60,
        callback: function(r) {
            frappe.hide_progress();

            if (!r.message || !r.message.success) {
                frappe.msgprint({
                    title: 'Invoice Scan Failed',
                    message: r.message?.error || 'Could not process invoice. Please create PI manually.',
                    indicator: 'red'
                });

                // Show manual PI creation button
                frappe.confirm(
                    'Would you like to create Purchase Invoice manually?',
                    function() {
                        frappe.new_doc('Purchase Invoice', {
                            supplier: frm.doc.supplier,
                            company: frm.doc.company
                        });
                    }
                );
                return;
            }

            const result = r.message;
            const pi_list = result.pi_list || [];

            if (pi_list.length === 0) {
                frappe.msgprint({
                    title: 'No PI Created',
                    message: 'No items found to create Purchase Invoice.',
                    indicator: 'orange'
                });
                return;
            }

            // Process each PI result
            pi_list.forEach(function(pi_result, index) {
                setTimeout(function() {
                    _handle_pi_result(pi_result, frm);
                }, index * 500); // stagger alerts for multiple POs
            });

            // Refresh PR form to show updated status
            frm.reload_doc();
        },
        error: function(err) {
            frappe.hide_progress();
            frappe.msgprint({
                title: 'Error',
                message: 'Failed to process invoice scan. Please try again or create PI manually.',
                indicator: 'red'
            });
        }
    });
}


function _handle_pi_result(pi_result, frm) {
    if (pi_result.status === 'exists') {
        // PI already exists
        frappe.show_alert({
            message: `PI already exists: <a href="/app/purchase-invoice/${pi_result.pi}" target="_blank">${pi_result.pi}</a>`,
            indicator: 'blue'
        }, 7);
        return;
    }

    if (pi_result.status === 'error' || !pi_result.pi) {
        frappe.msgprint({
            title: `PI Creation Failed for PO ${pi_result.po}`,
            message: pi_result.message || 'Unknown error',
            indicator: 'red'
        });
        return;
    }

    // Show warnings if any
    if (pi_result.warnings && pi_result.warnings.length > 0) {
        const warning_html = pi_result.warnings
            .map(w => `<li>${w}</li>`)
            .join('');

        frappe.msgprint({
            title: `⚠️ PI Created with Warnings — ${pi_result.pi}`,
            message: `<ul>${warning_html}</ul><br>
                      <a href="/app/purchase-invoice/${pi_result.pi}" target="_blank">
                        Open PI ${pi_result.pi}
                      </a>`,
            indicator: 'orange'
        });
    } else {
        // Success — no warnings
        frappe.show_alert({
            message: `✅ PI ${pi_result.pi} created and submitted successfully`,
            indicator: 'green'
        }, 7);
    }

    // Open PI in new tab
    setTimeout(function() {
        window.open(`/app/purchase-invoice/${pi_result.pi}`, '_blank');
    }, 800);
}