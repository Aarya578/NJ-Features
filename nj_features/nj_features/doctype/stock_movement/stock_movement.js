// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
//Racking and Stock Movement
$('.custom-actions.hidden-xs.hidden-md, .btn.btn-default.btn-sm[data-label="Cancel"], .icon-btn[data-original-title="Print"]')
    .hide();

function hideFieldsInChild() {
    // if (!frappe.user.has_role("Administrator")) {
    $('.custom-actions.hidden-xs.hidden-md, .menu-btn-group, .grid-download, .grid-upload').hide();
   
    // hide for Stock Accept
    var t_ware = frappe.meta.get_docfield("Stock Movement Detail", 't_warehouse', cur_frm.doc.name);
    if (t_ware && cur_frm.doc.stock_movement === 1) {
        t_ware.in_list_view = 0;
        t_ware.read_only = 1;
        t_ware.colsize = 0;
    }
    // hide for Move Stock
    var s_ware = frappe.meta.get_docfield("Stock Movement Detail", 's_warehouse', cur_frm.doc.name);
    if (s_ware && cur_frm.doc.move_stock === 1) {
        s_ware.in_list_view = 0;
        s_ware.read_only = 1;
    }
    if (t_ware && cur_frm.doc.move_stock === 1) {
        t_ware.read_only = 1;
    }

    var itemCodeField = frappe.meta.get_docfield("Stock Movement Detail", "item_code", cur_frm.doc.name);
    if (itemCodeField) {
        itemCodeField.colsize = 3;
    }
    
    cur_frm.refresh_fields('items');
    // }

}

var item_code_init = "";


