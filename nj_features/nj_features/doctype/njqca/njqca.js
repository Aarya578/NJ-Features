// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('NJQCA', {
    onload: function(frm) {
        if (frm.doc.docstatus == 0) {
            frm.events.serial_no(frm);
        }
    },
    
    refresh: function(frm) {
        
        $('.col-lg-2.layout-side-section').hide();
        $(frm.layout.wrapper).find('.form-message.red').remove();
        frm.get_field('njqca_laptop_ram').grid.cannot_add_rows = true;
        frm.get_field('njqca_laptop_storage').grid.cannot_add_rows = true;
        frm.get_field('njqca_item_component').grid.cannot_add_rows = true;
        frm.get_field('njqca_result_parameters').grid.cannot_add_rows = true;
        frm.get_field('njqca_laptop_processors').grid.cannot_add_rows = true;
        frm.refresh_field('njqca_laptop_ram');
        frm.refresh_field('njqca_laptop_storage');
        frm.refresh_field('njqca_item_component');
        frm.refresh_field('njqca_result_parameters');
        frm.refresh_field('njqca_laptop_processors');
        if (frm.doc.docstatus == 0) {
            
            frm.events.power_on();
            handleScannerInput(frm, 'serial_no');

            if (cur_frm.doc.error_message != '') {
                cur_frm.set_df_property('error_section_section', 'hidden', 0);
            }

            frm.set_query("inspection_type", () => {
                return { filters: { "active": 1 } };
            });
            
            frm.set_query('manual_repack_item_code', function(r) {
                var filters = {
                    disabled: 0, has_variants: 0,
                    brand: frm.doc.brand, item_group: frm.doc.item_group
                };
                
                if (frm.doc.model) { filters.item_model = frm.doc.model; }
                if (frm.doc.item_template) { filters.variant_of = frm.doc.item_template; }
                
                return { filters: filters };
            });

            frm.set_query("part_item_code", "njqca_item_component", function (doc, cdt, cdn) {
                const row = locals[cdt][cdn];
                return {
                    filters: {
                        item_group: row.item_group,
                        disabled: 0, has_variants: 0,
                    }
                }
            })
            
            frm.set_query("calculated_item_code", "njqca_laptop_processors", function (doc, cdt, cdn) {
                const row = locals[cdt][cdn];
                return {
                    filters: {
                        item_group: row.item_group,
                        disabled: 0, has_variants: 0
                    }
                }
            })

            frm.set_query("calculated_item_code", "njqca_laptop_ram", function (doc, cdt, cdn) {
                const row = locals[cdt][cdn];
                return {
                    filters: {
                        item_group: row.item_group,
                        disabled: 0, has_variants: 0
                    }
                }
            })

            frm.set_query("calculated_item_code", "njqca_laptop_storage", function (doc, cdt, cdn) {
                const row = locals[cdt][cdn];
                return {
                    filters: {
                        item_group: row.item_group,
                        disabled: 0, has_variants: 0
                    }
                }
            })

            // frm.set_query("calculated_item_code", "njqca_display", function (doc, cdt, cdn) {
            //     const row = locals[cdt][cdn];
            //     return {
            //         filters: {
            //             item_group: row.item_group,
            //             disabled: 0, has_variants: 0
            //         }
            //     }
            // })

            // frm.set_query("calculated_item_code", "njqca_adapter", function (doc, cdt, cdn) {
            //     const row = locals[cdt][cdn];
            //     return {
            //         filters: {
            //             item_group: row.item_group,
            //             disabled: 0, has_variants: 0
            //         }
            //     }
            // })
        }
    },

	onload_post_render: function(frm) {
        if (cur_frm.doc.error_message == "") {
            $(frm.layout.wrapper).find('.form-message.red').remove()
        } else {
            cur_frm.set_df_property('error_section_section', 'hidden', 0)
        }

        if (frm.doc.docstatus == 0) {

            if (!frm.doc.manual_repack_item_code && frm.doc.item_code) {
                frm.set_value('manual_repack_item_code', frm.doc.item_code);
                frm.refresh_field('manual_repack_item_code');
            }

            if (!frm.doc.inspection_type) {
                frappe.call({
                    method: 'nj_features.nj_features.doctype.njqca.njqca.get_inspection_type',
                    callback: function(r) {
                        frm.set_value('inspection_type', r.message);
                        cur_frm.refresh_field('inspection_type');
                    }
                })
            }
            
            get_model(frm.doc.manufacturer_model);
        }
	},
    
    validate: function(frm) {
        var requiredFields = ['serial_no', 'item_group', 'warehouse', 'brand', 'manufacturer_model'];
        var errorMessages = [];
        var dbError = [];
        for (var i = 0; i < requiredFields.length; i++) {
            var fieldname = requiredFields[i];
            if (!frm.doc[fieldname]) {
                var fieldLabel = frm.fields_dict[fieldname] ? frm.fields_dict[fieldname].df.label : fieldname;
                if (frm.fields_dict[fieldname]) {
                    frm.fields_dict[fieldname].$wrapper.addClass('has-error');
                }
                errorMessages.push(fieldLabel);
            }
        }
    
        if ($(frm.layout.wrapper).find('.form-message.red').length > 1) {
            $(frm.layout.wrapper).find('.form-message.red').last().remove();
        }
        
        var openedUrls = JSON.parse(localStorage.getItem('openedUrls')) || [];
        
        frappe.call({
            method: 'nj_features.nj_features.doctype.njqca.njqca.after_save_njqca',
            args: { 'docname': cur_frm.doc.name },
            callback: function(r) {
                if (r && r.message) {
                    let urlToCompare = r.message.njpulse_url.replace(/\/$/, '');
                    let pwd_njpulse_url = urlToCompare;

                    if (urlToCompare && !openedUrls.includes(urlToCompare)) {
                        openedUrls.push(urlToCompare);
                        localStorage.setItem('openedUrls', JSON.stringify(openedUrls));
    
                        if (frm.doc.pwd && r.message.base_url) {
                            pwd_njpulse_url = r.message.base_url + "api/authenticate?usr=" + frm.doc.created + "&pwd=" + frm.doc.pwd + "&encrypted_pwd=True&doctype_url=qi/" + r.message.qi_name;
                        }
    
                        window.open(pwd_njpulse_url, "_blank");
                    }

                    if (r.message.qi_name) {
                        frm.set_value('qi_name', r.message.qi_name);
                        frm.refresh_field('qi_name');

                        var $qiNameWrapper = frm.fields_dict['qi_name'].$wrapper;

                        $qiNameWrapper.closest('.control-input-wrapper').css('border-color', 'rgba(173, 216, 230, 0.5)');

                        $qiNameWrapper.css('cursor', 'pointer');
                        $qiNameWrapper.attr('title', 'Click to open ' + frm.doc.qi_name);

                        $qiNameWrapper.on('click', function() {
                            window.open(pwd_njpulse_url, '_blank');
                        });

                        $qiNameWrapper.css({
                            'user-select': 'none',
                            'pointer-events': 'auto'
                        });
                    }

                    if (r.message.msg_pnt) {
                        frappe.show_alert({
                            message: r.message.msg_pnt,
                            indicator: 'blue'
                        }, 10);
                    }

                } else {  console.error('QI name is not defined'); }
            }
        });
    },

    // before_submit: function(frm) {

    //     return new Promise((resolve, reject) => {
    //         let tablesToCheck = [ c ];
            
    //         let mismatches = [];
    //         let i = 0;
    
    //         tablesToCheck.forEach((table) => {
    //             frm.doc[table].forEach((row) => {
    //                 if (!row.calculated_item_code || row.calculated_item_code.trim() === "") {
    //                     mismatches.push(`<br><b>${++i}.</b> The calculated item code is missing for an entry in <b>${table}</b>.`);
    //                 } else if (row.calculated_item_code !== row.fetched_item_code) {
    //                     mismatches.push(`<br><b>${++i}.</b> The <b>fetched item code: ${row.fetched_item_code}</b> is different from the <b>calculated item code: ${row.calculated_item_code}</b>.`);
    //                 }
    //             });
    //         });
    
    //         if (mismatches.length > 0) {
    //             let mismatchMessage = mismatches.join('<br>');
    //             frappe.confirm(
    //                 `<b>The following issues were found:</b><br><br>${mismatchMessage}<br><br>Do you agree to change all mismatched or missing item codes?`,
    //                 () => { resolve(); },
    //                 () => { reject(); }
    //             );
    //         } else { resolve(); }

    //     }).then(() => {
    //         if (frm.doc.automated_repack_item != frm.doc.repack_item_code) {
    //             frappe.validated = false; 
    //             frappe.confirm(
    //                 `<b>Automated Item Code: ${frm.doc.automated_repack_item}</b> <br> <b>Repack Item Code: ${frm.doc.repack_item_code}</b> are not the same.<br>Are you sure you want to Submit?`, 
    //                 () => {
    //                     frappe.confirm( "Are you sure you want to proceed with submitting this form with the current item codes?",
    //                         () => {
    //                             frappe.validated = true;
    //                             frm.save('Submit');
    //                         },
    //                         () => { frm.set_value('repack_item_code', ''); }
    //                     );
    //                 },
    //                 () => { frm.set_value('repack_item_code', ''); }
    //             );
    //         }
    
    //         return false;
    //     });
    // },

    power_on: function() {
        const isYes = cur_frm.doc.power_on === "Yes";
        const isNone = cur_frm.doc.power_on === "";
        cur_frm.set_df_property('iqc_section', 'hidden', !isYes);
        cur_frm.set_df_property('section_break_6sw2s', 'hidden', isNone || 0);
        cur_frm.set_df_property('section_break_56eed', 'hidden', !isYes);
        cur_frm.set_df_property('warehouse', 'hidden', !isYes);
        cur_frm.set_df_property('manual_repack_item_code', 'hidden', !isYes);
        cur_frm.set_df_property('model', 'hidden', !isYes);
    },

    serial_no: function(frm) {
		handleScannerInput(frm, 'serial_no');
        if ((cur_frm.doc.serial_no || cur_frm.doc.bios_serialno) && cur_frm.doc.power_on == 'Yes') {
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_info_from_serial_no',
                args: {'doc': cur_frm.doc},
                callback: function(r) {
                    console.log('r', r);
                    Object.keys(r.message).forEach(field => {
                        frm.set_value(field, r.message[field]);
                        cur_frm.refresh_field(field);
                    });

                    if(!frappe.user.has_role("IQC Manager") && frm.doc.serial_no && frm.doc.serial_no.trim() !== ''){
                        cur_frm.set_df_property('serial_no', 'read_only', 1);
                    }
                }
            });
        }
    },

    warehouse: function(frm) {
    if (frm.doc.warehouse && frm.doc.serial_no) {
        let ware = cur_frm.doc.warehouse;
        
        frappe.db.get_value('Employee', {'user_id': frappe.session.user_email, 'status': 'Active'}, 'work_warehouse', function(r) {
            const workWarehouse = r.work_warehouse;

            if (!workWarehouse) {
                frappe.msgprint(`Work Warehouse is not set for employee: ${frappe.session.user_email}. Please mail to <b>IT Infra Team</b> at <strong><a href="mailto:itinfra@newjaisa.com">itinfra@newjaisa.com</a></strong> to create an employee.`);
            } else if (workWarehouse != ware) {
                let dialog = new frappe.ui.Dialog({
                    title: "Confirm Stock Transfer",
                    fields: [
                        {
                            fieldtype: "HTML",
                            fieldname: "message",
                            options: `Do you want to transfer stock to your Work Warehouse: ${workWarehouse}?`
                        },
                        {
                            fieldtype: "Data",
                            fieldname: "serial_num",
                            label: "Scan Serial No",
                            options: "Barcode",
                            change: function() {
                                handleScannerInput(dialog,'serial_num');
                            }
                        }
                                           
                    ],
                    static: true,
                    primary_action_label: "Yes, Transfer", 
                    primary_action: function() {
                        let scannedSerialNo = dialog.get_value("serial_num");
                        if (scannedSerialNo !== frm.doc.serial_no) {
                            frappe.msgprint({
                                title: 'Serial Number Mismatch',
                                message: `The scanned serial number ${scannedSerialNo} does not match the available serial number ${frm.doc.serial_no}. Please try again.`,
                            });
                            dialog.hide();
                            return;
                        }

                        let material_transfer_items = [{
                            'serial_no': frm.doc.serial_no,
                            'item_code': frm.doc.item_code,
                            't_warehouse': workWarehouse,
                            's_warehouse': frm.doc.warehouse
                        }];
                        
                        let data = {
                            "doctype": frm.doc.doctype,
                            "serial_no": frm.doc.serial_no,
                            "series": "NJ-STE-NJQCA-",
                            "t_warehouse": workWarehouse,
                            "stock_entry_type": "Material Transfer",
                            "reference_serial_no": frm.doc.serial_no,
                            "material_transfer_items": material_transfer_items,
                        };
                
                        frappe.call({
                            method: 'nj_lib.utils.stock_entry.stock_entry_using_nj_lib',
                            args: { 'data': JSON.stringify(data) },
                            freeze: true,
                            freeze_message: `<div style="text-align: center;">
                                <i class="fa fa-spinner fa-spin" style="font-size: 24px;"></i> 
                                <br>Transferring Stock... Please Wait
                            </div>`,
                            callback: function(response) {
                                frm.set_value('warehouse', workWarehouse);
                                frm.refresh_field('warehouse');
                            },
                            error: function(err) { console.log(err); }
                        });

                        dialog.hide();
                    },
                    secondary_action_label: "Cancel",
                    secondary_action: function() {
                        $('.primary-action').hide();
                        dialog.hide();
                    }
                });

                dialog.show();
            }
        });
    }},
    
    model: function(frm) {
        var selectedModel = frm.doc.model;
        var selectedBrand = frm.doc.brand;
        var selectedItemGroup = frm.doc.item_group;

        if (selectedModel && selectedBrand && cur_frm.doc.serial_no) {
            
            frappe.db.get_value('Serial No', {'serial_no': cur_frm.doc.serial_no,}, 'model', function(r) {

                if (!r.model) {
                    frappe.throw(`Model is not filled in Serial no: <b>${cur_frm.doc.serial_no}</b>. Please contact the NPD Team.`);
                }

                if(selectedModel && selectedModel != r.model){
                    frappe.confirm('Model in SerialNo and NJQCA are Different. Do you want to change the part list?',
                        () => {
                            frappe.call({
                                method: 'nj_features.nj_features.doctype.njqca.njqca.model_change_for_serial_no',
                                args: {
                                    'newmodel': cur_frm.doc.model,
                                    'serial_no': cur_frm.doc.serial_no
                                },
                                callback: function(r) {
                                    if(r.message.status === 'success'){
                                        var base_url = frappe.urllib.get_base_url();
                                        var serial_no_link = `${base_url}/app/serial-no/${cur_frm.doc.serial_no}`;
                                        frappe.msgprint(`Part List and Model is updated for Serial No : <strong><a href='${serial_no_link}'>${cur_frm.doc.serial_no}</a></strong> has been submitted successfully.`);
                                    }
                                }
                            });
                        }, () => { $('.primary-action').hide() })
                }
            })

        }
        get_item_template(selectedModel, selectedBrand, selectedItemGroup)

        frm.refresh_field('item_template');
    },

    item_template: function(frm) {
        if (frm.doc.item_template && frm.doc.docstatus == 0 && frm.doc.power_on == 'Yes') {
            processItemTemplate(frm);
        }
    }
});

