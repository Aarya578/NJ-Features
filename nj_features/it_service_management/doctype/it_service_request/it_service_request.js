frappe.ui.form.on("IT Service Request", {
    refresh(frm) {
        // Toggle rejection reason visibility
        frm.toggle_display("rejection_reason", frm.doc.status === "Rejected");
        
        // Add quick actions if not new
        if (!frm.is_new()) {
            if (frm.doc.status === "Open" || frm.doc.status === "Draft") {
                frm.add_custom_button(__("Start Progress"), function() {
                    frm.set_value("status", "In Progress");
                    frm.save();
                }, __("Actions"));
            }
            if (frm.doc.status === "In Progress") {
                frm.add_custom_button(__("Submit for Review"), function() {
                    frm.set_value("status", "Pending Review");
                    frm.save();
                }, __("Actions"));
            }
        }
    },

    priority(frm) {
        // D2-T05 safe fix: Guard condition to preserve assigned developer on priority change
        if (frm.doc.assigned_developer) {
            // Retain developer
            return;
        }
    },

    status(frm) {
        frm.toggle_display("rejection_reason", frm.doc.status === "Rejected");
    }
});
