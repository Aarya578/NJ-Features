frappe.ui.form.on('Issue', {
    after_save(frm) {
        if (frm.doc.issue_type === "MDT") {
            frappe.call({
                method: "nj_features.overrides.issue.raise_issue_in_model",
                args: { doc: frm.doc }
            });
        }
    }
});