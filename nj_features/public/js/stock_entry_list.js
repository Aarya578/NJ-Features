frappe.listview_settings['Stock Entry'] = {
    onload: function(listview) {
        // Material Transfer button
        listview.page.add_inner_button(__("Material Transfer"), function() {
            var stockType = 'stock_movement';
            openStockEntryForm(stockType);
        }).addClass('btn-primary');

        // Racking button
        // listview.page.add_inner_button(__("Racking"), function() {
        //     var stockType = 'racking';
        //     openStockEntryForm(stockType);
        // }).addClass('btn-primary');
    }
};

function openStockEntryForm(stockType) {
    var anchor = document.createElement('a');
    anchor.href = frappe.urllib.get_full_url(`/app/stock-entry/new-stock-entry-1?stock_type=${stockType}`);
    var event = new MouseEvent('click', {
        bubbles: true,
        cancelable: true,
        view: window
    });
    anchor.dispatchEvent(event);
}