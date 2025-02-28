// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
$('.custom-actions.hidden-xs.hidden-md, .btn.btn-default.btn-sm[data-label="Cancel"], .icon-btn[data-original-title="Print"]')
    .hide();

var item_code_init = "";
var default_ware = "";

frappe.ui.form.on('Stock Movement', {
    onload() {
        $('.col-lg-2.layout-side-section').hide();
        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
    },
    refresh() {
        $('[data-fieldname="scan_barcode"]').focus();
        $("button[data-original-title=Print]").hide();
    },

    scan_barcode: function () {
        if (cur_frm.doc.scan_barcode) {
            frappe.call({
                method: "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
                args: {  search_value: cur_frm.doc.scan_barcode },
                callback: function(r) {
                    const data = r && r.message;
                    if (r.message.scan === 1) {
                        if(cur_frm.doc.transfer_status == "Stock Accept") {
                            cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], true);
                        } else if (cur_frm.doc.transfer_status == "Racking") {
                            cur_frm.toggle_display(['scan_grade'], true);
                        }
                        $('[data-fieldname="scan_grade"]').focus();
                    } else {
                        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
                    }
    
                    if(r.message.serial_no) {
                        modify_table_after_scan(cur_frm, data)

                        frappe.call({
                            method: "nj_features.nj_features.doctype.stock_movement.stock_movement.get_grades_from_part_list",
                            args: {
                                search_value: r.message.serial_no
                            },
                            callback: function(gradesResponse) {
                                const gradesData = gradesResponse && gradesResponse.message;
                            
                                if (gradesData && gradesData.length > 0) {
                            
                                    // Extract department names from the response
                                    const departmentNames = gradesData.map(entry => entry.department);
                            
                                    // Update the options of the 'suggested_warehouse' field
                                    // cur_frm.set_df_property('suggested_warehouse', 'options', departmentNames.join('\n'));
                            
                                    // Optionally, set the first department as the default value
                                    cur_frm.set_value('suggested_warehouse', departmentNames.join(', '));
                                } else {
                                    // Clear the options if no data is found
                                    // cur_frm.set_df_property('suggested_warehouse', 'options', '');
                                    cur_frm.set_value('suggested_warehouse', '');
                                }
                            }
                        });
                    }
                }
            });
        }
        return false;
    },

    scan_grade: function(frm) {
        let changed_item_code = ''
        if (frm.doc.scan_barcode.includes('/')) {
            changed_item_code = frm.doc.scan_barcode;
            executeRemainingCode(frm, changed_item_code);
        } else if (frm.doc.scan_barcode.includes('@')) {
            changed_item_code = frm.doc.scan_barcode.replaceAll('@', '/');
            executeRemainingCode(frm, changed_item_code);
        } else {
            frappe.db.get_value('Non Serialized QR Code Mapping', {'name': frm.doc.scan_barcode}, 'item_code')
            .then(function(r) {
                if (r && r.message.item_code) {
                    changed_item_code = r.message.item_code;
                    executeRemainingCode(frm, changed_item_code);
                } else {
                    changed_item_code = frm.doc.scan_barcode
                    executeRemainingCode(frm, changed_item_code);
                }
            });
        }
        
        // Get the child table data
        // if (frm.doc.scan_grade != '' && changed_item_code != '') {
        //     var new_item_code = ''
        //     frappe.db.get_value('Grade', { 'name': cur_frm.doc.scan_grade }, 'name')
        //         .then(function (r) {
        //             if (r.message.name) {
        //                 new_item_code = changed_item_code + "-" + r.message.name
        //                 frappe.model.with_doc("Stock Movement", frm.docname, function() {
        //                     var table = frappe.model.get_doc("Stock Movement", frm.docname).items;
        //                     var child_item = table.find(d => d.idx === frm.selected_child);
        //                     if (child_item) {
        //                         frappe.model.set_value(child_item.doctype, child_item.name, 'grade', r.message.name);
        //                     }
        //                 });
                        
        //             } else {
        //                 frappe.msgprint(`Grade: <strong>${frm.doc.scan_grade}<\strong> not found. Please enter a valid Grade.`);
        //                 cur_frm.set_value('scan_grade', '');
        //                 cur_frm.set_value('scan_barcode', '');
        //                 $('[data-fieldname="scan_barcode"]').focus();
        //             }
                    
        //             if(r.message.name) {
        //                 frappe.db.get_value('Item', { name: new_item_code }, ['name', 'item_name'])
        //                 .then(function (r) {
        //                     if (r.message.name) {
        //                         item_code_init = r.message.name
        //                         if(frm.doc.transfer_status == "Racking") {
        //                             var data = {}
        //                             data['item_code'] = item_code_init
        //                             data['warehouse'] = frm.doc.default_source_warehouse
        //                             frappe.prompt({
        //                                 label: 'Enter Qty for Non-serialized Item',
        //                                 fieldname: 'qty',
        //                                 fieldtype: 'Int'
        //                             }, (values) => {
        //                                 data['qty'] = values.qty;
        //                                 modify_table_after_scan(cur_frm, data);
        //                                 cur_frm.set_value('scan_grade', '');
        //                                 cur_frm.set_value('scan_barcode', '');
        //                                 $('[data-fieldname="scan_barcode"]').focus();
        //                             })
        //                         }

        //                     } else {
        //                         frappe.msgprint(`Item: <strong>${new_item_code}</strong> doesn't exist. Please enter a valid Item.`);
        //                         cur_frm.set_value('scan_grade', '');
        //                         cur_frm.set_value('scan_barcode', '');
        //                         $('[data-fieldname="scan_barcode"]').focus();
        //                     }
        //             })
        //         }
        //     })
        // }
    },

    scan_warehouse: function(frm) {
        
        if (frm.doc.scan_warehouse != '') {
            var data = {}
            frappe.db.get_value('Warehouse', { name: frm.doc.scan_warehouse }, 'name').then(function (r) {
                if (r.message.name) {
                    var ware = r.message.name
                    let qty = 0
                    data['item_code'] = item_code_init
                    data['warehouse'] = ware
                    frappe.prompt({
                        label: 'Enter Qty for Non-serialized Item',
                        fieldname: 'qty',
                        fieldtype: 'Int'
                    }, (values) => {
                        data['qty'] = values.qty;
                        modify_table_after_scan(cur_frm, data);
                        cur_frm.set_value('scan_warehouse', '');
                        cur_frm.set_value('scan_grade', '');
                        cur_frm.set_value('scan_barcode', '');
                        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
                        $('[data-fieldname="scan_barcode"]').focus();
                        frm.refresh_field('scan_warehouse')
                        return false;
                    })
                } else {
                    cur_frm.set_value('scan_warehouse', '');
                    frappe.msgprint(`Warehouse: <strong>${cur_frm.doc.scan_warehouse}<\strong> does not exist. Please enter a valid Warehouse.`);
                    $('[data-fieldname="scan_warehouse"]').focus();
                }
            });
        }
        return false;
    },

    default_target_warehouse: function(frm) {
        autofill_warehouse(frm.doc.items, "t_warehouse", frm.doc.default_target_warehouse);
    },
    default_source_warehouse: function(frm) {
        autofill_warehouse(frm.doc.items, "s_warehouse", frm.doc.default_source_warehouse);
    },

    validate: function (frm) {

        frappe.call({
            method: "nj_features.nj_features.doctype.stock_movement.stock_movement.validate_stock_movement_for_grade",
            args: { doc: frm.doc },
            async: false, 
            callback: function (r) {
                if (r && r.message) {
                    if (r.message.error) {
                        frappe.msgprint({
                            title: __('Error'),
                            message: __(r.message.error),
                            indicator: 'red'
                        });
                        frappe.validated = false; 
                        return; 
                    }
                }
            }
        });
    
        if (cur_frm.doc.move_stock == 1) {
            for (var i = 0; i < frm.doc.items.length; i++) {
                (function (index) {
                    var t_warehouse = frm.doc.items[index].t_warehouse;
                    if (t_warehouse) {
                        frappe.call({
                            method: "frappe.client.get_value",
                            args: {
                                doctype: "Warehouse",
                                filters: { 'name': t_warehouse },
                                fieldname: ["available_capacity", "max_capacity", "qty_after_transaction"]
                            },
                            async: false,
                            callback: function (response) {
                                if (response && response.message && frm.doc.items[i]) {
                                    const available_capacity = response.message.available_capacity;
                                    const max_capacity = response.message.max_capacity;
                                    const qty_after_transaction = response.message.qty_after_transaction;
                                    const item_qty = frm.doc.items[i].qty;
    
                                    if (item_qty > available_capacity || item_qty > (max_capacity - qty_after_transaction)) {
                                        var msg = frappe.msgprint({
                                            message: `Reached maximum capacity of the warehouse in <strong>"${t_warehouse}"</strong>`,
                                            title: "Message",
                                            primary_action: {
                                                action: function () { msg.hide(); },
                                                label: "OK"
                                            }
                                        });
                                        frappe.validated = false; 
                                        return;
                                    }
                                }
                            }
                        });
    
                        $('[data-fieldname="scan_barcode"]').focus();
                    }
                })(i);
            }
        }
    }
    
    // after_submit(frm) {
    //     setTimeout(function(){
    //         frappe.set_route('List', frm.doc.doctype);
    //     }, 5000)
    // }
})

