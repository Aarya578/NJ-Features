// frappe.ui.form.on('Material Request Item', {
//     post_order_status: function(frm, cdt, cdn) {
//         let child = locals[cdt][cdn];
//         if (child.post_order_status == "Completed") {
//             frappe.user.get_role_profile("Modular Leads/Line Manager").then((result) => {
//                 if (result) { frappe.model.set_value(cdt, cdn, 'repaired_closed', 1); }
//             })
//         } else { frappe.model.set_value(cdt, cdn, 'repaired_closed', 0); }
//         frm.refresh_field('repaired_closed');
//     }
// });



// frappe.ui.form.on('Material Request Item', {
//     post_order_status: function(frm, cdt, cdn) {
//         console.log("inde===============================");
        
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
frappe.ui.form.on('Material Request Item', {
    post_order_status: function(frm, cdt, cdn) {
        console.log("Status change detected===============================");
        let row = locals[cdt][cdn];
        let new_status = row.post_order_status;
        
        // Get the initial status from the database or set default
        let initial_status = row.__original_post_order_status || row.__initial_post_order_status;
        
        // If initial status is not set, get it from the original doc
        if (!initial_status) {
            // Try to get from the original document in the database
            if (frm.doc.docstatus == 0) { // Only for draft documents
                frappe.db.get_value('Material Request Item', row.name, 'post_order_status')
                    .then(r => {
                        if (r.message && r.message.post_order_status) {
                            initial_status = r.message.post_order_status;
                            row.__initial_post_order_status = initial_status;
                        } else {
                            // If no value in DB, use current value as initial
                            initial_status = new_status;
                            row.__initial_post_order_status = initial_status;
                        }
                        processStatusChange(frm, cdt, cdn, new_status, initial_status);
                    });
                return;
            } else {
                // For new rows or when can't get from DB, assume current is initial
                initial_status = new_status;
                row.__initial_post_order_status = initial_status;
            }
        }
        
        processStatusChange(frm, cdt, cdn, new_status, initial_status);
    },

    store_team_comment: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        let initial_status = row.__initial_post_order_status || 'Not Completed';
        
        if (!row.store_team_comment || row.store_team_comment.trim() === "") {
            // If post_order_status is not initial status and comment is cleared, reset status
            if (row.post_order_status !== initial_status) {
                frappe.msgprint("Comment is required for post order status. Reverting to initial status.");
                frappe.model.set_value(cdt, cdn, 'post_order_status', initial_status);
            }
        }
    }
});

// Helper function to process status change
function processStatusChange(frm, cdt, cdn, new_status, initial_status) {
    let row = locals[cdt][cdn];
    
    // Only proceed if status is being changed from initial status
    if (new_status !== initial_status) {
        if (!row.store_team_comment || row.store_team_comment.trim() === "") {
            frappe.prompt(
                [
                    {
                        fieldtype: 'Text',
                        label: 'Enter reason for status change',
                        fieldname: 'reason',
                        reqd: 1
                    }
                ],
                function(values) {
                    // Save the comment
                    frappe.model.set_value(cdt, cdn, 'store_team_comment', values.reason);
                    // Re-set post_order_status after comment is provided
                    frappe.model.set_value(cdt, cdn, 'post_order_status', new_status);
                },
                function() {
                    // On cancel, revert back to initial status
                    frappe.model.set_value(cdt, cdn, 'post_order_status', initial_status);
                },
                'Provide Comment for Status Change',
                'Save Comment'
            );
            // Temporarily revert to initial status until confirmed
            frappe.model.set_value(cdt, cdn, 'post_order_status', initial_status);
        }
    }
}

// Store initial values when form is loaded
frappe.ui.form.on('Material Request', {
    refresh: function(frm) {
        // Store initial status for each row
        if (frm.doc.items) {
            frm.doc.items.forEach(function(row) {
                if (!row.__initial_post_order_status) {
                    row.__initial_post_order_status = row.post_order_status || 'Not Completed';
                }
            });
        }
    },
    
    items_add: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        // For new rows, set initial status
        row.__initial_post_order_status = row.post_order_status || 'Not Completed';
    }
});