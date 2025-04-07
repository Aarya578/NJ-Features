frappe.ui.form.on('Serial No', {
    refresh: function(frm) {
        applyReadOnlyStyling(frm)
        let is_read_only = frm.doc.bypass ? 1 : 0;
        frm.set_df_property("bypass", "read_only", is_read_only);
        frm.set_df_property("reason_for_warranty_bypass", "read_only", is_read_only);

        if (frappe.user.has_role('Developer')) {
            frm.set_df_property("bios_serial_no", "read_only", 0);
        }

        $('.col-lg-2.layout-side-section').hide();
        frm.add_custom_button(__('Print QR Code'), function() {
            printQRCode(frm);
        }).addClass('btn-primary');
        frm.add_custom_button(__('Generate Report'), function() {
            get_report_data(frm);
        }).addClass('btn-primary');

        if (frappe.user.has_role(["Item Wizard Manager"])) {
            frm.set_df_property('serial_no_component', 'read_only', 0);
            frm.set_df_property('model','read_only',0);
            frm.refresh_field('model');
            frm.refresh_field('serial_no_component');
        }

        frm.get_field('past_part_list').grid.cannot_add_rows = true;
        frm.get_field('bag_list').grid.cannot_add_rows = true;
        frm.refresh_field('past_part_list');
        frm.refresh_field('bag_list');

        // frappe.call({
        //     method: "nj_features.nj_features.doctype.stock_movement.stock_movement.get_grades_from_part_list",
        //     args: {
        //         search_value: cur_frm.doc.name
        //     },
        //     callback: function(gradesResponse) {
        //         const gradesData = gradesResponse && gradesResponse.message;
            
        //         if (gradesData && gradesData.length > 0) {
            
        //             // Extract department names from the response
        //             const departmentNames = gradesData.map(entry => entry.department);
            
        //             // Update the options of the 'suggested_warehouse' field
        //             // cur_frm.set_df_property('suggested_warehouse', 'options', departmentNames.join('\n'));
            
        //             // Optionally, set the first department as the default value
        //             cur_frm.set_value('suggested_warehouse', departmentNames.join(', '));
        //         } else {
        //             // Clear the options if no data is found
        //             // cur_frm.set_df_property('suggested_warehouse', 'options', '');
        //             cur_frm.set_value('suggested_warehouse', '');
        //         }
        //     }
        // });
    },
    after_save: (frm)=>{
        frm.set_df_property("bypass", "read_only", 1);
        frm.set_df_property("reason_for_warranty_pass", "read_only", 1);
        frm.refresh_field("bypass");
        frm.refresh_field("reason_for_warranty_pass");
    }
});

function applyReadOnlyStyling(frm) {

    frappe.db.get_value('NJ Settings', {'doc_type': 'Serial No', 'parameter': 'nc_modifier'}, 
    'value').then(function(r) {
        if (r.message && r.message.value) {
            if (!frappe.user.has_role(r.message.value)) {
                var sectionWrapper = frm.fields_dict['bypass_warranty'].wrapper;

                $(sectionWrapper).css({
                    'background-color': 'rgba(247, 247, 247, 0.3)',
                    'border-radius': '8px',
                    'padding': '10px',
                    'box-shadow': '0 8px 16px rgba(0, 0, 0, 0.1)'
                });

                frm.set_df_property("bypass", "read_only", 1);
                frm.set_df_property("reason_for_warranty_bypass", "read_only", 1);
                frm.set_df_property('bypass', 'hidden', 1);
                frm.set_df_property('reason_for_warranty_bypass', 'hidden', 1);

                var lockIconHtml = '<i class="fa fa-lock" style="margin-right: 5px;"></i>';
                $(sectionWrapper).prepend(lockIconHtml);
                $(sectionWrapper).append(
                    '<div>' + __('You are not allowed to edit this section') + '</div>'
                );
            }
        } else {
            console.error('Failed to retrieve role from NJ Settings:', r.message);
        }
    });
}

function printQRCode(frm) {
    var docname = encodeURIComponent(frm.doc.name);
    var format = "Serial No Barcode";
    var print_trigger = 0;

    frappe.call({
        method: 'nj_features.nj_features.api.qr_code.generate_and_save_qrcode',
        args: { data: frm.doc.name }
    });

    frappe.db.get_value('NJ Settings', {'parameter': 'max_qr_copy'}, 'value').then((r) => {
        let max_copies = r.message.value;
        frm.doc.qr_print_count = frm.doc.qr_print_count ? frm.doc.qr_print_count + 1 : 1;

        frappe.call({
            method: "frappe.client.set_value",
            args: {
                doctype: "Serial No", name: frm.doc.name,
                fieldname: "qr_print_count", value: frm.doc.qr_print_count
            },
            callback: function(response) {
                if (frm.doc.qr_print_count > max_copies) {
                    // Prompt for reason and comment if print limit exceeded
                    frappe.prompt([
                        {
                            fieldname: 'reason',
                            label: 'Reason',
                            fieldtype: 'Link',
                            reqd: 1,
                            options: 'Master Reasons'
                        },
                        {
                            fieldname: 'comment',
                            label: 'Comment',
                            fieldtype: 'Text',
                            reqd: 1
                        }
                    ], function(values) {
                        let reason = values.reason;
                        let comment = values.comment;

                        // Add comment for print reason
                        frappe.call({
                            method: "frappe.desk.form.utils.add_comment",
                            args: {
                                reference_doctype: frm.doctype,
                                reference_name: frm.doc.name,
                                content: frappe.session.user + ' has taken 1 copy. \nReason: ' + reason + '\nComment: ' + comment,
                                comment_email: frappe.session.user,
                                comment_by: frappe.session.user_fullname,
                            },
                            callback: function() {
                                // Generate QR code and open the print view
                                frappe.call({
                                    method: "nj_features.qr_code.get_print_format_role",
                                    callback: function(r) {
                                        if (r.message == true) {
                                            window.open(frappe.urllib.get_full_url("/printview?" +
                                            "doctype=" + encodeURIComponent("Serial No") +
                                            "&name=" + docname +
                                            "&trigger_print=" + print_trigger +
                                            "&format=" + format +
                                            "&no_letterhead=0" +
                                            "&_lang=" + (frappe.boot.lang || "en")));
                                            frm.reload_doc();
                                        }else{
                                            frappe.msgprint(__('QR code generation failed.'));
                                        }
                                    }
                                });
                            }
                        });
                    });
                } else {
                    // If under the limit, directly open the print view
                    window.open(frappe.urllib.get_full_url("/printview?" +
                        "doctype=" + encodeURIComponent("Serial No") +
                        "&name=" + docname +
                        "&trigger_print=" + print_trigger +
                        "&format=" + format +
                        "&no_letterhead=0" +
                        "&_lang=" + (frappe.boot.lang || "en")));
                    frm.reload_doc();
                }
            }
        });
    });
}



function  get_report_data(frm) {
    frappe.call({
        method: 'nj_p1_features.overrides.serial_no.get_checks_data',
        args: { serial_no: frm.doc.name }
    });
}