frappe.ui.form.on('NJ Audit', {
	onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();	
		frappe.db.get_value('NJ Settings',{'parameter' : 'audit_interval'},'value',(r)=>{
			if(r){
				frm.set_value('audit_interval',r.value);
			}
		})	
	}
});
