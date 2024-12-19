// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Security Inward Registry', {
	onload: function(frm) {
		frm.set_df_property('transfer_registry', 'cannot_add_rows', true);
		frm.set_df_property('purchase_inward_registry', 'cannot_add_rows', true);
		frm.set_df_property('customer_return_registry', 'cannot_add_rows', true);
	},
	refresh: function(frm) {
		frm.trigger("make_dashboard");

		if (frm.doc.docstatus == 0) {
			
			frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Employee",
					filters: { user_id: frappe.session.user, status: "Active" },
					fields: ["name", "work_warehouse", "location"]
				},
				callback: function(r) {
					if (r.message && r.message.length > 0) {
						const employee_warehouse = r.message[0].work_warehouse;
						const location = r.message[0].location;

						if (employee_warehouse) {
							frm.set_value('default_warehouse', employee_warehouse);
						} else {
							frappe.msgprint(__('Warehouse not set for the logged-in employee.'));
						}
	
						if (location) {
							frm.set_value('location', location);
						}
					}
				}
			});
	
			frm.set_query('ste_number', function() {
				return {
					query: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_ste_number",
					filters: { stock_entry_type: 'Material Transfer' }
				};
			});
		}

		if (frm.doc.docstatus == 1) {
			frappe.call({
				method: 'nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_total_qty',
				args: { 'doctype': frm.doc.doctype, 'docname': frm.doc.name },
				callback: function(r) {
					frm.set_value('total_qty', r.message);
					frm.refresh_field('total_qty');
				}
			});
		}
	},
	po_number: function(frm) {
		if (!frm.doc.registry_type) {
			frm.set_value('po_number', '');
			frappe.throw('Please select the Registry Type first');
		}
		if (frm.doc.po_number && frm.doc.po_number.trim() !== '' && frm.doc.registry_type === 'Purchase') {
			frappe.call({
				method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_po_number_details",
				args: {
					po_number: frm.doc.po_number
				},
				callback: function(r) {
					if (r.message && r.message.error) {
						frm.set_value('po_number', '');
						frappe.throw(r.message.error);
					} else {
						frm.set_value('reference_po_number', frm.doc.po_number);
						frm.refresh_field('reference_po_number');
						frm.clear_table('purchase_inward_registry_purchase_child');
						if (Array.isArray(r.message)) {
							r.message.forEach(item => {
								let new_row = frm.add_child("purchase_inward_registry_purchase_child");
								frappe.model.set_value(new_row.doctype, new_row.name, "item_group", item.item_group);
								frappe.model.set_value(new_row.doctype, new_row.name, "warehouse", frm.doc.default_warehouse);
								frappe.model.set_value(new_row.doctype, new_row.name, "available_qty", item.available_qty);
								frappe.model.set_value(new_row.doctype, new_row.name, "po_number", item.po_number);
							});
							frm.refresh_field("purchase_inward_registry_purchase_child");
						}
					}
				}
			});
		}
	},
	ste_number: function(frm) {
		frappe.call({
			method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_item_code_details_for_transfer",
			args: {
				ste_number: frm.doc.ste_number,
			},
			callback: function(r) {
				if (r.message.error){
					frm.set_value('ste_number', '');
					frappe.throw(r.message.error);
				}else{
					if (r.message) {
						frm.clear_table("transfer_registry");
						let errors = [];
						let has_errors = false;
		
						if (Array.isArray(r.message)) {
							r.message.forEach(item => {
								if (item.error) {
									errors.push(item.error);
									has_errors = true;
								} else if (item.item_code) {
									let new_row = frm.add_child("transfer_registry");
									frappe.model.set_value(new_row.doctype, new_row.name, "item_code", item.item_code);
									frappe.model.set_value(new_row.doctype, new_row.name, "warehouse", item.t_warehouse);
									frappe.model.set_value(new_row.doctype, new_row.name, "source_warehouse", item.s_warehouse);
									frappe.model.set_value(new_row.doctype, new_row.name, "qty", item.qty);
									frappe.model.set_value(new_row.doctype, new_row.name, "serial_no", item.serial_no.replace('\n', ', '));
								}
							});
							frm.refresh_field("transfer_registry");
						}
	
						// Store errors for validation
						frm.doc.transfer_errors = errors;
	
						if (has_errors) {
							frm.doc.has_transfer_errors = true;
							frappe.msgprint({
								title: __('Errors'),
								message: errors.join('<br>'),
								indicator: 'red'
							});
						} else {
							frm.doc.has_transfer_errors = false;
						}
					}
				}
			}
		});
	},

	validate: function(frm) {
		if (frm.doc.has_transfer_errors) {
			frappe.validated = false;
			frappe.msgprint({
				title: __('Validation Error'),
				message: __(`Cannot save or submit the document due to the following errors:<br><b>${frm.doc.transfer_errors.join('<br>')}</b>`),
				indicator: 'red'
			});
			return;
		}
	
		if (frm.doc.registry_type === 'Accept Registry') {
			frappe.call({
				method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.validate_accept_registry",
				args: {
					frm: frm.doc
				},
				async: false,
				callback: function(r) {
					if (r.message.error) {
						frappe.validated = false; 
						frappe.throw(r.message.error); 
					}
				}
			});
		}
	},	
		
	make_dashboard: (frm) => {
	
		if (!frm.is_new()) {
			
			frappe.call({
				method: 'nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_registry_qty',
				args: {frm: frm.doc},
				callback: (r) => {
					
					if (!r.message) {
						return;
					}
	
					const section = frm.dashboard.add_section('', __("Registry Stock Levels"));
	
					r.message.sort(function(a, b) { return a.qty > b.qty ? 1 : -1 });
	
					var rows = $('<div></div>').appendTo(section);

					(r.message || []).forEach(function(d) {
						if (d.qty > 0) {
							const rowTemplate = frm.doc.registry_type === 'Accept Registry' 
								? `<div class='row' style='margin-bottom: 10px;'>
										<div class='col-sm-7 small' style='padding-top: 3px;'>${d.item_code}</div>
										<div class='col-sm-2 small' style='padding-top: 3px;'>${d.item_group}</div>
										<div class='col-sm-2 small' style='padding-top: 3px;'>${d.warehouse}</div>
										<div class='col-sm-1 small text-right' style='padding-top: 3px;'>${d.qty}</div>
									</div>`
								: `<div class='row' style='margin-bottom: 10px;'>
										<div class='col-sm-7 small' style='padding-top: 3px;'>${d.item_group}</div>
										<div class='col-sm-4 small' style='padding-top: 3px;'>${d.warehouse}</div>
										<div class='col-sm-1 small text-right' style='padding-top: 3px;'>${d.qty}</div>
									</div>`;
					
							$(rowTemplate).appendTo(rows);
						}
					});
	
					frm.dashboard.show();
				}
			});
		}
	},
	tracking_id: function(frm) {
		let tracking_id = frm.doc.tracking_id;
	
		if (!tracking_id || tracking_id.trim() === '') {
			return;
		} else {
			
			let new_row = frm.add_child("customer_return_registry");
			frappe.model.set_value(new_row.doctype, new_row.name, "tracking_id", tracking_id);
			frappe.model.set_value(new_row.doctype, new_row.name, "warehouse", frm.doc.default_warehouse);
			frm.set_value("tracking_id", '');
			update_tracking_qty(frm);
	
			frm.refresh_field("customer_return_registry");
		}
	},

	
	stock_registry_no: function (frm) {
    if (frm.doc.stock_registry_no) {
        frappe.call({
            method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_stock_registry",
            args: { stock_registry_no: frm.doc.stock_registry_no },
            callback: function (r) {
                if (r && r.message) {
                    if (Array.isArray(r.message[0])) {

						frm.clear_table('purchase_inward_registry_child');
						frm.set_value('reference_po_number', r.message[2]);
						frm.refresh_field('reference_po_number');
						
                        r.message[0].forEach(item => {
                            let new_row = frm.add_child("purchase_inward_registry_child");
                            
                            frappe.model.set_value(new_row.doctype, new_row.name, "item_group", item.item_group);
                            frappe.model.set_value(new_row.doctype, new_row.name, "item_code", item.item_code);
                            frappe.model.set_value(new_row.doctype, new_row.name, "source_warehouse", item.warehouse);
                            frappe.model.set_value(new_row.doctype, new_row.name, "reference_parent", item.reference_parent);
							frappe.model.set_value(new_row.doctype, new_row.name, "reference_name", item.reference_name);
							frappe.model.set_value(new_row.doctype, new_row.name, "available_qty", item.available_qty);
                            frappe.model.set_value(new_row.doctype, new_row.name, "po_qty", item.qty);
                            frappe.model.set_value(new_row.doctype, new_row.name, "reference_po_number", item.po_number);
							frappe.model.set_value(new_row.doctype, new_row.name, "reference_item_group", item.reference_item_group);

                        });

                        frm.refresh_field("purchase_inward_registry_child");
                    }
					if(Array.isArray(r.message[1])){
						frm.clear_table('sir_inwarded_qty_table');
						r.message[1].forEach(item => {
							let new_row = frm.add_child("sir_inwarded_qty_table");

							frappe.model.set_value(new_row.doctype, new_row.name, "item_group", item.item_group);
							frappe.model.set_value(new_row.doctype, new_row.name, "received_qty", item.actual_qty);
							frappe.model.set_value(new_row.doctype, new_row.name, "reference_name", item.name);
							frappe.model.set_value(new_row.doctype, new_row.name, "reference_parent", item.parent);
						})
						frm.refresh_field("sir_inwarded_qty_table");
					}
					
                } else {
                    frappe.msgprint(`No records found for ${frm.doc.stock_registry_no}`);
                    frm.set_value('stock_registry_no', '');
                }
            }
        });
    }
}

});