function executeRemainingCode(frm, changed_item_code) {
    // Get the child table data
    if (frm.doc.scan_grade != '' && changed_item_code != '') {
        var new_item_code = '';
        frappe.db.get_value('Grade', { 'name': cur_frm.doc.scan_grade }, 'name')
            .then(function (r) {
                if (r.message.name) {
                    new_item_code = changed_item_code + "-" + r.message.name;
                    frappe.model.with_doc("Stock Movement", frm.docname, function() {
                        var table = frappe.model.get_doc("Stock Movement", frm.docname).items;
                        var child_item = table.find(d => d.idx === frm.selected_child);
                        if (child_item) {
                            frappe.model.set_value(child_item.doctype, child_item.name, 'grade', r.message.name);
                        }
                    });
                    
                } else {
                    frappe.msgprint(`Grade: <strong>${frm.doc.scan_grade}<\strong> not found. Please enter a valid Grade.`);
                    cur_frm.set_value('scan_grade', '');
                    cur_frm.set_value('scan_barcode', '');
                    $('[data-fieldname="scan_barcode"]').focus();
                }
                
                if(r.message.name) {
                    frappe.db.get_value('Item', { name: new_item_code }, ['name', 'item_name'])
                    .then(function (r) {
                        if (r.message.name) {
                            item_code_init = r.message.name;
                            if(frm.doc.transfer_status == "Racking") {
                                var data = {};
                                data['item_code'] = item_code_init;
                                data['warehouse'] = frm.doc.default_source_warehouse;
                                frappe.prompt({
                                    label: 'Enter Qty for Non-serialized Item',
                                    fieldname: 'qty',
                                    fieldtype: 'Int'
                                }, (values) => {
                                    data['qty'] = values.qty;
                                    modify_table_after_scan(cur_frm, data);
                                    cur_frm.set_value('scan_grade', '');
                                    cur_frm.set_value('scan_barcode', '');
                                    $('[data-fieldname="scan_barcode"]').focus();
                                });
                            }

                        } else {
                            frappe.msgprint(`Item: <strong>${new_item_code}</strong> doesn't exist. Please enter a valid Item.`);
                            cur_frm.set_value('scan_grade', '');
                            cur_frm.set_value('scan_barcode', '');
                            $('[data-fieldname="scan_barcode"]').focus();
                        }
                    });
                }
            });
    }
}

