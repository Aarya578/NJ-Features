frappe.listview_settings['Knowledge Base'] = {
    onload: function(listview) {
        listview.page.add_inner_button('Open Report View', function() {
            frappe.set_route("query-report", "Knowledge Base");
        }).addClass('btn-primary');
    }
};
