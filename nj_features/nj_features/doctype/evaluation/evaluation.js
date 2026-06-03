// Copyright (c) 2025, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Evaluation', {


// for getting only laptop product based on serial no.
	refresh(frm) {
        frm.set_query('serial_no', function() {
            return {
                filters: {
                    'item_group': 'Laptops'
                }
            };
        });
    },

// calculating the cost price and sell price
	part_cost:function(frm){
		let part_cost=frm.doc.part_cost;
		if (part_cost) {

			let rc=0.8*part_cost;
			frm.set_value('repair',rc);
			frm.refresh_field('repair')
		}
		let sp=frm.doc.sell_price;
		if (sp){
			// let cp = frm.doc.sell_price / (1 + (0.40 / 100));
			let cp=frm.doc.part_cost + frm.doc.purchase + frm.doc.repair;
			frm.set_value('cost_price',cp);
			frm.refresh_field(cost_price);
		}
	},
	
	// calculation based on the cost price and sell price to get the evaluation.
	calculate:function(frm){
		let sp=frm.doc.sell_price;
		let cp=frm.doc.cost_price;

		let profit_margin=((sp-cp)/sp)*100;
		console.log('margin============================',profit_margin);
		
		if (sp>cp && profit_margin>=30.0 ){
			frm.set_value('evaluation','Repaired');
		}
		else{
			frm.set_value('evaluation','Scrape');
		}

	},



	serial_no: function(frm){
		frappe.call({
			method: "nj_features.nj_features.doctype.evaluation.evaluation.get_serial_no_data",
			args:{
				serial_no: frm.doc.serial_no
			},
			callback: function(r) {
        	if (r.message) {
					console.log("Fetched parts:", r.message);

					let data = r.message;
	
					// inserting data into table which is parts 
					data.forEach(element => {
						console.log("element ----------- ", element);
						let row = frm.add_child("parts");
						row.item = element.item;
						row.item_name = element.item_group;
						row.grade = element.grade;
						if (element.grade ==='Grade C' || element.grade ==='Grade D' || element.grade ==='Grade B'  ){

							// for child_grade insertion.
							let child_col=frm.add_child("grade_table");
							child_col.item_name1=element.item_group;
							child_col.grade1=element.grade;

						}
					});
					frm.refresh_field('parts');
					frm.refresh_field('grade_table');
					
					
					// function call for the different functions whcch is given below.
					grade_table(frm);
					repairable(frm);


				}
    		}
		})
	},


//  gettig the data and setting it as sales price.
	part: function(frm){
		frappe.call({
			method: "nj_features.nj_features.doctype.evaluation.evaluation.get_valuation_rate",
			args:{
				part: frm.doc.part
			},
			callback: function(r) {
        	if (r.message) {
					console.log("valuation_rate:", r.message);
					frm.set_value('sell_price',r.message[0].valuation_rate);
					frm.refresh_field("sell_price"); 
				}
			}	
		})
	}
});


// frappe call for the function  to get price cost.
function repairable(frm) {
        if (frm.doc.repairable) {
            let items = frm.doc.repairable.split(',').map(i => i.trim()).filter(i => i);
            frappe.call({
                method: "nj_features.nj_features.doctype.evaluation.evaluation.get_total_cost",
                args: { items: JSON.stringify(items) },
                callback: function(r) {
                    if (r.message) {
                        frm.set_value('part_cost', r.message);
                        frm.refresh_field('part_cost');
                    }
                }
            });
        }
    }


// getting data from grade table and inserting it into field like repairable and grade.
function grade_table(frm) {
        let rows = frm.doc.grade_table || [];

		if (rows.length > 0){
        let combined = rows.map(r => r.item_name1).join(', ');
		let grade_combined=rows.map(r => r.grade1).join(', ');
        frm.set_value('repairable', combined);
		frm.set_value('grade',grade_combined);
	
    }
	frm.refresh_field('repairable');
	frm.refresh_field('grade');
}