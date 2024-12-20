frappe.listview_settings['Security Inward Registry'] = {
	add_fields: ["total_qty"],
	get_indicator: (doc) => {
		if (!doc.total_qty) {
			return [__("Empty"), "gray", "total_qty,=,0"];
		} else {
			return [__("Active"), "green", "total_qty,>,0"];
		};
	},
	onload: function(listview) {
		openAccessRegistry(listview);
	},
	refresh: function(listview) {
		openAccessRegistry(listview);
	}
};

function openAccessRegistry(listview) {
	listview.page.set_secondary_action("Accept Registry", function() {
		frappe.model.with_doctype('Security Inward Registry', function () {
			var doc = frappe.model.get_new_doc('Security Inward Registry');
			doc.registry_type = "Accept Registry";
			frappe.set_route('Form', 'Security Inward Registry', doc.name);
		});
	}).addClass('btn-primary');
}