frappe.listview_settings['NJQCA'] = {
    filters: [["created", "=", frappe.session.user]],
    refresh: function(listview) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
	}
};