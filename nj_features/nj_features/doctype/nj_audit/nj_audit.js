frappe.ui.form.on('NJ Audit', {
    onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
		
		frm.set_df_property('nj_audit_items', 'cannot_add_rows', true);
		
		frappe.db.get_value('NJ Settings',{'parameter': 'audit_interval'},'value',(r)=>{
			if(r){
				frm.set_value('audit_interval', r.value);
				frm.refresh_field('audit_interval');
			}
		});
	},

	refresh(frm) {
		$('[data-fieldname="scan_serial_no"]').focus();
	},

    scan_serial_no: function(frm) {
        if (frm.doc.scan_serial_no) {
            frappe.db.exists('Serial No', frm.doc.scan_serial_no).then((exists) => {
                if (exists) {
                    let child = frm.add_child('nj_audit_items', { 
                        serial_no: frm.doc.scan_serial_no 
                    });
                    frappe.db.get_value('Serial No', {'name': frm.doc.scan_serial_no}, ['item_code', 'warehouse','purchase_rate'])
                        .then((result) => {
                            if (result.message) {
                                child.item = result.message.item_code;
                                child.warehouse = result.message.warehouse;
								child.purchase_rate = result.message.purchase_rate
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
					frm.set_value('scan_serial_no', '');
                }
            });
        }
		$('[data-fieldname="scan_serial_no"]').focus();
    }
});


frappe.ui.form.on('NJ Audit Items', {
    accept: function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        let auditWarehouse = frm.doc.audit_warehouse;
		let stock_entry_items = [{
			'item_code': child.item,
			'basic_rate': child.purchase_rate,
			'serial_no': child.serial_no
		}];

		let data = {
			"serial_no": child.serial_no,
			"stock_entry_type": "Material Transfer",
			"t_warehouse": auditWarehouse,
			"series": "STRC-.YYYY.-.MM.-",
			"reference_serial_no": child.serial_no,
			"doctype": frm.doc.doctype,
			"stock_entry_for_material_transfer_or_repack_items": stock_entry_items
		}

		frappe.call({
			method: 'nj_lib.utils.stock_entry.stock_entry_using_nj_lib',
			args: { 'data': JSON.stringify(data) },
			callback: function(r){
				if(child.warehouse != cur_frm.doc.audit_warehouse){
					frappe.model.set_value(cdt,cdn,'warehouse',cur_frm.doc.audit_warehouse)
					frm.set_df_property('nj_audit_items', 'hidden', 1, frm.docname, 'accept', cdn);
					frm.refresh_field('nj_audit_items');
				}
			},
			error: function(err) {
				console.log(err);
			}
		});
    }
});
