// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
frappe.ui.form.on('Inward', {
    refresh(frm) {
        $('[data-fieldname="purchase_receipt"]').focus();

        // $('[data-original-title="Print"]').on('click', function() {
        //     frappe.call({
        //         method: 'frappe.www.printview.get_html_and_style',
        //         args: {
        //             doc: frm.doc,
        //             print_format: "Inward Barcode",
        //             no_letterhead: 1,
        //         },
        //         callback: function (r) {
        //             if (!r.exc) {
        //                 $preview_wrapper.find(".print-format").html(r.message.html);
        //                 const style = `
        //                     .print-format { box-shadow: 0px 0px 5px rgba(0,0,0,0.2); padding: 0.30in; min-height: 80vh; }
        //                     .print-preview { min-height: 0px; }
        //                     .modal-dialog { width: 720px; }`;
        
        //                 frappe.dom.set_style(style, "custom-print-style");
        //                 preview_dialog.show();
        //             }
        //         }
        //     });
        // });
        frm.set_query('purchase_receipt', function() {
            return {
                filters: {
                    "docstatus": ['=', 1]
                }
            };
        });
    },
    validate: function(frm) {
        if (!frm.doc.serial_no) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.inward.inward.create_serial_no',
                args:{
                    "item_group":frm.doc.item_group || null
                },
                callback: function(r) {
                    if (r.message) {
                        console.log("serial: ", r.message)
                        frm.set_value('serial_no', r.message);
                    }
                }
            });
        }
        // if (!frm.doc.serial_no) {
        //     frappe.msgprint("Serial number generation failed. Document cannot be saved.");
        //     frappe.validated = false;
        //     return false; // Prevent the form from being saved
        // }
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
                    console.log("msg: ", r.message);
                    if (r.message && r.message.result) {
                        var itemCodes = r.message.result.map(function(item) {
                            return item.item_code;
                        });
                        var options = itemCodes.join('\n');

                        frm.set_df_property('item_code', 'options', options);
                        frm.set_value('source_warehouse', r.message.result[0].warehouse);
                        frm.set_df_property('source_warehouse', 'read_only', 1);
                    } else {
                        frm.set_df_property('item_code', 'options', '');
                    }

                }
            });
        }
    },
    item_code: function(frm) {
        var selected_item_code = frm.doc.item_code;
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
            if (cur_frm.doc.purchase_receipt) {
                frappe.call({
                    method: 'nj_features.nj_features.doctype.inward.inward.get_items_from_pr',
                    args: {'pr': frm.doc.purchase_receipt, 'item_code': selected_item_code},
                    callback: function(r) {
                        if (r.message && r.message.result && r.message.result.length > 0) {
    
                            // Find the warehouse corresponding to the selected item_code
                            var warehouse = '';
                            for (var i = 0; i < r.message.result.length; i++) {
                                if (r.message.result[i].item_code === selected_item_code) {
                                    warehouse = r.message.result[i].warehouse;
                                    break;
                                }
                            }
    
                            // Check if warehouse value is not empty
                            if (warehouse) {
                                // Set the source_warehouse field directly
                                frm.set_value('source_warehouse', warehouse)
    
                                refresh_field('source_warehouse');
                            }
                        }
                    
                    }
                });
            }
        }
        if (cur_frm.doc.purchase_receipt) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.inward.inward.get_items_from_pr',
                args: {'pr': frm.doc.purchase_receipt, 'item_code': selected_item_code},
                callback: function(r) {
                    if (r.message) {
                        frm.set_value('base_rate', r.message.base_rate);
                    } else {
                        frm.set_df_property('item_code', 'options', '');
                    }
              

                }
            });
        }
    }
});

function warehouse_info(frm) {
    frappe.db.get_value('Employee', {'user_id': frappe.session.user_email}, ['name', 'work_warehouse'], function(response) {
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

// function printViewMethod(customParam) {
//     var csrftoken = frappe.csrf_token;
//     $.ajax({
//         url: '/api/method/frappe.www.printview.get_html_and_style',
//         type: 'POST',
//         dataType: 'json',
//         data: customParam,
//         headers: {
//             'X-Frappe-CSRF-Token': csrftoken
//         },
//         success: function(response) {
//             console.log(response);
//         },
//         error: function(xhr, status, error) {
//             console.error(xhr.responseText);
//         }
//     });
// }