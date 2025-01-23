frappe.ui.form.on('Department', {
    refresh: function(frm) {
        // console.log("refreshing...")
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

frappe.ui.form.on('Inventory Details', {
    warehouse: function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];

        if (child.iw && child.fw){
            frappe.model.set_value(cdt, cdn, 'warehouse', '');
            return
        }

        if (child.iw || child.fw) {
            console.log('Warehouse field triggered in child Doctype...');

            if (child.iw) {
                let inwarded_warehouse = child.inwarded_warehouse ? 
                    child.inwarded_warehouse.split(',').map(w => w.trim()) : [];

                if (!inwarded_warehouse.includes(child.warehouse)) {
                    inwarded_warehouse.push(child.warehouse.trim());
                }

                frappe.model.set_value(cdt, cdn, 'inwarded_warehouse', inwarded_warehouse.join(', '));
                frappe.model.set_value(cdt, cdn, 'warehouse', '');
            }

            if (child.fw) {
                let forwarded_warehouse = child.forwarded_warehouse ? 
                    child.forwarded_warehouse.split(',').map(w => w.trim()) : [];

                if (!forwarded_warehouse.includes(child.warehouse)) {
                    forwarded_warehouse.push(child.warehouse.trim());
                }

                frappe.model.set_value(cdt, cdn, 'forwarded_warehouse', forwarded_warehouse.join(', '));
                frappe.model.set_value(cdt, cdn, 'warehouse', '');
            }
        }
    }
});