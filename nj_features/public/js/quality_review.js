frappe.ui.form.on('Quality Review', {
    refresh: function(frm) {
        if (frm.doc.reviewee) {
            set_reviewee_data(frm);
        }
    },
    quality_procedure_name: function(frm) {
        if (frm.doc.review_type) {
            if (frm.doc.review_type != "Adhoc Review") {
                if(frm.doc.review_type != "Adhoc Review" && !frm.doc.reviewee){
                    frm.set_value('quality_procedure_name', '');
                    frappe.throw(__("Please select a Reviewee"));
                }
                console.log("quality_procedure_name", frm.doc.quality_procedure_name);
                frappe.call({
                    method: 'nj_features.overrides.quality_review.get_quality_procedure_details',
                    args: {
                        quality_procedure_name: frm.doc.quality_procedure_name,
                        review_type: frm.doc.review_type,
                        severity_level: frm.doc.severity_level
                    },
                    callback: function(r) {
                        // console.log("get_quality_procedure_details-------", r);
                        if (r.message && r.message.length > 0) {
                            frm.clear_table('review_procedures_table');

                            // loop r.message in reverse
                            for (let idx = r.message.length - 1; idx >= 0; idx--) {
                                let rowData = r.message[idx];

                                let tempDiv = document.createElement("div");
                                tempDiv.innerHTML = rowData.step || "";

                                let steps = tempDiv.querySelectorAll("li");

                                if (steps.length > 0) {
                                    // expand each <li> as separate row
                                    steps.forEach(function(li) {
                                        let row = frm.add_child('review_procedures_table');
                                        row.sub_procedure = rowData.procedure;
                                        row.task = rowData.task;
                                        row.severity = rowData.severity;
                                        row.reviewee = frm.doc.reviewee;
                                        row.item_group = rowData.item_group;
                                        row.step = li.innerText.trim();
                                    });
                                } else {
                                    // plain text fallback
                                    let row = frm.add_child('review_procedures_table');
                                    row.sub_procedure = rowData.procedure;
                                    row.task = rowData.task;
                                    row.severity = rowData.severity;
                                    row.reviewee = frm.doc.reviewee;
                                    row.item_group = rowData.item_group;
                                    row.step = (rowData.step || "").trim();
                                }
                            }

                            frm.refresh_field("review_procedures_table");
                        }


                        else{
                            frappe.msgprint({
                                title: __('Info'),
                                message: 'No matching Data found for Quality Procedure: <b>' + frm.doc.quality_procedure_name + '</b>',
                                indicator: 'orange'
                            });
                        }
                    }
                })
            }
            else{
                frm.clear_table('review_procedures_table');
                frm.refresh_field('review_procedures_table');
            }
        }
        else{
            frm.set_value('quality_procedure_name', '');
            frappe.msgprint(__("Please select a Review Type"));
        }
    },
    reviewee: function(frm) {
        if (frm.doc.reviewee) {
            set_reviewee_data(frm);
        }
    },
    serial_no: function(frm) {
        if (frm.doc.serial_no) {
            if(frm.doc.inspection){
                frappe.call({
                    method: 'nj_p1_features.nj_p1_features.doctype.nj_quality_inspection.nj_quality_inspection.validation_for_nj_readings_in_nj_qi',
                    args: {
                        serial_no: frm.doc.serial_no,
                        inspection_type: frm.doc.inspection,
                        is_defective: 0,
                        re_check: 0
                    },
                    callback: function(r) {
                        (frm.doc.review_procedures_table || []).forEach((row, idx) => {
                            if (row.item_group) {
                                frm.get_field("review_procedures_table").grid.grid_rows[idx].remove();
                            }
                        });
                        if(r.message.sequence_list_for_nj_readings_data){
                            r.message.sequence_list_for_nj_readings_data.forEach(function(rowData) {
                                let row = frm.add_child('review_procedures_table');
                                row.item_group = rowData.item_group;
                                row.step = rowData.quality_check;
                                row.reviewee = frm.doc.reviewee;
                                frappe.call({
                                    method: 'nj_features.overrides.quality_review.get_kms_data',
                                    args: {
                                        item_group: rowData.item_group,
                                        serial_no: frm.doc.serial_no,
                                        department: frm.doc.department,
                                    },
                                    callback: function(r) {
                                        if (r.message) {
                                            row.kms = r.message
                                        }
                                    }
                                })
                            })
                        }
                        frm.refresh_field("review_procedures_table");
                    }
                })
            }
            else{
                frappe.msgprint(__("Please select a Inspection Type"));
            }
        }
        else if(frm.doc.serial_no == null){
            frappe.msgprint(__("Please select a correct Serial No."));
        }
    }
});


function set_reviewee_data(frm) {
    frappe.db.get_doc('User', frm.doc.reviewee)
        .then(user => {
            if (user.role_profile_name) {
                frappe.db.get_doc('Role Profile', user.role_profile_name)
                    .then(roleProfile => {
                        // Department
                        if (roleProfile.department) {
                            frm.set_value('department', roleProfile.department);
                        }
                        else {
                            frm.set_value('department', '');
                        }

                        // Inspection Types
                        if (roleProfile.inspection_types && roleProfile.inspection_types.length > 0) {
                            let options = roleProfile.inspection_types.map(d => d.inspection_type);

                            // Update select field options
                            frm.set_df_property('inspection', 'options', options);

                            // Restore saved value if it exists, otherwise set default
                            if (frm.doc.inspection && options.includes(frm.doc.inspection)) {
                                frm.set_value('inspection', frm.doc.inspection);
                            } else if (!frm.doc.inspection) {
                                frm.set_value('inspection', options[0]);
                            }
                        }
                        else {
                            frm.set_value('inspection', '');
                            frm.set_df_property('inspection', 'options', []);
                        }
                    });
            } else {
                frappe.msgprint(__('No Role Profile found for this user'));
            }
        });
}

