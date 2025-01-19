// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('NJQCA', {
    onload: function(frm) {
        if (frm.doc.docstatus == 0) {
            
            $(document).on('frappe.error', function(event, error) {
                if (error instanceof frappe.TimestampMismatchError) {
                    frappe.msgprint(__('The document has been modified externally. Refreshing now.'));
                    frm.reload_doc();
                }
            });

            frm.events.serial_no(frm);
        }
    },
    
    refresh: function(frm) {
        
        $('.col-lg-2.layout-side-section').hide();
        $(frm.layout.wrapper).find('.form-message.red').remove();
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
        }
    },

	onload_post_render: function(frm) {
        if (cur_frm.doc.error_message == "") {
            $(frm.layout.wrapper).find('.form-message.red').remove()
        } else {
            cur_frm.set_df_property('error_section_section', 'hidden', 0)
        }

        if (frm.doc.docstatus == 0) {
            processItemTemplate(frm)
            if (frm.doc.item_template) {
                frm.set_df_property('item_template', 'read_only', 1)
            } else {
                frm.events.item_template(frm);
            }
            frm.refresh_field('item_template')
        }

        if (frm.doc.docstatus == 0 && !frm.doc.inspection_type) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_inspection_type',
                callback: function(r) {
                    frm.set_value('inspection_type', r.message);
                    cur_frm.refresh_field('inspection_type');
                }
            })
        }

        if (frm.doc.docstatus == 0 && !frm.doc.model) {
            cur_frm.set_df_property('model', 'read_only', 1);
            cur_frm.refresh_field('model');
        } else {
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
        if (cur_frm.doc.power_on == 'Yes') {
            new Promise(function(resolve, reject) {
                resolve();
            }).then(function() {
                frappe.call({
                    method: 'nj_features.nj_features.doctype.njqca.njqca.brand_model_validation',
                    args: {'brand': cur_frm.doc.brand, 'model': cur_frm.doc.model},
                    callback: function(r) {
                        if (!r.message.brand) {
                            dbError.push("Brand: "+cur_frm.doc.brand);
                        }
        
                        if (!r.message.model) {
                            dbError.push("Model: "+cur_frm.doc.model);
                        }
        
                        if (errorMessages.length > 0 || dbError.length > 0) {
                            frappe.utils.play_sound("error");
                            var errorMessageString = "";
        
                            if (errorMessages.length > 0) {
                                errorMessageString += errorMessages.join(', ') + " not filled<br>";
                            }
                            
                            if (dbError.length > 0) {
                                errorMessageString += dbError.join(', ') + " does not exist";
                            }
        
                            var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                            $(frm.wrapper).find('.form-message.blue').remove();
                            $(frm.layout.wrapper).prepend(errorDiv);
                            frm.set_value('error_message', errorMessageString);
                            frm.set_df_property('error_section_section', 'hidden', 0);
                            frappe.validated = false;

                        } else {
                            frm.set_value('error_message', '');
                        }
        
                        if ($(frm.layout.wrapper).find('.form-message.red').length > 1) {
                            $(frm.layout.wrapper).find('.form-message.red').last().remove();
                        }
                        frm.refresh_field('error_message')
                    }
                });
            });
        }
    
        if ($(frm.layout.wrapper).find('.form-message.red').length > 1) {
            $(frm.layout.wrapper).find('.form-message.red').last().remove();
        }

        let child_table_fieldname = ['njqca_laptop_processors', 'njqca_laptop_ram', 'njqca_laptop_storage', 'njqca_display', 'njqca_adaptor'];
            
        for (let i = 0; i < child_table_fieldname.length; i++) {
            if (frm.fields_dict[child_table_fieldname[i]]) {
                let grid = frm.fields_dict[child_table_fieldname[i]].grid;
                set_options_for_attribute_fields_in_child(frm, grid);
                frm.refresh_field(child_table_fieldname[i])
            }
        }
    },

    before_save: function(frm) {
        if (!window.isWindowOpened) {
            window.isWindowOpened = false;

            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.after_save_njqca',
                args: {
                    'docname': cur_frm.doc.name
                },
                callback: function(r) {
                    if (r && r.message) {
                        frm.set_value('qi_name', r.message.qi_name);
                        frm.refresh_field('qi_name');

                        if (!window.isWindowOpened) {
                            window.open(r.message.njpulse_url, "_blank");
                            window.isWindowOpened = true;
                        }
                    } else {
                        console.error('QI name is not defined');
                    }
                }
            });
        }
    },

    before_submit: function(frm) {

        let tablesToCheck = [ 'njqca_laptop_ram', 'njqca_laptop_processors', 
            'njqca_display',  'njqca_adaptor', 'njqca_laptop_storage' ];
        
        let missingCodes = [];
        let i = 0;

        tablesToCheck.forEach((table) => {
            frm.doc[table].forEach((row) => {
                if (!row.calculated_item_code) {
                    missingCodes.push(`<br><b>${++i}.</b> The <b>Calculated Item Code</b> is missing in table <b>${table}</b>, Row: ${row.idx || "unknown"}`);
                }
            });
        });

        if (missingCodes.length > 0) {
            let missingCodesMessage = missingCodes.join('<br>');

            frappe.msgprint({
                title: __('Validation Error'),
                indicator: 'red',
                message: `<b>The following issues were found:</b><br><br>${missingCodesMessage}<br><br>Please fill all missing calculated item codes before submission.`
            });
            frappe.validated = false;
            return;
        }

        return new Promise((resolve, reject) => {
            let tablesToCheck = [ 'njqca_laptop_ram', 'njqca_laptop_processors', 
                'njqca_display',  'njqca_adaptor', 'njqca_laptop_storage' ];
            
            let mismatches = [];
            let i = 0;
    
            tablesToCheck.forEach((table) => {
                frm.doc[table].forEach((row) => {
                    if (!row.calculated_item_code || row.calculated_item_code.trim() === "") {
                        mismatches.push(`<br><b>${++i}.</b> The calculated item code is missing for an entry in <b>${table}</b>.`);
                    } else if (row.calculated_item_code !== row.fetched_item_code) {
                        mismatches.push(`<br><b>${++i}.</b> The <b>fetched item code: ${row.fetched_item_code}</b> is different from the <b>calculated item code: ${row.calculated_item_code}</b>.`);
                    }
                });
            });
    
            if (mismatches.length > 0) {
                let mismatchMessage = mismatches.join('<br>');
    
                frappe.confirm(
                    `<b>The following issues were found:</b><br><br>${mismatchMessage}<br><br>Do you agree to change all mismatched or missing item codes?`,
                    () => { resolve(); },
                    () => { reject(); }
                );
            } else { resolve(); }
        });
    },

    power_on: function() {
        const isYes = cur_frm.doc.power_on === "Yes";
        const isNone = cur_frm.doc.power_on === "";
        cur_frm.set_df_property('iqc_section', 'hidden', !isYes);
        cur_frm.set_df_property('section_break_6sw2s', 'hidden', isNone || 0);
        cur_frm.set_df_property('section_break_56eed', 'hidden', !isYes);
        cur_frm.set_df_property('warehouse', 'hidden', !isYes);
        cur_frm.set_df_property('repack_item_code', 'hidden', !isYes);
        cur_frm.set_df_property('model', 'hidden', !isYes);
    },

    serial_no: function(frm) {
		handleScannerInput(frm, 'serial_no');
        if ((cur_frm.doc.serial_no || cur_frm.doc.bios_serialno) && cur_frm.doc.power_on == 'Yes') {
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_info_from_serial_no',
                args: {'doc': cur_frm.doc},
                callback: function(r) {
                    Object.keys(r.message).forEach(field => { 
                        frm.set_value(field, r.message[field]);
                        cur_frm.refresh_field(field);
                    });

                    if(!frappe.user.has_role("IQC Manager") && frm.doc.serial_no){
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
                       
                if (!r.work_warehouse) {
                    frappe.msgprint(`Work Warehouse is not set for employee: ${frappe.session.user_email}. Please mail to <b>IT Infra Team</b> at <strong><a href="mailto:itinfra@newjaisa.com">itinfra@newjaisa.com</a></strong> to create an employee.`)
                } else if (r.work_warehouse != ware) {
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
                                'serial_no': frm.doc.serial_no,
                                'item_code': frm.doc.item_code,
                                't_warehouse': r.work_warehouse,
                                's_warehouse': frm.doc.warehouse
                            }];
                            
                            let data = {
                                "doctype": frm.doc.doctype,
                                "serial_no": frm.doc.serial_no,
                                "series": "NJ-STE-NJQCA-",
                                "t_warehouse": r.work_warehouse,
                                "stock_entry_type": "Material Transfer",
                                "reference_serial_no": frm.doc.serial_no,
                                "material_transfer_items": material_transfer_items,
                            }
                    
                            frappe.call({
                                method: 'nj_lib.utils.stock_entry.stock_entry_using_nj_lib',
                                args: { 'data': JSON.stringify(data) },
                                freeze: true,
                                freeze_message: `<div style="text-align: center;">
                                    <i class="fa fa-spinner fa-spin" style="font-size: 24px;"></i> 
                                    <br>Transfering Stock... Please Wait
                                </div>`,
                                callback: function(response) {
                                    frm.set_value('warehouse', r.work_warehouse);
                                    frm.refresh_field('warehouse');
                                },
                                error: function(err) { 
                                    console.log(err);
                                }
                            });
                    
                            dialog.hide();
                        },
                        secondary_action_label: "Cancel",
                        secondary_action: function() {
                            $('.primary-action').hide()
                            dialog.hide();
                        }
                    });
                    
                    dialog.show();
                }
            })
        }
    },

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

            get_item_template(selectedModel, selectedBrand, selectedItemGroup)

        } else {
            cur_frm.set_df_property('item_template', 'options', []);
            cur_frm.set_value('item_template', '');
        }
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
                    frappe.msgprint("Serialized Item Code: <b>" + r.message.error + "</b> is not found. Please contact NPD Team");
                } else if (r.message.repack_item_code.error) {
                    console.log("Error while creating of Repack Item Code: <b>" + r.message.repack_item_code.error + "</b> Please contact NPD Team");
                } else {
                    frm.set_value('data_attr', r.message.data_attr);
                    frm.set_value('repack_item_code', r.message.repack_item_code);
                    frm.set_value('manual_repack_item_code', r.message.repack_item_code);
                    frm.refresh_fields(['repack_item_code', 'manual_repack_item_code', 'data_attr']);

                    const partData = JSON.parse(r.message.part_data);

                    frm.doc.njqca_item_component.forEach(row => {
                        const part = partData.find(p => p.name === row.name && p.response !== 'error');
                        if (part) {
                            frappe.model.set_value(row.doctype, row.name, 'part_item_code', part.part_item_code);
                            frappe.model.set_value(row.doctype, row.name, 'attr_data', JSON.stringify(part.attr_data));
                        }
                    });
                }
                console.log("r.message.part_data",r.message);
                
                if (r.message.part_data) {
                    
                    const partData = JSON.parse(r.message.part_data);
                    frm.clear_table("njqca_laptop_ram");
                    frm.clear_table("njqca_laptop_processors");
                    frm.clear_table("njqca_laptop_storage")
                    partData.forEach(row => {

                        if (row.item_group === "Laptop RAM") {
                            let newRow = frappe.model.add_child(frm.doc, "njqca_laptop_ram");

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
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', row.item_group);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'fetched_item_code', row.part_item_code);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_template', row.item_template);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'processor_type', row.attr_data["Processor Type"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'grade', row.attr_data["Grade"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'reference_row_name', row.name);
                        }else if(row.item_group === "LAPTOP STORAGE"){
                            let newRow = frappe.model.add_child(frm.doc, "njqca_laptop_storage");
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', row.item_group);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'fetched_item_code', row.part_item_code);        
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_template', row.item_template);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'storage_type', row.attr_data["Storage Type"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'grade', row.attr_data["Grade"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'reference_row_name', row.name);
                        }
                    });

                    if (!frm.doc.manual_repack_item_code) {
                        frm.set_value('manual_repack_item_code', frm.doc.item_code);
                        frm.refresh_field('manual_repack_item_code');
                    }

                    frm.set_df_property('laptop_processor_section', 'collapsible', 1);
                    frm.set_df_property('laptop_ram_section', 'collapsible', 1);
                    frm.set_df_property('laptop_storage_section', 'collapsible', 1);

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

                        frm.fields_dict.item_template.$input.on('change', function() {
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
                        [selectedBrand, selectedModel, selectedItemGroup]));
                }
            }
        }
    });
}

