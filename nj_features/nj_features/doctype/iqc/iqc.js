// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('IQC', {
    onload: function(frm) {
        if (cur_frm.doc.iqc_item_component) {
            frm.get_field('iqc_item_component').grid.cannot_add_rows = true;
        }
        
        if (cur_frm.doc.purchase_receipt) {
            frm.events.purchase_receipt(frm);
        }

        if (cur_frm.doc.serial_no) {
            frm.events.serial_no(frm);
        }
        
        if (cur_frm.doc.serial_no) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.iqc.iqc.generate_and_save_barcode',
                args: {"serial_no": cur_frm.doc.serial_no},
                callback: function(r) {
                    frm.set_value('barcode_svg', r.message.barcode_img);
                }
            });
        }
    },
    refresh: function(frm) {
        if (cur_frm.doc.iqc_item_component) {
            cur_frm.fields_dict.iqc_item_component.grid.grid_pagination.page_length = 110;
            cur_frm.refresh_fields('fields');
        }
        
        if(!frm.doc.item_code){
            frm.events.purchase_receipt(frm);
        }
        
        if (!frm.doc.item_template) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.iqc.iqc.get_templates_by_model_and_brand',
                args: {"model": cur_frm.doc.model, "brand": cur_frm.doc.brand, "item_group": cur_frm.doc.item_group},
                callback: function(r) {
                    frm.set_value('item_template', r.message);
                }
            });
        }
        cur_frm.set_df_property('original_price', 'hidden', 1);
    },
    purchase_receipt: function(frm) {
        if (cur_frm.doc.purchase_order) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.iqc.iqc.get_po_from_pr',
                args: {'pr': frm.doc.purchase_receipt},
                callback: function(r) {
                    frm.set_value('purchase_order', r.message.po);
                    r.message.item_code.unshift('');
                    var options = r.message.item_code.join('\n');
                    frm.set_df_property('item_code', 'options', options);
                }
            });
        }
    },
    purchase_order: function(frm) {
        frm.set_query('purchase_receipt', function() {
            return {
                filters: {
                    "purchase_order": frm.doc.purchase_order
                }
            };
        });
    },
    // item_code: function(frm){
    //     frappe.call({
    //         method: 'nj_features.nj_features.doctype.iqc.iqc.get_price_for_item_code',
    //         args: {"item_code":cur_frm.doc.item_code, "pr":cur_frm.doc.purchase_receipt},
    //         callback: function(r) {
    //             console.log("get_price_for_item_code: ", r);
    //             frm.set_value('base_price',r.message)
    //         }
    //     })
    // },
    serial_no: function(frm) {
        if (frm.doc.serial_no) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.iqc.iqc.get_info_from_serial_no',
                args: {'serial_no': frm.doc.serial_no},
                callback: function(r) {
                    frm.set_value('item_code',r.message.item_code);
                    frm.set_value('item_group',r.message.item_group);
                    frm.set_value('brand',r.message.brand);
                    frm.set_value('source_warehouse',r.message.warehouse);
                    frm.set_value('target_warehouse',r.message.warehouse);
                    frm.set_value('base_price',r.message.valuation_rate);
                    cur_frm.refresh_fields('fields');
                }
            });
        }
    },
    
	onload_post_render: function(frm) {
	    
        if (cur_frm.doc.iqc_item_component) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.iqc.iqc.get_part_mapping',
                args: { 'item_group': frm.doc.item_group },
                callback: function (r) {
                    if (r.message) {
                        var lastVariantValues = {};
                        r.message.forEach(function (mapping) {
                            frm.doc.iqc_item_component.forEach(function (row) {
                                var itemGroup = row.item_group;
                                var variants = mapping.mappng_fields.split('::');
                                if (itemGroup === mapping.item_group && variants.every(variant => row.hasOwnProperty(variant))) {
                                    variants.forEach(function (variant) {
                                        if (row.hasOwnProperty(variant)) {
                                            lastVariantValues[itemGroup] = lastVariantValues[itemGroup] || {};
                                            lastVariantValues[itemGroup][variant] = row[variant];
                                        }
                                    });
                                    
                                    var attributeValue = lastVariantValues[itemGroup];
                                    var attributeObject = {};
                                    
                                    frappe.model.set_value(row.doctype, row.name, 'attr_data', {});
                                    
                                    if (Object.keys(attributeValue).length > 1) {
                                        // Construct the dictionary directly
                                        attributeObject[mapping.attribute_name] = Object.values(attributeValue).join(' - ');
                                        row.attr_data = JSON.stringify(attributeObject);
                                        // console.log("if attributeObject: ", row.attr_data);
                                        frappe.model.set_value(row.doctype, row.name, 'attr_data', row.attr_data);
                                    } else {
                                        if (itemGroup.toLowerCase() === 'laptop ram'&& row.variant_1 === 'SYSTEM MEMORY') {
                                            // console.log("ram row.attr_data laptop ram: ", row.attr_data, row.variant_1);
                                            // Construct the dictionary directly
                                            attributeObject[mapping.attribute_name] = attributeValue[Object.keys(attributeValue)[0]];
                                            row.attr_data = JSON.stringify(attributeObject);
                                            frappe.model.set_value(row.doctype, row.name, 'attr_data', row.attr_data);
                                        } else if (itemGroup.toLowerCase() === 'laptop storage' && (!row.variant_3 ^ !row.variant_1) && attributeValue[Object.keys(attributeValue)[0]] !== null) {
                                            // console.log("storage row.attr_data: ", row.attr_data, "variant_1", row.variant_1, !row.variant_3, !row.variant_1);
                                            // Construct the dictionary directly
                                            attributeObject[mapping.attribute_name] = attributeValue[Object.keys(attributeValue)[0]] + " SSD";
                                            row.attr_data = JSON.stringify(attributeObject);
                                            frappe.model.set_value(row.doctype, row.name, 'attr_data', row.attr_data);
                                        } else {
                                            // console.log("else row.attr_data: ", row.attr_data);
                                            frappe.model.set_value(row.doctype, row.name, 'attr_data', '');
                                        }
                                    }
                                }
                            });
                        });
                        frm.refresh_field('iqc_item_component');
                    }
                }
            });
        }
            
        if (frm.doc.repack_item_code) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.iqc.iqc.set_value_for_pricing',
                args: {'self': cur_frm.doc},
                callback: function(r) {
                    console.log("from before_save: ", r.message);
                    frm.set_value('base_price', r.message.base_price);
                    frm.set_value('repack_itm_price', r.message.repack_itm_price);
                    frm.set_value('original_price', r.message.original_price);
                    cur_frm.refresh_fields('fields');
                }
            });
        }
        
        cur_frm.set_value('data_attr', '');
        if (cur_frm.doc.iqc_item_component) {
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
        
        if (cur_frm.doc.data_attr) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.iqc.iqc.get_variant_from_value',
                args: { 'template': frm.doc.item_template, 'args': frm.doc.data_attr },
                callback: function (r) {
                    // console.log("get_variant_from_value: ",r);
                    frm.set_value('repack_item_code', r.message);
                    cur_frm.refresh_fields('fields');
                }
            });
        }
	},

    validate: function(frm) {
        
        var requiredFields = ['purchase_order', 'item_code', 'purchase_receipt', 'serial_no', 'item_group', 'source_warehouse', 'target_warehouse', 'brand', 'model', 'make'];
        var errorMessages = [];
    
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
        
        if (errorMessages.length > 0) {
            frappe.utils.play_sound("error");
            var errorMessageString = errorMessages.join(', ') + " not filled";
    
            var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
            $(frm.wrapper).find('.form-message.blue').remove();
            $(frm.layout.wrapper).prepend(errorDiv);
            frm.set_value('error_message', errorMessageString);
            frm.set_df_property('error_section_section', 'hidden', 0);
            frm.fields_dict.error_message.$input.css('height', '50px');
            frappe.validated = false;
        }
    
        if ($(frm.layout.wrapper).find('.form-message.red').length > 1) {
            $(frm.layout.wrapper).find('.form-message.red').last().remove();
        }
        
    },
    before_submit: function(frm){
        frm.events.validate(frm);
    }
});