frappe.ui.form.on('Dispatch Security Checkpoints', {
    onload: function(frm) {
        if (frm.doc.docstatus == 0) {
            frm.set_df_property('dispatch_security_child_table', 'cannot_add_rows', true);
        }
    },
    refresh: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        if (frm.doc.docstatus == 0) {
            $('[data-fieldname="scan_serial_no"]').focus();
        }
    },
    scan_serial_no: function (frm) {
        if (frm.doc.scan_serial_no != '') {
            frappe.call({
                method: 'nj_features.nj_features.doctype.dispatch_security_checkpoints.dispatch_security_checkpoints.scan_serial_no_data',
                args: { 
                    serial_no: frm.doc.scan_serial_no            
                },
                callback: function (r) {
                    if (r.message) {
                        frm.set_value('scan_serial_no', '');
                        frm.refresh_field('scan_serial_no');
                        
                        let dispatch_security_child_table = {
                            "serial_no": r.message.serial_no,
                            "item_code": r.message.item_code || 'Not Available',
                            "sales_invoice": r.message.sales_invoice || 'Not Available',
                            "delivery_note": r.message.delivery_note || 'Not Available',
                            "si_status": r.message.si_status || 'Not Available',
                            "dn_status": r.message.dn_status || 'Not Available',
                            "si_approved": r.message.si_approved || 'Not Available',
                        };
                        
                        
                        frm.add_child("dispatch_security_child_table", dispatch_security_child_table);
                        frm.refresh_field("dispatch_security_child_table");
                    } else {
                        frm.set_value('scan_serial_no', '');
                        frm.refresh_field('scan_serial_no');
                    }
                }
            });
        }
    },
});