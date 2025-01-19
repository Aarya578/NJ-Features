frappe.ui.form.on('Department', {
    refresh: function(frm) {
        console.log('I am Refreshing...');
    }
});

frappe.ui.form.on('Stock Movement Restriction Child', {
    grade: function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        
        if (child.grade) {
            let currentGrades = child.restricted_grade ? child.restricted_grade.split(', ') : [];

            if (!currentGrades.includes(child.grade)) {
                currentGrades.push(child.grade);
            }

            frappe.model.set_value(cdt, cdn, 'restricted_grade', currentGrades.join(', '));
        }
    }
});

// Add item_group filter for weightage_table child table
cur_frm.fields_dict["weightage_table"].grid.get_field("item_group").get_query = function (doc, cdt, cdn) {
    return {
        filters: {
            parent_item_group: ["in", ["Laptop Spare Parts", "Desktop Spares"]]
        }
    };
};
