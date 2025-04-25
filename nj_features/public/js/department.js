frappe.ui.form.on('Department', {
    refresh: function(frm) {
        frm.set_query('linked_warehouse', function(doc) {
			return { filters: { "is_group": 1 } };
		});
    },
})

frappe.ui.form.on('Stock Movement Restriction Child', {

    grade: function(frm, cdt, cdn) {
        if (locals[cdt][cdn].item_group){
            let child = locals[cdt][cdn];
        
            if (child.grade) {
                let currentGrades = child.restricted_grade ? child.restricted_grade.split(', ') : [];

                if (!currentGrades.includes(child.grade)) {
                    currentGrades.push(child.grade);
                }

                frappe.model.set_value(cdt, cdn, 'restricted_grade', currentGrades.join(', '));
            }
        }else{
            frappe.model.set_value(cdt, cdn, 'grade', '');
            frappe.throw('Please Select Item Group')
        }
    }
});

frappe.ui.form.on('Inventory Details', {
    inwarded_warehouse: function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];

        if (child) {

            if (child) {
                let inwarded_warehouse_list = child.inwarded_warehouse_list ? 
                    child.inwarded_warehouse_list.split(',').map(w => w.trim()) : [];

                if (!inwarded_warehouse_list.includes(child.inwarded_warehouse)) {
                    inwarded_warehouse_list.push(child.inwarded_warehouse.trim());
                }

                frappe.model.set_value(cdt, cdn, 'inwarded_warehouse_list', inwarded_warehouse_list.join(', '));
                frappe.model.set_value(cdt, cdn, 'inwarded_warehouse', '');
            }

            // if (child.fw) {
            //     let forwarded_warehouse = child.forwarded_warehouse ? 
            //         child.forwarded_warehouse.split(',').map(w => w.trim()) : [];

            //     if (!forwarded_warehouse.includes(child.warehouse)) {
            //         forwarded_warehouse.push(child.warehouse.trim());
            //     }

            //     frappe.model.set_value(cdt, cdn, 'forwarded_warehouse', forwarded_warehouse.join(', '));
            //     frappe.model.set_value(cdt, cdn, 'warehouse', '');
            // }
        }
    },
});


// Add item_group filter for weightage_table child table
// cur_frm.fields_dict["weightage_table"].grid.get_field("item_group").get_query = function (doc, cdt, cdn) {
//     return {
//         filters: {
//             parent_item_group: ["in", ["Laptop Spare Parts", "Desktop Spares"]]
//         }
//     };
// };


