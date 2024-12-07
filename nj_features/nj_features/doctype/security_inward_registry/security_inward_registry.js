// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Security Inward Registry', {
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
				args: { 'doctype': frm.doc.doctype, 'docname': frm.doc.name }
			})
		}
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
							if (item.error) {
								errors.push(item.error);
							} else if (item.item_code) {
								let new_row = frm.add_child("transfer_registry");
								frappe.model.set_value(new_row.doctype, new_row.name, "item_code", item.item_code);
								frappe.model.set_value(new_row.doctype, new_row.name, "warehouse", item.t_warehouse);
								frappe.model.set_value(new_row.doctype, new_row.name, "source_warehouse", item.s_warehouse);
								frappe.model.set_value(new_row.doctype, new_row.name, "qty", item.qty);
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
							$(`<div class='row' style='margin-bottom: 10px;'>
								<div class='col-sm-7 small' style='padding-top: 3px;'>${d.item_code}</div>
								<div class='col-sm-4 small' style='padding-top: 3px;'>${d.warehouse}</div>
								<div class='col-sm-1 small text-right' style='padding-top: 3px;'>${d.qty}</div>
							</div>`).appendTo(rows);
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
			frappe.throw(__('Tracking ID cannot be empty.'));
		} else {
			let new_row = frm.add_child("customer_return_registry");
			frappe.model.set_value(new_row.doctype, new_row.name, "tracking_id", tracking_id);
			frm.refresh_field("customer_return_registry");
		}
	},
	stock_registry_no: function (frm) {
		
		if (frm.doc.stock_registry_no) {
			frappe.call({
				method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_stock_registry",
				args: {stock_registry_no: frm.doc.stock_registry_no},
				callback: function(r) {
					if (r && r.message) {
						if (Array.isArray(r.message)) {
							r.message.forEach(item => {
							let new_row = frm.add_child("transfer_registry");
								frappe.model.set_value(new_row.doctype, new_row.name, "qty", item.qty);
								frappe.model.set_value(new_row.doctype, new_row.name, "item_code", item.item_code);
								frappe.model.set_value(new_row.doctype, new_row.name, "source_warehouse", item.warehouse);
								frappe.model.set_value(new_row.doctype, new_row.name, "reference_name", item.reference_name);
								frappe.model.set_value(new_row.doctype, new_row.name, "reference_parent", item.reference_parent);
							})
						}
						frm.refresh_field("transfer_registry");
					} else {
						frappe.msgprint("Qty is not available in ", frm.doc.stock_registry_no);
						frm.set_value('stock_registry_no', '')
					}
				}
			})
		}
	}
});

// Security Inward Registry Child
frappe.ui.form.on('Security Inward Registry Child', {
	qty: function(frm, cdt, cdn) {
		let child = locals[cdt][cdn];
		frappe.call({
			method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.recieved_qty_details",
			args: {	
				received_qty: child.qty,
				item_code: child.item_code,
				po_number: frm.doc.po_number,
				item_group: child.item_group,
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

		set_actual_qty(cdt, cdn, child.qty);
	},
	item_code: function(frm, cdt, cdn) {
        var child = locals[cdt][cdn];
        autofill_warehouse([child], "warehouse", frm.doc.default_warehouse);
    }
});

frappe.ui.form.on('Customer Return for Security Inward Registry', {
	item_code: function(frm, cdt, cdn) {
        var child = locals[cdt][cdn];
        autofill_warehouse([child], "warehouse", frm.doc.default_warehouse);
    },
	qty: function(frm, cdt, cdn) {
		var child = locals[cdt][cdn];
		set_actual_qty(cdt, cdn, child.qty);
	}
});

frappe.ui.form.on('Security Inward Registry Transfer Child', {
	item_code: function(frm, cdt, cdn) {
        var child = locals[cdt][cdn];
        autofill_warehouse([child], "warehouse", frm.doc.default_warehouse);
    },
	qty: function(frm, cdt, cdn) {
		var child = locals[cdt][cdn];
		set_actual_qty(cdt, cdn, child.qty);
	}
});

function autofill_warehouse(child_table, warehouse_field, warehouse) {
    if (warehouse && child_table && child_table.length) {
        let doctype = child_table[0].doctype;
        $.each(child_table || [], function(i, item) {
            frappe.model.set_value(doctype, item.name, warehouse_field, warehouse);
        });
    }
}

function set_actual_qty(cdt, cdn, qty) {
	frappe.model.set_value(cdt, cdn, "actual_qty", qty);
}