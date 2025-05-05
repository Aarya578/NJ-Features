frappe.listview_settings['Employee'] = {
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
    }
}