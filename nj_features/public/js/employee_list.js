frappe.listview_settings['Employee'] = {
    filters: [["status", "=", "Active"]],
    get_indicator: function(doc) {
		if(doc.status == "Active") {
			return [__("Active"), "green", "status,=,Active"];
		} else if(doc.status == "Inactive") {
			return [__("Inactive"), "red", "status,=,Inactive"];
		} else if(doc.status == "Suspended") {
			return [__("Suspended"), "orange", "status,=,Suspended"];
		} else if(doc.status == "Left") {
			return [__("Left"), "orange", "status,=,Left"];
		}
	},
    onload: function(listview) {
        if (frappe.user.has_role('Developer')) {
            listview.page.add_inner_button(__('Disable Qty Check'), function() {
                frappe.db.get_value("NJ Settings",{"parameter":"disable_qty_check"},["value","name"]).then((r)=>{
                    if(r.message.value == 0){
                        frappe.db.set_value("NJ Settings", r.message.name, "value", "1")
                        $('[data-label="Disable%20Qty%20Check"]').addClass('btn-danger');
                        frappe.show_alert({
                            message: __('Qty Check has been de-activated successfully.'),
                            indicator: 'red'
                        });
                    } else {
                        frappe.db.set_value("NJ Settings", r.message.name, "value", "0")
                        $('[data-label="Disable%20Qty%20Check"]').removeClass('btn-danger');
                        frappe.show_alert({
                            message: __('Qty Check has been activated successfully.'),
                            indicator: 'green'
                        });
                    }
                })
            });

            frappe.db.get_value("NJ Settings",{"parameter":"disable_qty_check"},["value","name"]).then((r)=>{
                if(r.message.value == 1){
                    $('[data-label="Disable%20Qty%20Check"]').addClass('btn-danger');
                }
            })
        }
    },
    refresh: function() {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
    }
}