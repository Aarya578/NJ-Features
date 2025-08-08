frappe.ui.form.on('Dispatch Security Checkpoints', {
    onload: function(frm) {
        if (frm.doc.docstatus == 0) {
            frm.set_df_property('dispatch_security_child_table', 'cannot_add_rows', true);
            frm.set_df_property('dispatch_security_retutn_table', 'cannot_add_rows', true);
        }
    },
    // after_save(frm) {
    //     frappe.call({
    //         method: "nj_features.nj_features.doctype.dispatch_security_checkpoints.dispatch_security_checkpoints.fsetting_email_in_parent",
    //         args: {
    //             docname: frm.doc.name
    //         },
    //         callback: function (r) {
    //             if (r.message) {
    //                 frm.set_value("dispatch_email", r.message);
    //                 frm.refresh_field("dispatch_email");
    //                 frappe.show_alert({ message: "Dispatch Email Updated", indicator: "green" });
    //             }
    //         }
    //     });
    // },
    refresh: function(frm) {
        handleScannerInput(frm, 'scan_serial_no');
        $('.col-lg-2.layout-side-section').hide();
        if (frm.doc.docstatus == 0) {
            $('[data-fieldname="scan_serial_no"]').focus();
        }
    },

    barcode: function(frm) {
        handleScannerInput(frm, 'barcode');
		if (frm.doc.barcode) { 
			frappe.call({
				method: "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
				args: {  search_value: frm.doc.barcode, raise_exp: 0 },
				callback: function(r) {
					if (r.message) {
						if (r.message.serial_no) {
							frm.set_value('scan_serial_no', r.message.serial_no);
						} else if (r.message.scan) {
							frappe.msgprint("Please Scan the Serial No.");
							frm.set_value('barcode', '');
							frm.set_value('scan_serial_no', '');
						}
						frm.refresh_field("scan_serial_no");
						frm.refresh_field("barcode");
						$('[data-fieldname="barcode"]').focus();
					}
				},
				error: function(r) {
					frappe.msgprint("Error while scanning Serial No.");
					frm.set_value('barcode', '');
					frm.set_value('barcode', '');
					frm.refresh_field("barcode");
					frm.refresh_field("barcode");
					$('[data-fieldname="barcode"]').focus();
				}
			});
		}
    },

    scan_serial_no: function (frm) {

        if (frm.doc.scan_serial_no) {
            if (!frm.doc.dispatch_type) {
                frappe.msgprint('Please Select Dispatch Type');
                frm.set_value('scan_serial_no', '');
                frm.refresh_field('scan_serial_no');
            } else if (frm.doc.dispatch_type == 'Sales Order') {
                frappe.show_progress('Fething Data...', 10);
                frappe.call({
                    method: 'nj_features.nj_features.doctype.dispatch_security_checkpoints.dispatch_security_checkpoints.scan_serial_no_data_for_sales',
                    args: { serial_no: frm.doc.scan_serial_no },
                    callback: function (r) {
                        frappe.show_progress('Fething Data...', 90);
                        if (r.message) {
                            frm.set_value('scan_serial_no', '');
                            frm.refresh_field('scan_serial_no');
            
                            let exists = false;
                            if (frm.doc.dispatch_security_child_table) {
                                exists = frm.doc.dispatch_security_child_table.some(row => 
                                    row.serial_no === r.message.serial_no
                                );
                            }
            
                            if (!exists) {
                                let dispatch_security_child_table = {
                                    "serial_no": r.message.serial_no,
                                    "item_code": r.message.item_code || 'Not Available',
                                    "sales_invoice": r.message.sales_invoice || 'Not Available',
                                    "delivery_note": r.message.delivery_note || 'Not Available',
                                    "si_status": r.message.si_status || 'Not Available',
                                    "dn_status": r.message.dn_status || 'Not Available',
                                    "approved": r.message.approved,
                                    "sales_channel": r.message.sales_channel || 'Not Available',
                                    "customer_name": r.message.customer_name || 'Not Available',
                                    "courier_name": r.message.courier_name || 'Not Available',
                                    "tracking_id": r.message.tracking_id || 'Not Available',
                                    "email_id": r.message.email_id || 'Not Available'
                                };
                                frm.add_child("dispatch_security_child_table", dispatch_security_child_table);
                                frm.refresh_field("dispatch_security_child_table");
                            } else {
                                frm.set_value('scan_serial_no', '');
                                frm.refresh_field('scan_serial_no');
                            }
                        } else {
                            frm.set_value('scan_serial_no', '');
                            frm.refresh_field('scan_serial_no');
                        }
                        frappe.hide_progress();
                    },
                    error: function (err) {
                        frappe.hide_progress();
                        frappe.msgprint(__('Error occurred while scanning Serial No.', err));
                    }
                });
            }
            else if (frm.doc.dispatch_type == 'Purchase Return') {
                frappe.show_progress('Fething Data...', 10);
                frappe.call({
                    method: 'nj_features.nj_features.doctype.dispatch_security_checkpoints.dispatch_security_checkpoints.scan_serial_no_data_for_return',
                    args: { pr_name: frm.doc.purchase_reciept_name },
                    callback: function (r) {
                        frappe.show_progress('Fething Data...', 90);
                        if (r.message) {
                            frm.set_value('purchase_reciept_name', '');
                            frm.refresh_field('purchase_reciept_name');
                            
                            let dispatch_security_return_table = {
                                "purchase_invoice": r.message.purchase_invoice || 'Not Available',
                                "pi_status": r.message.pi_status || 'Not Available',
                                "purchase_receipt": r.message.purchase_receipt || 'Not Available',
                                "pr_status": r.message.pr_status || 'Not Available',
                            };
                            
                            frm.add_child("dispatch_security_return_table", dispatch_security_return_table);
                            frm.refresh_field("dispatch_security_return_table");
                        } else {
                            frm.set_value('purchase_reciept_name', '');
                            frm.refresh_field('purchase_reciept_name');
                        }
                        frappe.hide_progress();
                    },
                    error: function(err) {
                        frappe.hide_progress();
                        frappe.msgprint(__('Error occurred while scanning Serial No.', err));
                    }
                });
            }
            else if (frm.doc.dispatch_type == 'Transfer') {
                frappe.show_progress('Fething Data...', 10);
                frappe.call({
                    method: "nj_features.nj_features.doctype.dispatch_security_checkpoints.dispatch_security_checkpoints.get_item_code_details_for_transfer",
                    args: { ste_number: frm.doc.stock_entry_name },
                    callback: function(r) {
                        frappe.show_progress('Fething Data...', 90);
                        if (r.message) {
                            frm.set_value('stock_entry_name', '');
                            frm.refresh_field('stock_entry_name');
                            frm.clear_table("dispatch_security_stock_entry_table");
                            let errors = [];
                            let has_errors = false;
            
                            if (Array.isArray(r.message)) {
                                r.message.forEach(item => {
                                    if (item.error) {
                                        errors.push(item.error);
                                        has_errors = true;
                                    } else if (item.item_code) {
                                        let new_row = frm.add_child("dispatch_security_stock_entry_table");
                                        frappe.model.set_value(new_row.doctype, new_row.name, "stock_entry_name", item.parent);
                                        frappe.model.set_value(new_row.doctype, new_row.name, "item_code", item.item_code);
                                        frappe.model.set_value(new_row.doctype, new_row.name, "target_warehouse", item.t_warehouse);
                                        frappe.model.set_value(new_row.doctype, new_row.name, "source_warehouse", item.s_warehouse);
                                        frappe.model.set_value(new_row.doctype, new_row.name, "serial_no_quantity", item.qty);
                                        frappe.model.set_value(new_row.doctype, new_row.name, "serial_no", item.serial_no.replace('\n', ', '));
                                    }
                                });
                                frm.refresh_field("dispatch_security_stock_entry_table");
                            }
        
                            frm.doc.transfer_errors = errors;
        
                            if (has_errors) {
                                frm.doc.has_transfer_errors = true;
                                frappe.msgprint({
                                    title: __('Errors'),
                                    message: errors.join('<br>'),
                                    indicator: 'red'
                                });
                            } else { frm.doc.has_transfer_errors = false; }
                        }
                    },
                    error: function(err) {
                        frappe.hide_progress();
                        frappe.msgprint(__('Error occurred while scanning Serial No.', err));
                    }
                });
            }        
        }
    },
});