frappe.ui.form.on('Stock Movement Detail', {
    item_code: function(frm, cdt, cdn) {
        var child = locals[cdt][cdn];
        var userRoles = frappe.user_roles;
        var isKitter = userRoles.some(role => role.toLowerCase() === 'kitter');

        if (isKitter && cur_frm.doc.transfer_status.toLowerCase() == "racking") {
            
            if (child.serial_no) {
                frappe.db.get_value('Serial No', { 'name': child.serial_no }, 'warehouse').then(function (r) {
                    if (r.message && r.message.warehouse) {
                        frappe.model.set_value(child.doctype, child.name, 's_warehouse', r.message.warehouse);
                    }
                });
            }
        } else {
            autofill_warehouse([child], "t_warehouse", frm.doc.default_target_warehouse);
            autofill_warehouse([child], "s_warehouse", frm.doc.default_source_warehouse);
        }

        if (cur_frm.doc.transfer_status.toLowerCase() == "racking") {
            frm.set_df_property('items', 'read_only', 1, frm.docname, 's_warehouse', child.name);
            
            var lastRecordIndex = cur_frm.doc.items.length - 1;
            if (cur_frm.doc.items.indexOf(child) === lastRecordIndex) {
                createDialogForLastRecord(child, cdt, cdn);
            }
        }
    }
});

