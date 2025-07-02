frappe.listview_settings['Knowledge Base'] = {
    add_fields: ["active"],
    get_indicator: function(doc) {
		if(cint(doc.active) == 1) {
			return [__("Active"), "green", "active,=,1"];
		} else if(cint(doc.active) == 0) {
			return [__("InActive"), "red", "active,=,0"];
		}
	},
    onload: function() {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
	}
};

