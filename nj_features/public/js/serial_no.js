frappe.ui.form.on('Serial No', {
    onload: function(frm) {
        init_component_snapshot(frm);
    },
    refresh: function(frm) {
        init_component_snapshot(frm);
        applyReadOnlyStyling(frm);

        console.log('Current user roles:', frappe.user_roles);
        // to make field edit accessible for specific roles
        if (frappe.user_roles.includes('NPD Manager')) {
            console.log('User has NPD Manager role, making to_make field editable.');
            frm.set_df_property('to_make', 'read_only', 0);
            frm.set_df_property('item_wizard', 'read_only', 0);

        }

        // Get the current user id from the session
        const current_user_id = frappe.session.user;

        // Check if user has System Manager role
        const allowed_roles = ['System Manager'];
        const has_permission = frappe.user_roles.some(role => allowed_roles.includes(role));

        if (!has_permission){
            // Fetch the employee's work warehouse from the Employee doctype using the user_id
            frappe.db.get_value('Employee', {user_id: current_user_id}, 'work_warehouse', function(data) {
                const employee_work_warehouse = data && data.work_warehouse;
                const serial_no_warehouse = frm.doc.warehouse;

                console.log("serial_no_warehouse", serial_no_warehouse);
                console.log("employee_work_warehouse", employee_work_warehouse);

                // Function to hide/show print elements based on warehouse match
                function togglePrintVisibility() {
                    const shouldShow = serial_no_warehouse === employee_work_warehouse;
                    
                    // Get the print button using the data-original-title attribute
                    let printButton = document.querySelector('button[data-original-title="Print"]');
                    
                    // Get the "Print" option in the dropdown menu - more specific selector
                    let printDropdownOption = Array.from(document.querySelectorAll('a.grey-link.dropdown-item')).find(
                        el => el.querySelector('[data-label="Print"]')
                    );

                    // Alternative: If the above doesn't work, try finding by text content
                    if (!printDropdownOption) {
                        printDropdownOption = Array.from(document.querySelectorAll('a.grey-link.dropdown-item')).find(
                            el => el.textContent.trim() === 'Print'
                        );
                    }

                    // Hide/show print button
                    if (printButton) {
                        printButton.style.display = shouldShow ? 'block' : 'none';
                    }

                    // Hide/show dropdown print option
                    if (printDropdownOption) {
                        printDropdownOption.style.display = shouldShow ? 'block' : 'none';
                        // Also hide the parent li if it exists
                        if (printDropdownOption.closest('li')) {
                            printDropdownOption.closest('li').style.display = shouldShow ? 'block' : 'none';
                        }
                    }
                }

                // Initial toggle
                togglePrintVisibility();

                // Use MutationObserver to handle dynamically loaded dropdown
                const observer = new MutationObserver(function(mutations) {
                    togglePrintVisibility();
                });

                // Observe the menu container for changes
                const menuContainer = document.querySelector('.dropdown-menu');
                if (menuContainer) {
                    observer.observe(menuContainer, {
                        childList: true,
                        subtree: true
                    });
                }

                // Also trigger when dropdown is shown
                setTimeout(togglePrintVisibility, 500);
            });
        };

        let is_read_only = frm.doc.bypass ? 1 : 0;
        frm.set_df_property("bypass", "read_only", is_read_only);
        frm.set_df_property("reason_for_warranty_bypass", "read_only", is_read_only);

        if (frappe.user.has_role('Developer')) {
            frm.set_df_property("bios_serial_no", "read_only", 0);
        }

        $('.col-lg-2.layout-side-section').hide();

        frm.add_custom_button(__('Generate Report'), function() {
            get_report_data(frm);
        }).addClass('btn-primary');

        frm.add_custom_button(__('Print QR Code'), function() {
            printQRCode(frm);
        });

        if (frappe.user.has_role(["Item Wizard Manager"]) || frappe.user.has_role(["Item Manager"])) {
            frm.set_df_property('serial_no_component', 'read_only', 0);
            frm.set_df_property('model', 'read_only', 0);
            frm.refresh_field('model');
            frm.refresh_field('serial_no_component');
        }

        frm.get_field('past_part_list').grid.cannot_add_rows = true;
        frm.refresh_field('past_part_list');

        frm.get_field('bag_list').grid.cannot_add_rows = true;
        frm.refresh_field('bag_list');

        // Department Count History is entirely managed by server-side hooks
        // (seed on creation, increment on real stock movement, hourly backfill
        // for pre-existing serials) -- only Restrict / Limit Count are meant
        // to be hand-edited. Hiding Add/Delete Row here is just the UI half;
        // nj_features.overrides.serial_no.prevent_manual_department_history_edits
        // (Serial No validate hook) is what actually enforces it server-side.
        frm.get_field('department_history').grid.cannot_add_rows = true;
        frm.get_field('department_history').grid.cannot_delete_rows = true;
        frm.get_field('department_history').grid.update_docfield_property('departmant', 'read_only', 1);
        frm.get_field('department_history').grid.update_docfield_property('count', 'read_only', 1);
        frm.refresh_field('department_history');

        // frappe.db.get_value('User', frappe.session.user, 'role_profile_name', (r) => {
        //     let role_profile = r ? r.role_profile_name : '';
        //     let is_admin_profile = (role_profile === 'Administrator')
        //         || frappe.session.user === 'Administrator'
        //         || frappe.user.has_role('Administrator')
        //         || frappe.user.has_role('System Manager');

        //     if (!is_admin_profile) {
        //         frm.set_df_property('bag_list', 'read_only', 1);
        //         if (frm.get_field('bag_list') && frm.get_field('bag_list').grid) {
        //             frm.get_field('bag_list').grid.cannot_add_rows = true;
        //             frm.get_field('bag_list').grid.cannot_delete_rows = true;
        //         }
        //     } else {
        //         frm.set_df_property('bag_list', 'read_only', 0);
        //         if (frm.get_field('bag_list') && frm.get_field('bag_list').grid) {
        //             frm.get_field('bag_list').grid.cannot_add_rows = false;
        //             frm.get_field('bag_list').grid.cannot_delete_rows = false;
        //         }
        //     }
        //     frm.refresh_field('bag_list');
        // });

        let update_features_table = frm.add_custom_button(__('Fetch Features Table'), function() {
            frappe.show_alert({
                message: __('Generating AWB Number...'),
                indicator: 'blue'
            });

            frappe.call({
                method: 'nj_p1_features.overrides.serial_no.updating_features_table_from_item_wizard',
                args: { serial_no: frm.doc.name },
                callback: function(response) {
                    if (response.message) {
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __('Courier Name Fetched successfully!'),
                            indicator: 'green'
                        });
                    }
                }
            });
        });

        // Add styling to the button
        update_features_table.addClass('btn-primary');


        frm.add_custom_button(__('Generate HTML Temp'), function () {

            frappe.show_alert({
                message: __('Generating QR HTML template...'),
                indicator: 'blue'
            }, 3);

            frappe.call({
                method: "nj_p1_features.overrides.serial_no.generate_qr_html_and_image",
                args: {
                    doctype: frm.doc.doctype,
                    docname: frm.doc.name
                },
                callback: function (r) {
                    if (r.message && !r.message.startsWith("Template rendering failed")) {

                        frm.set_value('qr', r.message);
                        frm.refresh_field('qr');
                   
                        frappe.msgprint({
                            title: __('Success'),
                            message: __('QR HTML and image generated successfully.'),
                            indicator: 'green'
                        });

                    } else {
                        frappe.msgprint({
                            title: __('Error'),
                            message: r.message || __('Failed to generate QR HTML.'),
                            indicator: 'red'
                        });
                    }
                }
            });
        });


                // Add styling to the button
        frm.add_custom_button(__('Generate QC Report'), function () {

            frappe.show_alert({
                message: __('Generating Performance Report...'),
                indicator: 'blue'
            }, 3);

            frappe.call({
                method: "nj_p1_features.overrides.serial_no.generating_report",
                args: {
                    docname: frm.doc.name
                },
                callback: function () {
                    frm.reload_doc(); // 🔄 render data in table
                }
            });
        });

    

    },
    
    after_save: (frm)=>{
        frm.set_df_property("bypass", "read_only", 1);
        frm.set_df_property("reason_for_warranty_pass", "read_only", 1);
        frm.refresh_field("bypass");
        frm.refresh_field("reason_for_warranty_pass");
    }
});