function processItemTemplate(frm) {
    if (frm.doc.njqca_item_component && frm.doc.power_on == 'Yes') {
        frappe.call({
            method: 'nj_features.nj_features.doctype.njqca.njqca.get_part_mapping',
            args: {'doc': frm.doc},
            callback: function (r) {
                if (r.message.error) {
                    frappe.show_alert({
                        message:__("<b>Error " + r.message.error + "</b>"),
                        indicator:'red'
                    }, 10);
                } 

                if (typeof r.message === 'string') {
                    try {
                        r.message = JSON.parse(r.message);
                    } catch (e) {
                        console.error("Failed to parse message:", e);
                    }
                }

                if (r.message) {
                    // if (r.message.data_attr !== undefined && r.message.data_attr !== null) {
                    //     frm.set_value('data_attr', r.message.data_attr);
                    // }
                
                    if (r.message.repack_item_code !== undefined && r.message.repack_item_code !== null) {
                        frm.set_value('repack_item_code', r.message.repack_item_code);
                        frm.set_value('manual_repack_item_code', r.message.repack_item_code);
                    }
                    frm.refresh_fields(['repack_item_code', 'manual_repack_item_code', 'data_attr']);

                    const partData = r.message.part_data;

                    frm.doc.njqca_item_component.forEach(row => {
                        const part = partData.find(p => p.name === row.name && p.response !== 'error');
                        if (part) {
                            frappe.model.set_value(row.doctype, row.name, 'part_item_code', part.part_item_code);
                            frappe.model.set_value(row.doctype, row.name, 'attr_data', JSON.stringify(part.attr_data));
                        }
                    });
                }
                
                if (r.message.part_data) {
                    
                    const partData = r.message.part_data;
                    frm.clear_table("njqca_laptop_ram");
                    frm.clear_table("njqca_laptop_processors");
                    frm.clear_table("njqca_laptop_storage")
                    partData.forEach(row => {

                        if (row.item_group === "Laptop RAM") {
                            let newRow = frappe.model.add_child(frm.doc, "njqca_laptop_ram");
                            
                            const child_table_fieldname = 'njqca_laptop_ram';
                            const grid = frm.fields_dict[child_table_fieldname].grid;
                            set_options_for_attribute_fields_in_child(frm, grid);

                            frappe.model.set_value(newRow.doctype, newRow.name, 'ram_type', row.attr_data["RAM Type"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'ram_capacity', row.attr_data["RAM Capacity"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'ram_speed', row.attr_data["RAM Speed"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'grade', row.attr_data["Grade"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'fetched_item_code', row.part_item_code);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', row.item_group);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_template', row.item_template);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'reference_row_name', row.name);
                        }else if(row.item_group === "Laptop Processors"){
                            let newRow = frappe.model.add_child(frm.doc, "njqca_laptop_processors");
                            const child_table_fieldname = 'njqca_laptop_processors';
                            const grid = frm.fields_dict[child_table_fieldname].grid;
                            set_options_for_attribute_fields_in_child(frm, grid);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', row.item_group);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'fetched_item_code', row.part_item_code);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_template', row.item_template);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'processor_type', row.attr_data["Processor Type"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'grade', row.attr_data["Grade"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'reference_row_name', row.name);
                        }else if(row.item_group === "LAPTOP STORAGE"){
                            let newRow = frappe.model.add_child(frm.doc, "njqca_laptop_storage");
                            const child_table_fieldname = 'njqca_laptop_storage';
                            const grid = frm.fields_dict[child_table_fieldname].grid;
                            set_options_for_attribute_fields_in_child(frm, grid);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', row.item_group);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'fetched_item_code', row.part_item_code);        
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_template', row.item_template);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'storage_type', row.attr_data["Storage Type"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'storage_capacity', row.attr_data["Storage Capacity"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'storage_interface', row.attr_data["Storage Interface"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'storage_length', row.attr_data["Storage Length"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'grade', row.attr_data["Grade"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'reference_row_name', row.name);
                        }
                    });

                    frm.refresh_field("njqca_laptop_ram");
                    frm.refresh_field("njqca_laptop_processors");
                    frm.refresh_field("njqca_laptop_storage");
                }
                frm.refresh_field('njqca_item_component');
            }
        });
    }
}

function get_item_template(model, brand, item_group) {
    frappe.call({
        method: 'nj_features.nj_features.doctype.njqca.njqca.get_njqca_item_template',
        args: {
            'model': model,
            'brand': brand,
            'item_group': item_group
        },
        callback: function(r) {
            if (r.message) {
                var itemTemplates = r.message.item_template ? r.message.item_template.map(item => item.name) : [];

                if (Array.isArray(itemTemplates) && itemTemplates.length > 0) {
                    cur_frm.set_value('item_template', '');
                    if (itemTemplates.length == 1) {
                        cur_frm.set_value('item_template', itemTemplates[0]);
                        cur_frm.set_df_property('item_template', 'read_only', 1);
                        cur_frm.refresh_field('item_template');
                        $('[data-fieldname="item_template"]').closest('.control-input-wrapper').css({
                            'border-radius': '0.25rem',
                            'border': '2px solid rgba(173, 216, 230, 0.5)' 
                        });

                        var selectedOption = itemTemplates[0];
                        var wizardList = r.message.wizard_list || [];

                        if (wizardList.includes(selectedOption)) {
                            $('[data-fieldname="item_template"]').closest('.control-input-wrapper').css('border-color', 'green');
                        } else {
                            $('[data-fieldname="item_template"]').closest('.control-input-wrapper').css('border-color', 'red');
                        }

                    } else {
                        cur_frm.set_df_property('item_template', 'read_only', 0);
                        var wizardList = r.message.wizard_list || [];
                        cur_frm.set_df_property('item_template', 'options', itemTemplates);
                        cur_frm.refresh_field('item_template');
                        $('[data-fieldname="item_template"]').focus().closest('.control-input-wrapper').css({
                            'border-radius': '0.25rem',
                            'border': '2px solid rgba(173, 216, 230, 0.5)'  
                        });

                        cur_frm.fields_dict.item_template.$input.on('change', function() {
                            var selectedOption = $(this).val();
                            $('[data-fieldname="item_template"]').closest('.control-input-wrapper').css('border-color', 'rgba(173, 216, 230, 0.5)');
                            if (wizardList.includes(selectedOption)) {
                                $(this).closest('.control-input-wrapper').css('border-color', 'green');
                            } else {
                                $(this).closest('.control-input-wrapper').css('border-color', 'red');
                            }
                        });

                        frappe.show_alert({
                            message: __('Select Item Template'),
                            indicator: 'green'
                        });
                    }

                } else {
                    cur_frm.set_value('item_template', '');
                    cur_frm.set_df_property('item_template', 'options', []);
                    cur_frm.refresh_field('item_template');
                    $('[data-fieldname="item_template"]').closest('.control-input-wrapper').css({
                        'border-radius': '0.25rem',
                        'border': '2px solid red'
                    });
                    
                    frappe.msgprint(__("Item Template is not found using <b>Brand: {0}</b>,<br><b>Model: {1}</b>,<br><b>Item Group: {2}</b>.<br>Please contact <b>NPD Team.</b>", 
                        [brand, model, item_group]));
                }
            }
        }
    });
}

function get_model(manufacturer_model) {
    console.log("function is triggered==========609=======");
    
    
    frappe.call({
        method: 'nj_features.nj_features.doctype.njqca.njqca.get_model',
        args: { 'manufacturer_model': manufacturer_model },
        callback: function(r) {
            if (r.message) {
                var model_list = r.message;
                if (Array.isArray(model_list) && model_list.length > 0) {
                    if (model_list.length === 1) {
                        cur_frm.set_value('model', model_list[0].model);
                        cur_frm.set_df_property('model', 'read_only', 1);
                    } else {
                        var options = model_list.map(function(item) {
                            return item.model;
                        }).join('\n');
                        cur_frm.set_df_property('model', 'options', options);
                        $('[data-fieldname="model"]').focus().closest('.control-input').css({
                            'border-radius': '0.25rem',
                            'border': '2px solid rgba(173, 216, 230, 0.5)'
                        });
                        
                        frappe.show_alert({
                            message: __('Select Model'),
                            indicator: 'green'
                        });
                    }
                    cur_frm.events.model(cur_frm);
                }
                cur_frm.refresh_field('model');
            }
        }
    });
}

// frappe.ui.form.on('NJQCA Adaptor', {
//     njqca_adaptor_add: function(frm, cdt, cdn) {

//         const child_table_fieldname = 'njqca_adaptor';
//         const grid = frm.fields_dict[child_table_fieldname].grid;

//         set_options_for_attribute_fields_in_child(frm, grid);
//     },
//     brand: function(frm, cdt, cdn) {
//         const child = locals[cdt][cdn];  
//         generateAdaptorItemCode(frm, cdt, cdn, child); 
//     },
//     wattage_capacity: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateAdaptorItemCode(frm, cdt, cdn, child);
//     },
//     adapter_pin_type: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateAdaptorItemCode(frm, cdt, cdn, child);
//     },
//     grade: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateAdaptorItemCode(frm, cdt, cdn, child);
//     }
// });

// frappe.ui.form.on('NJQCA Laptop Ram', {

//     njqca_laptop_ram_add: function(frm, cdt, cdn) {

//         const child_table_fieldname = 'njqca_laptop_ram';
//         const grid = frm.fields_dict[child_table_fieldname].grid;

//         set_options_for_attribute_fields_in_child(frm, grid);
//     }, 

//     ram_type: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateRamItemCode(frm, cdt, cdn, child); 
//     },

//     ram_capacity: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateRamItemCode(frm, cdt, cdn, child); 
//     },
//     ram_speed: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateRamItemCode(frm, cdt, cdn, child); 
//     },
//     grade: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateRamItemCode(frm, cdt, cdn, child); 
//     },
// });

// frappe.ui.form.on('NJQCA Display', {

//     njqca_display_add: function(frm, cdt, cdn) {

//         const child_table_fieldname = 'njqca_display';
//         const grid = frm.fields_dict[child_table_fieldname].grid;

//         set_options_for_attribute_fields_in_child(frm, grid);
//     },

//     model: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateDisplayItemCode(frm, cdt, cdn, child); 
//     },
//     display_tech: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateDisplayItemCode(frm, cdt, cdn, child); 
//     },
//     display_pin_type: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateDisplayItemCode(frm, cdt, cdn, child); 
//     },  
    
//     display_size: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateDisplayItemCode(frm, cdt, cdn, child); 
//     },  
    
//     resolution: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateDisplayItemCode(frm, cdt, cdn, child); 
//     },  
    
//     thickness: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateDisplayItemCode(frm, cdt, cdn, child); 
//     },  
    
//     display_bracket: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateDisplayItemCode(frm, cdt, cdn, child); 
//     },  
    
//     grade: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateDisplayItemCode(frm, cdt, cdn, child); 
//     },
// })

// frappe.ui.form.on('NJQCA PROCESSOR', {
//     njqca_laptop_processors_add: function(frm, cdt, cdn) {
//         const child_table_fieldname = 'njqca_laptop_processors';
//         const grid = frm.fields_dict[child_table_fieldname].grid;
        
//         set_options_for_attribute_fields_in_child(frm, grid);
//     },
//     processor_type: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateProcessorItemCode(frm, cdt, cdn, child); 
//     },
//     grade: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateProcessorItemCode(frm, cdt, cdn, child); 
//     },
// });

// frappe.ui.form.on('NJQCA Laptop Storage', {
//     njqca_laptop_storage_add: function(frm, cdt, cdn) {

//         const child_table_fieldname = 'njqca_laptop_storage';
//         const grid = frm.fields_dict[child_table_fieldname].grid;
        
//         set_options_for_attribute_fields_in_child(frm, grid);
//     },
//     storage_type: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateStorageItemCode(frm, cdt, cdn, child); 
//     },
//     storage_capacity: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateStorageItemCode(frm, cdt, cdn, child); 
//     },
//     storage_interface: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateStorageItemCode(frm, cdt, cdn, child); 
//     },
//     storage_length: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateStorageItemCode(frm, cdt, cdn, child); 
//     },
//     grade: function(frm, cdt, cdn){
//         const child = locals[cdt][cdn];  
//         generateStorageItemCode(frm, cdt, cdn, child); 
//     },
// });

function generateAdaptorItemCode(frm, cdt, cdn, child) {
    const item_templates = child.item_template;
    const row_name = child.reference_row_name;

    let Brand = child.brand;
    let waltage = child.wattage_capacity;
    let adaptor_pins = child.adapter_pin_type;
    let grade = child.grade;

    const adaptor_properties = [{
        "Brand": Brand, "Wattage Capacity": waltage,
        "Adapter Pin Type": adaptor_pins, "Grade": grade
    }];

    if (Brand && waltage && adaptor_pins && grade) {
        frappe.call({
            method: "nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value",
            args: {
                item_template: item_templates,
                args: adaptor_properties
            },
            callback: function(r) {
                if (r.message) {
                    if (r.message.error) {
                        frappe.utils.play_sound("error");
                        var errorMessageString = 'Item code not found: ' + r.message.error;
                        var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                        $(frm.layout.wrapper).find('.form-message.red').remove();
                        $(frm.layout.wrapper).prepend(errorDiv);
                        frm.set_df_property('error_section_section', 'hidden', 0);
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', '');
                    } else {
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
                        frm.set_df_property('error_section_section', 'hidden', 1);
                    }
                }
            }
        });
    } else {
        frappe.utils.play_sound("error");
        var missingFieldsMessage = 'Please fill all the required fields in Adaptor.';
        var errorDiv = $('<div class="form-message red"></div>').html(missingFieldsMessage);
        $(frm.layout.wrapper).find('.form-message.red').remove();
        $(frm.layout.wrapper).prepend(errorDiv);
        frm.set_df_property('error_section_section', 'hidden', 0);
    }
}

function generateStorageItemCode(frm, cdt, cdn, child){
    const item_template = child.item_template;
    const row_name = child.reference_row_name;

    let storage_type = child.storage_type;
    let storage_capacity = child.storage_capacity;
    let storage_interface = child.storage_interface;
    let storage_length = child.storage_length;
    let grade = child.grade;

    const storage_properties = [{
        "Storage Type": storage_type,
        "Storage Interface": storage_interface,
        "Storage Capacity": storage_capacity,
        "Storage Length": storage_length,
        "Grade": grade
    }];

    if (storage_type && storage_capacity && storage_interface && storage_length && grade) {
        frappe.call({
            method: "nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value",
            args: {
                item_template: item_template,
                args: storage_properties
            },
            callback: function(r) {
                if (r.message) {
                    if (r.message.error) {
                        frappe.utils.play_sound("error");
                        var errorMessageString = 'Item code not found: ' + r.message.error;
                        var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                        $(frm.layout.wrapper).find('.form-message.red').remove();
                        $(frm.layout.wrapper).prepend(errorDiv);
                        frm.set_df_property('error_section_section', 'hidden', 0);
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', '');
                    } else {
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
                        frm.set_df_property('error_section_section', 'hidden', 1);
                    }
                }
            }
        });
    } else {
        var missingFieldsMessage = 'Please fill all the required fields in Storage.';
        frappe.utils.play_sound("error");
        var errorDiv = $('<div class="form-message red"></div>').html(missingFieldsMessage);
        $(frm.layout.wrapper).find('.form-message.red').remove();
        $(frm.layout.wrapper).prepend(errorDiv);
        frm.set_df_property('error_section_section', 'hidden', 0);
    }
}

function generateProcessorItemCode(frm, cdt, cdn, child) {
    const item_template = child.item_template;
    const row_name = child.reference_row_name;

    let processor_type = child.processor_type;
    let grade = child.grade;

    const processor_properties = [{
        "Processor Type": processor_type,
        "Grade": grade
    }];

    if (processor_type && grade) {
        frappe.call({
            method: "nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value",
            args: {
                item_template: item_template,
                args: processor_properties
            },
            callback: function(r) {
                if (r.message) {
                    if (r.message.error) {
                        frappe.utils.play_sound("error");
                        var errorMessageString = 'Item code not found: ' + r.message.error;
                        var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                        $(frm.layout.wrapper).find('.form-message.red').remove();
                        $(frm.layout.wrapper).prepend(errorDiv);
                        frm.set_df_property('error_section_section', 'hidden', 0);
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', '');
                    } else {
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
                        frm.set_df_property('error_section_section', 'hidden', 1);
                    }
                }
            }
        });
    } else {
        frappe.utils.play_sound("error");
        var missingFieldsMessage = 'Please fill all the required fields in Processor.';
        var errorDiv = $('<div class="form-message red"></div>').html(missingFieldsMessage);
        $(frm.layout.wrapper).find('.form-message.red').remove();
        $(frm.layout.wrapper).prepend(errorDiv);
        frm.set_df_property('error_section_section', 'hidden', 0);
    }
}

function generateDisplayItemCode(frm, cdt, cdn, child) {
   
    const item_template = child.item_template;
    const row_name = child.reference_row_name;
    let model = child.model;
    let display_tech = child.display_tech;
    let display_pin_type = child.display_pin_type;
    let display_size = child.display_size;
    let resolution = child.resolution;
    let thickness = child.thickness;
    let display_bracket = child.display_bracket;
    let grade = child.grade;

    const display_properties = [{
        "MODEL": model,
        "Display Tech": display_tech,
        "Display PIN Type": display_pin_type,
        "Display Size": display_size,
        "Resolution": resolution,
        "Thickness": thickness,
        "Display Bracket": display_bracket,
        "Grade": grade
    }];

    if (model && display_tech && display_pin_type && display_size && resolution && thickness && display_bracket && grade) {

        frappe.call({
            method: 'nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value',
            args: { 
                item_template: item_template, 
                args: display_properties,
            },
            callback: function(r) {
                if (r.message) {
                    if (r.message.error) {
                        frappe.utils.play_sound("error");
                        var errorMessageString = 'Item code not found: ' + r.message.error;
                        var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                        $(frm.layout.wrapper).find('.form-message.red').remove();
                        $(frm.layout.wrapper).prepend(errorDiv);
                        frm.set_df_property('error_section_section', 'hidden', 0);
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', '');
                    } else {
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
                        frm.set_df_property('error_section_section', 'hidden', 1);
                    }
                }
            }
        });
    } else {
        frappe.utils.play_sound("error");
        var missingFieldsMessage = 'One or more required attributes are not filled in Display.';
        var errorDiv = $('<div class="form-message red"></div>').html(missingFieldsMessage);
        $(frm.layout.wrapper).find('.form-message.red').remove();
        $(frm.layout.wrapper).prepend(errorDiv);
        frm.set_df_property('error_section_section', 'hidden', 0);
    }
}

function generateRamItemCode(frm, cdt, cdn, child) {
    const item_template = child.item_template;
    const row_name = child.reference_row_name;

    const ram_properties = [
        {
            "RAM Type": child.ram_type,
            "RAM Capacity": child.ram_capacity,
            "RAM Speed": child.ram_speed,
            "Grade": child.grade
        }
    ];
    if (child.ram_type && child.ram_capacity && child.ram_speed && child.grade) {
        frappe.call({
            method: 'nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value',
            args: { 
                item_template: item_template, 
                args: ram_properties,
            },
            callback: function(r) {
                if (r.message) {
                    if (r.message.error) {
                        frappe.utils.play_sound("error");
                        var errorMessageString = 'Item code not found: ' + r.message.error;
                        var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                        $(frm.layout.wrapper).find('.form-message.red').remove();
                        $(frm.layout.wrapper).prepend(errorDiv);
                        frm.set_df_property('error_section_section', 'hidden', 0);
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', '');
                    } else {
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
                        frm.set_df_property('error_section_section', 'hidden', 1);
                    }
                }
            }
        });
    } else {
        frappe.utils.play_sound("error");
        var missingFieldsMessage = 'Please fill all the required fields in RAM.';
        var errorDiv = $('<div class="form-message red"></div>').html(missingFieldsMessage);
        $(frm.layout.wrapper).find('.form-message.red').remove();
        $(frm.layout.wrapper).prepend(errorDiv);
        frm.set_df_property('error_section_section', 'hidden', 0);
    }
}

function set_options_for_attribute_fields_in_child(frm, grid) {
    let selectFields = [];
    
    $.each(grid.grid_rows, function(i, row) {
        $.each(row.columns, function(j, field) {
            if (field.df.fieldtype === 'Select') {
                selectFields.push({
                    fieldname: field.df.fieldname,
                    rowname: row.doc.name,
                    label: field.df.label
                });
            }
        });
    });

    frappe.call({
        method: "nj_features.nj_features.doctype.njqca.njqca.get_item_attributes",
        args: { selected_fields: selectFields },
        callback: function(r) {
            if (r.message) {
                $.each(r.message, function(i, field) {
                    frm.set_df_property(grid.df.fieldname, 'options', field.options, frm.docname, field.fieldname, field.rowname);
                    frm.refresh_field(grid.df.fieldname);
                });
            }
        }
    });
}


frappe.ui.form.on('NJQCA Display', {
    check_button: async function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        let item_group = child.item_group;
        let grid = frm.get_field(child.parentfield);

        // Create a pop-up dialog
        let d = new frappe.ui.Dialog({
            title: 'Edit Display Attributes',
            fields: [
                { label: 'Model', fieldname: 'model', fieldtype: 'Select', options: ['Loading...'], default: child.model || '' },
                { label: 'Display Tech', fieldname: 'display_tech', fieldtype: 'Select', options: ['Loading...'], default: child.display_tech || '' },
                { label: 'Display PIN Type', fieldname: 'display_pin_type', fieldtype: 'Select', options: ['Loading...'], default: child.display_pin_type || '' },
                { label: 'Display Size', fieldname: 'display_size', fieldtype: 'Select', options: ['Loading...'], default: child.display_size || '' },
                { label: 'Resolution', fieldname: 'resolution', fieldtype: 'Select', options: ['Loading...'], default: child.resolution || '' },
                { label: 'Thickness', fieldname: 'thickness', fieldtype: 'Select', options: ['Loading...'], default: child.thickness || '' },
                { label: 'Display Bracket', fieldname: 'display_bracket', fieldtype: 'Select', options: ['Loading...'], default: child.display_bracket || '' },
                { label: 'Grade', fieldname: 'grade', fieldtype: 'Select', options: ['Loading...'], default: child.grade || '' },
            ],
            primary_action_label: 'Save',
            primary_action(values) {
                // Update the grid values using set_df_property
                Object.keys(values).forEach(fieldname => {
                    if (values[fieldname]) {
                        frm.set_df_property( grid.df.fieldname, 'options',
                            values[fieldname], frm.docname, fieldname, cdn
                        );

                        frappe.model.set_value(cdt, cdn, fieldname, values[fieldname]);
                    }
                });

                frm.refresh_field(grid.df.fieldname);

                fetch_item_template_disp_adp(frm, item_group, function(item_template_data) {

                    frappe.model.set_value(cdt, cdn, 'item_template', item_template_data);

                    frm.refresh_field(grid.df.fieldname);

                    generateDisplayItemCode(frm, cdt, cdn, child);
                });

                d.hide();
            }
        });

        const fieldToAttribute = {
            'model': 'Model',
            'display_tech': 'Display Tech',
            'display_pin_type': 'Display PIN Type',
            'display_size': 'Display Size',
            'resolution': 'Resolution',
            'thickness': 'Thickness',
            'display_bracket': 'Display Bracket',
            'grade': 'Grade'
        };

        Object.keys(fieldToAttribute).forEach(async (fieldname) => {
            try {
                let attributeName = fieldToAttribute[fieldname];
                let options = await get_options(attributeName);

                d.set_df_property(fieldname, 'options', options);

                if (child[fieldname]) {
                    d.set_value(fieldname, child[fieldname]);
                }
            } catch (error) {
                console.error(`Error loading options for ${fieldname}:`, error);
            }
        });

        d.show();

        async function get_options(attributeName) {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "nj_features.nj_features.doctype.njqca.njqca.get_options_for_label",
                    args: { label: attributeName },
                    callback: function(r) {
                        if (r.message && Array.isArray(r.message)) {
                            resolve(r.message);
                        } else { resolve([]); }
                    },
                    error: function(err) {
                        console.error("API Error:", err);
                        reject(err);
                    }
                });
            });
        }
    }
});

