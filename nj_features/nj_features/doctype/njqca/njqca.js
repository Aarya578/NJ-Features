// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('NJQCA', {
    onload: function(frm) {
        if (frm.doc.docstatus == 0) {

            frm.set_query("inspection_type", () => {
                return {
                    filters: {
                        "active": 1
                    }
                };
            });

            frappe.db.get_value('Employee', {'user_id': frappe.session.user, 'status': 'Active'}, 'department').then((r) => {
                if (r.message.department) {
                    cur_frm.set_value("department", r.message.department);
                } else {
                    frappe.throw("Your department is not set. Please mail to <b>IT Infra Team</b> at <strong><a href='mailto:itinfra@newjaisa.com'>itinfra@newjaisa.com</a></strong> to update employee.");
                }
            })

            if (!cur_frm.doc.model && !frm.doc.manufacturer_model) {
                frappe.msgprint("Manufacturer Model is not found")
                return
            }

            if (cur_frm.doc.serial_no && cur_frm.doc.docstatus == 0 && cur_frm.doc.power_on == 'Yes') {
                frm.events.serial_no(frm);
            }    
    
            if(!frm.doc.sudden_drop){
                frappe.call({
                    method: 'nj_features.nj_features.doctype.njqca.njqca.get_sudden_drop',
                    args: {
                        'parent_name': frm.doc.name,
                        'item_group': frm.doc.item_group
                    },
                    callback: function(r) {
                        
                        if(r && r.message){
                            frm.set_value("sudden_drop", r.message);
                        }
                    }
                });
            }

            if (frm.doc.bios_serialno) {
                frappe.db.get_value('Serial No', {'bios_serial_no': frm.doc.bios_serialno}, ['name', 'model', 'item_code'], (r) => {
                    if (r && r.name && r.model && r.item_code) {
                        frm.set_value("serial_no", r.name);
                        if (frm.fields_dict.model) {
                            let options = frm.fields_dict.model.df.options || '';
                            if (!options.includes(r.model)) {
                                options += '\n' + r.model;
                                frm.fields_dict.model.df.options = options;
                                frm.refresh_field('model');
                            }
                            frm.set_value("model", r.model);
                        }
                        frappe.db.get_value('Item', {'item_code': r.item_code}, ['variant_of'], (r) => {
                            if (r && r.variant_of) {
                                frm.set_value("item_template", r.variant_of);
                                frm.set_df_property('item_template', 'read_only', 1);
                                // processItemTemplate(frm);
                                frm.save();
                            }
                        });
                    } else {
                        if (frm.doc.model) {
                            frm.set_df_property('model', 'read_only', 1);
                        } else {
                            get_model(frm.doc.manufacturer_model);
                            frm.trigger("model");
                        }
                    }
                });
            }
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
            
            frm.set_query('manual_repack_item_code', function(r) {
                var filters = {
                    disabled: 0,
                    has_variants: 0,
                    brand: frm.doc.brand,
                    item_group: frm.doc.item_group
                };
            
                if (frm.doc.model) {
                    filters.item_model = frm.doc.model;
                }
            
                return { filters: filters };
            });
        }
    },

    before_submit: function(frm) {
        
        return new Promise((resolve, reject) => {
            let tablesToCheck = [
                'njqca_laptop_ram', 
                'njqca_laptop_processors', 
                'njqca_display', 
                'njqca_adaptor', 
                'njqca_laptop_storage'
            ];
            
            let mismatches = [];
            
            tablesToCheck.forEach((table) => {
                frm.doc[table].forEach((row) => {
                    if(row.calculated_item_code !== row.fetched_item_code) {
                        mismatches.push(`Table: ${table}, Item Code: ${row.calculated_item_code} is different from fetched item code: ${row.fetched_item_code}`);
                        console.log(`Mismatch found - Table: ${table}, Item Code: ${row.calculated_item_code} vs Fetched: ${row.fetched_item_code}`);
                    }
                });
            });
            
            if (mismatches.length > 0) {
                let mismatchMessage = mismatches.join('<br>');
                
                frappe.confirm(
                    `The following item code mismatches were found:<br><br>${mismatchMessage}<br><br>Do you agree to change all mismatched item codes?`,
                    () => {
                        console.log('User confirmed all item code mismatches.');
                        resolve(); 
                    },
                    () => {
                        console.log('User canceled submission due to item code mismatches.');
                        reject(); 
                    }
                );
            } else {
                resolve();
            }
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
        if (cur_frm.doc.serial_no && cur_frm.doc.power_on == 'Yes') {
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_info_from_serial_no',
                args: {'doc': cur_frm.doc},
                callback: function(r) {
                    
                    const fieldsToUpdate = ['item_group', 'brand', 'warehouse', 'base_price', 'item_code'];
                    if(!r.message.brand){
                        frappe.throw(`Brand is not filled in Serial no: <b>${cur_frm.doc.serial_no}</b>. Please contact the NPD Team.`);
                    }

                    fieldsToUpdate.forEach(field => {                    
                        if (!frm.doc[field]) {
                            frm.set_value(field, r.message[field]);
                            cur_frm.refresh_field(field);
                        }
                    });
                    
                    // if(cur_frm.doc.model && cur_frm.doc.model != r.message.model){
                    //     frappe.confirm('Model in SerialNo and NJQCA are Different. Do you want to change the part list?',
                    //         () => {
                    //             frappe.call({
                    //                 method: 'nj_features.nj_features.doctype.njqca.njqca.model_change_for_serial_no',
                    //                 args: {
                    //                     'newmodel': cur_frm.doc.model,
                    //                     'serial_no': cur_frm.doc.serial_no
                    //                 },
                    //                 callback: function(r) {
                    //                     if(r.message.status === 'success'){
                    //                         var base_url = frappe.urllib.get_base_url();

                    //                         var serial_no_link = `${base_url}/app/serial-no/${cur_frm.doc.serial_no}`;
                                            
                    //                         frappe.msgprint(`Part List and Model is updated for Serial No : <strong><a href='${serial_no_link}'>${cur_frm.doc.serial_no}</a></strong> has been submitted successfully.`);
                    //                     }
                    //                 }
                    //             });
                    //         }, () => {
                    //             $('.primary-action').hide()
                    //         })
                    // }
                }
            });
        }
    },

    warehouse: function(frm) {
        if (cur_frm.doc.warehouse) {
            let ware = cur_frm.doc.warehouse;
            frappe.db.get_value('Employee', {'user_id': frappe.session.user_email, 'status': 'Active'}, 'work_warehouse', function(r) {
                       
                if (!r.work_warehouse) {
                    frappe.msgprint(`Work Warehouse is not set for employee: ${frappe.session.user_email}. Please mail to <b>IT Infra Team</b> at <strong><a href="mailto:itinfra@newjaisa.com">itinfra@newjaisa.com</a></strong> to create an employee.`)
                } else if (r.work_warehouse != ware) {
                    let dialog = frappe.confirm(
                        `Do you want to transfer stock to your Work Warehouse: ${r.work_warehouse}?`,
                        () => {
                            
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
                                callback: function(response) {
                                    frm.set_value('warehouse', r.work_warehouse)
                                },
                                error: function(err) {
                                    console.log(err);
                                }
                            })
                            dialog.hide()
                        },
                        () => {
                            $('.primary-action').hide()
                        }
                    );
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
                        }, () => {
                            $('.primary-action').hide()
                        })
                }
            })


            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_njqca_item_template',
                args: {
                    'model': selectedModel,
                    'brand': selectedBrand,
                    'item_group': selectedItemGroup
                },
                callback: function(r) {
                    if (r.message) {
    
                        var itemTemplates = r.message.item_template ? r.message.item_template.map(item => item.name) : [];
    
                        if (Array.isArray(itemTemplates) && itemTemplates.length > 0) {
                            cur_frm.set_value('item_template', '');
                            if (itemTemplates.length == 1) {
                                cur_frm.set_value('item_template', itemTemplates[0]);
                                cur_frm.set_df_property('item_template', 'read_only', 1);
                                // cur_frm.save()
    
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
                            frm.refresh_field('item_template');
                        } else {
                            cur_frm.set_df_property('item_template', 'read_only', 0);
                            cur_frm.set_value('item_template', '');
                            cur_frm.set_df_property('item_template', 'options', []);
                            
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
        } else {
            cur_frm.set_df_property('item_template', 'options', []);
            cur_frm.set_value('item_template', '');
        }
    
        if (cur_frm.doc.error_message) {
            cur_frm.set_df_property('error_message', 'hidden', 0);
        }
    },
    
	onload_post_render: function(frm) {
        if (cur_frm.doc.error_message == "") {
            $(frm.layout.wrapper).find('.form-message.red').remove()
        } else {
            cur_frm.set_df_property('error_section_section', 'hidden', 0)
        }
        if (frm.doc.docstatus == 0 && frm.doc.serial_no) {
            
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_serial_no_attribute_data',
                args: {
                    serial_no: frm.doc.serial_no
                },
                callback: function(r) {
                    if (r && r.message) {
            
                        frm.clear_table('njqca_display');
                        frm.clear_table('njqca_adaptor');
            
                        r.message.forEach(item_data => {
                            if (item_data.item_group.toUpperCase() === "DISPLAY") {
                                let display_row = frappe.model.add_child(frm.doc, 'njqca_display');
                                
                                frappe.model.set_value(display_row.doctype, display_row.name, 'fetched_item_code', item_data.item);
                                frappe.model.set_value(display_row.doctype, display_row.name, 'calculated_item_code', item_data.item);
                                frappe.model.set_value(display_row.doctype, display_row.name, 'item_group', item_data.item_group);
                                frappe.model.set_value(display_row.doctype, display_row.name, 'item_template', item_data.item_template);
                                frappe.model.set_value(display_row.doctype, display_row.name, 'grade', item_data.grade);
                                // frm.save();
                            } 
                            else if (item_data.item_group.toUpperCase() === "ADAPTOR") {
                                let adaptor_row = frappe.model.add_child(frm.doc, 'njqca_adaptor');
                                
                                frappe.model.set_value(adaptor_row.doctype, adaptor_row.name, 'fetched_item_code', item_data.item);
                                frappe.model.set_value(display_row.doctype, display_row.name, 'calculated_item_code', item_data.item);
                                frappe.model.set_value(adaptor_row.doctype, adaptor_row.name, 'item_group', item_data.item_group);
                                frappe.model.set_value(display_row.doctype, display_row.name, 'item_template', item_data.item_template);
                                frappe.model.set_value(adaptor_row.doctype, adaptor_row.name, 'grade', item_data.grade);
                                // frm.save();
                            }
                        });
            
                        frm.refresh_field('njqca_display');
                        frm.refresh_field('njqca_adaptor');
                    }
                }
            });
        }
	},

    validate: function(frm) {
        var requiredFields = ['serial_no', 'item_group', 'warehouse', 'brand', 'make', 'manufacturer_model'];
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
                    }
                });
            });
        }
    
        if ($(frm.layout.wrapper).find('.form-message.red').length > 1) {
            $(frm.layout.wrapper).find('.form-message.red').last().remove();
        }
    },

    item_template: function(frm) {
        if (frm.doc.item_template && frm.doc.docstatus == 0 && frm.doc.power_on == 'Yes') {
            processItemTemplate(frm);
        }
    },

    after_save:function(frm){
        console.log('triggerring after save...');
        frappe.call({
            method: 'nj_features.nj_features.doctype.njqca.njqca.after_save_njqca',
            args: {
                'docname': cur_frm.doc.name
            }
        });
        // if(cur_frm.doc.item_code && cur_frm.doc.repack_item_code){
        //     if(cur_frm.doc.item_code == cur_frm.doc.repack_item_code){
        //         frappe.confirm = function(message, yes, no) {
        //             if (yes) yes();
        //         };
        //         frm.savesubmit();
        //     }
        // }
        // else{
        //     console.log("repack item code and item code are not same");
        // }
    }
});