function applyReadOnlyStyling(frm) {

    frappe.db.get_value('NJ Settings', {'parameter': 'nc_modifier'}, 
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
    var doctype = encodeURIComponent("Serial No");
    var format = "Serial No Barcode";
    var print_trigger = 0;

    frappe.call({
        method: 'nj_features.nj_features.api.qr_code.generate_and_save_qrcode',
        args: { data: frm.doc.name },
        callback: function(r) {
            if (r.message) {
                frappe.db.get_value('NJ Settings', {'parameter': 'max_qr_copy'}, 'value').then((r) => {
                    let max_copies = r.message.value;
                    frm.doc.qr_print_count = frm.doc.qr_print_count ? frm.doc.qr_print_count + 1 : 1;

                    if (frm.doc.is_encrypted == 1) {
                        format = "SN QR Code Mapping";
                        docname = frm.doc.qr_code_mapping
                        doctype=encodeURIComponent("QR Code Mapping")
                    }
            
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
                                                method: "nj_features.nj_features.api.qr_code.get_print_format_role",
                                                callback: function(r) {
                                                    if (r.message == true) {
            
                                                        window.open(frappe.urllib.get_full_url("/printview?" +
                                                        "doctype=" + doctype +
                                                        "&name=" + docname +
                                                        "&trigger_print=" + print_trigger +
                                                        "&format=" + format +
                                                        "&no_letterhead=0" +
                                                        "&_lang=" + (frappe.boot.lang || "en")));
                                                        frm.reload_doc();
                                                    } else {
                                                        frappe.msgprint(__('You do not have permission to print QR code. Please contact your Reporting Manager.'));
                                                    }
                                                }
                                            });
                                        }
                                    });
                                });
                            } else {
                                // If under the limit, directly open the print view
                                window.open(frappe.urllib.get_full_url("/printview?" +
                                    "doctype=" + doctype +
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
        }
    });

}


