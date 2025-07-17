frappe.ui.form.on('Quality Review', {
    refresh: function(frm) {
        console.log("🔁 Quality Review loaded");
    },
    quality_procedure_name: function(frm) {
        if (frm.doc.review_type && frm.doc.review_type !== 'Adhoc Review') {
            if (frm.doc.review_type &&  frm.doc.reviewee) {
                console.log("quality_procedure_name", frm.doc.quality_procedure_name);
                frappe.call({
                    method: 'nj_features.overrides.quality_review.get_quality_procedure_details',
                    args: {
                        quality_procedure_name: frm.doc.quality_procedure_name,
                        review_type: frm.doc.review_type,
                        severity_level: frm.doc.severity_level
                    },
                    callback: function(r) {
                        console.log("get_quality_procedure_details-------", r);
                        if (r.message && r.message.length > 0) {
                            frm.clear_table('review_procedures_table');
                            r.message.forEach(function(rowData) {
                                let row = frm.add_child('review_procedures_table');
                                row.sub_procedure = rowData.procedure;
                                row.task = rowData.task;
                                row.severity = rowData.severity;
                                row.reviewee = frm.doc.reviewee;
                                row.item_group = rowData.item_group;
                                row.step = rowData.step;
                            });
                            frm.refresh_field('review_procedures_table');
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
                frm.set_value('quality_procedure_name', '');
                frappe.msgprint(__("Please select a Review Type and Reviewee"));
            }
        }
    },
});