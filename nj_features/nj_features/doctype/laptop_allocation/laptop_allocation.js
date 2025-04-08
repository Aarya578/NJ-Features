// Copyright (c) 2025, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Laptop Allocation', {
	refresh: function(frm) {
		console.log("refreshing....")
	},

	allocate: function(frm){

		frappe.call({
			method: 'nj_features.nj_features.doctype.laptop_allocation.laptop_allocation.allocate_laptop_parts',
			callback: function(r) {
				let data = r.message;
				console.log("allocate_laptop_parts", r.message);
				frm.clear_table('laptop_allocation_child');
		
				if (data) {
					data.sort((a, b) => {
						if (a.item_code === b.item_code) {
							return b.available_stock - a.available_stock;
						}
						return a.item_code.localeCompare(b.item_code); 
					});
		
					data.forEach((item) => {
						let child = frm.add_child('laptop_allocation_child', {});
						child.serial_no = item.against_serial_no;
						child.mreq_no = item.material_request;
						child.item = item.item_code;
						child.sb_qty = item.available_stock;
						child.mr_qty = item.mr_qty;
						child.status = item.status;
						child.allocated_status = item.allocated_status;
					});
				}
				frm.refresh_field('laptop_allocation_child');
			}
		});
		
	}
});
