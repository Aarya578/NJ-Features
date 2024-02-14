// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Inward', {
	// refresh: function(frm) {

	// }
	purchase_receipt: function(frm) {
        if (cur_frm.doc.purchase_order) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.inward.inward.get_items_from_pr',
                args: {'pr': frm.doc.purchase_receipt},
                callback: function(r) {
                    r.message.item_code.unshift('');
                    var options = r.message.item_code.join('\n');
                    console.log("options: ", options);
                    frm.set_df_property('item_code', 'options', options);
                }
            });
        }
    }
});