function  get_report_data(frm) {
    frappe.call({
        method: 'nj_p1_features.overrides.serial_no.generate_customer_data',
        args: { serial_no: frm.doc.name }
    });
}

// =========================================================================
// Serial No Component UI Change Audit Log
// Monitors 'item' (item_code) and 'grade' modifications in child table
// =========================================================================

function init_component_snapshot(frm) {
    if (!frm.doc) return;
    frm._component_original_snapshot = {};
    const rows = frm.doc.serial_no_component || [];
    rows.forEach(row => {
        if (row.name) {
            frm._component_original_snapshot[row.name] = {
                item: (row.item || "").trim(),
                grade: (row.grade || "").trim(),
                item_group: (row.item_group || "").trim()
            };
        }
    });
}

function prompt_for_component_reason(frm, row, fieldname, label, old_val, new_val, item_group, on_success, on_cancel) {
    const dialog = new frappe.ui.Dialog({
        title: __('Reason for Change'),
        fields: [
            {
                fieldtype: 'HTML',
                fieldname: 'change_info',
                options: `
                    <div style="margin-bottom: 12px; font-size: 13px; line-height: 1.5;">
                        <p>You changed: <b>${frappe.utils.escape_html(label)}</b></p>
                        <p style="margin-bottom: 4px;">Old Value: <span class="text-muted font-weight-bold">${frappe.utils.escape_html(old_val || "(Empty)")}</span></p>
                        <p style="margin-bottom: 4px;">New Value: <span class="text-primary font-weight-bold">${frappe.utils.escape_html(new_val || "(Empty)")}</span></p>
                        <p class="text-danger" style="margin-top: 8px;"><b>Please enter the reason for this change. Minimum 15 characters.</b></p>
                    </div>
                `
            },
            {
                label: __('Reason for change'),
                fieldname: 'reason',
                fieldtype: 'Small Text',
                reqd: 1,
                description: __('Minimum 15 characters (excluding leading/trailing spaces)')
            }
        ],
        primary_action_label: __('Continue'),
        primary_action(values) {
            const reason = (values.reason || "").trim();
            if (reason.length < 15) {
                frappe.msgprint({
                    title: __('Validation Failed'),
                    indicator: 'red',
                    message: __('Please provide a reason with at least 15 characters.')
                });
                return;
            }
            dialog.hide();
            on_success(reason);
        }
    });

    let is_submitted = false;
    dialog.get_primary_btn().on('click', () => { is_submitted = true; });

    dialog.$wrapper.find('.modal-header .close, .modal-footer .btn-default').on('click', function() {
        if (!is_submitted && on_cancel) {
            on_cancel();
        }
    });

    dialog.show();
}

