// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('NJQCA', {
    onload: function(frm) {
        if (frm.doc.docstatus == 0) {
            if (cur_frm.doc.serial_no && cur_frm.doc.docstatus == 0 && cur_frm.doc.power_on == 'Yes') {
                frm.events.serial_no(frm);
            }
    
            if (!cur_frm.doc.model && !frm.doc.manufacturer_model) {
                frappe.msgprint("Manufacturer Model is not found")
                return
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
    
            if(!frm.doc.backup_duration){
                frappe.call({
                    method: 'nj_features.nj_features.doctype.njqca.njqca.get_backup_duration',
                    args: {
                        'parent_name': frm.doc.name,
                        'item_group': frm.doc.item_group
                    },
                    callback: function(r) {
                        if(r && r.message){
                            frm.set_value("backup_duration", r.message[0]);
                            frm.set_value("sudden_drop", r.message[1]);
                        }
                    }
                });
            }

            if(!frm.doc.inspection_type){
                frappe.call({
                    method: 'nj_features.nj_features.doctype.njqca.njqca.get_inspection_type',
                    callback: function(r) {
                        if(r && r.message){
                            frm.set_value("inspection_type", r.message);
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
                                frm.save();
                            }
                        });
                    } else {
                        get_model(frm.doc.manufacturer_model);
                        frm.trigger("model");
                    }
                });
            }
            
            frm.fields_dict['njqca_item_component'].grid.get_field('part_item_code').get_query = function(doc, cdt, cdn) {
                var row = locals[cdt][cdn];
                if(row.variant_1 && row.variant_1 != '[EMPTY]' && row.variant_1 != 'SYSTEM MEMORY'){
                    return {
                        filters: {
                            item_group: row.item_group,
                            has_variants: 0
                        }
                    };
                }
                frm.refresh_field("part_item_code");
            };
        }
    },

    refresh: function(frm) {
        handleScannerInput(frm, 'serial_no');
        $('.col-lg-2.layout-side-section').hide();
        $(frm.layout.wrapper).find('.form-message.red').remove();
        frm.events.power_on();

        if(cur_frm.doc.error_message != ''){
            cur_frm.set_df_property('error_section_section', 'hidden', 0)
        }
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
            console.log("Model and/or Brand is not selected.");
            cur_frm.set_df_property('item_template', 'options', []);
            cur_frm.set_value('item_template', '');
        }
    
        if (cur_frm.doc.error_message) {
            console.log("empty error ", cur_frm.doc.error_message);
            cur_frm.set_df_property('error_message', 'hidden', 0);
        }
    },
    
	onload_post_render: function(frm) {
        if (cur_frm.doc.error_message == "") {
            $(frm.layout.wrapper).find('.form-message.red').remove()
        }

	    // if (cur_frm.doc.docstatus ==0 && cur_frm.doc.power_on == 'Yes') {
            // if (cur_frm.doc.njqca_item_component && cur_frm.doc.item_group) {
            //     frappe.call({
            //         method: 'nj_features.nj_features.doctype.njqca.njqca.get_part_mapping',
            //         args: { 
            //             'item_group': cur_frm.doc.item_group,
            //             'docname': cur_frm.doc.name
            //         },
            //         callback: function (r) {
                        // if (r.message) {
                        //     var lastVariantValues = {};
                        //     console.log("get_part_mapping",r.message);
                        //     r.message.values.forEach(function (param) { //get value from NJ Settings
                        //         window[param.parameter] = param.value;
                        //     });

                        //     r.message.mappings.forEach(function (mapping) {   // for each part in Item Group mapping (3)
                        //         frm.doc.njqca_item_component.forEach(function (row) {    // iterate elements in iqc child table
                        //             var itemGroup = row.item_group;
                        //             var variants = mapping.mappng_fields.split('::');
                                    
                        //             if (itemGroup === mapping.item_group) {

                        //                 variants.forEach(function (variant) {
                        //                     lastVariantValues[itemGroup] = lastVariantValues[itemGroup] || {};
                        //                     lastVariantValues[itemGroup][variant] = row[variant];
                        //                 });
                                        
                        //                 var attributeValue = lastVariantValues[itemGroup];
                        //                 var attributeObject = {};
                                        

                        //                 frappe.model.set_value(row.doctype, row.name, 'attr_data', {});
                        //                 if (itemGroup.toLowerCase() == cpu.toLowerCase()) {
                        //                     var anyAttributeUndefined = Object.values(attributeValue).some(value => value === undefined);
                        //                     var cpuValue = anyAttributeUndefined ? unk_cpu : Object.values(attributeValue).join(' - ');
                        //                     attributeObject[mapping.attribute_name] = cpuValue;
                        //                     row.attr_data = JSON.stringify(attributeObject);
                        //                     frappe.model.set_value(row.doctype, row.name, 'attr_data', row.attr_data);
                        //                 } 
                        //                 else if (itemGroup.toLowerCase() == ram.toLowerCase()  && (row.variant_1 !== 'SYSTEM MEMORY' && row.variant_1 !== '[EMPTY]')) {
                        //                     let anyAttributeUndefined = Object.values(attributeValue).some(value => value === undefined);
                        //                     let ramValue = anyAttributeUndefined ? unk_ram : Object.values(attributeValue).join(' ');
                        //                     attributeObject[mapping.attribute_name] = ramValue;
                        //                     row.attr_data = JSON.stringify(attributeObject);
                        //                     console.log("ram : ",ramValue, row.idx, row);
                        //                     frappe.model.set_value(row.doctype, row.name, 'attr_data', row.attr_data);
                        //                 }
                        //                 else if (itemGroup.toLowerCase() == storage.toLowerCase() && (!row.variant_3 ^ !row.variant_1) && 
                        //                 attributeValue[Object.keys(attributeValue)[0]] !== undefined && attributeValue[Object.keys(attributeValue)[0]] !== "") {
                        //                     // console.log("idx: ",row.idx, "\nstorage: ", row.attr_data, "variant_1", row.variant_1, !row.variant_3 ^ !row.variant_1, storage, unk_storage);
                        //                     attributeObject[mapping.attribute_name] = attributeValue[Object.keys(attributeValue)[0]] + " SSD" || unk_storage;
                        //                     var sValue = JSON.stringify(attributeObject);
                        //                     frappe.model.set_value(row.doctype, row.name, 'attr_data', sValue);
                        //                 } 
                        //                 else {
                        //                     frappe.model.set_value(row.doctype, row.name, 'attr_data', '');
                        //                 }
                        //             }
                        //         });
                        //     });
                        //     frm.refresh_field('njqca_item_component');
                        // }
            //         }
            //     });
            // }
            
            // if (cur_frm.doc.data_attr == "") {
            //     cur_frm.set_value('data_attr', '');
            //     var child_attr_data = [];
            //     // console.log("set data arg");
            //     frm.doc.njqca_item_component.forEach(function (row) {
            //         if (row.attr_data) {
            //             // console.log("row: ", row.attr_data);
            //             child_attr_data.push(JSON.parse(row.attr_data));
            //         }
            //     });
            //     console.log("child_attr_data: ", JSON.stringify(child_attr_data));
            //     const consolidated = consolidateRamCapacities(child_attr_data);
            //     console.log("consolidated",consolidated);
            //     console.log("2", JSON.stringify(consolidated));
            //     cur_frm.set_value('data_attr', JSON.stringify(child_attr_data));
            //     cur_frm.refresh_field('data_attr');
            // }
    
            // if (cur_frm.doc.repack_item_code && cur_frm.doc.docstatus !=1 && cur_frm.doc.power_on == 'Yes') {
            //     frappe.call({
            //         method: 'nj_features.nj_features.doctype.iqc.iqc.set_value_for_pricing',
            //         args: {'self': cur_frm.doc},
            //         callback: function(r) {
            //             frm.set_value('original_price', r.message.original_price);
            //             cur_frm.refresh_fields('fields');
            //         }
            //     });
            // } 
        // }
        // if (cur_frm.doc.model && cur_frm.doc.make && cur_frm.doc.manufacturer_model) {
        //     get_model(cur_frm.doc.manufacturer_model, cur_frm.doc.make)
        //     frm.events.validate(frm);
        // }

        if(cur_frm.doc.error_message != ''){
            cur_frm.set_df_property('error_section_section', 'hidden', 0)
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
        if(frm.doc.item_template){
            console.log('trigerring item_itemplate...')
            if (cur_frm.doc.njqca_item_component && cur_frm.doc.docstatus == 0 && cur_frm.doc.power_on == 'Yes') {
                frappe.call({
                    method: 'nj_features.nj_features.doctype.njqca.njqca.get_part_mapping',
                    args: { 
                        'item_group': cur_frm.doc.item_group,
                        'docname': cur_frm.doc.name,
                        'model':cur_frm.doc.model,
                        'item_template': cur_frm.doc.item_template
                    },
                    callback: function (r) {
                        if (r.message.error) {
                            frappe.msgprint("Serialized Item Code: <b>"+r.message.error+"</b> is not found. Please contact NPD Team")
                        } 
                        else if (r.message.repack_item_code.error){
                            frappe.msgprint("Error while creating of Repack Item Code: <b>"+r.message.repack_item_code.error+"</b> Please contact NPD Team")
                        } 
                        else {
                            
                            console.log("came to print repack item code");
                            cur_frm.set_value('repack_item_code', r.message.repack_item_code)
                            cur_frm.set_value('manual_repack_item_code',r.message.repack_item_code)
                            cur_frm.set_value('data_attr',r.message.data_attr)
                            cur_frm.refresh_field('repack_item_code');
                            cur_frm.refresh_field('manual_repack_item_code');
                            cur_frm.refresh_field('data_attr');
        
                            const partData = JSON.parse(r.message.part_data);
    
                            frm.doc.njqca_item_component.forEach(row => {
                                const part = partData.find(p => p.name === row.name);
                                if (part) {
                                    frappe.model.set_value(row.doctype, row.name, 'part_item_code', part.part_item_code);
                                    frappe.model.set_value(row.doctype, row.name, 'attr_data', JSON.stringify(part.attr_data)); // Assuming attr_data is stored as a JSON string
                                }
                            });
    
                            frm.refresh_field('njqca_item_component'); // Refresh the child table
                        }
                    }
                });
            }
        }else{
            console.log('item_template is empty...')
        }
        
    },
    after_save:function(frm){
        frappe.call({
            method: 'nj_features.nj_features.doctype.njqca.njqca.after_save_njqca',
            args: {
                'docname': cur_frm.doc.name
            },
            callback: function(r) {
                if (r.message) {
                    console.log("after save njqca method executed successfully.");
                }
            }
        });
        // if(cur_frm.doc.item_code && cur_frm.doc.repack_item_code){
        //     if(cur_frm.doc.item_code == cur_frm.doc.repack_item_code){
        //         console.log("repack item code and item code are same");
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