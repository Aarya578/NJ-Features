frappe.listview_settings['Doc Attachment'] = {
    filters: [["owner", "=", frappe.session.user]],
    refresh: function(listview) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
	}
};