function get_model(manufacturer_model) {
    
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
                }
                cur_frm.refresh_field('model');
            }
        }
    });
}

frappe.ui.form.on('NJQCA Adaptor', {
    njqca_adaptor_add: function(frm, cdt, cdn) {

        const child_table_fieldname = 'njqca_adaptor';
        const grid = frm.fields_dict[child_table_fieldname].grid;

        set_options_for_attribute_fields_in_child(frm, grid);
    },
    brand: function(frm, cdt, cdn) {
        const child = locals[cdt][cdn];  
        generateAdaptorItemCode(frm, cdt, cdn, child); 
    },
    wattage_capacity: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateAdaptorItemCode(frm, cdt, cdn, child);
    },
    adapter_pin_type: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateAdaptorItemCode(frm, cdt, cdn, child);
    },
    grade: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateAdaptorItemCode(frm, cdt, cdn, child);
    }
});

frappe.ui.form.on('NJQCA Laptop Ram', {

    njqca_laptop_ram_add: function(frm, cdt, cdn) {

        const child_table_fieldname = 'njqca_laptop_ram';
        const grid = frm.fields_dict[child_table_fieldname].grid;

        set_options_for_attribute_fields_in_child(frm, grid);
    }, 

    ram_type: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateRamItemCode(frm, cdt, cdn, child); 
    },

    ram_capacity: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateRamItemCode(frm, cdt, cdn, child); 
    },
    ram_speed: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateRamItemCode(frm, cdt, cdn, child); 
    },
    grade: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateRamItemCode(frm, cdt, cdn, child); 
    },
});

