// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('NJ Part Results', {
	onload: function() {
		$('.col-lg-2.layout-side-section').hide();
	},
	refresh: function(frm) {
		frm.page.wrapper.find(".comment-box").css({'display':'none'});
	}
});
