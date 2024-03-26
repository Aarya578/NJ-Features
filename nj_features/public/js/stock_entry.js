// //Racking and Stock Movement

// function hideFieldsInChild() {
//     // if (!frappe.user.has_role("Administrator")) {
//     $('.custom-actions.hidden-xs.hidden-md, .menu-btn-group, .grid-download, .grid-upload').hide();
//     console.log("1");
//     var fieldsToHide = ['basic_rate', 'uom', 'stock_uom', 'section_break_8', 'transfer_qty', 'reason', 'basic_amount',
//         'retain_sample', 'uom', 'stock_uom', 'conversion_factor', 'sample_quantity', 'batch_no', 'additional_cost',
//         'more_info', 'reference_section', 'rates_section', 'is_finished_item', 'is_scrap_item', 'is_process_loss',
//         'accounting', 'accounting_dimensions_section', 'project', 'set_basic_rate_manually'];
//     fieldsToHide.forEach(function (field) {
//         var df = frappe.meta.get_docfield("Stock Entry Detail", field, cur_frm.doc.name);
//         if (df) {
//             df.hidden = 1;
//             df.colsize = 0;
//             df.in_list_view = 0;
//         }
//     });
//     // hide for Stock Accept
//     var fields_to_modify = ['reason', 'basic_rate', 't_warehouse'];
//     fields_to_modify.forEach(function (field_name) {
//         var field = frappe.meta.get_docfield("Stock Entry Detail", field_name, cur_frm.doc.name);
//         if (field && cur_frm.doc.stock_movement === 1) {
//             field.in_list_view = 0;
//             field.colsize = 0;
//         }
//     });
//     // hide for Move Stock
//     var fields_to_modify = ['reason', 'basic_rate', 's_warehouse'];
//     fields_to_modify.forEach(function (field_name) {
//         var field = frappe.meta.get_docfield("Stock Entry Detail", field_name, cur_frm.doc.name);
//         if (field && cur_frm.doc.move_stock === 1) {
//             field.in_list_view = 0;
//         } 
//     });

//     var itemCodeField = frappe.meta.get_docfield("Stock Entry Detail", "item_code", cur_frm.doc.name);
//     if (itemCodeField) {
//         itemCodeField.colsize = 3;
//     }
    
//     cur_frm.refresh_fields('items');
//     // }

// }

// function hideOnload() {
//     // if (!frappe.user.has_role("Administrator")) {
//     $('.custom-actions.hidden-xs.hidden-md, .btn.btn-default.btn-sm[data-label="Cancel"], .icon-btn[data-original-title="Print"]')
//         .hide();
//     $(".title-text").html("New Stock Movement")
//     const fieldsToHide = [
//         'total_additional_costs', 'apply_putaway_rule', 'bom_info_section', 'from_bom', 'additional_costs_section',
//         'printing_settings', 'more_info', 'get_stock_and_rate', 'additional_costs', 'items_section', 'sb1', 'from_warehouse',
//         'section_break_19', 'source_warehouse_address', 'target_warehouse_address', 'accounting_dimensions_section',
//         'reason', 'comments', 'workflow_state', 'to_warehouse'
//     ];
//     fieldsToHide.forEach(field => cur_frm.set_df_property(field, 'hidden', 1));
//     cur_frm.set_value('stock_entry_type', 'Material Transfer');
//     cur_frm.set_df_property('stock_entry_type', 'hidden', 1);
//     cur_frm.refresh_fields();
//     // }
// }

// var item_code_init = "";

// nj_features.nj_features.doctype.stock_entry.stockaccess


frappe.ui.form.on('Stock Entry', {
    onload: function(frm) {
        frappe.call({
            method: 'nj_features.nj_features.doctype.stock_entry.stockaccess',
            args: {'doc': frm.doc},
            callback: function(r) {
                if (r.message && r.message.stock_entry_type_query) {
                    console.log("r.message.stock_entry_type_query==",r.message.stock_entry_type_query)
                    frm.set_query('stock_entry_type', function() {
                        return {
                            filters: {
                                'name': ['in', r.message.stock_entry_type_query]
                            }
                        }
                    });
                }
                // if (r.message && !r.message.stock_entry_type) {
                //     console.log("!r.message.stock_entry_type========>>>>>>inside read only fields",!r.message.stock_entry_type)
                //     frm.set_df_property('stock_entry_type', 'read_only', 1);
                // }
            }
        });
    }
});

