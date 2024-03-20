frappe.listview_settings['Stock Entry'] = {
    refresh: function(listview) {
        // Material Transfer button
        listview.page.add_inner_button(__("Stock Accept"), function() {
            openStockEntryForm(1);
        }).addClass('btn-primary');
        // Move Stock button
        listview.page.add_inner_button(__("Racking"), function() {
            openStockEntryForm(0);
        }).addClass('btn-primary');
    },
};

function openStockEntryForm(stockType) {
    frappe.db.get_value('Employee', {'user_id': frappe.session.user_email}, ['name', 'work_warehouse'], function(response) {
        console.log('name', response.name, 'work', response.work_warehouse)
        if (!response.name) {
            frappe.msgprint('Employee not found for User: <b>'+frappe.session.user_email+'</b>. Please mail to <b>IT Infra Team</b> at <strong><a href="mailto:itinfra@newjaisa.com">itinfra@newjaisa.com</a></strong> to create an employee.');
            return;
        }

        // Employee exists, proceed with Stock Entry creation
        frappe.model.with_doctype('Stock Entry', function () {
            var doc = frappe.model.get_new_doc('Stock Entry');
            if (stockType === 1) {
                doc.stock_movement = 1;

                if (!response.work_warehouse) {
                    frappe.msgprint('Work Warehouse does not exist.');
                    return;
                } else {
                    doc.to_warehouse = response.work_warehouse;
                    doc.default_target_warehouse = response.work_warehouse;
                }
            } else if (stockType === 0) {
                doc.move_stock = 1;
                if (!response.work_warehouse) {
                    frappe.msgprint('Work Warehouse does not exist.');
                    return;
                } else {
                    doc.from_warehouse = response.work_warehouse;
                }
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
