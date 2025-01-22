frappe.ui.form.on('Productivity', {
    department: function (frm) {
        if (frm.doc.department) {
            // Fetch data using the server-side function
            frappe.call({
                method: "nj_features.nj_features.doctype.productivity.productivity.fetch_productivity_data",
                args: {
                    doc: frm.doc
                },
                callback: function (response) {
                    if (response.message) {
                        console.log("Response:", response.message);
                        // Clear existing child table data
                        frm.clear_table("productivity_child");

                        // Populate the child table with fetched data
                        response.message.forEach(row => {
                            let child = frm.add_child("productivity_child");
                            child.posting_date = row.posting_date;
                            child.serial_no = row.serial_no;
                            child.stock_entry_name = row.stock_entry_name;
                            child.stock_entry_creation = row.stock_entry_creation;
                            child.item_group = row.item_group;
                            child.item_code = row.item_code;
                            child.qty = row.qty;
                            child.t_warehouse = row.t_warehouse;
                            child.source_dept = row.source_dept;
                            child.target_dept = row.target_dept;
                            child.target_department = row.target_department;
                            child.dept_prd = row.dept_prd;
                            child.weightage_value = row.weightage_value;
                            child.wtd_qty = row.wtd_qty;
                        });

                        // Refresh the field to display the updated child table
                        frm.refresh_field("productivity_child");
                    }
                }
            });
        }
    }
});