function createDialogForLastRecord(child, cdt, cdn) {
    const item = child;
    if (item.serial_no || item.item_code) {
        var userRoles = frappe.user_roles;
        var hasCentralizedRole = userRoles.includes('Centralized Warehouse');
        
        if (item.idx > 1 && cur_frm.doc.is_default_target_warehouse == 1) {
            let default_target_warehouse = cur_frm.doc.items[0].t_warehouse;
            frappe.db.get_value('Warehouse', {name: default_target_warehouse}, 'name').then(function(r) {
                if (r.message && r.message.name) {
                    frappe.model.set_value(cdt, cdn, 't_warehouse', r.message.name);
                } else {
                    frappe.msgprint(`Warehouse: <strong>"${r.message.name}"</strong> does not exist. Please enter a valid Warehouse.`);
                    $('[data-fieldname="scan_barcode"]').focus();
                }
            });

        } else {
            frappe.call({
                method: 'nj_features.nj_features.doctype.stock_movement.stock_movement.get_all_emp_warehouse',
                args: {'user': frappe.session.user_email},
                callback: function(response) {
                    if (response.message && response.message.error) {
                        // Handle error
                    } else {
                        var recommended = response.message.recommended;
                        var centralized = response.message.centralized;

                        let fields = [
                            {
                                label: 'Warehouse',
                                fieldname: 't_warehouse',
                                fieldtype: 'Data',
                                options: 'Barcode'
                            },
                            {
                                label: 'Recommended Warehouse',
                                fieldname: 'req_warehouse',
                                fieldtype: 'Small Text',
                                default: recommended,
                                read_only: 1
                            }
                        ];
    
                        // Add the "Centralized Warehouse" field if the user has the role
                        if (hasCentralizedRole) {
                            fields.push({
                                label: 'Centralized Warehouse',
                                fieldname: 'cen_warehouse',
                                fieldtype: 'Small Text',
                                default: centralized,
                                read_only: 1
                            });
                        }
                        
                        fields.push({
                            label: 'Close',
                            fieldtype: 'Button',
                            click: function() {
                                let t_warehouse_value = $('[data-fieldname="t_warehouse"]').val();
                                // Only remove the row if t_warehouse is empty
                                if (t_warehouse_value.trim() === '') {
                                    let row = cur_frm.fields_dict.items.grid.grid_rows_by_docname[cdn];
                                    if (row) {
                                        row.remove();  // Remove the row from the grid
                                    } else {
                                        console.log('Row not found for the current cdn.');
                                    }
                                }
                                d.hide();
                            }
                        });
                        
                        let d = new frappe.ui.Dialog({
                            fields: fields,
                            size: 'small',
                            static: 1
                        });
                        
                        // On blur of the t_warehouse field
                        d.fields_dict.t_warehouse.$input.on("blur", function() {
                            handleScannerInput(d, 't_warehouse');
                            let t_warehouse_value = $(this).val().trim();
                        
                            if (t_warehouse_value === '') {
                                return; // No further checks or messages, just return
                            }
                        
                            let isValidWarehouse = recommended.includes(t_warehouse_value) || centralized.includes(t_warehouse_value);
                        
                            if (isValidWarehouse) {
                                frappe.db.get_value('Warehouse', { name: t_warehouse_value }, 'name').then(function(r) {
                                    if (r.message && r.message.name) {
                                        frappe.model.set_value(cdt, cdn, 't_warehouse', r.message.name);
                                        setTimeout(() => { d.hide(); }, 200);
                                    } else {
                                        frappe.msgprint(`Warehouse: <strong>"${t_warehouse_value}"</strong> does not exist. Please enter a valid Warehouse.`);
                                        $('[data-fieldname="scan_barcode"]').focus();
                                    }
                                });
                            } else {
                                frappe.msgprint(`Warehouse: <strong>"${t_warehouse_value}"</strong> does not match with recommended or centralized warehouse.`);
                                $('[data-fieldname="t_warehouse"]').val('').focus(); // Clear and refocus the field
                            }
                        });
                        
                        // Prevent form refresh by blocking ENTER key in the dialog
                        d.$wrapper.on("keydown", function(event) {
                            if (event.key === "Enter") {
                                event.preventDefault();
                                return false;
                            }
                        });
                        d.show();
                    }
                }
            });
        }
        cur_frm.refresh_field('items');
    }
}


