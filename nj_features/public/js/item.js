frappe.ui.form.on('Item', {
    refresh: function(frm) {
        $('.col-lg-2.layout-side-section').hide();

        if (frm.doc.has_serial_no == 0 && frm.doc.has_variants == 1) {
            let qr_code_name = ''

            frm.add_custom_button(__('Print QR Code'), function() {
                var docname = encodeURIComponent(frm.doc.name);
                var format = "Item Barcode";
                var print_trigger = 1;
    
                frappe.call({
                    method: 'nj_features.qr_code.generate_and_save_qrcode',
                    args: {
                        data: frm.doc.name
                    },
                    callback: (r) => {
                        console.log("mes from qr code", r.message);
                        qr_code_name = r.message
                        window.open(frappe.urllib.get_full_url("/printview?" +
                        "doctype=" + encodeURIComponent("Item") +
                        "&name=" + docname +
                        "&trigger_print=" + print_trigger +
                        "&format=" + format +
                        "&no_letterhead=0" +
                        "&qr_code_name=" + qr_code_name +
                        "&_lang=" + (frappe.boot.lang || "en")));
                    }
                });
                
                // frappe.db.get_value('NJ Settings', {'parameter': 'max_qr_copy'}, 'value').then((r) => {
                //     console.log("frm.doc.qr_print_count", frm.doc.qr_print_count, "max", r.message.value);
                //     if (frm.doc.qr_print_count > r.message.value) {
                //         frappe.prompt([
                //             {
                //                 fieldname: 'reason',
                //                 label: 'Reason',
                //                 fieldtype: 'Link',
                //                 reqd: 1,
                //                 options: 'Master Reasons'
                //             },
                //             {
                //                 fieldname: 'comment',
                //                 label: 'Comment',
                //                 fieldtype: 'Data',
                //                 reqd: 1
                //             }
                //         ], function(values) {
                //             let reason = values.reason;
                //             let comment = values.comment;
                //             cur_frm.timeline.insert_comment(frappe.session.user+' has taken 1 copy. \nReason: '+reason+'\nComment: '+comment)
                //             // frappe.call({
                //             //     "method": "frappe.desk.form.utils.add_comment",
                //             //     "args": {
                //             //       reference_doctype: frm.doctype,
                //             //       reference_name: frm.docname,
                //             //       content: frappe.session.user+' has taken 1 copy. \nReason: '+reason+'\nComment: '+comment,
                //             //       comment_email: frappe.session.user,
                //             //       comment_by: frappe.session.user_fullname,
                //             //     }
                                
                //             // });
                //             window.open(frappe.urllib.get_full_url("/printview?" +
                //             "doctype=" + encodeURIComponent("Serial No") +
                //             "&name=" + docname +
                //             "&trigger_print=" + print_trigger +
                //             "&format=" + format +
                //             "&no_letterhead=0" +
                //             "&_lang=" + (frappe.boot.lang || "en")));
                //         })
                        
                //     } else {
                        
                    // }
                // })
            }).addClass('btn-primary');
        }
    }
});