frappe.ui.form.on('Stock Movement', {
    onload() {
        $('.col-lg-2.layout-side-section').hide();
        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
        hideFieldsInChild();
    },
    before_load: function () {
        hideFieldsInChild();

    },
    refresh() {
        hideFieldsInChild();
        if (cur_frm.doc.stock_movement == 1) {
			cur_frm.set_df_property('default_source_warehouse', 'hidden', 1);
            var t_ware = frappe.meta.get_docfield("Stock Movement Detail", 't_warehouse', cur_frm.doc.name);
            if (t_ware) {
                t_ware.read_only = 1;
                t_ware.in_list_view = 1;
            }
        }
        if (cur_frm.doc.move_stock == 1) {
			cur_frm.set_df_property('default_target_warehouse', 'hidden', 1);
            var s_ware = frappe.meta.get_docfield("Stock Movement Detail", 's_warehouse', cur_frm.doc.name);
            if (s_ware) {
                s_ware.read_only = 1;
                s_ware.in_list_view = 1;
            }
        }

        if (cur_frm.doc.default_target_warehouse) {
            console.log("default_target_warehouse", cur_frm.doc.default_target_warehouse);
            autofill_warehouse(cur_frm.doc.items, "t_warehouse", cur_frm.doc.default_target_warehouse);
        }
        if (cur_frm.doc.default_source_warehouse) {
            console.log("default_source_warehouse", cur_frm.doc.default_source_warehouse);
            autofill_warehouse(cur_frm.doc.items, "s_warehouse", cur_frm.doc.default_source_warehouse);
        }
        cur_frm.refresh_fields('items')
    },

    scan_barcode: function () {
        if (cur_frm.doc.scan_barcode && (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1)) {
            frappe.call({
                method: "nj_features.api_files.search_for_serial_or_batch_or_barcode_no",
                args: {
                    search_value: cur_frm.doc.scan_barcode
                },
                callback: function(r) {
                    console.log("search value: ", r.message.scan);
                    const data = r && r.message;
                    if (r.message.scan === 1) {
                        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], true);
                    } else {
                        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
                    }
    
                    if(r.message.serial_no && cur_frm.doc.stock_movement == 1) {
                        console.log("serialised data stock movement: ", data);
                        modify_table_after_scan(cur_frm, data)
                    }
    
                    else if(r.message.serial_no && r.message.s_warehouse === cur_frm.doc.from_warehouse && cur_frm.doc.move_stock == 1) {
                        console.log("serialised data stock movement: ", data);
                        modify_table_after_scan(cur_frm, data)
                    } 
                    else if (cur_frm.doc.move_stock == 1){
                        cur_frm.set_value('scan_barcode', '')
                        frappe.throw(`You are not allowed to move stock from warehouse: <strong>${r.message.s_warehouse}</strong>`);  
                    }
                }
            });
        }
        return false;
    },    


    scan_warehouse: function(frm) {
        // Update the s_warehouse field in each row of the items child table
        if (frm.doc.scan_warehouse !== '' && (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1)) {
            var data = {}
            frappe.db.get_value('Warehouse', { name: frm.doc.scan_warehouse }, 'name').then(function (r) {
                if (r.message.name) {
                    console.log("new item code", item_code_init);
                    var ware = r.message.name
                        data['item_code'] = item_code_init
                        data['warehouse'] = ware
                        console.log("data after scan ware: ", data);
                        modify_table_after_scan(cur_frm, data);
                        cur_frm.set_value('scan_warehouse', '');
                        cur_frm.set_value('scan_grade', '');
                        cur_frm.set_value('scan_barcode', '');
                        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
                        
                } else {
                    frappe.msgprint(`Warehouse: <strong>${frm.doc.scan_warehouse}<\strong> does not exist. Please enter a valid Warehouse.`);
                    cur_frm.set_value('scan_warehouse', '');
                }
            });
        }
        return false;
    },

    scan_grade: function(frm) {
        // Get the child table data
        if (frm.doc.scan_grade !== '' && (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1)) {
            var new_item_code = ''
            frappe.db.get_value('Grade', { 'name': cur_frm.doc.scan_grade }, 'name')
                .then(function (r) {
                    if (r.message.name) {
                        new_item_code = cur_frm.doc.scan_barcode + "-" + r.message.name
                        frappe.model.with_doc("Stock Movement", frm.docname, function() {
                            var table = frappe.model.get_doc("Stock Movement", frm.docname).items;
                            var child_item = table.find(d => d.idx === frm.selected_child);
                            if (child_item) {
                                frappe.model.set_value(child_item.doctype, child_item.name, 'grade', r.message.name);
                                console.log("new_item_code: ", new_item_code);
                            }
                        });
                        console.log("new_item_code: ", new_item_code)
                        
                    } else {
                        frappe.msgprint(`Grade: <strong>${frm.doc.scan_grade}<\strong> not found. Please enter a valid Grade.`);
                        cur_frm.set_value('scan_grade', '');
                        cur_frm.set_value('scan_barcode', '');
                    }
                    
                if(r.message.name) {
                    frappe.db.get_value('Item', { name: new_item_code }, ['name', 'item_name'])
                        .then(function (r) {
                            console.log("r from new item", r);
                            if (r.message.name) {
                                item_code_init = r.message.name
                                console.log("item code in DB: ", r.message.name)

                            } else {
                                frappe.msgprint(`Item: <strong>${new_item_code}</strong> doesn't exist. Please enter a valid Item.`);
                            }
                    })
                }
            })

        }
    },
    default_target_warehouse: function(frm) {
        autofill_warehouse(frm.doc.items, "t_warehouse", frm.doc.default_target_warehouse);
    },
    default_source_warehouse: function(frm) {
        autofill_warehouse(frm.doc.items, "s_warehouse", frm.doc.default_source_warehouse);
    },
	
    validate: function (frm) {

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
                                fieldname: "available_capacity"
                            },
                            async: false,
                            callback: function (response) {
                                if (response && response.message && frm.doc.items[i]) {
                                    if (frm.doc.items[i].qty > response.message.available_capacity || frm.doc.items[i].qty > (response.message.max_capacity - response.message.qty_after_transaction)) {
                                        var msg = frappe.msgprint({
                                            message: `Reached maximum capacity of the warehouse in <strong>"${t_warehouse}"</strong>`,
                                            title: "Message",
                                            primary_action: {
                                                action: function () {
                                                    msg.hide();
                                                },
                                                label: "OK"
                                            }
                                        });

                                        frappe.validated = false;
                                    }
                                }
                            }
                        });
                    } else {
                        console.log("Warehouse is not found");
                    }
                })(i);
            }
        }
    }
})