function processItemTemplate(frm) {
    if (frm.doc.njqca_item_component && frm.doc.docstatus == 0 && frm.doc.power_on == 'Yes') {
        frappe.call({
            method: 'nj_features.nj_features.doctype.njqca.njqca.get_part_mapping',
            args: { 
                'item_group': frm.doc.item_group,
                'docname': frm.doc.name,
                'model': frm.doc.model,
                'item_template': frm.doc.item_template
            },
            callback: function (r) {
                if (r.message.error) {
                    frappe.msgprint("Serialized Item Code: <b>" + r.message.error + "</b> is not found. Please contact NPD Team");
                } else if (r.message.repack_item_code.error) {
                    frappe.msgprint("Error while creating of Repack Item Code: <b>" + r.message.repack_item_code.error + "</b> Please contact NPD Team");
                } else {
                    frm.set_value('repack_item_code', r.message.repack_item_code);
                    frm.set_value('manual_repack_item_code', r.message.repack_item_code);
                    frm.set_value('data_attr', r.message.data_attr);
                    frm.refresh_fields(['repack_item_code', 'manual_repack_item_code', 'data_attr']);

                    const partData = JSON.parse(r.message.part_data);

                    frm.doc.njqca_item_component.forEach(row => {
                        const part = partData.find(p => p.name === row.name);
                        if (part) {
                            frappe.model.set_value(row.doctype, row.name, 'part_item_code', part.part_item_code);
                            frappe.model.set_value(row.doctype, row.name, 'attr_data', JSON.stringify(part.attr_data));
                        }
                    });

                    if (partData) {
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
                                frappe.model.set_value(newRow.doctype, newRow.name, 'calculated_item_code', row.part_item_code);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', row.item_group);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'item_template', row.item_template);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'reference_row_name', row.name);
                            }else if(row.item_group === "Laptop Processors"){
                                let newRow = frappe.model.add_child(frm.doc, "njqca_laptop_processors");
                                frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', row.item_group);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'fetched_item_code', row.part_item_code);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'calculated_item_code', row.part_item_code);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'item_template', row.item_template);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'processor_type', row.attr_data["Processor Type"]);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'grade', row.attr_data["Grade"]);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'reference_row_name', row.name);
                            }else if(row.item_group === "Laptop Storage"){
                                let newRow = frappe.model.add_child(frm.doc, "njqca_laptop_storage");
                                frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', row.item_group);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'fetched_item_code', row.part_item_code);        
                                frappe.model.set_value(newRow.doctype, newRow.name, 'calculated_item_code', row.part_item_code);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'item_template', row.item_template);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'storage_type', row.attr_data["Storage Type"]);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'grade', row.attr_data["Grade"]);
                                frappe.model.set_value(newRow.doctype, newRow.name, 'reference_row_name', row.name);
                            }
                        });
                        frm.refresh_field("njqca_laptop_ram");
                        frm.refresh_field("njqca_laptop_processors");
                    }
                    frm.refresh_field('njqca_item_component');
                }
            }
        });
    }
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
            }
        }
    });
}

