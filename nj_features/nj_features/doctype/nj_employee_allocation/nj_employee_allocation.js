// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

// frappe.ui.form.on('NJ Employee Allocation', {
// 	// refresh: function(frm) {

// 	// }
// });
// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('NJ Employee Allocation', {
    onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        // Get current session user details
        var currentUserEmail = frappe.session.user;
        
        // Make a server-side call to fetch the user's first name
        frappe.call({
            method: "frappe.client.get_value",
            args: {
                doctype: "User",
                filters: { "email": currentUserEmail },
                fieldname: ["full_name"]
            },
            callback: function(response) {
                // Set the user's first name to the 'user' field
                var full_name = response.message.full_name;
                frm.set_value('user', full_name);
            }
        });

        // Get current date and time
        var currentDateTime = frappe.datetime.now_datetime();

        // Set the current date and time to the respective field
        // frm.set_value('date_and_time', currentDateTime);
    }
});