//     before_load: function () {
//         if (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1) {
//             hideFieldsInChild();
//         } else if (cur_frm.doc.stock_entry_type == "Material Transfer") {
//             hideFieldsInChild();
//             hideOnload()
//         }

//     },
//     refresh() {
//         if (cur_frm.doc.stock_entry_type == "Material Transfer") {
//             hideFieldsInChild();
//             hideOnload();
//         }
//         if (cur_frm.doc.docstatus == 1) {
//             cur_frm.set_df_property('additional_costs_section', 'hidden', 1);
//         }
//         if (cur_frm.doc.stock_movement == 1) {
//             var t_ware = frappe.meta.get_docfield("Stock Entry Detail", 't_warehouse', cur_frm.doc.name);
//             if (t_ware) {
//                 t_ware.read_only = 1;
//                 t_ware.in_list_view = 1;
//             }
//         }
//         if (cur_frm.doc.move_stock == 1) {
//             var s_ware = frappe.meta.get_docfield("Stock Entry Detail", 's_warehouse', cur_frm.doc.name);
//             if (s_ware) {
//                 s_ware.read_only = 1;
//                 s_ware.in_list_view = 1;
//             }
//         }
//         cur_frm.refresh_fields('items')
//     },
//     onload_post_render() {
//         if (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1) {
//             cur_frm.set_df_property('additional_costs_section', 'hidden', 1);
//         }
//     },

//     scan_barcode: function () {
//         if (cur_frm.doc.scan_barcode && (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1)) {
//             frappe.call({
//                 method: "nj_features.api_files.search_for_serial_or_batch_or_barcode_no",
//                 args: {
//                     search_value: cur_frm.doc.scan_barcode
//                 },
//                 callback: function(r) {
//                     console.log("search value: ", r.message.scan);
//                     const data = r && r.message;
//                     if (r.message.scan === 1) {
//                         cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], true);
//                     } else {
//                         cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
//                     }

//                     if(r.message.serial_no && cur_frm.doc.stock_movement == 1) {
//                         console.log("serialised data stock movement: ", data);
//                         modify_table_after_scan(cur_frm, data)
//                     }

//                     else if(r.message.serial_no && r.message.s_warehouse === cur_frm.doc.from_warehouse && cur_frm.doc.move_stock == 1) {
//                         console.log("serialised data stock movement: ", data);
//                         modify_table_after_scan(cur_frm, data)
//                     } else {
//                         cur_frm.set_value('scan_barcode', '')
//                         frappe.throw(`You are not allowed to move stock from warehouse: <strong>${r.message.s_warehouse}<\strong>`)
//                     }
//                 }
//             });
//         }
//         return false;
//     },


//     scan_warehouse: function(frm) {
//         // Update the s_warehouse field in each row of the items child table
//         if (frm.doc.scan_warehouse !== '' && (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1)) {
//             var data = {}
//             frappe.db.get_value('Warehouse', { name: frm.doc.scan_warehouse }, 'name').then(function (r) {
//                 if (r.message.name) {
//                     console.log("new item code", item_code_init);
//                     var ware = r.message.name
//                         data['item_code'] = item_code_init
//                         data['warehouse'] = ware
//                         console.log("data after scan ware: ", data);
//                         modify_table_after_scan(cur_frm, data);
//                         cur_frm.set_value('scan_warehouse', '');
//                         cur_frm.set_value('scan_grade', '');
//                         cur_frm.set_value('scan_barcode', '');
                        
//                 } else {
//                     frappe.msgprint(`Warehouse: <strong>${r.message.name}<\strong> does not exist. Please enter a valid Warehouse.`);
//                     cur_frm.set_value('scan_warehouse', '');
//                 }
//             });
//         }
//         return false;
//     },

