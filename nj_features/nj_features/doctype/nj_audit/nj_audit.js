frappe.ui.form.on('NJ Audit', {
	onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();	
		frappe.db.get_value('NJ Settings',{'parameter' : 'audit_interval'},'value',(r)=>{
			if(r){
				frm.set_value('audit_interval',r.value);
			}
		})	
	},

	scan_serial_no: function(frm) {
		if (frm.doc.scan_serial_no) {
			frappe.db.exists('Serial No', frm.doc.scan_serial_no).then((resp)=> {
				if (resp) {
					frm.add_child('nj_audit_items', { serial_no: frm.doc.scan_serial_no });
				} else {
					frappe.throw("<b>Serial No: "+frm.doc.scan_serial_no+"</b> is not found!")
				}
				frm.set_value('scan_serial_no', '');
				frm.refresh_field('nj_audit_items');
			});
		}
	}
});
