frappe.ui.form.on('Change Management Request', {

    refresh: function(frm) {
        setup_action_buttons(frm);
        setup_assign_widget(frm);
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


// ─────────────────────────────────────────────────────────────
//  ASSIGN TO -- page-header widget (dropdown + Assign button)
// ─────────────────────────────────────────────────────────────
//
// Only shown to users with approval access (server re-checks this on every
// call regardless of what's rendered here). Assigning: saves Assigned To
// on this record, creates a native Frappe ToDo assignment, and emails the
// assignee via the default outgoing Email Account with a link back here.

function setup_assign_widget(frm) {
    if (frm.is_new() || frm.__change_mgmt_assign_widget_added) return;

    const MODULE = "nj_features.nj_features.doctype.change_management_request.change_management_request";

    frappe.call({
        method: MODULE + ".can_assign_change_request",
    }).then(r => {
        if (!r.message || frm.__change_mgmt_assign_widget_added) return;
        frm.__change_mgmt_assign_widget_added = true;
        render_assign_widget(frm, MODULE);
    });
}

function render_assign_widget(frm, MODULE) {
    const assign_field = frm.page.add_field({
        fieldtype: "Link",
        fieldname: "assign_to_user",
        label: __("Assign To"),
        options: "User",
        get_query: () => ({
            query: MODULE + ".get_assignable_users",
        }),
    });

    // page_form (frm.page.add_field's parent) is a full-width Bootstrap
    // row directly under the title/breadcrumb, not inline with the title
    // text itself -- push this field to the right end of that row so it
    // reads as "beside the title, on the right".
    $(assign_field.wrapper).css("margin-left", "auto");

    if (frm.doc.assigned_to) {
        assign_field.set_value(frm.doc.assigned_to);
    }

    const $btn = $(`<button class="btn btn-xs btn-primary">${__("Assign")}</button>`)
        .css({ display: "block", "margin-top": "6px", width: "100%" });
    $(assign_field.wrapper).append($btn);

    $btn.on("click", function() {
        const user = assign_field.get_value();
        if (!user) {
            frappe.msgprint(__("Select a user to assign to."));
            return;
        }
        frappe.call({
            method: MODULE + ".assign_change_request",
            args: { name: frm.doc.name, user: user },
            freeze: true,
            freeze_message: __("Assigning..."),
            callback: function(r) {
                if (r.message) {
                    frappe.show_alert({ message: __("Assigned and notified"), indicator: "green" }, 5);
                    frm.reload_doc();
                }
            }
        });
    });
}