//     scan_grade: function(frm) {
//         // Get the child table data
//         if (frm.doc.scan_grade !== '' && (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1)) {
//             var new_item_code = ''
//             frappe.db.get_value('Grade', { 'name': cur_frm.doc.scan_grade }, 'name')
//                 .then(function (r) {
//                     if (r.message.name) {
//                         new_item_code = cur_frm.doc.scan_barcode + "-" + r.message.name
//                         console.log("new_item_code: ", new_item_code)
                        
//                     } else {
//                         frappe.msgprint(`Grade: <strong>${r.message.name}<\strong> not found. Please enter a valid Grade.`);
//                         cur_frm.set_value('scan_grade', '');
//                         cur_frm.set_value('scan_barcode', '');
//                     }
                    
//                 if(r.message.name) {
//                     frappe.db.get_value('Item', { name: new_item_code }, ['name', 'item_name'])
//                         .then(function (r) {
//                             console.log("r from new item", r);
//                             if (r.message.name) {
//                                 item_code_init = r.message.name
//                                 console.log("item code in DB: ", r.message.name)

//                             } else {
//                                 frappe.msgprint(`Item: <strong>${new_item_code}</strong> doesn't exist. Please enter a valid Item.`);
//                             }
//                     })
//                 }
//             })

//         }
//     },
//     validate: function (frm) {

//         if (cur_frm.doc.move_stock == 1) {
//             for (var i = 0; i < frm.doc.items.length; i++) {
//                 (function (index) {
//                     var t_warehouse = frm.doc.items[index].t_warehouse;
//                     if (t_warehouse) {
//                         frappe.call({
//                             method: "frappe.client.get_value",
//                             args: {
//                                 doctype: "Warehouse",
//                                 filters: { 'name': t_warehouse },
//                                 fieldname: "available_capacity"
//                             },
//                             async: false,
//                             callback: function (response) {
//                                 if (response && response.message && frm.doc.items[i]) {
//                                     if (frm.doc.items[i].qty > response.message.available_capacity || frm.doc.items[i].qty > (response.message.max_capacity - response.message.qty_after_transaction)) {
//                                         var msg = frappe.msgprint({
//                                             message: `Reached maximum capacity of the warehouse in <strong>"${t_warehouse}"</strong>`,
//                                             title: "Message",
//                                             primary_action: {
//                                                 action: function () {
//                                                     msg.hide();
//                                                 },
//                                                 label: "OK"
//                                             }
//                                         });

//                                         frappe.validated = false;
//                                     }
//                                 }
//                             }
//                         });
//                     } else {
//                         console.log("Warehouse is not found");
//                     }
//                 })(i);
//             }
//         }
//     }
// })

// frappe.ui.form.on('Stock Movement Detail', {
//     item_code: function (frm, cdt, cdn) {
//         var child = locals[cdt][cdn]
//         if (cur_frm.doc.move_stock == 1) {
//             console.log("move_stock");
//             for (let i = 0; i < cur_frm.doc.items.length; i++) {
//                 const item = cur_frm.doc.items[i];
//                 if (item.serial_no || item.item_code) {
//                     var itemCode = item.item_code;
                    
//                     frappe.db.get_value('Item', { "name": itemCode }, ['item_group', 'brand'])
//                         .then(function (r) {
//                             var itemGroup = r.message.item_group;
//                             var brand = r.message.brand;
//                             if (item.item_group) {
//                                 frappe.model.set_value(cdt, cdn, 'item_group', itemGroup);
//                             }
//                             frappe.model.set_value(cdt, cdn, 'brand', brand);
//                             // get all emp_ware
//                             frappe.call({
//                                 method: 'nj_features.api_files.get_all_emp_warehouse',
//                                 args: {
//                                     'user': frappe.session.user_email
//                                 },
//                                 callback: function (response) {
//                                     if (response.message && response.message.error) {
//                                         // frappe.msgprint('Error: ' + response.message.error);
//                                     } else {
//                                         var warehouse_info = response.message;
//                                         console.log("warehouse_info", warehouse_info);
//                                         var warehouse_list = '';
//                                         for (var warehouse in warehouse_info) {
//                                                 warehouse_list += `${warehouse} =>   ${warehouse_info[warehouse]} qty\n`;
//                                         }
//                                         let d = new frappe.ui.Dialog({
//                                             fields: [
//                                                 {
//                                                     label: 'Target Warehouse',
//                                                     fieldname: 't_warehouse',
//                                                     fieldtype: 'Data'
//                                                 },
//                                                 {
//                                                     label: 'Recommended Warehouse',
//                                                     fieldname: 'req_warehouse',
//                                                     fieldtype: 'Small Text',
//                                                     default: warehouse_list,
//                                                     read_only: 1
//                                                 }
//                                             ],
//                                             size: 'small'
//                                         });
                            
