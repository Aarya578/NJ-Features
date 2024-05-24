// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('NJQCA', {
    onload: function(frm) {
        if (cur_frm.doc.serial_no && cur_frm.doc.docstatus ==0 && cur_frm.doc.power_on == 'Yes') {
            frm.events.serial_no(frm);
         
        }
        if (!cur_frm.doc.model) {
            if (!frm.doc.manufacturer_model) {
                frappe.msgprint("Manufacturer Model is not found")
                return
            }
            get_model(frm.doc.manufacturer_model, frm.doc.make);
        } else {
            frm.set_df_property('model', 'read_only', 1)
        }


        frm.fields_dict['njqca_item_component'].grid.get_field('part_item_code').get_query = function(doc, cdt, cdn) {
            
            
            var row = locals[cdt][cdn];

            console.log('row value is ',row);
            if(row.variant_1 && row.variant_1 != '[EMPTY]' && row.variant_1 != 'SYSTEM MEMORY'){
                return {
                    filters: {
                        item_group: row.item_group,
                        has_variants: 0
                    }
                    
                };
            }            
            else{
                frm.refresh_field("part_item_code");
            }
           
		};

        frm.set_query('manual_repack_item_code', function(r) {
            return {
                filters: {
                    item_group : frm.doc.item_group,
                    has_variants: 0
                }
                
            }
        });
    },
    refresh: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        $(frm.layout.wrapper).find('.form-message.red').remove();
        frm.events.power_on();

        if(cur_frm.doc.bios_serialno){
            cur_frm.set_df_property('cur_frm.doc.bios_serialno', 'read_only', 1)
        }

        if(cur_frm.doc.error_message != ''){
            cur_frm.set_df_property('error_section_section', 'hidden', 0)
        }
        // frm.fields_dict['njqca_item_components'].grid.grid_rows.forEach(function(row) {
        //     var child_doc = row.doc;
        //     console.log('47 working ',child_doc);
        //     // Check if the variant_1 field is empty
        //     // if () {
        //     //     // Set the read-only property for the part_item_code field
        //     //     row.fields_dict['part_item_code'].set_read_only(true);
        //     // } else {
        //     //     // Set the part_item_code field as editable
        //     //     row.fields_dict['part_item_code'].set_read_only(false);
        //     // }
        // });

    },
    // barcode:function(frm){
	// 	$("input[data-fieldname='barcode']").on('blur', function() {
	// 		var inputValue = $(this).val();
	// 		if ((inputValue)) {
	// 			get_itm_code_on_barcode(frm)
	// 			// fill_nj_quality_reading_from_serial_or_itm_wizard(frm)
	// 		} 
	// 		else{ $(this).val(''); }
	// 	});
	// },
    // :function(frm){
    //     $("input[data-fieldname='serial_no']").on('blur', function() {
    //         var inputValue = $(this).val();
    //         if (inputValue) {
    //             frappe.call({
    //                 method: "nj_features.doctype.njqca.njqca.get_itm_code_on_barcode",
    //                 args: {
    //                     barcode: inputValue
    //                 },
    //                 callback: function(r) {
    //                     if (r.message) {
    //                         var data = r.message;
    //                         frm.set_value("item_code", data.item_code);
    //                         frm.set_value("bios_serial_number", data.bios_serial_number);
    //                         frm.set_value("item_group", data.item_group);
    //                         frm.set_value("item_name", data.item_name);
    //                         frm.set_value("warehouse", data.warehouse);
    //                         frm.set_value("base_price", data.base_price);
    //                         frm.set_value("preferred_a_grade_price", data.preferred_a_grade_price);
    
    //                         for (var key in data.attribute_values) {
    //                             if (data.attribute_values.hasOwnProperty(key)) {
    //                                 frm.set_value(key, data.attribute_values[key]);
    //                             }
    //                         }
    
    //                         if (data.disable_save) {
    //                             frm.disable_save();
    //                         } else if (data.enable_save) {
    //                             frm.enable_save();
    //                         }
    //                     }
    //                 }
    //             });
    //         } else {
    //             $(this).val('');
    //         }
    //     });    
    // },
    power_on: function() {
            const isYes = cur_frm.doc.power_on === "Yes";
            const isNone = cur_frm.doc.power_on === "";
            cur_frm.set_df_property('iqc_section', 'hidden', !isYes);
            cur_frm.set_df_property('section_break_6sw2s', 'hidden', isNone || 0);
            cur_frm.set_df_property('section_break_56eed', 'hidden', !isYes);
            cur_frm.set_df_property('warehouse', 'hidden', !isYes);
            cur_frm.set_df_property('repack_item_code', 'hidden', !isYes);
            cur_frm.set_df_property('model', 'hidden', !isYes);
            // if (isYes) {
                // cur_frm.events.validate(cur_frm)
            // }
            
    },
    serial_no: function(frm) {
        if (cur_frm.doc.serial_no && cur_frm.doc.power_on == 'Yes') {
            // console.log("serial_no is triggered");
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_info_from_serial_no',
                args: {'doc': cur_frm.doc},
                callback: function(r) {
                    
                    console.log("r value is ",r);
                    const fieldsToUpdate = ['item_group', 'brand', 'warehouse', 'base_price', 'item_code'];
                    if(!r.message.brand){
                        
                        frappe.throw(`Brand is not filled in Serial no: <b>${cur_frm.doc.serial_no}</b>. Please contact the NPD Team.`);
                    } 
                    fieldsToUpdate.forEach(field => {
                        console.log(field, " : ",r.message[field]);                      
                        if (!frm.doc[field]) {
                            frm.set_value(field, r.message[field]);
                            cur_frm.refresh_field(field);
                        }
                    });
                    let ware = r.message.warehouse
                    frappe.db.get_value('Employee', {'user_id': frappe.session.user_email}, 'work_warehouse', function(r) {
                       
                        console.log("work warehouse: ", r.work_warehouse, "| ware from serial no: ", ware);
                        if (!r.work_warehouse) {
                            frappe.msgprint(`Work Warehouse is not set for employee: ${frappe.session.user_email}. Please mail to <b>IT Infra Team</b> at <strong><a href="mailto:itinfra@newjaisa.com">itinfra@newjaisa.com</a></strong> to create an employee.`)
                        }
                        else if (r.work_warehouse != ware) {
                            console.log("79 work warehouse: ", r.work_warehouse)
                            let d = frappe.confirm(
                            `Do you want to transfer stock to your Work Warehouse: ${r.work_warehouse}?`,
                                () => {

                                        let stock_repack_item = [{
                                            'item_code': frm.doc.item_code,
                                            'basic_rate': frm.doc.base_price,
                                            'serial_no': frm.doc.serial_no
                                        }];
    
                                        let data = {
                                            "serial_no": frm.doc.serial_no,
                                            "stock_entry_type": "Material Transfer",
                                            "s_warehouse": frm.doc.warehouse,
                                            "t_warehouse": r.work_warehouse,
                                            "series": "NJ-STE-NJQCA-",
                                            "reference_serial_no": frm.doc.serial_no,
                                            "doctype": frm.doc.doctype,
                                            "stock_entry_for_material_transfer_or_repack_items": stock_repack_item,
                                        }
                                        console.log("data", data);
                                        frappe.call({
                                            method: 'nj_lib.utils.stock_entry.stock_entry_using_nj_lib',
                                            args: { 'data': JSON.stringify(data) },
                                            error: function(err) {
                                                console.log(err);
                                            }
                                        })
                                        console.log('r value is ', r)
                                        console.log("work warehouse: ", r.work_warehouse, "| ware from serial no: ", ware);
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
        }
    },

    model: function(frm) {
        var selectedModel = frm.doc.model;
        if (selectedModel) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.inward.inward.fetch_model_description',
                args: {
                    'model': selectedModel
                },
                callback: function(r) {
                    $('.desc').remove();
                    if (r.message && r.message.model_description) {
                        var description = r.message.model_description;
                         var htmlContent = `<div class='desc'><strong>Model Description: </strong> ${description}</div>`;
                        $(frm.fields_dict['model'].wrapper).append(htmlContent);

                    }
                }
            });
        }
        if(cur_frm.doc.error_message != ''){
            cur_frm.set_df_property('cur_frm.doc.error_message', 'hidden', 0)
        }
    },
    
	onload_post_render: function(frm) {
        // console.log("empty error ", cur_frm.doc.error_message);
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
                            console.log("model exist", r.message.model);
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

    after_save: function() {
        if (cur_frm.doc.njqca_item_component && cur_frm.doc.docstatus == 0 && cur_frm.doc.power_on == 'Yes') {
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_part_mapping',
                args: { 
                    'item_group': cur_frm.doc.item_group,
                    'docname': cur_frm.doc.name,
                },
                callback: function (r) {
                    console.log("on save", r);
                    if (r.message.error) {
                        frappe.msgprint("Serialized Item Code: <b>"+r.message.error+"</b> is not found. Please contact NPD Team")
                        frappe.validated = false
                    } else {
                        cur_frm.set_value('repack_item_code', r.message)
                        cur_frm.set_value('manual_repack_item_code',r.message)
                        cur_frm.set_value("created",cur_frm.doc.owner);
                        console.log("The created user value is done ");
                    }
                }
            })
        }
    }
});

