// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('IQC', {
    onload: function(frm) {
        if (cur_frm.doc.serial_no && cur_frm.doc.docstatus !=1 && cur_frm.doc.power_on == 'Yes') {
            frm.events.serial_no(frm);
        }
        if (!cur_frm.doc.model) {
            get_model(frm.doc.manufacturer_model, frm.doc.make);
        }
    },

    refresh: function(frm) {
        $(frm.layout.wrapper).find('.form-message.red').remove();
        frm.events.power_on();
        
        if (!cur_frm.doc.warehouse && cur_frm.doc.power_on == 'Yes') {
            // frm.events.serial_no(frm)
            cur_frm.refresh_fields('warehouse');
        }

        if(cur_frm.doc.bios_serialno){
            cur_frm.set_df_property('cur_frm.doc.bios_serialno', 'read_only', 1)
        }

        // if (!frm.doc.item_template && cur_frm.doc.brand && cur_frm.doc.model && cur_frm.doc.power_on == 'Yes') {
        //     frappe.call({
        //         method: 'nj_features.nj_features.doctype.iqc.iqc.get_templates_by_model_and_brand',
        //         args: {"model": cur_frm.doc.model, "brand": cur_frm.doc.brand, "item_group": cur_frm.doc.item_group},
        //         callback: function(r) {
        //             frm.set_value('item_template', r.message);
        //         }
        //     });
        // }
        

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
            cur_frm.set_df_property('bios_serialno', 'hidden', !isYes);
            if (isYes) {
                // cur_frm.events.validate(cur_frm)
            }
            
    },
    serial_no: function(frm) {
        if (cur_frm.doc.serial_no && cur_frm.doc.power_on == 'Yes') {
            // console.log("serial_no is triggered");
            frappe.call({
                method: 'nj_features.nj_features.doctype.iqc.iqc.get_info_from_serial_no',
                args: {'doc': cur_frm.doc},
                callback: function(r) {
                    const fieldsToUpdate = ['item_group', 'brand', 'warehouse', 'base_price', 'item_code'];
                    fieldsToUpdate.forEach(field => {
                        console.log(field, " : ",r.message[field]);
                        // if (!frm.doc[field]) {
                            frm.set_value(field, r.message[field]);
                            cur_frm.refresh_field(field);
                        // }
                    });
                    let ware = r.message.warehouse
                    frappe.db.get_value('Employee', {'user_id': frm.doc.created}, 'work_warehouse', function(r) {
                        console.log("work: ", r.work_warehouse, "| ware: ", ware);
                        if (!r.work_warehouse) {
                            frappe.msgprint(`Work Warehouse is not set for employee: ${frm.doc.created}`)
                        }
                        else if (r.work_warehouse != ware) {
                            let d = frappe.confirm(
                            `Do you want to transfer stock to your Work Warehouse: ${r.work_warehouse}?`,
                                () => {
                                    makeMaterialTransfer(frm.doc.name, r.work_warehouse)
                                    frm.set_value('warehouse', r.work_warehouse)
                                    d.hide()
                                },
                                () => {
                                    $('.primary-action').hide()
                                }
                            );
                        }
                    })
                        
    
                }
            });

            frappe.call({
                method: 'nj_features.nj_features.doctype.iqc.iqc.generate_and_save_barcode',
                args: {"serial_no": cur_frm.doc.serial_no},
                callback: function(r) {
                    frm.set_value('barcode_svg', r.message.barcode_img);
                    frappe.show_alert({
                        message: __(`Barcode is generated for Barcode/Serial No: ${cur_frm.doc.serial_no}`),
                        indicator: 'green'
                    });
                }
            });
        }

        // if (!cur_frm.doc.serial_no && cur_frm.doc.power_on == 'Yes') {
        //     const d = frappe.confirm('Are you sure you want to generate serial no?',
        //     () => {
        //         frappe.call({
        //             method: 'nj_features.nj_features.doctype.iqc.iqc.create_serial_no',
        //             args: { 'item_code': cur_frm.doc.item_code},
        //             callback: function (r) {
        //                 frm.set_value('serial_no', r.message);
        //                 cur_frm.refresh_fields('fields');
        //             }
        //         });
        //     }, () => {
        //     })
        // }
    },

    model: function(frm) {
        frm.set_value('repack_item_code', "")
        let temp = 'S-'+cur_frm.doc.brand+'-'+cur_frm.doc.model
        frappe.call({
            method: 'nj_features.nj_features.doctype.iqc.iqc.get_variant_from_value',
            args: { 'item_template': frm.doc.item_template || temp, 'args': cur_frm.doc.data_attr},
            callback: function (r) {
                // console.log("get_variant_from_value : ", r.message)
                if (r.message){
                    frm.set_value('repack_item_code', r.message)
                }
                cur_frm.refresh_fields('fields');
            }
        });
    },
    
	onload_post_render: function(frm) {
        if (cur_frm.doc.error_message == "") {
            $(frm.layout.wrapper).find('.form-message.red').remove()
        }

        if (!cur_frm.doc.repack_item_code && cur_frm.doc.docstatus ==0 && cur_frm.doc.power_on == 'Yes' 
        && cur_frm.doc.brand && cur_frm.doc.model) {
            let temp = 'S-'+cur_frm.doc.brand+'-'+cur_frm.doc.model
            frappe.call({
                method: 'nj_features.nj_features.doctype.iqc.iqc.get_variant_from_value',
                args: { 'item_template': frm.doc.item_template || temp, 'args': cur_frm.doc.data_attr},
                callback: function (r) {
                    if (r.message){
                        frm.set_value('repack_item_code', r.message)
                    }
                    cur_frm.refresh_fields('fields');
                }
            });
        }

	    if (cur_frm.doc.docstatus ==0 && cur_frm.doc.power_on == 'Yes') {
            if (cur_frm.doc.iqc_item_component && cur_frm.doc.item_group) {
                frappe.call({
                    method: 'nj_features.nj_features.doctype.iqc.iqc.get_part_mapping',
                    args: { 'item_group': cur_frm.doc.item_group },
                    callback: function (r) {
                        if (r.message) {
                            var lastVariantValues = {};
                            console.log("get_part_mapping",r.message);
                            r.message.values.forEach(function (param) { //get value from NJ Settings
                                window[param.parameter] = param.value;
                            });

                            r.message.mappings.forEach(function (mapping) {   // for each part in Item Group mapping (3)
                                frm.doc.iqc_item_component.forEach(function (row) {    // iterate elements in iqc child table
                                    var itemGroup = row.item_group;
                                    var variants = mapping.mappng_fields.split('::');
                                    
                                    if (itemGroup === mapping.item_group) {

                                        variants.forEach(function (variant) {
                                            lastVariantValues[itemGroup] = lastVariantValues[itemGroup] || {};
                                            lastVariantValues[itemGroup][variant] = row[variant];
                                        });
                                        
                                        var attributeValue = lastVariantValues[itemGroup];
                                        var attributeObject = {};
                                        

                                        frappe.model.set_value(row.doctype, row.name, 'attr_data', {});
                                        if (itemGroup.toLowerCase() == cpu.toLowerCase()) {
                                            var anyAttributeUndefined = Object.values(attributeValue).some(value => value === undefined);
                                            var cpuValue = anyAttributeUndefined ? unk_cpu : Object.values(attributeValue).join(' - ');
                                            attributeObject[mapping.attribute_name] = cpuValue;
                                            row.attr_data = JSON.stringify(attributeObject);
                                            frappe.model.set_value(row.doctype, row.name, 'attr_data', row.attr_data);
                                        } 
                                        else if (itemGroup.toLowerCase() == ram.toLowerCase()  && row.variant_1 == 'SYSTEM MEMORY') {
                                            attributeObject[mapping.attribute_name] = attributeValue[Object.keys(attributeValue)[0]] || unk_ram;
                                            var ramValue = JSON.stringify(attributeObject);
                                            frappe.model.set_value(row.doctype, row.name, 'attr_data', ramValue);
                                        } 
                                        else if (itemGroup.toLowerCase() == storage.toLowerCase() && (!row.variant_3 ^ !row.variant_1) && attributeValue[Object.keys(attributeValue)[0]] !== undefined) {
                                            // console.log("storage: ", row.attr_data, "variant_1", row.variant_1, !row.variant_3 ^ !row.variant_1, storage, unk_storage);
                                            attributeObject[mapping.attribute_name] = attributeValue[Object.keys(attributeValue)[0]] + " SSD" || unk_storage;
                                            var sValue = JSON.stringify(attributeObject);
                                            frappe.model.set_value(row.doctype, row.name, 'attr_data', sValue);
                                        } 
                                        else {
                                            frappe.model.set_value(row.doctype, row.name, 'attr_data', '');
                                        }
                                    }
                                });
                            });
                            frm.refresh_field('iqc_item_component');
                        }
                    }
                });
            }
            
            if (cur_frm.doc.iqc_item_component && cur_frm.doc.docstatus !=1 && cur_frm.doc.power_on == 'Yes') {
                cur_frm.set_value('data_attr', '');
                var child_attr_data = [];
                frm.doc.iqc_item_component.forEach(function (row) {
                    // console.log("row: ", row);
                    if (row.attr_data) {
                        child_attr_data.push(JSON.parse(row.attr_data));
                    }
                });
                // console.log("child_attr_data: ", child_attr_data);
                cur_frm.set_value('data_attr', JSON.stringify(child_attr_data));
                cur_frm.refresh_fields('fields');
            }
    
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
        }
        if (cur_frm.doc.model && cur_frm.doc.make && cur_frm.doc.manufacturer_model) {
            get_model(cur_frm.doc.manufacturer_model, cur_frm.doc.make)
            frm.events.validate(frm)
        }
	},

    validate: function(frm) {
        var requiredFields = ['serial_no',
        'item_group', 'warehouse', 'brand', 'make'];
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
                    method: 'nj_features.nj_features.doctype.iqc.iqc.brand_model_validation',
                    args: {'brand': cur_frm.doc.brand, 'model': cur_frm.doc.model},
                    callback: function(r) {
                        if (cur_frm.doc.brand && !r.message.brand) {
                            dbError.push("Brand: "+cur_frm.doc.brand);
                        }
        
                        if (cur_frm.doc.model && !r.message.model) {
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

    before_save: function(frm) {
        if (cur_frm.doc.repack_item_code == "" || cur_frm.doc.repack_item_code == undefined) {
            frappe.msgprint("You are not allowed to save IQC without Repack Item")
            frappe.validated = false;
        }
    }
});

function makeMaterialTransfer(doc, work_warehouse) {
    frappe.call({
        method: 'nj_features.nj_features.material_transfer.material_transfer',
        args: {'doc': doc, 'work_warehouse':work_warehouse}
    })
}

function get_model(manufacturer_model, make) {
    frappe.call({
        method: 'nj_features.nj_features.doctype.iqc.iqc.get_model',
        args: { 'manufacturer_model': manufacturer_model, 'make': make },
        callback: function(r) {
            if (r.message) {
                var model_list = r.message;
                if (Array.isArray(model_list) && model_list.length > 0) {
                    if (model_list.length === 1) {
                        // Set value and make read-only if only one model
                        cur_frm.set_value('model', model_list[0].model);
                        cur_frm.set_df_property('model', 'read_only', 1);
                    } else {
                        // Set options and focus on model field if multiple models
                        var options = model_list.map(function(item) {
                            return item.model;
                        }).join('\n');
                        cur_frm.set_df_property('model', 'options', options);
                        $('[data-fieldname="model"]').focus().closest('.control-input').css({
                            'border-radius': '0.25rem',
                            'border': '2px solid rgba(173, 216, 230, 0.2)'
                        });
                        // Show alert for selecting model
                        frappe.show_alert({
                            message: __('Select Model'),
                            indicator: 'green'
                        });
                    }
                } else {
                    // Show message if no models found
                    frappe.msgprint("Model not found for the given manufacturer_model: " + manufacturer_model + " and make: " + make);
                }
            }
        }
    });
}


// function get_model(manufacturer_model, make) {
//     frappe.call({
//         method: 'nj_features.nj_features.doctype.iqc.iqc.get_model',
//         args: { 'manufacturer_model': manufacturer_model, 'make': make },
//         callback: function(r) {
//             // console.log("model list: ", r.message);
//             if (r.message) {
//                 if (Array.isArray(r.message) && r.message.length > 0) {
//                     if (r.message.length === 1) {
//                         cur_frm.set_value('model', r.message[0]);
//                         cur_frm.set_df_property('model', 'read_only', 1);
//                     } else {
//                         var options = r.message.join('\n');
//                         cur_frm.set_df_property('model', 'options', options);
//                         $('[data-fieldname="model"]').focus().closest('.control-input').css({
//                             'border-radius': '0.25rem',
//                             'border': '2px solid rgba(173, 216, 230, 0.2)'
//                         });
                        
//                         frappe.show_alert({
//                             message: __('Select Model'),
//                             indicator: 'green'
//                         });
//                     }
//                 } else {
//                     frappe.msgprint("Model not found for the given manufacturer_model: "+manufacturer_model+" and make: "+make);
//                 }
//             }
//         }
//     });
// }