//                                         d.fields_dict.t_warehouse.$input.on("change", function() {
//                                             let t_warehouse_value = $(this).val();
//                                             // Perform validation
//                                             frappe.db.get_value('Warehouse', { name: t_warehouse_value }, 'name').then(function (r) {
//                                                 if (r.message && r.message.name) {
//                                                     // Set the value in the form
//                                                     frappe.model.set_value(cdt, cdn, 't_warehouse', r.message.name);
//                                                     d.hide();
//                                                 } else {
//                                                     frappe.msgprint('Warehouse does not exist. Please enter a valid Warehouse.');
//                                                 }
//                                             });
//                                         });
//                                         if (response.message.error) {
//                                             d.show();
//                                         }
//                                     }
//                                 }
//                             });
                            

//                             frm.refresh_field('items');
//                         })
//                 }
//             }
//         }
//     }
    
// });

// function modify_table_after_scan(frm, data) {
//     let cur_grid = frm.fields_dict.items.grid;
//     let row_to_modify = null;

//     row_to_modify = cur_frm.doc.items.find(d => !d.item_code);

//     if (!row_to_modify) {
//         row_to_modify = frappe.model.add_child(cur_frm.doc, cur_grid.doctype, 'items');
//     }
    
//     var existing_record = cur_frm.doc.items.find(d => d.serial_no === data.serial_no);
//     if (existing_record) {
//         frappe.show_alert({
//             message: __('Serial Number already exists in the items list'),
//             indicator: 'orange'
//         });
//     }
//     console.log("row_to_modify: ", row_to_modify, "data: ", data, "existing_record: ", existing_record)
    

//     show_scan_message(row_to_modify.idx, row_to_modify.item_code);
//     set_scanned_values(row_to_modify, data);
//     // if(!existing_record) {
//     // }
// }

// function set_scanned_values(row_to_modify, data) {
//     // Set values in the correct row
//     let values = {
//         item_code: data.item_code,
//         s_warehouse: data.s_warehouse,
//         qty: 1
//     }
//     if (data.serial_no) {
//         values.serial_no = data.serial_no
//         // values.item_code = data.item_code
//     }
//     console.log("data: ", data, " | values", values );
//     frappe.model.set_value(row_to_modify.doctype, row_to_modify.name, values);

//     cur_frm.set_value('scan_barcode', '');
//     cur_frm.set_value('scan_grade', '');
//     cur_frm.set_value('scan_warehouse', '');
//     refresh_field("items");
// }

// // function get_row_to_modify_on_scan(frm, row_to_modify, data) {
// // 	const existing_item_row = frm.doc.items.find(d => d.serial_no === data.serial_no);
// // 	const blank_item_row = frm.doc.items.find(d => !d.serial_no);

// // 	if (existing_item_row) {
// // 		row_to_modify = existing_item_row;
// // 	} else if (blank_item_row) {
// // 		row_to_modify = blank_item_row;
// // 	}
// // 	return row_to_modify;
// // }

// // function get_row_to_modify_on_scan() {
// //     // const existing_item_row = cur_frm.doc.items.find(d => d.serial_no === data.serial_no);
// //     const blank_item_row = cur_frm.doc.items.find(d => !d.item_code);
    

// //     // if (existing_item_row) {
// //     //     row_to_modify = existing_item_row;
// //     // } else if (blank_item_row) {
// //     //     row_to_modify = blank_item_row;
// //     // }

// //     return blank_item_row;
// // }

// function show_scan_message(idx, exist = null) {
//     if (!exist) {
//         frappe.show_alert({
//             message: __('Row #{0}: Item added', [idx]),
//             indicator: 'green'
//         });
//     }
// }