frappe.ui.form.on('NJQCA Display', {

    njqca_display_add: function(frm, cdt, cdn) {

        const child_table_fieldname = 'njqca_display';
        const grid = frm.fields_dict[child_table_fieldname].grid;

        set_options_for_attribute_fields_in_child(frm, grid);
    },

    model: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateDisplayItemCode(frm, cdt, cdn, child); 
    },
    display_tech: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateDisplayItemCode(frm, cdt, cdn, child); 
    },
    display_pin_type: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateDisplayItemCode(frm, cdt, cdn, child); 
    },  
    
    display_size: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateDisplayItemCode(frm, cdt, cdn, child); 
    },  
    
    resolution: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateDisplayItemCode(frm, cdt, cdn, child); 
    },  
    
    thickness: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateDisplayItemCode(frm, cdt, cdn, child); 
    },  
    
    display_bracket: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateDisplayItemCode(frm, cdt, cdn, child); 
    },  
    
    grade: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateDisplayItemCode(frm, cdt, cdn, child); 
    },
})

frappe.ui.form.on('NJQCA PROCESSOR', {
    njqca_laptop_processors_add: function(frm, cdt, cdn) {
        const child_table_fieldname = 'njqca_laptop_processors';
        const grid = frm.fields_dict[child_table_fieldname].grid;
        
        set_options_for_attribute_fields_in_child(frm, grid);
    },
    processor_type: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateProcessorItemCode(frm, cdt, cdn, child); 
    },
    grade: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateProcessorItemCode(frm, cdt, cdn, child); 
    },
});

