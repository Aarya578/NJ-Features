frappe.ui.form.on('Serial No', {
    refresh: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        frm.add_custom_button(__('Print QR Code'), function() {
            printQRCode(frm);
        }).addClass('btn-primary');
    }
});

function printQRCode(frm) {
    var docname = encodeURIComponent(frm.doc.name);
    var format = "Serial No Barcode";
    var print_trigger = 0;

    console.log("frm.doc.qr_print_count", frm.doc.qr_print_count);
    console.log("frm.doc.name", frm.doc.name);
    console.log("docname", docname);

    frappe.call({
        method: 'nj_features.nj_features.api.qr_code.generate_and_save_qrcode',
        args: {
            data: frm.doc.name
        }
    });

    frappe.db.get_value('NJ Settings', {'parameter': 'max_qr_copy'}, 'value').then((r) => {
        let max_copies = r.message.value;
        console.log("frm.doc.qr_print_count", frm.doc.qr_print_count, "max", max_copies);

        frm.doc.qr_print_count = frm.doc.qr_print_count ? frm.doc.qr_print_count + 1 : 1;

        frappe.call({
            method: "frappe.client.set_value",
            args: {
                doctype: "Serial No",
                name: frm.doc.name,
                fieldname: "qr_print_count",
                value: frm.doc.qr_print_count
            },
            callback: function(response) {
                if (frm.doc.qr_print_count > max_copies) {
                    // Prompt for reason and comment if print limit exceeded
                    frappe.prompt([
                        {
                            fieldname: 'reason',
                            label: 'Reason',
                            fieldtype: 'Link',
                            reqd: 1,
                            options: 'Master Reasons'
                        },
                        {
                            fieldname: 'comment',
                            label: 'Comment',
                            fieldtype: 'Text',
                            reqd: 1
                        }
                    ], function(values) {
                        let reason = values.reason;
                        let comment = values.comment;

                        // Add comment for print reason
                        frappe.call({
                            method: "frappe.desk.form.utils.add_comment",
                            args: {
                                reference_doctype: frm.doctype,
                                reference_name: frm.doc.name,
                                content: frappe.session.user + ' has taken 1 copy. \nReason: ' + reason + '\nComment: ' + comment,
                                comment_email: frappe.session.user,
                                comment_by: frappe.session.user_fullname,
                            },
                            callback: function() {
                                // Generate QR code and open the print view
                                frappe.call({
                                    method: "nj_features.qr_code.get_print_format_role",
                                    callback: function(r) {
                                        if (r.message == true) {
                                            console.log("QR code generated successfully");
                                            window.open(frappe.urllib.get_full_url("/printview?" +
                                            "doctype=" + encodeURIComponent("Serial No") +
                                            "&name=" + docname +
                                            "&trigger_print=" + print_trigger +
                                            "&format=" + format +
                                            "&no_letterhead=0" +
                                            "&_lang=" + (frappe.boot.lang || "en")));
                                            frm.reload_doc();
                                        }else{
                                            console.log('QR code generation failed');
                                            frappe.msgprint(__('QR code generation failed.'));
                                        }
                                    }
                                });
                            }
                        });
                    });
                } else {
                    // If under the limit, directly open the print view
                    window.open(frappe.urllib.get_full_url("/printview?" +
                        "doctype=" + encodeURIComponent("Serial No") +
                        "&name=" + docname +
                        "&trigger_print=" + print_trigger +
                        "&format=" + format +
                        "&no_letterhead=0" +
                        "&_lang=" + (frappe.boot.lang || "en")));
                    frm.reload_doc();
                }
            }
        });
    });
}
