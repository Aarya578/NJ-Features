frappe.ui.form.on('Laptop Box', {
    onload: function() {
        $('[data-fieldname="nj_barcode"]').focus();
    },

    nj_barcode: function(frm) {
		handleScannerInput(frm, 'nj_barcode');
		if (frm.doc.nj_barcode) { 
			frappe.call({
				method: "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
				args: {  search_value: frm.doc.nj_barcode, raise_exp: true },
				callback: function(r) {
					if (r.message) {
						if (r.message.serial_no) {
							frm.set_value('barcode', r.message.serial_no);
						} else if (r.message.scan) {
							frappe.msgprint("Please Scan the Serial No.");
							frm.set_value('nj_barcode', '');
							frm.set_value('barcode', '');
						}
						frm.refresh_field("nj_barcode");
						frm.refresh_field("barcode");
						$('[data-fieldname="nj_barcode"]').focus();
					}
				},
				error: function(r) {
					frappe.msgprint("Error while scanning Serial No.");
					frm.set_value('barcode', '');
					frm.set_value('nj_barcode', '');
					frm.refresh_field("barcode");
					frm.refresh_field("nj_barcode");
					$('[data-fieldname="nj_barcode"]').focus();
				}
			});
        } else {
            frm.set_value('barcode', '');
        }
    },

    nj_adaptor_barcode: function(frm) {
		handleScannerInput(frm, 'nj_adaptor_barcode');
		if (frm.doc.nj_adaptor_barcode) { 
			frappe.call({
				method: "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
				args: {  search_value: frm.doc.nj_adaptor_barcode, raise_exp: false },
				callback: function(r) {
					if (r.message) {
						if (r.message.serial_no) {
							frm.set_value('adapter_serial_no', r.message.serial_no);
						} else if (r.message.scan) {
							frappe.msgprint("Please Scan the Serial No.");
							frm.set_value('nj_adaptor_barcode', '');
							frm.set_value('adapter_serial_no', '');
						}
						frm.refresh_field("nj_adaptor_barcode");
						frm.refresh_field("adapter_serial_no");
						$('[data-fieldname="nj_adaptor_barcode"]').focus();
					}
				},
				error: function(r) {
					frappe.msgprint("Error while scanning Serial No.");
					frm.set_value('adapter_serial_no', '');
					frm.set_value('nj_adaptor_barcode', '');
					frm.refresh_field("adapter_serial_no");
					frm.refresh_field("nj_adaptor_barcode");
					$('[data-fieldname="nj_adaptor_barcode"]').focus();
				}
			});
		}
    },

    barcode: function(frm) {
        
        if (frm.doc.barcode) {
            frappe.call({
                method: 'nj_features.nj_features.api.qr_code.generate_and_save_qrcode',
                args: { data: frm.doc.barcode },
                callback: function(r) {
                    console.log("saved qr code",r);
                },
                error: function(r) {
                    frappe.msgprint("Error while generating QR Code.", r);
                }
            });
            
            frappe.call({
                method: "frappe.client.get",
                args: {
                    doctype: "Serial No",
                    name: frm.doc.barcode, 
                },
                callback: function(r) {
                    if (r.message) {
                        $('.primary-action').show();
                        let serial_no_data = r.message;

                        frm.set_value("brand", serial_no_data.brand);  
                        frm.set_value("model", serial_no_data.model);
                        frm.set_value("bios_serial_no", serial_no_data.bios_serial_no);  
                        frm.set_value("warehouse", serial_no_data.warehouse);  
                        frm.set_value("item_code", serial_no_data.item_code);  

                        if (serial_no_data.is_encrypted == 1) {
                            frm.set_value("qr_code_mapping", serial_no_data.qr_code_mapping);
                        }

                        frappe.call({
                            method: "frappe.client.get",
                            args: {
                                doctype: "Item",
                                name: serial_no_data.item_code,  
                            },
                            callback: function(item_data) {
                                if (item_data.message) {
                                    let item = item_data.message;

                                    if (item.attributes && item.attributes.length > 0) {
                                        let processor_type = '';
                                        let ram_capacity = '';
                                        let storage_capacity = '';

                                        item.attributes.forEach(function(attr) {
                                            if (attr.attribute == "Processor Type") {
                                                processor_type = attr.attribute_value;
                                            }
                                            if (attr.attribute == "RAM Capacity" || attr.attribute == "RAM") {
                                                ram_capacity = attr.attribute_value;
                                            }
                                            if (attr.attribute == "Storage Capacity") {
                                                storage_capacity = attr.attribute_value;
                                            }
                                        });

                                        frm.set_value("processor_type", processor_type);
                                        frm.set_value("ram_capacity", ram_capacity);
                                        frm.set_value("storage_capacity", storage_capacity);
                                    } else {
                                        frappe.throw("No attributes found in the Item Variant Attribute table.");
                                    }
                                } else {
                                    frappe.throw("Item not found for the scanned Serial No.");
                                }
                            }
                        });
                    } else {
                        frm.set_value("barcode", null);
                        frappe.throw(`Serial No <b>'${frm.doc.barcode}'</b> not found. Please select an existing Serial No.`);
                    }
                },
                error: function() {
                    $('.primary-action').hide();
                    frappe.throw("Error fetching data for the barcode.");
                }
            });
        }
    },

    warehouse: function(frm) {
		frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "work_warehouse", function(r) {
			if (!r.work_warehouse) {
				frappe.msgprint(__('Please Set Work Warehouse in Employee Profile: <b>{0}</b>.', [frappe.session.user]));
			}
			if (r.work_warehouse != frm.doc.warehouse) {
				
				let dialog = new frappe.ui.Dialog({
					title: "Confirm Stock Transfer",
					fields: [
						{
							fieldtype: "HTML",
							fieldname: "message",
							options: `Do you want to transfer stock to your Work Warehouse: ${r.work_warehouse}?`
						}
					],
					static:true,
					primary_action_label: "Yes, Transfer", 
					primary_action: function() {
						let material_transfer_items = [{
							'serial_no': frm.doc.barcode,
							'item_code': frm.doc.item_code,
							't_warehouse': r.work_warehouse,
							's_warehouse': frm.doc.warehouse
						}];
		
						let data = {
							"doctype": frm.doc.doctype,
							"t_warehouse": r.work_warehouse,
							"stock_entry_type": "Material Transfer",
							"reference_serial_no": frm.doc.barcode,
							"material_transfer_items": material_transfer_items
						}

						frappe.call({
							method: 'nj_lib.utils.stock_entry.stock_entry_using_nj_lib',
							args: { 'data': JSON.stringify(data) },
							freeze: true,
                            freeze_message: `<div style="text-align: center;">
								<i class="fa fa-spinner fa-spin" style="font-size: 24px;"></i> 
								<br>Transfering Stock... Please Wait
							</div>`,
							error: function(err) { console.log(err); }
						});

						dialog.hide();
                    },
                    secondary_action_label: "Cancel",
                    secondary_action: function() {
                        $('.primary-action').hide()
                        dialog.hide();
                        $("button[data-original-title=Print]").hide();
                    }
                });
                dialog.show();
			} else { $("button[data-original-title=Print]").show(); }
		})
	},

    before_save: async function(frm) {
        if (frm.doc.barcode) {
            frappe.validated=true
            let serial_item_group = await frappe.db.get_value('Serial No', {'name': frm.doc.barcode}, 'item_group');
            
            if(serial_item_group.message && serial_item_group.message.item_group && serial_item_group.message.item_group=='Laptops' || serial_item_group.message.item_group=='Chromebooks') {
                console.log("adapter serial no",frm.doc.adapter_serial_no)
                if(!frm.doc.adapter_serial_no) {
                    frappe.validated=false
                    frappe.throw("Please enter Adapter Serial No");
                }
            } else { return; }
            
            await frappe.call({
                method:'nj_features.nj_features.api.qr_code.adapter_repacked_serial_no',
                args: { "nj_serial_no": frm.doc.barcode },
                callback: function(r) {
                    if (r.message) {
                        if(r.message!=frm.doc.adapter_serial_no) {
                            frappe.validated=false
                            frappe.throw("Repacked Adapter Serial No: '" + r.message + "' does not match with the scanned Serial No");
                        }
                    }
                }
            })
        }
    }
});