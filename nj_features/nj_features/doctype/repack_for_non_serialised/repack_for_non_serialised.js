// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Repack For Non Serialised', {
	refresh: function(frm) {
		$('.col-lg-2.layout-side-section').hide();
		frm.set_query('new_grade', function(){
			return {
				query : "nj_features.nj_features.doctype.repack_for_non_serialised.repack_for_non_serialised.get_new_grade",
				filters: {
					'grade': frm.doc.grade
				}
			}
		})
		if (frm.doc.__islocal) {
			frm.set_query('item_code', function() {
				return {
					filters: {
						'has_variants': 0,
						'disabled': 0,
						'has_serial_no': 0
					}
				}
			})
		}
	},
	item_code: function(frm) {
		if (frm.doc.item_code) {
			frappe.call({
				method: "nj_features.nj_features.doctype.repack_for_non_serialised.repack_for_non_serialised.get_item_code_and_warehouse",
				args: {
					item_code: frm.doc.item_code
				},
				callback: function(r) {
					if (r.message) {
						frm.set_value('warehouse', r.message.warehouse);
						frm.set_value('grade', r.message.grade);
						frm.set_value('item_code_price', r.message.item_code_price);
						frm.set_value('new_grade','');
						frm.set_value('repack_item_code', '');
						frm.set_value('quantity', '');
						frm.set_value('repack_item_code_price', '');
					}
				}
			})
		}
	},
	new_grade: function(frm) {
		if (frm.doc.new_grade != ''){
			if (frm.doc.new_grade && frm.doc.item_code) {
				frappe.call({
					method: "nj_features.nj_features.doctype.repack_for_non_serialised.repack_for_non_serialised.get_repack_item_code_with_new_grade",
					args: {
						item_code: frm.doc.item_code,
						new_grade: frm.doc.new_grade
					},
					callback: function(r) {
						if (r.message) {
							frm.set_value('repack_item_code', r.message);
							frappe.call({
								method: "nj_features.nj_features.doctype.repack_for_non_serialised.repack_for_non_serialised.get_valuation_rate",
								args: {
									item_code: r.message,
									grade: frm.doc.new_grade
								},
								callback: function(r) {
									if (r.message) {
										frm.set_value('repack_item_code_price', r.message);
									}
								}
							})
						}
					}
				})
			}
			else if (!frm.doc.item_code) {
				frappe.msgprint("Please Select Item Code")
				frm.set_value('new_grade', '');
			}
		}
	},

	
});
