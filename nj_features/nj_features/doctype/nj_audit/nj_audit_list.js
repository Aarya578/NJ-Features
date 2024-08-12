// frappe.listview_settings['NJ Audit'] = {
//     onload: function(listview) {
//         $('span.sidebar-toggle-btn').hide();
//         $('.col-lg-2.layout-side-section').hide();
//         $('.btn-primary.btn-sm.primary-action').hide();

//         if (frappe.user.has_role('NJ Audit Manager')) {

//             frappe.call({
//                 method: 'frappe.client.get_value',
//                 args: {
//                     doctype: 'NJ Settings',
//                     parameter: {'parameter': 'nj_audit_activation_level'},
//                     fieldname: ['value']
//                 },
//                 callback: function(response) {
//                     let currentValue = response.message.value;
//                     if (currentValue == '1') {
//                         $('.btn-primary.btn-sm.primary-action').show();
//                         $('[data-label="Active"]').addClass('btn-primary');
//                     } else {
//                         $('[data-label="Active"]').removeClass('btn-primary');
//                     }
//                 }
//             })
            
//             listview.page.add_inner_button("Active", function() {
//                 frappe.call({
//                     method: 'frappe.client.get_value',
//                     args: {
//                         doctype: 'NJ Settings',
//                         parameter: {'parameter': 'nj_audit_activation_level'},
//                         fieldname: ['name', 'value']
//                     },
//                     callback: function(response) {
//                         let nj_setting_name = response.message.name
//                         let currentValue = response.message.value;
//                         let newValue = (currentValue == "0") ? "1" : "0";
    
//                         frappe.call({
//                             method: 'frappe.client.set_value',
//                             args: {
//                                 doctype: 'NJ Settings',
//                                 name: nj_setting_name,
//                                 fieldname: 'value',
//                                 value: newValue,
//                             },
//                             callback: function(response) {
    
//                                 if (response.message.value == '1') {
//                                     $('.btn-primary.btn-sm.primary-action').show();
//                                     $('[data-label="Active"]').addClass('btn-primary');
//                                     frappe.show_alert({
//                                         message: __('NJ Audit has been activated successfully.'),
//                                         indicator: 'green'
//                                     });
//                                 } else if (response.message.value == '0') {
//                                     $('.btn-primary.btn-sm.primary-action').hide();
//                                     $('[data-label="Active"]').removeClass('btn-primary');
//                                     frappe.show_alert({
//                                         message: __('NJ Audit has been de-activated successfully.'),
//                                         indicator: 'red'
//                                     });
//                                 } else {
//                                     frappe.msgprint(__('Failed to Active.'));
//                                 }
//                             }
//                         });
//                     }
//                 });
//             });
            
//             listview.page.add_inner_button("Get Report", function() {
//             }).addClass('btn-primary')
//         }

// 	}
// };


// document.addEventListener('DOMContentLoaded', function() {
//     console.log('DOM fully loaded and parsed');
//     var getReportButton = document.querySelector('.btn.btn-default.ellipsis.btn-primary');
  
//     if (getReportButton) {
//       console.log('Get Report button found');
//       getReportButton.addEventListener('click', function(event) {
//         console.log('Get Report button was clicked!');
//       });
//     } else {
//       console.error('Get Report button not found');
//     }
// });

frappe.listview_settings['NJ Audit'] = {
    onload: function(listview) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        $('.btn-primary.btn-sm.primary-action').hide();

        if (frappe.user.has_role('NJ Audit Manager')) {

            frappe.call({
                method: 'frappe.client.get_value',
                args: {
                    doctype: 'NJ Settings',
                    parameter: {'parameter': 'nj_audit_activation_level'},
                    fieldname: ['value']
                },
                callback: function(response) {
                    let currentValue = response.message.value;
                    if (currentValue == '1') {
                        $('.btn-primary.btn-sm.primary-action').show();
                        $('[data-label="Active"]').addClass('btn-primary');
                    } else {
                        $('[data-label="Active"]').removeClass('btn-primary');
                    }
                }
            });

            listview.page.add_inner_button("Active", function() {
                frappe.call({
                    method: 'frappe.client.get_value',
                    args: {
                        doctype: 'NJ Settings',
                        parameter: {'parameter': 'nj_audit_activation_level'},
                        fieldname: ['name', 'value']
                    },
                    callback: function(response) {
                        let nj_setting_name = response.message.name;
                        let currentValue = response.message.value;
                        let newValue = (currentValue == "0") ? "1" : "0";

                        frappe.call({
                            method: 'frappe.client.set_value',
                            args: {
                                doctype: 'NJ Settings',
                                name: nj_setting_name,
                                fieldname: 'value',
                                value: newValue,
                            },
                            callback: function(response) {
                                if (response.message.value == '1') {
                                    $('.btn-primary.btn-sm.primary-action').show();
                                    $('[data-label="Active"]').addClass('btn-primary');
                                    frappe.show_alert({
                                        message: __('NJ Audit has been activated successfully.'),
                                        indicator: 'green'
                                    });
                                } else if (response.message.value == '0') {
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
                    }
                });
            }).addClass('btn-primary');

            listview.page.add_inner_button("Get Report", function() {
                console.log('Get Report button was clicked 167!');
                frappe.set_route(["query-report", "NJ Audit Report"]);
            }).addClass('btn btn-default ellipsis btn-primary');

        }
    }
};



  
  
  
  
