// Copyright (c) 2025, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Auto Stock Entry', {

	setup: function(frm) { fill_work_warehouse(frm) },

	onload: function(frm) {
		$(document).on('keydown', function(event) {
			if (event.ctrlKey && event.shiftKey && event.key === 'B') {
				
				new frappe.ui.Scanner({
					dialog: true,
					multiple: false,
					on_scan: function on_scan(data) {
						if (data && data.result && data.result.text) {
							frm.set_value('serial_no', data.result.text);
						}
					}
				});
			}
		})
	},

	refresh: function(frm) {
        $('.primary-action').hide();
		$('[data-fieldname="serial_no"]').focus();
		handleScannerInput(frm, 'serial_no');
	},

	serial_no: function(frm) {
		if (frm.doc.serial_no) {
			handleScannerInput(frm, 'serial_no');
			frappe.call({
				method: 'nj_features.nj_features.doctype.auto_stock_entry.auto_stock_entry.submit_ste',
				args: { serial_no: frm.doc.serial_no, t_warehouse: frm.doc.default_target_warehouse },
				freeze: true,
				freeze_message: `<div style="text-align: center;">
					<i class="fa fa-spinner fa-spin" style="font-size: 24px;"></i> 
					<br>Transferring Stock... Please Wait
				</div>`,
				callback: function(r) {
					if (r && r.message) {
						frappe.utils.play_sound('submit')
					}
				},
				error: function(err) {
					frappe.utils.play_sound('error')
				}
			})
			frm.set_value('serial_no', '')
			frm.refresh_field('serial_no')
			$('[data-fieldname="serial_no"]').focus();
		}
	}
});

function fill_work_warehouse(frm) {
	frappe.call({
		method: 'nj_features.nj_features.doctype.auto_stock_entry.auto_stock_entry.get_work_warehouse',
		callback: function(r) {
			if (r && r.message) {
				frm.set_value('default_target_warehouse', r.message.work_warehouse)
				frm.refresh_field('default_target_warehouse')
			}
		},
		error: function(err) { frappe.utils.play_sound('error') }
	})
}