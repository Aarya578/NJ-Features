frappe.ui.form.on('Change Management Request', {

    refresh: function(frm) {
        setup_action_buttons(frm);
    }

});


// ─────────────────────────────────────────────────────────────
//  ACTION BUTTONS
// ─────────────────────────────────────────────────────────────

function setup_action_buttons(frm) {

    if (frm.is_new()) return;

    const status = frm.doc.status;
    const MODULE = "nj_features.nj_features.doctype.change_management_request.change_management_request";

    // ── Leading: jump to Change Management Settings ───────────
    if (frappe.model.can_read("Change Management Settings")) {
        frm.add_custom_button(__("Change Management Settings"), function() {
            frappe.set_route("Form", "Change Management Settings");
        });
    }

    // ── Pending Approval → Approve / Reject ───────────────────
    // Both buttons call the same server-side check (Change Management
    // Approver flag on the acting user's Role Profile, self-approval
    // allowed) -- the button just saves a trip to dev console.
    if (status === "Pending Approval") {

        frm.add_custom_button(__("Approve"), function() {
            frappe.confirm(
                __("Approve this Change Management Request? The change will be applied to {0} {1} immediately.",
                    [frm.doc.reference_doctype, frm.doc.is_new_record ? __("(new record)") : frm.doc.reference_name]),
                function() {
                    frappe.call({
                        method: MODULE + ".approve_change_request",
                        args: { name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Applying change..."),
                        callback: function(r) {
                            if (r.message) {
                                frappe.show_alert({ message: __("Change Management Request Approved"), indicator: "green" }, 5);
                                frm.reload_doc();
                            }
                        }
                    });
                }
            );
        }).addClass("btn-primary");

        frm.add_custom_button(__("Reject"), function() {
            frappe.prompt(
                { fieldtype: "Small Text", fieldname: "reason", label: "Rejection Reason", reqd: 1 },
                function(values) {
                    frappe.call({
                        method: MODULE + ".reject_change_request",
                        args: { name: frm.doc.name, reason: values.reason },
                        callback: function(r) {
                            if (r.message) {
                                frappe.show_alert({ message: __("Change Management Request Rejected"), indicator: "red" }, 4);
                                frm.reload_doc();
                            }
                        }
                    });
                },
                __("Reject Change Management Request"), __("Reject")
            );
        }).addClass("btn-danger");
    }

    // ── Approved / Rejected → read-only outcome banners ───────
    if (status === "Approved") {
        frm.dashboard.set_headline_alert(
            __("Approved by {0} on {1}", [frm.doc.approved_by, frappe.datetime.str_to_user(frm.doc.approved_on)]),
            "green"
        );
    }

    if (status === "Rejected" && frm.doc.rejection_reason) {
        frm.dashboard.set_headline_alert(
            __("Rejected: {0}", [frm.doc.rejection_reason]),
            "red"
        );
    }
}
