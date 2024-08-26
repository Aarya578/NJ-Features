frappe.listview_settings['NJ Audit'] = {

    onload: function(listview) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        $('.btn-primary.btn-sm.primary-action').hide();

        frappe.call({
            method: 'nj_features.nj_features.doctype.nj_audit.nj_audit.update_create_permission',
            args: {doctype: cur_list.doctype},
            callback: function(response) {
                let currentValue = response.message;
                if (currentValue == '1') {
                    $('.btn-primary.btn-sm.primary-action').show();
                    $('[data-label="Active"]').addClass('btn-primary');
                } else {
                    $('[data-label="Active"]').removeClass('btn-primary');
                }
            }
        });

        if (frappe.user.has_role('NJ Audit Manager')) {

            listview.page.add_inner_button("Active", function() {
                frappe.call({
                    method: 'nj_features.nj_features.doctype.nj_audit.nj_audit.update_create_permission',
                    args: {
                        doctype: cur_list.doctype,
                        active_status: 1,
                    },
                    callback: function(response) {
    
                        if (response.message == '1') {
                            $('.btn-primary.btn-sm.primary-action').show();
                            $('[data-label="Active"]').addClass('btn-primary');
                            frappe.show_alert({
                                message: __('NJ Audit has been activated successfully.'),
                                indicator: 'green'
                            });
                        } else if (response.message == '0') {
                            $('.btn-primary.btn-sm.primary-action').hide();
                            $('[data-label="Active"]').removeClass('btn-primary');
                            frappe.show_alert({
                                message: __('NJ Audit has been de-activated successfully.'),
                                indicator: 'red'
                            });
                        } else {
                            frappe.msgprint(__('Failed to Active.'));
                        }
                    }
                });
            });
            
            listview.page.add_inner_button("Duplicate Serial No Report", function() {
                frappe.set_route(["query-report", "NJ Audit Report"]);
            }).addClass('btn-primary');
            listview.page.add_inner_button("Not Scan Serial NO", function() {
                frappe.set_route(["query-report", "Not Scan Serial No Report"]);
            }).addClass('btn-primary');
        }

	}
};