function update_tracking_qty(frm) {
    let row_count = frm.doc.customer_return_registry ? frm.doc.customer_return_registry.length : 0;
    frm.set_value("tracking_qty", row_count);
}

function autofill_warehouse(child_table, warehouse_field, warehouse) {
	if (warehouse && child_table && child_table.length) {
		let doctype = child_table[0].doctype;
		$.each(child_table || [], function(i, item) {
			
			if (doctype === "Security Inward Registry Transfer Child") {
				if (item.source_warehouse === warehouse) {
					frappe.throw("Source and Target Warehouse can not be same!");
					frappe.validated = false;
				}
			}
			frappe.model.set_value(doctype, item.name, warehouse_field, warehouse);
			frappe.validated = true;
		});
	}
}

function set_actual_qty(cdt, cdn, qty) {
	frappe.model.set_value(cdt, cdn, "actual_qty", qty);
}


frappe.ui.form.on('Customer Return for Security Inward Registry', {
	customer_return_registry_remove: function(frm, cdt, cdn) {
		update_tracking_qty(frm);
	},		
});


frappe.ui.form.on('Security Inward Registry Child', {
	received_qty: function(frm, cdt, cdn) {
		let child = locals[cdt][cdn];

		frappe.call({
			method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.recieved_qty_details",
			args: {	
				received_qty: child.received_qty,
				item_code: child.item_code,
				po_number: child.reference_po_number,
				item_group: child.item_group,
				available_qty: child.available_qty
			},
			callback: function(r) {
				if (r.message.error) {
					frappe.model.set_value(cdt, cdn, 'received_qty', parseFloat(0));
					frappe.model.set_value(cdt, cdn, 'actual_qty', parseFloat(0));
					frappe.throw(__(r.message.error));
				}else{
					frappe.model.set_value(cdt, cdn, 'actual_qty', child.received_qty);
					frappe.model.set_value(cdt, cdn, 'invoice_value', r.message.part_price);
				}
				frm.refresh_field('actual_qty');
			}
		});

		// set_actual_qty(cdt, cdn, child.qty);
	},
	item_code: function(frm, cdt, cdn) {
        var child = locals[cdt][cdn];
        autofill_warehouse([child], "warehouse", frm.doc.default_warehouse);
    }
});



frappe.ui.form.on('Security Inward Registry Transfer Child', {
	item_code: function(frm, cdt, cdn) {
		if(frm.doc.registry_type  === 'Accept Registry'){
			var child = locals[cdt][cdn];
			autofill_warehouse([child], "warehouse", frm.doc.default_warehouse);
		}
    },
	qty: function(frm, cdt, cdn) {
		var child = locals[cdt][cdn];
		set_actual_qty(cdt, cdn, child.qty);
	}
});


frappe.ui.form.on('Security Inward Registry Purchase Child', { 	
    received_qty: function(frm, cdt, cdn) { 		
        var child = locals[cdt][cdn]; 		
        const available_qty = child.available_qty; 		
        const received_qty = child.received_qty; 		

        if (received_qty > available_qty) { 	
			frappe.model.set_value(cdt, cdn, 'received_qty', parseFloat(0));
			frappe.model.set_value(cdt, cdn, 'actual_qty', parseFloat(0));		
            frappe.throw('Received Quantity cannot be greater than Available Quantity'); 		
        } else { 			
            frappe.model.set_value(cdt, cdn, 'actual_qty', received_qty); 			
            frm.refresh_field('actual_qty'); 		
        } 	
		frm.refresh_field('received_qty');
    } 
});

