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
    refresh: function(frm) {
        console.log("🔁 Quality Procedure loaded");
    }
});
