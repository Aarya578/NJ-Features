frappe.ui.form.on('Purchase Receipt', {
    refresh(frm) {
        console.log("refresh")
    },
    validate: function(frm) {
        frm.doc.items.forEach(function(item) {
            if (!item.batch_no) {
                frappe.model.set_value(item.doctype, item.name, 'batch_no', item.purchase_order);
            }
        });
    }
});
