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

frappe.ui.form.on('Quality Processes', {
    procedure: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const procedure = row.procedure;

        if (procedure) {
            frappe.call({
                method: "frappe.client.get",
                args: {
                    doctype: "Quality Procedure",
                    name: procedure
                },
                callback: function(r) {
                    if (r.message && r.message.quality_processes) {
                        // Take the first process step and set it directly in the current row
                        if (r.message.quality_processes.length > 0) {
                            row.procedure = procedure;
                            row.step = r.message.quality_processes[0].step;
                        }

                        // If you want to add *additional* steps (2nd, 3rd, etc.)
                        for (let i = 1; i < r.message.quality_processes.length; i++) {
                            let proc = r.message.quality_processes[i];
                            let child = frm.add_child("quality_processes");
                            child.procedure = procedure;
                            child.step = proc.step;
                        }

                        frm.refresh_field("quality_processes");
                    }
                }
            });
        }
    }
});


