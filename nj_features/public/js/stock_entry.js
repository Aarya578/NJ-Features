//Racking and Stock Movement

function hideFieldsInChild() {
    // if (!frappe.user.has_role("Administrator")) {
    $('.custom-actions.hidden-xs.hidden-md, .menu-btn-group, .grid-download, .grid-upload').hide();
    var fieldsToHide = ['basic_rate', 'uom', 'stock_uom', 'section_break_8', 'transfer_qty', 'reason',
        'retain_sample', 'uom', 'stock_uom', 'conversion_factor', 'sample_quantity', 'batch_no',
        'more_info', 'reference_section', 'rates_section', 'is_finished_item', 'is_scrap_item', 'is_process_loss',
        'accounting', 'accounting_dimensions_section', 'project', 'set_basic_rate_manually'];
    fieldsToHide.forEach(function (field) {
        var df = frappe.meta.get_docfield("Stock Entry Detail", field, cur_frm.doc.name);
        if (df) {
            df.hidden = 1;
            df.colsize = 0;
            df.in_list_view = 0;
        }
    });
    // hide for Stock Accept
    var fields_to_modify = ['reason', 'basic_rate', 't_warehouse'];
    fields_to_modify.forEach(function (field_name) {
        var field = frappe.meta.get_docfield("Stock Entry Detail", field_name, cur_frm.doc.name);
        if (field && cur_frm.doc.stock_movement === 1) {
            field.in_list_view = 0;
        }
    });
    // hide for Move Stock
    var fields_to_modify = ['reason', 'basic_rate', 's_warehouse'];
    fields_to_modify.forEach(function (field_name) {
        var field = frappe.meta.get_docfield("Stock Entry Detail", field_name, cur_frm.doc.name);
        if (field && cur_frm.doc.move_stock === 1) {
            field.in_list_view = 0;
        }
    });

    var itemCodeField = frappe.meta.get_docfield("Stock Entry Detail", "item_code", cur_frm.doc.name);
    if (itemCodeField) {
        itemCodeField.colsize = 3;
    }
    cur_frm.refresh_fields('items');
    // }

}

function hideOnload() {
    // if (!frappe.user.has_role("Administrator")) {
    $('.custom-actions.hidden-xs.hidden-md, .btn.btn-default.btn-sm[data-label="Cancel"], .icon-btn[data-original-title="Print"]')
        .hide();
    $(".title-text").html("New Stock Movement")
    const fieldsToHide = [
        'total_additional_costs', 'apply_putaway_rule', 'bom_info_section', 'from_bom', 'additional_costs_section',
        'printing_settings', 'more_info', 'get_stock_and_rate', 'additional_costs', 'items_section', 'sb1', 'from_warehouse',
        'section_break_19', 'source_warehouse_address', 'target_warehouse_address', 'accounting_dimensions_section',
        'reason', 'comments', 'workflow_state', 'to_warehouse'
    ];
    fieldsToHide.forEach(field => cur_frm.set_df_property(field, 'hidden', 1));
    cur_frm.set_value('stock_entry_type', 'Material Transfer');
    cur_frm.set_df_property('stock_entry_type', 'hidden', 1);
    cur_frm.refresh_fields();
    // }
}

