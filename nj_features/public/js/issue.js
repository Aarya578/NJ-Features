frappe.ui.form.on('Issue', {
    refresh(frm) {
        console.log("Refreshing...");
    },
    
    after_save(frm) {
        // Only proceed with the API call if issue_type is MDT
        if (frm.doc.issue_type === "MDT") {
            console.log('Current doc:', frm.doc);
            frappe.call({
                method: "nj_features.overrides.issue.raise_issue_in_model",
                args: {
                    doc: frm.doc
                },
                callback: function(r) {
                    if (r.message) {
                        console.log("Success:", r.message);
                    }
                }
            });
        }
    }
});