// frappe.ui.form.on('Stock Movement Detail', {
//     item_code: function(frm, cdt, cdn) {
//         var child = locals[cdt][cdn];
//         autofill_warehouse([child], "t_warehouse", cur_frm.doc.default_target_warehouse);
//         autofill_warehouse([child], "s_warehouse", cur_frm.doc.default_source_warehouse);

//         if (cur_frm.doc.move_stock == 1) {
//             var lastRecordIndex = cur_frm.doc.items.length - 1;

//             if (cur_frm.doc.items.indexOf(child) === lastRecordIndex) {
//                 createDialogForLastRecord(child, cdt, cdn);
//             }
//         }
//     }
// });

// function createDialogForLastRecord(child, cdt, cdn) {
//     const item = child;
//     if (item.serial_no || item.item_code) {
//         var itemCode = item.item_code;

//         frappe.db.get_value('Item', {"name": itemCode}, ['item_group', 'brand']).then(function(r) {
//             var itemGroup = r.message.item_group;
//             var brand = r.message.brand;

//             if (item.item_group) {
//                 frappe.model.set_value(cdt, cdn, 'item_group', itemGroup);
//             }
//             frappe.model.set_value(cdt, cdn, 'brand', brand);
//             var userRoles = frappe.user_roles;
//             var hasCentralizedRole = userRoles.includes('Centralized Warehouse');
//             // Get all employee warehouses
//             frappe.call({
//                 method: 'nj_features.nj_features.doctype.stock_movement.stock_movement.get_all_emp_warehouse',
//                 args: {'user': frappe.session.user_email},
//                 callback: function(response) {
//                     if (response.message && response.message.error) {
//                         // frappe.msgprint('Error: ' + response.message.error);
//                     } else {
//                         var recommended = response.message.recommended;
//                         var centralized = response.message.centralized;

//                         let fields = [
//                             {
//                                 label: 'Target Warehouse',
//                                 fieldname: 't_warehouse',
//                                 fieldtype: 'Data'
//                             },
//                             {
//                                 label: 'Recommended Warehouse',
//                                 fieldname: 'req_warehouse',
//                                 fieldtype: 'Small Text',
//                                 default: recommended,
//                                 read_only: 1
//                             }
//                         ];

//                         // Add the "Centralized Warehouse" field if the user has the role
//                         if (hasCentralizedRole) {
//                             fields.push({
//                                 label: 'Centralized Warehouse',
//                                 fieldname: 'cen_warehouse',
//                                 fieldtype: 'Small Text',
//                                 default: centralized,
//                                 read_only: 1
//                             });
//                         }

//                         fields.push({
//                             label: 'Close',
//                             fieldtype: 'Button',
//                             click: function() {
//                                 cur_frm.get_field('items').grid.grid_rows_by_docname[cdn].remove();
//                                 d.hide();
//                             }
//                         });

