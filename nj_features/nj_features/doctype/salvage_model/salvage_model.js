// Copyright (c) 2025, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Salvage Model', {
    onload: function(frm) {
        frappe.call({
            method: "nj_features.nj_features.doctype.salvage_model.salvage_model.get_unique_models",
            callback: function(r) {
                if (r.message) {
                    // Add options dynamically to the Select field
                    frm.set_df_property('model_no', 'options', [''].concat(r.message));
					
                }
            }
        });
    },
		model_no:function (frm) {
        if (frm.doc.model_no) {
            frappe.call({
                method: "nj_features.nj_features.doctype.salvage_model.salvage_model.get_total_purchase_price",
                args: {
                    model_no: frm.doc.model_no
                },
                callback: function(r) {
                    if (r.message) {
						console.log('total_price================================',r.message);
                        frm.set_value('total_price', r.message);
						get_serial_no(frm);
                    }
					frm.refresh_field('total_price')
                }
            });
        }
    },

});

	function get_serial_no(frm){
		if (frm.doc.model_no){
			frappe.call({
				method:"nj_features.nj_features.doctype.salvage_model.salvage_model.get_serial_no_data",
				args:{
					model_no:frm.doc.model_no
				},
				callback:function(r){
					if (r.message){
						console.log('serial_no======================',r.message);
					}
				}
			})
		}
	}

		function get_serial_no(frm){
		if (frm.doc.model_no){
			frappe.call({
				method:"nj_features.nj_features.doctype.salvage_model.salvage_model.get_serial_item_grade_price",
				args:{
					model_no:frm.doc.model_no
				},
				callback:function(r){
					if (r.message){
						let total_price_of_components=0;
						let count=0;
						console.log('data======================',r.message);
						let data = r.message
						data.forEach(element => {
						let row = frm.add_child("item_child");
						row.serial_no_child=element.serial_no;
						row.item_child=element.item;
						row.grade_child=element.grade;
						row.price_item=element.price;
						if (element.grade==='Grade D'){
							count=count+1

						}
						
						

						if(element.grade==='Grade C' || element.grade==='Grade D'){
							let row_child=frm.add_child('item_price');
							row_child.serial_no1=element.serial_no;
							row_child.item_group1=element.item;
							row_child.grade1=element.grade;
							row_child.price1=element.price;
							total_price_of_components=total_price_of_components+element.price;
						};

						});
						frm.set_value('total_price_component',total_price_of_components);
						console.log('price of prod======================',total_price_of_components);
						console.log('Grade D count==============================',count);
						console.log('Grade D repairable================================',Math.round(0.4*count));


						frm.refresh_field('item_child');
						frm.refresh_field('item_price');
						frm.refresh_field('total_price_component');
					}
				}
			})
		}
	}



 