frappe.ui.form.on('NJQCA PROCESSOR', {
    njqca_laptop_processors_add: function(frm, cdt, cdn) {
        console.log(frm, cdt, cdn);
        const child_table_fieldname = 'njqca_laptop_processors';
        const grid = frm.fields_dict[child_table_fieldname].grid;
        
        set_options_for_attribute_fields_in_child(frm, cdt, cdn, grid);
    }
});

frappe.ui.form.on('NJQCA Adaptor', {
    njqca_adaptor_add: function(frm, cdt, cdn) {

        const child_table_fieldname = 'njqca_adaptor';
        const grid = frm.fields_dict[child_table_fieldname].grid;

        set_options_for_attribute_fields_in_child(frm, cdt, cdn, grid);
    }
});

frappe.ui.form.on('NJQCA Laptop Storage', {
    njqca_laptop_storage_add: function(frm, cdt, cdn) {

        const child_table_fieldname = 'njqca_laptop_storage';
        const grid = frm.fields_dict[child_table_fieldname].grid;

        set_options_for_attribute_fields_in_child(frm, cdt, cdn, grid);
    }
});

function set_options_for_attribute_fields_in_child(frm, cdt, cdn, grid) {
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
                                return d.attribute_value; 
                            });
                            frm.set_df_property(grid.df.fieldname, 'options', options, frm.docname, field.df.fieldname, cdn);
                        }
                    }
                });
            }
        });
    });
}

