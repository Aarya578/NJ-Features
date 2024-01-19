//Racking and Stock Movement
frappe.ui.form.on('Stock Entry', {
	refresh(frm) {
        if(frm.doc.__islocal){
            cur_frm.doc.racking_check;
            console.log("doc status: ", cur_frm.doc.docstatus, "| is new: ", frm.doc.__islocal, "| Racking: ", cur_frm.doc.racking_check);
            
            const rackingButton = frm.add_custom_button('Racking', function() {
                frm.set_value('racking_check', 1);
                rackingButton.addClass('btn-primary');
                    const fieldsToHide = [
                        'naming_series', 'posting_date', 'posting_time', 'is_rejected',
                        'set_posting_time', 'inspection_required', 'add_to_transit', 'is_customer_return',
                        'apply_putaway_rule', 'bom_info_section', 'to_warehouse', 'from_bom', 'additional_costs_section', 'accounting_dimensions_section',
                        'printing_settings', 'more_info', 'get_stock_and_rate'
                    ];
                    fieldsToHide.forEach(field => frm.set_df_property(field, 'hidden', 1));
                    frm.set_value('stock_entry_type', 'Material Transfer');
                    console.log('Racking!!!');
                    
                    frm.refresh_field('items');
                    console.log("Racking clicked so: ", cur_frm.doc.racking_check);
            });
        }
        if(frappe.user.has_role("Stock Movement") && frappe.session.user !== "Administrator") {
            console.log("User has Stock Movement role");
            const fieldsToHide = [
                'naming_series', 'posting_date', 'posting_time', 'is_rejected',
                'set_posting_time', 'inspection_required', 'add_to_transit', 'is_customer_return',
                'apply_putaway_rule', 'bom_info_section', 'to_warehouse', 'from_bom', 'additional_costs_section', 'accounting_dimensions_section',
                'printing_settings', 'more_info', 'get_stock_and_rate', 'section_break_12'
            ];
            fieldsToHide.forEach(field => frm.set_df_property(field, 'hidden', 1));
            frm.doc.stock_movement = 1;
            frm.set_value('stock_entry_type', 'Material Transfer');
            frm.refresh_field('items');
        }
	},
	scan_barcode: function(frm) {   
        if(frm.doc.scan_barcode) {
            frappe.call({
				method: "nj_features.api_files.search_for_serial_or_batch_or_barcode_no",
				args: {
					search_value: frm.doc.scan_barcode
				}
			}).then(r => {
				const data = r && r.message;
				if (!data || Object.keys(data).length === 0) {
					frappe.show_alert({
						message: __('Cannot find Item with this Barcode'),
						indicator: 'red'
					});
					return;
				}
				modify_table_after_scan(frm, data);
			});
		}
		return false;
	},
	validate: function(frm) {
        if(cur_frm.doc.racking_check === 1){
            console.log("validate loop");
            for (var i = 0; i < frm.doc.items.length; i++) {
                (function(index) {
                    var t_warehouse = frm.doc.items[index].t_warehouse;
                    console.log('t_warehouse: ',t_warehouse);
                    if (t_warehouse) {
							frappe.call({
							method: "frappe.client.get_value",
							args: {
								doctype: "Warehouse",
								filters: { 'name': t_warehouse },
								fieldname: "available_capacity"
							},
                            async: false,
                            callback: function(response) {
                                if (response && response.message && frm.doc.items[i]) {
                                console.log("ava_cap: " + response.message.available_capacity, " | qty", frm.doc.items[i].qty);
                                if (frm.doc.items[i].qty > response.message.available_capacity || frm.doc.items[i].qty > (response.message.max_capacity - response.message.qty_after_transaction)) {
                                      var msg = frappe.msgprint({
                                            message: `Reached maximum capacity of the warehouse in <strong>"${t_warehouse}"</strong>`,
                                            title: "Message",
                                            primary_action: {
                                                action: function() {
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
    item_code: function(frm, cdt, cdn) {
        if (frm.doc.items && frm.doc.items.length > 0 && cur_frm.doc.racking_check === 1) {
         
            for (let i = 0; i < frm.doc.items.length; i++) {
                const item = frm.doc.items[i];
                console.log(i);
                if (item.serial_no) {
                    var serialNo = item.serial_no;
                    
                    frappe.db.get_value('Serial No', { name: serialNo }, ['item_group', 'brand'])
                    .then(function(r) {
                        var itemGroup = r.message.item_group;
                        var brand = r.message.brand;
                        console.log("Item Group: ",itemGroup,"| Brand: ",brand);
                        if(item.item_group){
							frappe.model.set_value(cdt, cdn, 'item_group', itemGroup);
						}
                        frappe.model.set_value(cdt, cdn, 'brand', brand);
                        
                        frm.refresh_field('items');
                    })
                } else {
                    console.log("Serial No not found!");
                }
                if(item.brand && item.group) {
                    frm.fields_dict['items'].grid.get_field('t_warehouse').get_query = function(doc, cdt, cdn) {
            			var row = locals[cdt][cdn];
            			return {
            				filters: {
            					item_group: row.group,
            					brand : row.brand,
            					is_group: 1,
            					available_capacity: ['>', 0],
            					company: frm.doc.company
            				}
            			};
        		    };
                }
            }
        }
    }
});

function modify_table_after_scan(frm, data) {
	let scan_barcode_field = frm.fields_dict["scan_barcode"];
	let cur_grid = frm.fields_dict.items.grid;
	let row_to_modify = null;
	let batch_no_scan = Boolean(data.batch_no) && frappe.meta.has_field(cur_grid.doctype, "batch_no");
	console.log("data: ",data)
	if (batch_no_scan) {
		row_to_modify = get_batch_row_to_modify(frm, data.batch_no);
	} else {
		row_to_modify = get_row_to_modify_on_scan(frm, row_to_modify, data);
	}
	
	if (!row_to_modify) {
		row_to_modify = frappe.model.add_child(frm.doc, cur_grid.doctype, 'items');
	} else {
        if (row_to_modify.serial_no === data.serial_no) {
            frappe.show_alert({
                message: __('Serial Number already exists in the items list'),
                indicator: 'orange'
            });
        }
	}		
	show_scan_message(row_to_modify.idx, row_to_modify.item_code);
	set_scanned_values(frm, row_to_modify, data, scan_barcode_field);
	
}
	
function set_scanned_values(frm, row_to_modify, data, scan_barcode_field) {
	console.log("data: ",data);
	frm.from_barcode = frm.from_barcode ? frm.from_barcode + 1 : 1;
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

function get_row_to_modify_on_scan(frm, row_to_modify, data) {
	const existing_item_row = frm.doc.items.find(d => d.serial_no === data.serial_no);
	const blank_item_row = frm.doc.items.find(d => !d.serial_no);

	if (existing_item_row) {
		row_to_modify = existing_item_row;
	} else if (blank_item_row) {
		row_to_modify = blank_item_row;
	}
	return row_to_modify;
}

function get_batch_row_to_modify(frm, batch_no) {
	const existing_batch_row = frm.doc.items.find(d => d.batch_no === batch_no);
	return existing_batch_row || null;
}

function show_scan_message (idx, exist = null) {
	if (!exist) {
		frappe.show_alert({
			message: __('Row #{0}: Item added', [idx]),
			indicator: 'green'
		});
	}
}