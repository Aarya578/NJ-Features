// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('NJ Settings', {
    onload: function() {
        $('.col-lg-2.layout-side-section').hide();
    },
    module: function(frm) {
        // Fetch filtered options for the doc_type field based on the selected module
        frm.set_query('doc_type', function() {
            return {
                filters: {
                    module: frm.doc.module
                }
            };
        });
    }
});