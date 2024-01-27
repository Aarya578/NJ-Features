frappe.listview_settings['Stock Entry'] = {
    refresh: function(listview) {
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
    frappe.model.with_doctype('Stock Entry', function() {
        var doc = frappe.model.get_new_doc('Stock Entry');
        
        frappe.model.set_value(doc.doctype, doc.name, 'stock_type', stockType);
        frappe.set_route('Form', 'Stock Entry', doc.name);
    });
}
