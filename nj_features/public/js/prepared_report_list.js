frappe.listview_settings['Prepared Report'] = {
    onload: function(listview) {
        filters: [['created_by', '=', frappe.session.user_email]],
        listview.refresh();
    }
};
