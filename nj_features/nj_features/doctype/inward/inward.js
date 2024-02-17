// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
frappe.ui.form.on('Inward', {
    refresh(frm) {
        frm.set_query('purchase_receipt', function() {
            return {
                filters: {
                    "docstatus": ['=', 1]
                }
            };
        });
    },
    before_save: function(frm) {
        if (!frm.doc.serial_no) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.inward.inward.create_serial_no',
                callback: function(r) {
                    if (r.message) {
                        frm.set_value('serial_no', r.message);
                        console.log("serial no is generated i.e",r.message)
                    }
                }
            });
        }
    },
    onload: function(frm) {
        warehouse_info(frm);
    },
    purchase_receipt: function(frm) {
        console.log(cur_frm.doc.purchase_receipt);
        if (cur_frm.doc.purchase_receipt) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.inward.inward.get_items_from_pr',
                args: {'pr': frm.doc.purchase_receipt},
                callback: function(r) {
                    console.log("msg: ", r.message.items);
                    if (r.message && r.message.result) {
                        var itemCodes = r.message.result.map(function(item) {
                            return item.Item_code;
                        });
                        var options = itemCodes.join('\n');
                        console.log("options: ", options);

                        frm.set_df_property('item_code', 'options', options);
                        frm.set_value('source_warehouse', r.message.result[0].warehouse);
                        frm.set_df_property('source_warehouse', 'read_only', 1);
                    } else {
                        console.log("No items found for the purchase receipt.");
                        frm.set_df_property('item_code', 'options', '');
                    }

                }
            });
        }
    },
    item_code: function(frm) {
        var selected_item_code = frm.doc.item_code;
        console.log("selected_item_code",selected_item_code)
        if (selected_item_code) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.inward.inward.fetch_item_group',
                args: {'item_code': selected_item_code},
                callback: function(r) {
                    if (r.message && r.message.item_group) {
                        frm.set_value('item_group', r.message.item_group);
                        frm.set_df_property('item_group', 'read_only', 1);
                    }
                }
            });
        }
        if (cur_frm.doc.purchase_receipt) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.inward.inward.get_items_from_pr',
                args: {'pr': frm.doc.purchase_receipt, 'item_code': selected_item_code},
                callback: function(r) {
                    if (r.message) {
                        console.log("item_code: ", r.message);
                        frm.set_value('base_rate', r.message.base_rate);
                    } else {
                        console.log("No items found for the purchase receipt.");
                        frm.set_df_property('item_code', 'options', '');
                    }
              

                }
            });
        }
    }
});

function warehouse_info(frm) {
    frappe.db.get_value('Employee', {'user_id': frappe.session.user_email}, ['name', 'work_warehouse'], function(response) {
        console.log('name', response.name, 'work', response.work_warehouse)
        if (!response.name) {
            frappe.msgprint('Employee not found. Please mail us at <strong><a href="mailto:itsupport@newjaisa.com">itsupport@newjaisa.com</a></strong> to create an employee.');
            return;
        }
        console.log("warehouse function")
        if (response.work_warehouse) {
            frm.set_value('target_warehouse', response.work_warehouse);
        } else {
            frappe.msgprint('Work Warehouse does not exist.');
        }
        frm.set_df_property('target_warehouse', 'read_only', 1);

    });
}