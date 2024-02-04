frappe.listview_settings['Stock Entry'] = {
    refresh: function(listview) {
        // Material Transfer button
        listview.page.add_inner_button(__("Stock Movement"), function() {
            openStockEntryForm(1);
        }).addClass('btn-primary');

        // Racking button
        listview.page.add_inner_button(__("Racking"), function() {
            openStockEntryForm(0);
        }).addClass('btn-primary');
    },
};

function openStockEntryForm(stockType) {
    frappe.db.get_value('Employee', {'user_id': frappe.session.user_email}, ['name', 'work_warehouse'], function(response) {
        if (!response.name) {
            frappe.msgprint('Employee not found. Please mail us at <strong><a href="mailto:itsupport@newjaisa.com">itsupport@newjaisa.com</a></strong> to create an employee.');
            return;
        }

        // Employee exists, proceed with Stock Entry creation
        frappe.model.with_doctype('Stock Entry', function () {
            var doc = frappe.model.get_new_doc('Stock Entry');
            if (stockType === 1) {
                doc.stock_movement = 1;

                if (!response.work_warehouse) {
                    frappe.msgprint('Warehouse does not exist. Please mail us at <strong><a href="mailto:itsupport@newjaisa.com">itsupport@newjaisa.com</a></strong> to create work warehouse.');
                    return;
                } else {
                    doc.to_warehouse = response.work_warehouse;
                    doc.default_target_warehouse = response.work_warehouse;
                }
            } else if (stockType === 0) {
                doc.racking_check = 1;
            }

            frappe.model.with_doctype('Stock Entry Detail', function () {
                var child_table = frappe.model.get_new_doc('Stock Entry Detail');
                child_table.parent = doc.name;
                child_table.parenttype = doc.doctype;
                child_table.parentfield = "items";
                doc.items = [child_table];
                frappe.set_route('Form', 'Stock Entry', doc.name);
            });
        });
    });
}