// function get_itm_code_on_barcode(frm) {
//     frm.set_value("bios_serial_number", '');
//     if (frm.doc.barcode) {

//         frappe.call({
//             method: "frappe.client.get",
//             args: {
//                 doctype: "Serial No",
//                 filters: { name: frm.doc.barcode },
//             },
//             callback: function(r) {
//                 if (r.message) {
//                     let serial_no_data = r.message;
//                     // console.log("serial no data: ", serial_no_data);
//                     frm.set_value("item_code", serial_no_data.item_code);
//                     frm.set_value("bios_serial_number", serial_no_data.bios_serial_no);
//                     frm.set_value("item_group", serial_no_data.item_group);
//                     frm.set_value("item_name", serial_no_data.item_name);
//                     frm.set_value("warehouse", serial_no_data.warehouse);
//                     frm.set_value("base_price", serial_no_data.purchase_rate);

// 					// console.log("frm.doc.barcode", cur_frm.doc.barcode);
// 					frappe.db.get_value('Item Group', { 'name': frm.doc.item_group }, 'is_component', function(r) {
// 						// console.log("is_component: ", r, frm.doc.item_group );
// 						if (r.is_component == 0) {
			
// 							frappe.call({
// 								method: "nj_p1_features.nj_p1_features.doctype.nj_quality_inspection.nj_quality_inspection.update_total_preferred_grade_a",
// 								args: { barcode: frm.doc.barcode },
// 								callback: function(r) {
// 									// console.log("----------==", r.message.attribute_values);
// 									let attribute_values = r.message.attribute_values
// 									frm.set_value('preferred_a_grade_price', r.message.preferred_a_grade_price)
// 									for (let key in attribute_values) {
// 										frm.set_value(key, attribute_values[key]);
// 									}
// 								}
// 							})
// 						}
// 					})