// NJQCA LAPTOP RAM
frappe.ui.form.on('NJQCA Laptop Ram', {

    njqca_laptop_ram_add: function(frm, cdt, cdn) {

        const child_table_fieldname = 'njqca_laptop_ram';
        const grid = frm.fields_dict[child_table_fieldname].grid;

        set_options_for_attribute_fields_in_child(grid);
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

// NJQCA LAPTOP DISPLAY
frappe.ui.form.on('NJQCA Display', {

    njqca_display_add: function(frm, cdt, cdn) {

        const child_table_fieldname = 'njqca_display';
        const grid = frm.fields_dict[child_table_fieldname].grid;

        set_options_for_attribute_fields_in_child(frm, cdt, cdn, grid);
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

function generateDisplayItemCode(frm, cdt, cdn, child) {
    const item_template = child.item_template;
    const row_name = child.reference_row_name;

    let model = frm.doc.model;
    let display_tech = frm.doc.display_tech;
    let display_pin_type = frm.doc.display_pin_type;
    let display_size = frm.doc.display_size;
    let resolution = frm.doc.resolution;
    let thickness = frm.doc.thickness;
    let display_bracket = frm.doc.display_bracket;
    let grade = frm.doc.grade;
    
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

    if(model === '' && display_tech === '' && display_pin_type === '' && display_size === '' && resolution === '' && thickness === '' && display_bracket === '' && grade === '') {
        frappe.call({
            method: 'nj_features.nj_features.doctype.njqca.njqca.construct_item_code',
            args: { 
                item_template: item_template, 
                args_list: display_properties,
            },
            callback: function(r) {
                console.log('r:', r);
                if (r.message.error) {
                    frappe.throw('Item code not found: ' + r.message.error);
                } else {
                    frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
                }
            }
        });
    }else{
        console.log('one of the attribute is not filled...');
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

    frappe.call({
        method: 'nj_features.nj_features.doctype.njqca.njqca.construct_item_code',
        args: { 
            item_template: item_template, 
            args_list: ram_properties,
        },
        callback: function(r) {
            console.log('r:', r);
            if (r.message.error) {
                frappe.throw('item_code not found ---------------- ' + r.message.error);
            } else {
                frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
                frm.doc.njqca_item_component.forEach(row => {
                    frappe.model.set_value(row.doctype, row_name, 'part_item_code', r.message);
                });
            }
        }
    });
}