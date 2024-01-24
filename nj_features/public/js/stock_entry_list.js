frappe.listview_settings['Stock Entry'] = {
    onload: function(listview) {
        listview.page.add_inner_button(__("Material Transfer"), function() {
            var stockType = 'stock_movement';
            var anchor = document.createElement('a');
            anchor.href = frappe.urllib.get_full_url('/app/stock-entry/new-stock-entry-1?stock_type=' + stockType);
            var event = new MouseEvent('click', {
                bubbles: true,
                cancelable: true,
                view: window
            });
            anchor.dispatchEvent(event);
        }).addClass('btn-primary');
        

        // listview.page.add_inner_button('Stock Movement', function() {
        //     frappe.set_route("query-report", "Knowledge Base");
        // }).addClass('btn-primary');
    }
};