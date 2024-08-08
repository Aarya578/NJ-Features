frappe.ui.form.on('NJ Audit', {
    onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();	

		frm.set_df_property('nj_audit_items', 'cannot_add_rows', true);

		frappe.db.get_value('NJ Settings',{'parameter' : 'audit_interval'},'value',(r)=>{
			if(r){
				frm.set_value('audit_interval',r.value);
				frm.set_value('audit_warehouse','WK-Post Man-EMP879 - N')
			}
		});
	},

    scan_serial_no: function(frm) {
        if (frm.doc.scan_serial_no) {
            frappe.db.exists('Serial No', frm.doc.scan_serial_no).then((exists) => {
                if (exists) {
                    let child = frm.add_child('nj_audit_items', { 
                        serial_no: frm.doc.scan_serial_no 
                    });
                    frappe.db.get_value('Serial No', {'name': frm.doc.scan_serial_no}, ['item_code', 'warehouse'])
                        .then((result) => {
                            if (result.message) {
                                child.item = result.message.item_code;
                                child.warehouse = result.message.warehouse;
                                if (frm.doc.audit_warehouse === result.message.warehouse) {
                                    frappe.meta.get_docfield('NJ Audit Items', 'accept', frm.doc.name).hidden = 1;
                                } else {
                                    frappe.meta.get_docfield('NJ Audit Items', 'accept', frm.doc.name).hidden = 0;
                                }

                                frm.refresh_field('nj_audit_items');
                            }
                        });

                    frm.set_value('scan_serial_no', '');
                } else {
                    frappe.throw(`Serial No: <b>${frm.doc.scan_serial_no}</b> is not found!`);
                }
            });
        }
    }
});