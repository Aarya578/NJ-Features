frappe.ui.form.on('Issue', {    
    refresh(frm) { 
        console.log("refreshing..");
    },

    after_save(frm) {
        console.log('current doc:', frm.doc);
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
});