frappe.ui.form.on('Stock Entry', {

    onload() {
        $('.col-lg-2.layout-side-section').hide();
        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
        if (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1) {
            hideOnload()
            hideFieldsInChild();
        }
    },
    before_load: function () {
        if (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1) {
            hideFieldsInChild();
        } else if (cur_frm.doc.stock_entry_type == "Material Transfer") {
            hideFieldsInChild();
            hideOnload()
        }

    },
    refresh() {
        if (cur_frm.doc.stock_entry_type == "Material Transfer") {
            hideFieldsInChild();
            hideOnload();
        }
        if (cur_frm.doc.docstatus == 1) {
            cur_frm.set_df_property('additional_costs_section', 'hidden', 1);
        }
        if (cur_frm.doc.stock_movement == 1) {
            var t_ware = frappe.meta.get_docfield("Stock Entry Detail", 't_warehouse', cur_frm.doc.name);
            if (t_ware) {
                t_ware.read_only = 1;
                t_ware.in_list_view = 1;
            }
        }
        if (cur_frm.doc.move_stock == 1) {
            var s_ware = frappe.meta.get_docfield("Stock Entry Detail", 's_warehouse', cur_frm.doc.name);
            if (s_ware) {
                s_ware.read_only = 1;
                s_ware.in_list_view = 1;
            }
        }
    },
    onload_post_render() {
        if (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1) {
            cur_frm.set_df_property('additional_costs_section', 'hidden', 1);
        }
    },

    scan_barcode: function () {
        if (cur_frm.doc.scan_barcode && (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1)) {
            frappe.call({
                method: "nj_features.api_files.search_for_serial_or_batch_or_barcode_no",
                args: {
                    search_value: cur_frm.doc.scan_barcode
                },
                callback: function (r) {
                    const data = r && r.message;
                    var child_table_data = cur_frm.fields_dict.items.grid.grid_rows_by_docname;
                    var child_records = Object.values(child_table_data);
                    console.log("len:", child_records.length);
                    var last_child_record = child_records[child_records.length - 1].doc;
                    
                    // if (child_records.length > 1) {
                    //     var last_child_record = child_records[child_records.length - 1].doc;

                    //     if (!last_child_record.item_code || !last_child_record.qty) {
                    //         frappe.msgprint('Please fill Item Code and Quantity fields in the last row before scanning the barcode.');
                    //         return false;
                    //     }
                    //     if (last_child_record.serial_no) {
                    //         if (!last_child_record.item_code || !last_child_record.s_warehouse || !last_child_record.t_warehouse) {
                    //             frappe.msgprint('Please fill Item Code, Source Warehouse, and Target Warehouse fields in the last row when Serial No. is filled.');
                    //             return false;
                    //         }
                    //     } else if (last_child_record.item_code && !last_child_record.serial_no && !last_child_record.grade) {
                    //         frappe.msgprint('Grade is mandatory for non-serialized items. Please fill the Grade field.');
                    //         return false;
                    //     } else if (last_child_record.item_code && !last_child_record.serial_no && last_child_record.is_stock_item == 1 && !last_child_record.s_warehouse) {
                    //         frappe.msgprint('Source Warehouse is mandatory for non-serialized stock items. Please fill the Source Warehouse field.');
                    //         return false;
                    //     }
                    // }

                        if (data && Object.keys(data).length !== 0) {
                            modify_table_after_scan(cur_frm, data);

                            if (data.serial_no) {
                                last_child_record.serial_no = data.serial_no;
                                last_child_record.item_code = data.item_code;
                            } else if (data.item_code) {
                                last_child_record.item_code = data.item_code;

                            }

                            // Check if scan_grade should be hidden based on the serial number
                            frappe.call({
                                method: 'nj_features.api_files.serializer_or_notserializer',
                                args: {
                                    item_code: last_child_record.item_code
                                },
                                callback: function (response) {
                                    var has_serial_no = response.message;
                                    if (has_serial_no === 0) { // Check if non-serializable
                                        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], true);
                                    } else { // Serializable
                                        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
                                    }
                                }
                            });
                            
                        }
                }
            });
        }
        return false;
    },

    scan_warehouse: function (frm, cdt, cdn) {
        // Update the s_warehouse field in each row of the items child table
        if (frm.doc.scan_warehouse !== '' && (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1)) {
            var child = locals[cdt][cdn];
            var child_table_data = frm.fields_dict.items.grid.grid_rows_by_docname;
            var child_records = Object.values(child_table_data);
            var last_child_record = child_records[child_records.length - 1].doc;
            frappe.call({
                method: 'nj_features.api_files.serializer_or_notserializer',
                args: {
                    serial_no: last_child_record.serial_no
                },
                callback: function (response) {
                    var has_serial_no = response.message;
                    if (has_serial_no === 0 && child_records && child_records.length > 0) {
                        frappe.db.get_value('Warehouse', { name: frm.doc.scan_warehouse }, 'name').then(function (r) {
                            if (r.message.name) {
                                frappe.model.set_value(last_child_record.doctype, last_child_record.name, "s_warehouse", r.message.name);
                                cur_frm.set_value('scan_warehouse', '');
                                frm.refresh_fields('items');
                            } else {
                                frappe.msgprint('Warehouse does not exist. Please enter a valid Warehouse.');
                            }
                        });
                    } else {
                        cur_frm.set_df_property('items', 'hidden', 1, cur_frm.docname, 's_warehouse', last_child_record.name);
                    }
                }
            });
        }
        return false;
    },

    scan_grade: function (frm, cdt, cdn) {
        // Get the child table data
        if (frm.doc.scan_grade !== '' && (cur_frm.doc.stock_movement == 1 || cur_frm.doc.move_stock == 1)) {
            var child = locals[cdt][cdn]
            var child_table_data = frm.fields_dict.items.grid.grid_rows_by_docname;
            var child_records = Object.values(child_table_data);
            var last_child_record = child_records[child_records.length - 1].doc;
            frappe.call({
                method: 'nj_features.api_files.serializer_or_notserializer',
                args: {
                    serial_no: last_child_record.serial_no
                },
                callback: function (response) {
                    var has_serial_no = response.message;
                    if (has_serial_no === 0 && child_records && child_records.length > 0) {
                        frappe.db.get_value('Item', { 'name': last_child_record.item_code }, 'has_serial_no').then(function (r) {
                            if (r.has_serial_no === 0) {
                                cur_frm.set_df_property('items', 'reqd', 1, cur_frm.docname, 'grade', last_child_record.name)
                            }
                        })
                        frappe.db.get_value('Grade', { name: frm.doc.scan_grade }, 'name')
                            .then(function (r) {
                                if (r.message.name) {
                                    frappe.model.set_value(last_child_record.doctype, last_child_record.name, "grade", r.message.name);
                                    cur_frm.set_value('scan_grade', '');
                                    frm.refresh_fields('items');
                                } else {
                                    frappe.msgprint('Grade not found. Please enter a valid Grade.');
                                }
                            })

                    } else {
                        cur_frm.set_df_property('items', 'hidden', 1, cur_frm.docname, 'grade', last_child_record.name)
                    }
                }
            });

        }
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

frappe.ui.form.on('Stock Entry Detail', {
    item_code: function (frm, cdt, cdn) {
        var child = locals[cdt][cdn]
        if (cur_frm.doc.move_stock == 1) {

            for (let i = 0; i < cur_frm.doc.items.length; i++) {
                const item = cur_frm.doc.items[i];
                if (item.serial_no) {
                    var serialNo = item.serial_no;
                    frappe.db.get_value('Serial No', { "name": serialNo }, ['item_group', 'brand'])
                        .then(function (r) {
                            var itemGroup = r.message.item_group;
                            var brand = r.message.brand;
                            if (item.item_group) {
                                frappe.model.set_value(cdt, cdn, 'item_group', itemGroup);
                            }
                            frappe.model.set_value(cdt, cdn, 'brand', brand);
                            // get all emp_ware
                            frappe.call({
                                method: 'nj_features.api_files.get_all_emp_warehouse',
                                args: {
                                    'user': frappe.session.user_email
                                },
                                callback: function (response) {
                                    var all_emp_ware = response.message;
                                    console.log("all_emp_ware", all_emp_ware);

                                    frm.fields_dict.items.grid.get_field('t_warehouse').get_query = function (doc, cdt, cdn) {
                                        return {
                                            filters: {
                                                item_group: ['in', itemGroup !== '' ? [itemGroup, ''] : ['']],
                                                brand: ['in', brand !== '' ? [brand, ''] : ['']],
                                                is_group: 0,
                                                available_capacity: ['>', 0],
                                                company: frm.doc.company,
                                                name: ['in', all_emp_ware]
                                            }
                                        };
                                    };
                                }
                            });


                            frm.refresh_field('items');
                        })
                }
            }
        }

    }
});

function modify_table_after_scan(frm, data) {
    let scan_barcode_field = frm.fields_dict["scan_barcode"];
    let cur_grid = frm.fields_dict.items.grid;
    let row_to_modify = null;
    // let batch_no_scan = Boolean(data.batch_no) && frappe.meta.has_field(cur_grid.doctype, "batch_no");

    // if (batch_no_scan) {
    //     row_to_modify = get_batch_row_to_modify(frm, data.batch_no);
    // } else {
    row_to_modify = get_row_to_modify_on_scan(frm, row_to_modify, data);
    console.log('row_to_modify: ', row_to_modify, "data: ", data)
    // }

    if (!row_to_modify) {
        row_to_modify = frappe.model.add_child(frm.doc, cur_grid.doctype, 'items');
    }
    else {
        if (row_to_modify.serial_no === data.serial_no && row_to_modify.serial_no) {
            frappe.show_alert({
                message: __('Serial Number already exists in the items list'),
                indicator: 'orange'
            });

        }
        if (row_to_modify.item_code) {
            row_to_modify = frappe.model.add_child(frm.doc, cur_grid.doctype, 'items');
        }
    }

    show_scan_message(row_to_modify.idx, row_to_modify.item_code);
    set_scanned_values(row_to_modify, data, scan_barcode_field);
}

function set_scanned_values(row_to_modify, data, scan_barcode_field) {
    // Set values in the correct row
    frappe.model.set_value(row_to_modify.doctype, row_to_modify.name, {
        item_code: data.item_code,
        s_warehouse: data.warehouse,
        qty: 1
    });

    ['serial_no', 'batch_no', 'barcode'].forEach(field => {
        if (data[field] && frappe.meta.has_field(row_to_modify.doctype, field)) {
            let value = data[field];
            frappe.model.set_value(row_to_modify.doctype, row_to_modify.name, field, value);
        }
    });

    scan_barcode_field.set_value('');
    refresh_field("items");
}

// function get_row_to_modify_on_scan(frm, row_to_modify, data) {
// 	const existing_item_row = frm.doc.items.find(d => d.serial_no === data.serial_no);
// 	const blank_item_row = frm.doc.items.find(d => !d.serial_no);

// 	if (existing_item_row) {
// 		row_to_modify = existing_item_row;
// 	} else if (blank_item_row) {
// 		row_to_modify = blank_item_row;
// 	}
// 	return row_to_modify;
// }

function get_row_to_modify_on_scan(frm, row_to_modify, data) {
    let existing_row = null;

    // Check if the data contains a serial number or item code
    if (data.serial_no) {
        // Find an existing row with the same serial number
        existing_row = frm.doc.items.find(d => d.serial_no === data.serial_no);
    } else if (data.item_code) {
        // Find an existing row with the same item code
        existing_row = frm.doc.items.find(d => d.item_code === data.item_code);
    }

    // If no existing row found, return the first blank row
    if (!existing_row && !row_to_modify) {
        row_to_modify = frm.doc.items.find(d => !d.item_code);
    }

    return row_to_modify || existing_row;
}



function get_batch_row_to_modify(frm, batch_no) {
    const existing_batch_row = frm.doc.items.find(d => d.batch_no === batch_no);
    return existing_batch_row || null;
}

function show_scan_message(idx, exist = null) {
    if (!exist) {
        frappe.show_alert({
            message: __('Row #{0}: Item added', [idx]),
            indicator: 'green'
        });
    }
}


