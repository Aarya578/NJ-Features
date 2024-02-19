// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
//List View

frappe.listview_settings['Stock Movement'] = {
    onload: function(listview) {
        viewButton(listview)
    },
    refresh: function(listview) {
        viewButton(listview)
    },
};

function viewButton(listview) {
    $('.btn-primary.btn-sm.primary-action').hide();
        $('.custom-btn-group').hide();
		console.log("Stock Movement");
        // Material Transfer button
        listview.page.add_inner_button(__("Stock Accept"), function() {
            openStockEntryForm(1);
        }).addClass('btn-primary');
        // Move Stock button
        listview.page.add_inner_button(__("Racking"), function() {
            openStockEntryForm(0);
        }).addClass('btn-primary');
}

function openStockEntryForm(stockType) {
    frappe.db.get_value('Employee', {'user_id': frappe.session.user_email}, ['name', 'work_warehouse'], function(response) {
        console.log('name', response.name, 'work', response.work_warehouse)
        if (!response.name) {
            frappe.msgprint('Employee not found. Please mail us at <strong><a href="mailto:itsupport@newjaisa.com">itsupport@newjaisa.com</a></strong> to create an employee.');
            return;
        }

        // Employee exists, proceed with Stock Entry creation
        frappe.model.with_doctype('Stock Movement', function () {
            var doc = frappe.model.get_new_doc('Stock Movement');
            if (stockType === 1) {
                doc.stock_movement = 1;

                if (!response.work_warehouse) {
                    frappe.msgprint('Work Warehouse does not exist.');
                    return;
                } else {
                    doc.default_target_warehouse = response.work_warehouse;
                }
            } else if (stockType === 0) {
                doc.move_stock = 1;
                if (!response.work_warehouse) {
                    frappe.msgprint('Work Warehouse does not exist.');
                    return;
                } else {
                    doc.default_source_warehouse = response.work_warehouse;
                }
            }

            frappe.model.with_doctype('Stock Movement Detail', function () {
                var child_table = frappe.model.get_new_doc('Stock Movement Detail');
                child_table.parent = doc.name;
                child_table.parenttype = doc.doctype;
                child_table.parentfield = "items";
                doc.items = [child_table];
                frappe.set_route('Form', 'Stock Movement', doc.name);
            });
        });
    });
}