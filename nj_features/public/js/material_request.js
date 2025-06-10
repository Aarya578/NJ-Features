frappe.ui.form.on('Material Request Item', {
    post_order_status: function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        if (child.post_order_status == "Completed") {
            frappe.user.get_role_profile("Modular Leads/Line Manager").then((result) => {
                if (result) { frappe.model.set_value(cdt, cdn, 'repaired_closed', 1); }
            })
        } else { frappe.model.set_value(cdt, cdn, 'repaired_closed', 0); }
        frm.refresh_field('repaired_closed');
    }
});



// frappe.ui.form.on('Material Request Item', {
//     post_order_status: function(frm, cdt, cdn) {
//         let row = locals[cdt][cdn];
//         let new_status = row.post_order_status;

//         if (new_status !== "Pending") {
//             if (!row.store_team_comment || row.store_team_comment.trim() === "") {
//                 frappe.prompt(
//                     [
//                         {
//                             fieldtype: 'Text',
//                             label: 'Enter reason for status change',
//                             fieldname: 'reason',
//                             reqd: 1
//                         }
//                     ],
//                     function(values) {
//                         // Save the comment
//                         frappe.model.set_value(cdt, cdn, 'store_team_comment', values.reason);
//                         // Re-set post_order_status after comment is provided
//                         frappe.model.set_value(cdt, cdn, 'post_order_status', new_status);
//                     },
//                     function() {
//                         // On cancel, revert back to Pending
//                         frappe.model.set_value(cdt, cdn, 'post_order_status', 'Pending');
//                     },
//                     'Provide Comment for Status Change',
//                     'Save Comment'
//                 );

//                 // Temporarily revert to Pending until confirmed
//                 frappe.model.set_value(cdt, cdn, 'post_order_status', 'Pending');
//             }
//         }
//     },

//     store_team_comment: function(frm, cdt, cdn) {
//         let row = locals[cdt][cdn];
//         if (!row.store_team_comment || row.store_team_comment.trim() === "") {
//             // If post_order_status is not Pending and comment is cleared, reset status
//             if (row.post_order_status !== "Pending") {
//                 frappe.msgprint("Comment is required for post order status. Reverting to Pending.");
//                 frappe.model.set_value(cdt, cdn, 'post_order_status', 'Pending');
//             }
//         }
//     }
// });
