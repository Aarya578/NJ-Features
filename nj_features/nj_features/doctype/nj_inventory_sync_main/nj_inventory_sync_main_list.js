frappe.listview_settings['NJ Inventory Sync Main'] = {
    filters: [["is_active", "=", 1]],
    get_indicator: function (doc) {
        if (doc.status === "Error") {
            return [__("Error"), "red", "status,=,Error"];
        } else if (doc.status === "Queued") {
            return [__("Queued"), "orange", "status,=,Queued"];
        } else if (doc.status === "Completed") {
            return [__("Completed"), "green", "status,=,Completed"];
        }
    },
    refresh: function() {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
	}
};
