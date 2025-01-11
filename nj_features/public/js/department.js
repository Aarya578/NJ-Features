frappe.ui.form.on('Department', {
    refresh: function(frm) {
        console.log('Iam Refreshing...')
    },
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