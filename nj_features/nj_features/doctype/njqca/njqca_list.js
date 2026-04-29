
frappe.listview_settings['NJQCA'] = {
    filters: [["created", "=", frappe.session.user]],
    refresh: function(listview) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
	}
};

frappe.listview_settings['NJQCA'] = {
    onload(listview) {
        // Call server to check department of logged-in user
        frappe.call({
            method: "frappe.client.get_value",
            args: {
                doctype: "Employee",
                filters: { user_id: frappe.session.user },
                fieldname: "department"
            },
            callback: function(r) {
                if (r && r.message) {
                    let user_department = r.message.department;
                    console.log(user_department);
                    // ✅ Show button only if department matches
                    if (user_department in ("BG - Core IQC - NJ", "")) {   // <-- put your department name here
                        listview.page.add_inner_button(__('Duplicate NJQCA'), function () {
                            let dialog = new frappe.ui.Dialog({
                                title: "Duplicate NJQCA by Serial No",
                                fields: [
                                    {
                                        fieldtype: "Data",
                                        fieldname: "serial_num",
                                        label: "Enter / Scan Serial No",
                                        reqd: 1
                                    }
                                ],
                                primary_action_label: "Duplicate",
                                primary_action(values) {
                                    if (!values.serial_num) {
                                        frappe.msgprint("Please enter a serial number");
                                        return;
                                    }

                                    frappe.call({
                                        method: "nj_features.nj_features.doctype.njqca.njqca.duplicate_njqca",
                                        args: { serial_no: values.serial_num },
                                        freeze: true,
                                        freeze_message: `<div style="text-align: center;">
                                            <i class="fa fa-spinner fa-spin" style="font-size: 24px;"></i> 
                                            <br>Loading Duplicate NJQCA... Please Wait
                                        </div>`,
                                        callback: function (r) {
                                            if (r.message) {
                                                dialog.hide();

                                                let new_doc = frappe.model.sync(r.message)[0];
                                                console.log(new_doc);
                                                frappe.set_route("Form", new_doc.doctype, new_doc.name);

                                                // call your external function
                                                njqca.get_model(new_doc.manufacturer_model);
                                            } else {
                                                frappe.msgprint("No NJQCA found for the given serial number.");
                                            }
                                        }
                                    });
                                },
                                secondary_action_label: "Cancel",
                                secondary_action() {
                                    dialog.hide();
                                }
                            });

                            dialog.show();
                        });
                    }
                }
            }
        });
    }
};
