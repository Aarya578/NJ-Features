frappe.ui.form.on('Resource Reallocation', {
	refresh(frm) {
		if (frm.is_new()) return;
		const run = (method, msg) => frm.call({ doc: frm.doc, method, freeze: true, freeze_message: msg })
			.then(() => frm.reload_doc());

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__('Compute'), () => run('compute', __('Reading ERP and allocating…')), __('Actions'));
			if (frm.doc.status !== 'Draft') {
				frm.add_custom_button(__('Recompute figures'), () => run('recompute', __('Recomputing…')), __('Actions'));
				frm.add_custom_button(__('Re-optimise around my changes'), () => run('reoptimise', __('Re-optimising…')), __('Actions'));
			}
		}
		if (frm.doc.status !== 'Draft') {
			frm.add_custom_button(__('Open Control Panel'), () => {
				frappe.route_options = { reallocation: frm.doc.name };
				frappe.set_route('List', 'Resource Reallocation Line', 'Report');
			}).addClass('btn-primary');
		}
		if (frm.doc.status === 'Computed' && frm.doc.docstatus === 0) {
			frm.dashboard.set_headline(__('{0} moves recommended. Release {1} units from Inward to Core IQC. Submit to apply to Employee records.',
				[frm.doc.moves_count, frm.doc.inward_release]));
		}
	},
	after_save(frm) {
		if (frm.doc.docstatus === 0) {
			frm.call({ doc: frm.doc, method: 'compute', freeze: true, freeze_message: __('Reading ERP and allocating…') })
				.then(() => frm.reload_doc());
		}
	},
});
