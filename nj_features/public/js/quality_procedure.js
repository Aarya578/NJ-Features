frappe.ui.form.on('Tools and Equipements', {
    tool_name: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const toolName = row.tool_name;

        if (toolName) {
            frappe.db.get_doc('Tool Names', toolName)
                .then(doc => {
                    frappe.model.set_value(cdt, cdn, 'specification', doc.specification || '');
                    frappe.model.set_value(cdt, cdn, 'value', doc.value || '');
                })
                .catch(err => {
                    console.error("❌ Failed to fetch Tool Names:", err);
                });
        }
    }
});

frappe.ui.form.on('Quality Procedure', {
    onload: function(frm) {
        frm.fields_dict.quality_processes.grid.get_field('procedure').get_query = function(doc, cdt, cdn) {
            return {
                filters: [
                    ['name', '!=', frm.doc.name] // exclude self-reference
                ]
            };
        };
    }
});