// Function to fetch item_template first, then call generateDisplayItemCode
function fetch_item_template_disp_adp(frm, item_group, callback) {
    frappe.call({
        method: "nj_features.nj_features.doctype.njqca.njqca.get_serial_no_attribute_data",
        args: { 
            serial_no: frm.doc.serial_no,
            item_group: item_group
        },
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                callback(r.message[0].item_template);
            } else {
                console.warn("No item template found.");
                callback(''); 
            }
        },
        error: function(err) {
            console.error("API Error:", err);
            callback('');
        }
    });
}

frappe.ui.form.on('NJQCA Adaptor', {
    check_button: async function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        let item_group = "Laptop Adaptors";
        let grid = frm.get_field(child.parentfield);

        // Create a pop-up dialog
        let d = new frappe.ui.Dialog({
            title: 'Edit Adaptor Attributes',
            fields: [
                { label: 'Brand', fieldname: 'brand', fieldtype: 'Select', options: ['Loading...'], default: child.brand || '' },
                { label: 'Wattage Capacity', fieldname: 'wattage_capacity', fieldtype: 'Select', options: ['Loading...'], default: child.wattage_capacity || '' },
                { label: 'Adapter Pin Type', fieldname: 'adapter_pin_type', fieldtype: 'Select', options: ['Loading...'], default: child.adapter_pin_type || '' },
                { label: 'Grade', fieldname: 'grade', fieldtype: 'Select', options: ['Loading...'], default: child.grade || '' },
            ],
            primary_action_label: 'Save',
            primary_action(values) {
                // Update the grid values using set_df_property
                Object.keys(values).forEach(fieldname => {
                    if (values[fieldname]) {
                        frm.set_df_property( grid.df.fieldname, 'options',
                            values[fieldname], frm.docname, fieldname, cdn
                        );

                        frappe.model.set_value(cdt, cdn, fieldname, values[fieldname]);
                    }
                });

                frm.refresh_field(grid.df.fieldname);

                fetch_item_template_disp_adp(frm, item_group, function(item_template_data) {

                    frappe.model.set_value(cdt, cdn, 'item_template', item_template_data);

                    frm.refresh_field(grid.df.fieldname);

                    generateAdaptorItemCode(frm, cdt, cdn, child);
                });

                d.hide();
            }
        });

        const fieldToAttribute = {
            'brand': 'Brand',
            'wattage_capacity': 'Wattage Capacity',
            'adapter_pin_type': 'Adapter Pin Type',
            'grade': 'Grade'
        };

        Object.keys(fieldToAttribute).forEach(async (fieldname) => {
            try {
                let attributeName = fieldToAttribute[fieldname];
                let options = await get_options(attributeName);

                d.set_df_property(fieldname, 'options', options);

                if (child[fieldname]) {
                    d.set_value(fieldname, child[fieldname]);
                }
            } catch (error) {
                console.error(`Error loading options for ${fieldname}:`, error);
            }
        });

        d.show();

        async function get_options(attributeName) {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "nj_features.nj_features.doctype.njqca.njqca.get_options_for_label",
                    args: { label: attributeName },
                    callback: function(r) {
                        if (r.message && Array.isArray(r.message)) {
                            resolve(r.message);
                        } else { resolve([]); }
                    },
                    error: function(err) {
                        console.error("API Error:", err);
                        reject(err);
                    }
                });
            });
        }
    }
});


