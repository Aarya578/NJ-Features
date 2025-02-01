frappe.ui.form.on('Productivity', {
    department: function (frm) {
        if (frm.doc.department) {
            // Fetch data using the server-side function
            console.log('cur_frm', cur_frm.doc);
            frappe.call({
                method: "nj_features.nj_features.doctype.productivity.productivity.fetch_productivity_data",
                args: {
                    doc: frm.doc
                },
                callback: function (response) {
                    if (response.message) {
                        // Set role profile
                        if (response.message.role_profile) {
                            frm.set_value("role_profile", response.message.role_profile);
                        }

                        // Ensure productivity_data is an array
                        if (Array.isArray(response.message.productivity_data)) {
                            // Store the fetched data in a custom property
                            frm.original_productivity_data = response.message.productivity_data;

                            // Populate the child table with the fetched data
                            populate_productivity_table(frm, frm.original_productivity_data);
                        } else {
                            console.error("Productivity data is not an array.");
                        }
                    }
                }
            });
        }
    },

    to: function (frm) {
        // Trigger filtering when "to" field is changed
        filter_productivity_table(frm);
    },

    from: function (frm) {
        // Trigger filtering when "from" field is changed
        filter_productivity_table(frm);
    }
});

function filter_productivity_table(frm) {
    console.log('triggering...');
    if (frm.doc.from && frm.doc.to) {
        // Convert "from" and "to" to Date objects for comparison
        let from_date = frappe.datetime.str_to_obj(frm.doc.from);
        let to_date = frappe.datetime.str_to_obj(frm.doc.to);

        // Filter the original fetched data
        let filtered_data = frm.original_productivity_data.filter(row => {
            let posting_date = frappe.datetime.str_to_obj(row.posting_date);
            return posting_date >= from_date && posting_date <= to_date;
        });

        // Populate the child table with the filtered data
        populate_productivity_table(frm, filtered_data);
    }
}

function populate_productivity_table(frm, data) {
    // Clear the child table
    frm.clear_table("productivity_child_table");

    // Add rows to the child table
    data.forEach(row => {
        console.log(" ------------------ ", row)
        let child = frm.add_child("productivity_child_table");
        child.posting_date = row.posting_date;
        child.serial_no = row.serial_no;
        child.stock_entry_name = row.stock_entry_name;
        child.stock_entry_creation = row.stock_entry_creation;
        child.item_group = row.item_group;
        child.item_code = row.item_code;
        child.qty = row.qty;
        child.src_warehouse = row.Src_warehouse; // Updated field mapping
        child.t_warehouse = row.t_warehouse;
        child.source_dept = row.Source_dept; // Updated field mapping
        child.target_dept = row.Target_Dept; // Updated field mapping
        child.source_profile = row.Source_Profile; // Updated field mapping
        child.target_profile = row.Target_Profile; // Updated field mapping
        child.weightage_value = row.Itemgroup_weightage_value; // Updated field mapping
        child.wtd_qty = row.wtd_qty;
        child.dept_prd = row.dept_prd;
        child.profile_prd = row.profile_prd; // Updated field mapping
        child.match_prd_flag = row.match_prd_flag; // Updated field mapping
    });

    // Refresh the field to display the updated child table
    frm.refresh_field("productivity_child_table");
}