//                     let current_date = new Date();
//                     let serial_item_date = new Date(r.message.purchase_date);
//                     let difference = current_date.getTime() - serial_item_date.getTime();

//                     if (((r.message.item_group == "laptops" || r.message.item_group == "desktops" || r.message.item_group == "chromebooks" ||
//                             r.message.item_group == "chromeboxes") && difference < 0) && r.message.purchase_date > "2024-03-20"
//                     ) {
//                         if (r.message.bios_serial_no && r.message.bios_serial_no.startsWith('nj') && r.message.bios_serial_no === frm.doc.barcode) {
//                             frappe.msgprint("Barcode and BIOS serial number should not both start with 'nj' and be identical. Please insert Dongle and run.");
//                             frm.disable_save();
//                         } else if (r.message.bios_serial_no && r.message.bios_serial_no != frm.doc.barcode) {
//                             frm.enable_save();
//                         } else if (!r.message.bios_serial_no && r.message.bios_serial_no != frm.doc.barcode) {
//                             frappe.msgprint("BIOS serial number not found for Serial No: <b>" + frm.doc.barcode + "</b>. Please insert Dongle and run.");
//                             frm.disable_save();
//                         }
//                     }

//                     if (r.message.warehouse) {
//                         let ware = r.message.warehouse
//                         frappe.db.get_value('Employee', { 'user_id': frappe.session.user_email }, 'work_warehouse', function(r) {
//                             console.log("work: ", r.work_warehouse, "| ware: ", ware);
//                             if (!r.work_warehouse) {
//                                 frappe.msgprint(`Work Warehouse is not set for Employee: <b>${frappe.session.user_email}</b>`)
//                             } else if (r.work_warehouse != ware) {
//                                 let d = frappe.confirm(
//                                     `Do you want to transfer stock to your Work Warehouse: <b>${r.work_warehouse}?</b>`,
//                                     () => {
// 										let stock_entry_items = [{
// 											'item_code': frm.doc.item_code,
// 											'basic_rate': frm.doc.base_price,
// 											'serial_no': frm.doc.barcode
// 										}];

//                                         let data = {
//                                             "serial_no": frm.doc.barcode,
//                                             "stock_entry_type": "Material Transfer",
//                                             "t_warehouse": r.work_warehouse,
//                                             "series": "STE-NJ-QI-",
//                                             "reference_serial_no": frm.doc.serial_no,
//                                             "doctype": frm.doc.doctype,
// 											"stock_entry_for_material_transfer_or_repack_items": stock_entry_items
//                                         }
//                                         frappe.call({
//                                             method: 'nj_lib.utils.stock_entry.stock_entry_using_nj_lib',
//                                             args: { 'data': JSON.stringify(data) },
//                                             error: function(err) {
//                                                 console.log(err);
//                                             }
//                                         })
//                                         frm.set_value('warehouse', r.work_warehouse)
//                                         d.hide()
//                                     },
//                                     () => {
//                                         $('.primary-action').hide()
//                                     }
//                                 );
//                             }
//                         })
//                     } else {
//                         frappe.msgprint("Warehouse is not updated in Serial No: <b>" + frm.doc.barcode + "</b>");
//                         frm.disable_save();
//                     }

//                 } else {
//                     frm.set_value("barcode", null);
//                     frappe.msgprint(`Serial No <b>'${frm.doc.barcode}'</b> not found. Please select an existing Serial No.`);
//                 }
//             },
//             error: function(r) {
//                 frm.set_value("item_group", null);
//             }

//         });
    
        

//     }
// }


function get_model(manufacturer_model, make) {
    frappe.call({
        method: 'nj_features.nj_features.doctype.njqca.njqca.get_model',
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
                            'border': '2px solid rgba(173, 216, 230, 0.5)'
                        });
                        // Show alert for selecting model
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