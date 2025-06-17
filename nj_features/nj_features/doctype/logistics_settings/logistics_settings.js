// Copyright (c) 2025, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Logistics Settings', {
    refresh: function(frm) {
		console.log("inside refresh=================================================");
		
        // Add custom button on form refresh
        let fetch_SRT_Courier_Names = frm.add_custom_button(__('Fetch_SRT_Courier_Names'), function() {
            frappe.show_alert({
                message: __('Generating AWB Number...'),
                indicator: 'blue'
            });

            frappe.call({
                method: 'nj_features.nj_features.doctype.logistics_settings.logistics_settings.shiprocket_shiprocket_courier_name',
                args: { doc: JSON.stringify(frm.doc) },
                callback: function(response) {
                    if (response.message) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __('Courier Name Fetched successfully!'),
                            indicator: 'green'
                        });
                    }
                }
            });
        });

        // Add styling to the button
        fetch_SRT_Courier_Names.addClass('btn-primary');
    }
});