//                         let d = new frappe.ui.Dialog({
//                             fields: fields,
//                             size: 'small',
//                         });
//                         // var recommended_list = parseWarehouseList(recommended)
//                         // var centralized_list = parseWarehouseList(centralized)
//                         d.fields_dict.t_warehouse.$input.on("change", function() {
//                             let t_warehouse_value = $(this).val();
//                             // if (!recommended_list[t_warehouse_value] || !centralized_list[t_warehouse_value]) { // || (!centralized_list[t_warehouse_value] && hasCentralizedRole)
//                             //     frappe.msgprint(`You are not allowed to move stock from warehouse: <strong>${t_warehouse_value}</strong>`);
//                             //     cur_frm.get_field('items').grid.grid_rows_by_docname[cdn].remove();
//                             //     $('[data-fieldname=""]').focus();
//                             //     return;
//                             // } 
//                             // else if (centralized_list[t_warehouse_value] && !hasCentralizedRole) {
//                             //     frappe.msgprint(`You are not allowed to move stock from centralized warehouse: <strong>${t_warehouse_value}</strong>`);
//                             //     cur_frm.get_field('items').grid.grid_rows_by_docname[cdn].remove();
//                             //     return;
//                             // }

//                             // Perform validation
//                             frappe.db.get_value('Warehouse', {name: t_warehouse_value}, 'name').then(function(r) {
//                                 if (r.message && r.message.name) {
//                                     frappe.model.set_value(cdt, cdn, 't_warehouse', r.message.name);
//                                 } else {
//                                     frappe.msgprint(`Warehouse: <strong>"${r.message.name}"</strong> does not exist. Please enter a valid Warehouse.`);
//                                     $('[data-fieldname="scan_barcode"]').focus();
//                                 }
//                                 d.hide();
//                             });
//                         });

//                         if (!response.message.error) {
//                             d.show();
//                         }
//                     }
//                 }
//             });

//             cur_frm.refresh_field('items');
//         });
//     }
// }

// function parseWarehouseList(demo) {
//     let warehouseObject = {};
//     if(demo) {
//         demo.split('\n').forEach(entry => {
//             let [warehouse, qty] = entry.split(' => ');
//             warehouseObject[warehouse.trim()] = parseInt(qty);
//         });
//     }
//     return warehouseObject;
// }


function modify_table_after_scan(frm, data) {
    let cur_grid = frm.fields_dict.items.grid;
    let row_to_modify = null;

    row_to_modify = cur_frm.doc.items.find(d => !d.item_code);

    if (!row_to_modify) {
        row_to_modify = frappe.model.add_child(cur_frm.doc, cur_grid.doctype, 'items');
    }
	if (data.serial_no != "" && data.serial_no != undefined) {
		var existing_record = cur_frm.doc.items.find(d => d.serial_no === data.serial_no);
		if (existing_record) {
			frappe.show_alert({
				message: __('Serial Number already exists in the items list'),
				indicator: 'orange'
			});
            cur_frm.set_value('scan_barcode', '');
            return;
		}
	}

    show_scan_message(row_to_modify.idx, row_to_modify.item_code);
    set_scanned_values(row_to_modify, data);
}

function set_scanned_values(row_to_modify, data) {
    // Fetch item details from the backend
    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'Item',
            name: data.item_code
        },
        callback: function(response) {
            let item_details = response.message;
            let quantity = data.qty ? data.qty : 1;
            // if (item_details && item_details.has_serial_no === 1) {
            //     frappe.msgprint('Item code: <b>'+data.item_code+'</b> is serialized.');
            // } else {
                let values = {
                    item_code: data.item_code,
                    s_warehouse: data.warehouse,
                    qty: quantity,
                    transfer_qty: 1
                };
                if (data.serial_no) {
                    values.serial_no = data.serial_no;
                }
                frappe.model.set_value(row_to_modify.doctype, row_to_modify.name, values);
            // }
        }
    });

    cur_frm.set_value('scan_barcode', '');
    cur_frm.set_value('scan_warehouse', '');
    cur_frm.refresh_field('scan_warehouse');
    cur_frm.refresh_field('items');
}

function show_scan_message(idx, exist = null) {
    if (!exist) {
        frappe.show_alert({
            message: __('Row #{0}: Item added', [idx]),
            indicator: 'green'
        });
    }
}

function autofill_warehouse(child_table, warehouse_field, warehouse) {
    if (warehouse && child_table && child_table.length) {
        let doctype = child_table[0].doctype;
        $.each(child_table || [], function(i, item) {
            frappe.model.set_value(doctype, item.name, warehouse_field, warehouse);
        });
    }
}