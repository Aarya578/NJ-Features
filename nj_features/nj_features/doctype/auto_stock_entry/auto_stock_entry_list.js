frappe.listview_settings['Auto Stock Entry'] = {
    refresh: function(listview) {
        $('.menu-btn-group').hide();
        $('.custom-btn-group').hide();
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
	}
};