frappe.ui.form.on('Stock Movement Detail', {
    item_code: function(frm, cdt, cdn) {
        var child = locals[cdt][cdn];
        autofill_warehouse([child], "t_warehouse", child.t_warehouse);
        autofill_warehouse([child], "s_warehouse", child.s_warehouse);

        if (cur_frm.doc.move_stock == 1) {
            console.log("move_stock");

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
        var itemCode = item.item_code;

        frappe.db.get_value('Item', {"name": itemCode}, ['item_group', 'brand']).then(function(r) {
            var itemGroup = r.message.item_group;
            var brand = r.message.brand;

            if (item.item_group) {
                frappe.model.set_value(cdt, cdn, 'item_group', itemGroup);
            }
            frappe.model.set_value(cdt, cdn, 'brand', brand);
            // var userRoles = frappe.user_roles;
            // var hasCentralizedRole = userRoles.includes('Centralized Warehouse');
            // Get all employee warehouses
            frappe.call({
                method: 'nj_features.api_files.get_all_emp_warehouse',
                args: {'user': frappe.session.user_email},
                callback: function(response) {
                    console.log("get_all_emp_warehouse: ",response.message);
                    if (response.message && response.message.error) {
                        // frappe.msgprint('Error: ' + response.message.error);
                    } else {
                        var recommended = response.message.recommended;
                        // var centralized = response.message.centralized;

                        let fields = [
                            {
                                label: 'Target Warehouse',
                                fieldname: 't_warehouse',
                                fieldtype: 'Data'
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
                        // if (hasCentralizedRole) {
                        //     fields.push({
                        //         label: 'Centralized Warehouse',
                        //         fieldname: 'cen_warehouse',
                        //         fieldtype: 'Small Text',
                        //         default: centralized,
                        //         read_only: 1
                        //     });
                        // }

                        fields.push({
                            label: 'Close',
                            fieldtype: 'Button',
                            click: function() {
                                cur_frm.get_field('items').grid.grid_rows_by_docname[cdn].remove();
                                d.hide();
                            }
                        });

                        let d = new frappe.ui.Dialog({
                            fields: fields,
                            size: 'small',
                        });
                        var recommended_list = parseWarehouseList(recommended)
                        // var centralized_list = parseWarehouseList(centralized)
                        d.fields_dict.t_warehouse.$input.on("change", function() {
                            let t_warehouse_value = $(this).val();
                            if (!recommended_list[t_warehouse_value]) { // || (!centralized_list[t_warehouse_value] && hasCentralizedRole)
                                frappe.msgprint(`You are not allowed to move stock from warehouse: <strong>${t_warehouse_value}</strong>`);
                                cur_frm.get_field('items').grid.grid_rows_by_docname[cdn].remove();
                                return;
                            } 
                            // else if (centralized_list[t_warehouse_value] && !hasCentralizedRole) {
                            //     frappe.msgprint(`You are not allowed to move stock from centralized warehouse: <strong>${t_warehouse_value}</strong>`);
                            //     cur_frm.get_field('items').grid.grid_rows_by_docname[cdn].remove();
                            //     return;
                            // }

                            // Perform validation
                            frappe.db.get_value('Warehouse', {name: t_warehouse_value}, 'name').then(function(r) {
                                if (r.message && r.message.name) {
                                    frappe.model.set_value(cdt, cdn, 't_warehouse', r.message.name);
                                    d.hide();
                                } else {
                                    frappe.msgprint(`Warehouse: <strong>"${r.message.name}"</strong> does not exist. Please enter a valid Warehouse.`);
                                }
                            });
                        });

                        if (!response.message.error) {
                            d.show();
                        }
                    }
                }
            });

            cur_frm.refresh_field('items');
        });
    }
}

function parseWarehouseList(warehouseList) {
    let warehouseObject = {};
    warehouseList.split('\n').forEach(entry => {
        let [warehouse, qty] = entry.split(' => ');
        warehouseObject[warehouse.trim()] = parseInt(qty);
    });
    return warehouseObject;
}


function modify_table_after_scan(frm, data) {
    let cur_grid = frm.fields_dict.items.grid;
    let row_to_modify = null;

    row_to_modify = cur_frm.doc.items.find(d => !d.item_code);

    if (!row_to_modify) {
        console.log("!row_to_modify")
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
		console.log("row_to_modify: ", row_to_modify, "data: ", data, "existing_record: ", existing_record)
	}

    show_scan_message(row_to_modify.idx, row_to_modify.item_code);
    set_scanned_values(row_to_modify, data);
}

function set_scanned_values(row_to_modify, data) {
    // Set values in the correct row
    let values = {
        item_code: data.item_code,
        s_warehouse: data.warehouse,
        qty: 1,
        transfer_qty: 1
    }
    if (data.serial_no) {
        values.serial_no = data.serial_no
        // values.item_code = data.item_code
    }
    console.log("data: ", data, " | values", values );
    frappe.model.set_value(row_to_modify.doctype, row_to_modify.name, values);

    cur_frm.set_value('scan_barcode', '');
    cur_frm.set_value('scan_grade', '');
    cur_frm.set_value('scan_warehouse', '');
    refresh_field("items");
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