function append_to_serial_no_change_log(frm, log_entry_text) {
    const existing_log = (frm.doc.serial_no_changes_log || "").trim();
    let new_log = "";
    if (!existing_log) {
        new_log = log_entry_text;
    } else {
        new_log = existing_log + "\n\n--------------------------------------------------\n\n" + log_entry_text;
    }
    frm.set_value('serial_no_changes_log', new_log);
    frm.refresh_field('serial_no_changes_log');
}

frappe.ui.form.on('Serial No Component', {
    item: function(frm, cdt, cdn) {
        if (!frm._component_original_snapshot) {
            init_component_snapshot(frm);
        }
        const row = locals[cdt][cdn];
        const original = frm._component_original_snapshot[row.name];
        const old_item = original ? original.item : "";
        const new_item = (row.item || "").trim();

        // If not changed, skip
        if (original && old_item === new_item) {
            return;
        }

        if (!new_item) {
            return;
        }

        // Determine Item Group from row or fetch from Item master
        let item_group = row.item_group || (original ? original.item_group : "");
        const proceed_with_item = (final_item_group) => {
            prompt_for_component_reason(
                frm,
                row,
                'item_code',
                original ? 'Item Code' : 'Item Code (New Row)',
                old_item || "(None - New)",
                new_item,
                final_item_group,
                function(valid_reason) {
                    frappe.call({
                        method: 'nj_features.overrides.serial_no.format_component_audit_entry',
                        args: {
                            serial_no: frm.doc.name,
                            item_group: final_item_group,
                            component: row.name,
                            field_changed: 'item_code',
                            old_value: old_item || "(None - New Row)",
                            new_value: new_item,
                            reason: valid_reason
                        },
                        callback: function(r) {
                            if (r.message) {
                                append_to_serial_no_change_log(frm, r.message);
                                if (!frm._component_original_snapshot[row.name]) {
                                    frm._component_original_snapshot[row.name] = { item: "", grade: "", item_group: "" };
                                }
                                frm._component_original_snapshot[row.name].item = new_item;
                                if (final_item_group) {
                                    frm._component_original_snapshot[row.name].item_group = final_item_group;
                                }
                            }
                        }
                    });
                },
                function() {
                    frappe.model.set_value(cdt, cdn, 'item', old_item);
                }
            );
        };

        if (!item_group && new_item) {
            frappe.db.get_value('Item', new_item, 'item_group', function(r) {
                proceed_with_item(r ? r.item_group : "");
            });
        } else {
            proceed_with_item(item_group);
        }
    },

    grade: function(frm, cdt, cdn) {
        if (!frm._component_original_snapshot) {
            init_component_snapshot(frm);
        }
        const row = locals[cdt][cdn];
        const original = frm._component_original_snapshot[row.name];
        const old_grade = original ? original.grade : "";
        const new_grade = (row.grade || "").trim();

        // If not changed, skip
        if (original && old_grade === new_grade) {
            return;
        }

        if (!new_grade) {
            return;
        }

        const item_group = row.item_group || (original ? original.item_group : "");

        prompt_for_component_reason(
            frm,
            row,
            'grade',
            original ? 'Grade' : 'Grade (New Row)',
            old_grade || "(None - New)",
            new_grade,
            item_group,
            function(valid_reason) {
                frappe.call({
                    method: 'nj_features.overrides.serial_no.format_component_audit_entry',
                    args: {
                        serial_no: frm.doc.name,
                        item_group: item_group,
                        component: row.name,
                        field_changed: 'grade',
                        old_value: old_grade || "(None - New Row)",
                        new_value: new_grade,
                        reason: valid_reason
                    },
                    callback: function(r) {
                        if (r.message) {
                            append_to_serial_no_change_log(frm, r.message);
                            if (!frm._component_original_snapshot[row.name]) {
                                frm._component_original_snapshot[row.name] = { item: "", grade: "", item_group: "" };
                            }
                            frm._component_original_snapshot[row.name].grade = new_grade;
                        }
                    }
                });
            },
            function() {
                frappe.model.set_value(cdt, cdn, 'grade', old_grade);
            }
        );
    }
});