frappe.ui.form.on('NJQCA Laptop Storage', {
    check_button: async function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        let item_group = child.item_group;
        let grid = frm.get_field(child.parentfield);

        let d = new frappe.ui.Dialog({
            title: 'Laptop Storage Attributes',
            fields: [
                { label: 'Storage Type', fieldname: 'storage_type', fieldtype: 'Select', options: ['Loading...'], default: child.storage_type || '' },
                { label: 'Storage Interface', fieldname: 'storage_interface', fieldtype: 'Select', options: ['Loading...'], default: child.storage_interface || '' },
                { label: 'Storage Capacity', fieldname: 'storage_capacity', fieldtype: 'Select', options: ['Loading...'], default: child.storage_capacity || '' },
                { label: 'Storage Length', fieldname: 'storage_length', fieldtype: 'Select', options: ['Loading...'], default: child.storage_length || '' },
                { label: 'Grade', fieldname: 'grade', fieldtype: 'Select', options: ['Loading...'], default: child.grade || '' },
            ],
            primary_action_label: 'Save',
            primary_action(values) {
                Object.keys(values).forEach(fieldname => {
                    if (values[fieldname]) {
                        frm.set_df_property( grid.df.fieldname, 'options',
                            values[fieldname], frm.docname, fieldname, cdn
                        );

                        frappe.model.set_value(cdt, cdn, fieldname, values[fieldname]);
                    }
                });

                frm.refresh_field(grid.df.fieldname);

                fetch_item_template_disp_adp(frm, item_group, function(item_template_data) {

                    frappe.model.set_value(cdt, cdn, 'item_template', item_template_data);

                    frm.refresh_field(grid.df.fieldname);

                    generateStorageItemCode(frm, cdt, cdn, child);
                });

                d.hide();
            }
        });

        const fieldToAttribute = {
            'storage_type': 'Storage Type',
            'storage_interface':'Storage Interface',
            'storage_capacity': 'Storage Capacity',
            'storage_length': 'Storage Length',
            'grade': 'Grade'
        };

        Object.keys(fieldToAttribute).forEach(async (fieldname) => {
            try {
                let attributeName = fieldToAttribute[fieldname];
                let options = await get_options(attributeName);

                d.set_df_property(fieldname, 'options', options);

                if (child[fieldname]) {
                    d.set_value(fieldname, child[fieldname]);
                }
            } catch (error) {
                console.error(`Error loading options for ${fieldname}:`, error);
            }
        });

        d.show();

        async function get_options(attributeName) {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "nj_features.nj_features.doctype.njqca.njqca.get_options_for_label",
                    args: { label: attributeName },
                    callback: function(r) {
                        if (r.message && Array.isArray(r.message)) {
                            resolve(r.message);
                        } else { resolve([]); }
                    },
                    error: function(err) {
                        console.error("API Error:", err);
                        reject(err);
                    }
                });
            });
        }
    }
});

