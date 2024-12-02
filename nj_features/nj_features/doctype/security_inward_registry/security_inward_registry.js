// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Security Inward Registry', {
	refresh: function(frm) {
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Employee",
				filters: {
					user_id: frappe.session.user
				},
				fields: ["name", "work_warehouse"]
			},
			callback: function(r) {
				if (r.message && r.message.length > 0) {
					const employee_warehouse = r.message[0].work_warehouse;
					if (employee_warehouse) {
						frm.set_value('default_warehouse', employee_warehouse);
					} else {
						frappe.msgprint(__('Warehouse not set for the logged-in employee.'));
					}
				}
			}
		});

		frm.set_query('ste_number', function() {
            return {
                query: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_ste_number",
                filters: {
                    stock_entry_type: 'Material Transfer'
                }
            };
        });
	},
	po_number: function(frm) {
		if (!frm.doc.registry_type) {
			frm.set_value('po_number', '');
			frappe.throw('Please select the Registry Type first');
		}
		if (frm.doc.po_number && frm.doc.po_number.trim() !== '') {
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
						frm.clear_table('purchase_inward_registry');
						if (Array.isArray(r.message)) {
							r.message.forEach(item => {
								let new_row = frm.add_child("purchase_inward_registry");
								frappe.model.set_value(new_row.doctype, new_row.name, "item_group", item.item_group);
								frappe.model.set_value(new_row.doctype, new_row.name, "item_code", item.item_code);
								frappe.model.set_value(new_row.doctype, new_row.name, "warehouse", frm.doc.default_warehouse);
								frappe.model.set_value(new_row.doctype, new_row.name, "po_qty", item.po_qty);
								frappe.model.set_value(new_row.doctype, new_row.name, "available_qty", item.available_qty);
							});
							frm.refresh_field("purchase_inward_registry");
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
				if (r.message) {
					frm.clear_table("transfer_registry");
					let errors = [];
	
					if (Array.isArray(r.message)) {
						r.message.forEach(item => {
							console.log('items', item);
							if (item.error) {
								errors.push(item.error);
							} else if (item.item_code) {
								console.log('s_warehouse', item.s_warehouse);
								console.log('t_warehouse', item.t_warehouse);
								let new_row = frm.add_child("transfer_registry");
								frappe.model.set_value(new_row.doctype, new_row.name, "item_code", item.item_code);
								frappe.model.set_value(new_row.doctype, new_row.name, "target_warehouse", item.t_warehouse);
								frappe.model.set_value(new_row.doctype, new_row.name, "source_warehouse", item.s_warehouse);
								frappe.model.set_value(new_row.doctype, new_row.name, "qty", item.qty);
								console.log( item.item_code);
								console.log( item.t_warehouse);
								console.log(item.s_warehouse);
							}
						});
	
						frm.refresh_field("transfer_registry");
					}
	
					if (errors.length > 0) {
						frappe.msgprint({
							title: __('Errors'),
							message: errors.join('<br>'),
							indicator: 'red'
						});
					}
				}
			}
		});
	}
	
});

// Security Inward Registry Child

frappe.ui.form.on('Security Inward Registry Child', {
	received_qty: function(frm, cdt, cdn) {
		let child = locals[cdt][cdn];
		frappe.call({
			method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.recieved_qty_details",
			args: {	
				item_code: child.item_code,
				po_number: frm.doc.po_number,
				item_group: child.item_group,
				received_qty: child.received_qty,
				available_qty: child.available_qty
			},
			callback: function(r) {
				if (r.message.error) {
					frappe.model.set_value(cdt, cdn, 'received_qty', parseFloat(0));
					frappe.throw(__(r.message.error));
				}else{
					frappe.model.set_value(cdt, cdn, 'invoice_value', r.message.part_price);
				}
			}
		});
	}
});


// Security Inward Registry  Transfer Child

frappe.ui.form.on('Security Inward Registry  Transfer Child', {
	// item_code: function (frm, cdt, cdn) {
	// 	if(!frm.doc.ste_number){
	// 		frappe.model.set_value(cdt, cdn, 'source_warehouse', '');
	// 		frappe.throw('Please fill the STE Number first');
	// 		return
	// 	}else{
	// 		let child = locals[cdt][cdn];
	// 		frappe.call({
	// 			method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_item_code_details_for_transfer",
	// 			args: {
	// 				ste_number: frm.doc.ste_number,
	// 				item_code: child.item_code,
	// 			},
	// 			callback: function (r) {
	// 				if (r.message) {
	// 					if (Array.isArray(r.message)) {
	// 						r.message.forEach(item => {
	// 							frappe.model.set_value(cdt, cdn, 'source_warehouse', item.t_warehouse);
	// 							frappe.model.set_value(cdt, cdn, 'qty', item.qty);
	// 						})
	// 					}
	// 				}
	// 			}
	// 		});
	// 	}
	// }
});