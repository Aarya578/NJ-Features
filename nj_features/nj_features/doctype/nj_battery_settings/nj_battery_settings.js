// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('NJ Battery Settings', {
	onload: function() {
		$('.col-lg-2.layout-side-section').hide();
		if (cur_frm.doc.department) {
			get_nj_settings()
		}
	},

	department: function() {
		get_nj_settings()
	},

	validate() {
		frappe.call({
			method: 'nj_features.nj_features.doctype.nj_battery_settings.nj_battery_settings.update_nj_battery_settings',
			args: {doc: cur_frm.doc}
		})
	}
});

function get_nj_settings() {
	frappe.call({
		method: 'nj_features.nj_features.doctype.nj_battery_settings.nj_battery_settings.get_nj_settings',
		args: {doc: cur_frm.doc},
		callback: function(r) {
			if (r.message) {
				let data = r.message;
				Object.keys(data).forEach(row => {
					if (!cur_frm.doc.row) {
						cur_frm.set_value(row, data[row]);
					}
				});
			}
		}
	})
}