frappe.ui.form.on('Serial No', {
    refresh: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        frm.add_custom_button(__('Print QR Code'), function() {
            var docname = encodeURIComponent(frm.doc.name);
            var format = "Serial No Barcode";
            var print_trigger = 0;

            console.log("frm.doc.qr_print_count", frm.doc.qr_print_count);
            console.log("frm.doc.name", frm.doc.name);
            console.log("docname", docname);

            frappe.call({
                method: 'nj_features.qr_code.generate_and_save_qrcode',
                args: {
                    data: frm.doc.name
                }
            });

            frappe.db.get_value('NJ Settings', {'parameter': 'max_qr_copy'}, 'value').then((r) => {
                console.log("frm.doc.qr_print_count", frm.doc.qr_print_count, "max", r.message.value);

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
                        if (frm.doc.qr_print_count > r.message.value) {
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

                                frappe.call({
                                    method: "frappe.desk.form.utils.add_comment",
                                    args: {
                                        reference_doctype: frm.doctype,
                                        reference_name: frm.doc.name,
                                        content: frappe.session.user + ' has taken 1 copy. \nReason: ' + reason + '\nComment: ' + comment,
                                        comment_email: frappe.session.user,
                                        comment_by: frappe.session.user_fullname,
                                    }
                                });

                                frappe.msgprint({
                                    title: __('Reason Submitted'),
                                    indicator: 'green',
                                    message: __('Reason and Comment have been submitted successfully.')
                                });

                                frm.reload_doc(); 
                            });
                        }
                    }
                });
            });
        }).addClass('btn-primary');
    }
});