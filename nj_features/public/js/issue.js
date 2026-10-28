frappe.ui.form.on('Issue', {
    priority(frm) {
        // D2-T05 safe fix: Guard to prevent priority change from clearing assigned developer
        if (frm.doc.assigned_to || frm.doc.assigned_developer) {
            return;
        }
    },
    after_save(frm) {
        if (frm.doc.issue_type === "MDT") {
            frappe.call({
                method: "nj_features.overrides.issue.raise_issue_in_model",
                args: { doc: frm.doc }
            });
        }
    }
});