frappe.ui.form.on('NJQCA Laptop Ram', {
    check_button: async function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        let item_group = child.item_group;
        let grid = frm.get_field(child.parentfield);

        let d = new frappe.ui.Dialog({
            title: 'Laptop Ram Attributes',
            fields: [
                { label: 'RAM Type', fieldname: 'ram_type', fieldtype: 'Select', options: ['Loading...'], default: child.ram_type || '' },
                { label: 'RAM Capacity', fieldname: 'ram_capacity', fieldtype: 'Select', options: ['Loading...'], default: child.ram_capacity || '' },
                { label: 'RAM Speed', fieldname: 'ram_speed', fieldtype: 'Select', options: ['Loading...'], default: child.ram_speed || '' },
                { label: 'Grade', fieldname: 'grade', fieldtype: 'Select', options: ['Loading...'], default: child.grade || '' },
            ],
            primary_action_label: 'Save',
            primary_action(values) {
                Object.keys(values).forEach(fieldname => {
                    if (values[fieldname]) {
                        frm.set_df_property( grid.df.fieldname, 'options',
                            values[fieldname], frm.docname, fieldname, cdn
                        );

                        frappe.model.set_value(cdt, cdn, fieldname, values[fieldname]);
                    }
                });

                frm.refresh_field(grid.df.fieldname);

                fetch_item_template_disp_adp(frm, item_group, function(item_template_data) {

                    frappe.model.set_value(cdt, cdn, 'item_template', item_template_data);

                    frm.refresh_field(grid.df.fieldname);

                    generateRamItemCode(frm, cdt, cdn, child);
                });

                d.hide();
            }
        });

        const fieldToAttribute = {
            'ram_type': 'RAM Type',
            'ram_capacity':'RAM Capacity',
            'ram_speed': 'RAM Speed',
            'grade': 'Grade'
        };

        Object.keys(fieldToAttribute).forEach(async (fieldname) => {
            try {
                let attributeName = fieldToAttribute[fieldname];
                let options = await get_options(attributeName);

                d.set_df_property(fieldname, 'options', options);

                if (child[fieldname]) {
                    d.set_value(fieldname, child[fieldname]);
                }
            } catch (error) {
                console.error(`Error loading options for ${fieldname}:`, error);
            }
        });

        d.show();

        async function get_options(attributeName) {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "nj_features.nj_features.doctype.njqca.njqca.get_options_for_label",
                    args: { label: attributeName },
                    callback: function(r) {
                        if (r.message && Array.isArray(r.message)) {
                            resolve(r.message);
                        } else { resolve([]); }
                    },
                    error: function(err) {
                        console.error("API Error:", err);
                        reject(err);
                    }
                });
            });
        }
    }
});


