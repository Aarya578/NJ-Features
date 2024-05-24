// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
//List View

frappe.listview_settings['Stock Movement'] = {
    onload: function(listview) {
        $('.col-lg-2.layout-side-section').hide();
        viewButton(listview)
    },
    refresh: function(listview) {
        viewButton(listview)
    },
};

function viewButton(listview) {
    // $('.btn-primary.btn-sm.primary-action').hide();
    $('.custom-btn-group').hide();
        // Materiprimaryal Transfer button
        listview.page.set_primary_action("Stock Accept", function() {
            openStockEntryForm(1);
        })
        // Move Stock button
        listview.page.set_secondary_action("Racking", function() {
            openStockEntryForm(0);
        }).addClass('btn-primary')
}

function openStockEntryForm(stockType) {
    frappe.db.get_value('Employee', {'user_id': frappe.session.user_email}, ['name', 'work_warehouse'], function(response) {
        if (!response.name) {
            frappe.msgprint(`Employee not found for User: `+$(frappe.session.user_email)+`. Please mail us at <strong><a href="mailto:itsupport@newjaisa.com">itsupport@newjaisa.com</a></strong> to create an employee.`);
            return;
        }

        // Employee exists, proceed with Stock Entry creation
        frappe.model.with_doctype('Stock Movement', function () {
            var doc = frappe.model.get_new_doc('Stock Movement');
            if (stockType === 1) {
                doc.transfer_status = "Stock Accept";
                doc.stock_entry_type = "Material Transfer"
                if (!response.work_warehouse) {
                    frappe.msgprint('Work Warehouse does not exist.');
                    return;
                } else {
                    doc.default_target_warehouse = response.work_warehouse;
                }
            } else if (stockType === 0) {
                doc.transfer_status = "Racking";
                doc.stock_entry_type = "Material Transfer"
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