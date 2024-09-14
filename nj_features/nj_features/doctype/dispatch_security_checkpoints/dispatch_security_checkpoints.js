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
					scan_serial_no: frm.doc.scan_serial_no 
				},
				callback: function (r) {
					if (r.message) {
						frm.set_value('scan_serial_no', '');
						frm.refresh_field('scan_serial_no');
					}
				}
			})
            frappe.db.get_value("Serial No", {serial_no: frm.doc.scan_serial_no}, ["name"], (r) => {
                if (r) {
                    let dispatch_security_child_table = {
                        "serial_no": r.name,
						"sales_invoice": 'sales_invoice',
						"delivery_note": 'delivery_note',
						"si_status": 'si_status',
						"dn_status": 'dn_status'
                    };
					frm.add_child("dispatch_security_child_table", dispatch_security_child_table);
					frm.refresh_field("dispatch_security_child_table");
                    frm.set_value("scan_serial_no", "");
                    frm.refresh_field("scan_serial_no");
                }
            })
        }
    },
});