frappe.ui.form.on('NJQCA Laptop Storage', {
    njqca_laptop_storage_add: function(frm, cdt, cdn) {

        const child_table_fieldname = 'njqca_laptop_storage';
        const grid = frm.fields_dict[child_table_fieldname].grid;
        
        set_options_for_attribute_fields_in_child(frm, grid);
    },
    storage_type: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateStorageItemCode(frm, cdt, cdn, child); 
    },
    storage_capacity: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateStorageItemCode(frm, cdt, cdn, child); 
    },
    storage_interface: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateStorageItemCode(frm, cdt, cdn, child); 
    },
    storage_length: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateStorageItemCode(frm, cdt, cdn, child); 
    },
    grade: function(frm, cdt, cdn){
        const child = locals[cdt][cdn];  
        generateStorageItemCode(frm, cdt, cdn, child); 
    },
});

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
                item_template: "S-Laptop Adaptors",
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
    $.each(grid.grid_rows, function(i, row) {
            
        $.each(row.columns, function(j, field) {

            if (field.df.fieldtype === 'Select') {
                
                frappe.call({
                    method: "erpnext.stock.doctype.item.item.get_item_attribute",
                    args: {
                        parent: field.df.label,
                        attribute_value: ''
                    },
                    callback: function(r) {
                        if (r.message) {
                            var options = r.message.map(function(d) { 
                                return d.attribute_value.toUpperCase(); 
                            });
                            
                            frm.set_df_property(grid.df.fieldname, 'options', options, frm.docname, field.df.fieldname, row.doc.name);
                        }
                    }
                });
            }
        });
    });
}