frappe.ui.form.on('NJQCA PROCESSOR', {
    check_button: async function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        let item_group = child.item_group;
        let grid = frm.get_field(child.parentfield);

        let d = new frappe.ui.Dialog({
            title: 'Processor Attributes',
            fields: [
                { label: 'Processor Type', fieldname: 'processor_type', fieldtype: 'Select', options: ['Loading...'], default: child.processor_type || '' },
                { label: 'Grade', fieldname: 'grade', fieldtype: 'Select', options: ['Loading...'], default: child.grade || '' },
            ],
            primary_action_label: 'Save',
            primary_action(values) {
                Object.keys(values).forEach(fieldname => {
                    if (values[fieldname]) {
                        frm.set_df_property(
                            grid.df.fieldname,
                            'options',
                            values[fieldname],
                            frm.docname,
                            fieldname,
                            cdn
                        );

                        frappe.model.set_value(cdt, cdn, fieldname, values[fieldname]);
                    }
                });

                frm.refresh_field(grid.df.fieldname);

                fetch_item_template_disp_adp(frm, item_group, function(item_template_data) {

                    frappe.model.set_value(cdt, cdn, 'item_template', item_template_data);

                    frm.refresh_field(grid.df.fieldname);

                    generateProcessorItemCode(frm, cdt, cdn, child);
                });

                d.hide();
            }
        });

        const fieldToAttribute = {
            'processor_type': 'Processor Type',
            'grade': 'Grade'
        };

        Object.keys(fieldToAttribute).forEach(async (fieldname) => {
            try {
                let attributeName = fieldToAttribute[fieldname];
                let options = await get_options(attributeName);

                d.set_df_property(fieldname, 'options', options);

                if (child[fieldname]) {
                    d.set_value(fieldname, child[fieldname]);
                }
            } catch (error) {
                console.error(`Error loading options for ${fieldname}:`, error);
            }
        });

        d.show();

        async function get_options(attributeName) {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "nj_features.nj_features.doctype.njqca.njqca.get_options_for_label",
                    args: { label: attributeName },
                    callback: function(r) {
                        if (r.message && Array.isArray(r.message)) {
                            resolve(r.message);
                        } else {  resolve([]); }
                    },
                    error: function(err) {
                        console.error("API Error:", err);
                        reject(err);
                    }
                });
            });
        }
    }
});