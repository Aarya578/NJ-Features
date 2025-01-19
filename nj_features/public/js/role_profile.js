frappe.ui.form.on('Role Profile', {
    refresh: function(frm) {
        // console.log('I am Refreshing...');
    },
   
    validate: function(frm) {
        let total_weightage = 0;
             
        (frm.doc.kpi_parameter_table || []).forEach(row => {
            if (row.weightage) {
                total_weightage += row.weightage;
            }
        });

        if (total_weightage > 100) {
            frappe.throw(__('Weightage exceeds 100. Please adjust the values in the KPI Parameter Table.'));
        }
    }
});
