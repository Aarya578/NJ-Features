frappe.ui.form.on('Address', {
    refresh: function(frm) {
        frappe.call({
            method: "nj_features.overrides.address.hiding_gst_filed",
            args: { links: JSON.stringify(frm.doc.links || []) },
            callback: function(r) {
                if (r.message && r.message.hide_gstin) {
                    frm.set_df_property('gstin', 'hidden', 1);
                } else {
                    frm.set_df_property('gstin', 'hidden', 0);
                }
            }
        });
        
      let gst_btn = frm.add_custom_button(__('Fetch GST Details'), function() {
			frappe.show_alert({ message: __('Fetching GST details...'), indicator: 'blue' });

			frappe.call({
				method: 'nj_features.overrides.address.fetch_gst_details',
				args: { doc: JSON.stringify(frm.doc) },
				callback: function(response) {
					if (response.message && response.message.status === "success") {
						frm.reload_doc();

						// Show success message
						frappe.show_alert({
							message: __('GST details fetched and updated successfully!'),
							indicator: 'green'
						});

						// Optional: Log requestid (generated server-side)
						if (response.message.requestid) {
							console.log("Generated Request ID:", response.message.requestid);
						}
					}
				}
			});
		});
		gst_btn.addClass('btn-primary');
	
            
    }
});
