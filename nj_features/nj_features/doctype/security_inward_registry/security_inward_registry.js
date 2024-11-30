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
				console.log('response', r);
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
            console.log('Triggered ste_number query');
            return {
                query: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_ste_number",
                filters: {
                    stock_entry_type: 'Material Transfer'
                }
            };
        });

		frm.fields_dict['purchase_inward_registry'].grid.get_field('item_group').get_query = function(doc, cdt, cdn) {
			if (frm.doc.po_number === ''){
				frappe.throw('Please fill the PO Number first');
			}
            console.log('triggering item_group');
            let child = locals[cdt][cdn];
            return {
                query: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_po_item_group",
                filters: {
                    po_number :  frm.doc.po_number,
                }
            };
        };
		frm.fields_dict['purchase_inward_registry'].grid.get_field('item_code').get_query = function(doc, cdt, cdn){
			if (frm.doc.po_number === ''){
				frappe.throw('Please fill the PO Number first');
			}
			let child = locals[cdt][cdn];
			console.log('child', child.item_group);

			return {
				query: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_po_item_code",
				filters: {
					po_number: frm.doc.po_number,
					item_group: child.item_group,
				}
			}
		}
		frm.fields_dict['transfer_registry'].grid.get_field('item_code').get_query = function(doc, cdt, cdn){
			if(frm.doc.ste_number === ''){
				frappe.throw('Please fill the STE Number first');
			}
			let child = locals[cdt][cdt];
			return {
				query: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_ste_number_item_code",
				filters: {
					ste_number: frm.doc.ste_number,
				}
			}
		}
		
		frm.fields_dict['transfer_registry'].grid.get_field('target_warehouse').get_query = function(doc, cdt, cdn){
			let child = locals[cdt][cdn];
			console.log('source_warehouse ---- ', child.source_warehouse);
			return {
				query: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_target_warehouse",
				filters: {
					source_warehouse: child.source_warehouse
				}
			}
		}
	},
	po_number: function(frm) {
		if (!frm.doc.registry_type && !frm.doc.po_number) {
			frm.set_value('po_number', '');
			frappe.throw('Please select the Registry Type first');
		}
		if (frm.doc.po_number && frm.doc.po_number.trim() !== '') {
			console.log('triggering po_number', frm.doc.po_number);
			frappe.call({
				method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_po_number_details",
				args: {
					po_number: frm.doc.po_number
				},
				callback: function(r) {
					console.log('response', r.message);
					if (r.message && r.message.error) {
						frm.set_value('po_number', '');
						frappe.throw(r.message.error);
					}
				}
			});
		}
	},
});


// Security Inward Registry Child

frappe.ui.form.on('Security Inward Registry Child', {
    item_group: function (frm, cdt, cdn) {
        let row = frappe.get_doc(cdt, cdn);
        if (row){
            frappe.model.set_value(cdt, cdn, 'warehouse', frm.doc.default_warehouse);
        }
    },
	item_code: function(frm, cdt, cdn) {
		console.log('triggering item_code');
		let child = locals[cdt][cdn];
		frappe.call({
			method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_item__code_details",
			args: {
				item_code: child.item_code,
				po_number: frm.doc.po_number,
				item_group: child.item_group
			},
			callback: function(r) {
				if (r.message) {
					console.log('response', r.message);
					frappe.model.set_value(cdt, cdn, 'po_qty', parseFloat(r.message.po_qty));
					frappe.model.set_value(cdt, cdn, 'available_qty', parseFloat(r.message.available_qty));
				}
			}
		});
	},
	received_qty: function(frm, cdt, cdn) {
		console.log('triggering received_qty');
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
					console.log('error', r.message.error);
					frappe.model.set_value(cdt, cdn, 'received_qty', parseFloat(0));
					frappe.throw(__(r.message.error));
				}else{
					console.log('response', r.message);
					frappe.model.set_value(cdt, cdn, 'invoice_value', r.message.part_price);
				}
			}
		});
	}
});


// Security Inward Registry  Transfer Child

frappe.ui.form.on('Security Inward Registry  Transfer Child', {
	item_code: function (frm, cdt, cdn) {
		if(!frm.doc.ste_number){
			frappe.model.set_value(cdt, cdn, 'source_warehouse', '');
			frappe.throw('Please fill the STE Number first');
			return
		}else{
			console.log('triggering item_code');
			let child = locals[cdt][cdn];
			frappe.call({
				method: "nj_features.nj_features.doctype.security_inward_registry.security_inward_registry.get_item_code_details_for_transfer",
				args: {
					ste_number: frm.doc.ste_number,
					item_code: child.item_code,
				},
				callback: function (r) {
					if (r.message) {
						console.log('response', r.message);
						if (Array.isArray(r.message)) {
							r.message.forEach(item => {
								frappe.model.set_value(cdt, cdn, 'source_warehouse', item.t_warehouse);
								frappe.model.set_value(cdt, cdn, 'qty', item.qty);
							})
						}
					}
				}
			});
		}
	}
	
});
