// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('IQC', {
    onload: function(frm) {
        frm.get_field('iqc_item_component').grid.cannot_add_rows = true;
        $('.col-lg-2.layout-side-section').hide();
    },
    refresh: function(frm) {
        frm.add_custom_button(
            __(`
                <svg xmlns="http://www.w3.org/2000/svg" height="16" width="14" viewBox="0 0 448 512">
                    <!--!Font Awesome Free 6.5.1 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2024 Fonticons, Inc.-->
                    <path d="M0 80C0 53.5 21.5 32 48 32h96c26.5 0 48 21.5 48 48v96c0 26.5-21.5 48-48 48H48c-26.5 0-48-21.5-48-48V80zM64 96v64h64V96H64zM0 336c0-26.5 21.5-48 48-48h96c26.5 0 48 21.5 48 48v96c0 26.5-21.5 48-48 48H48c-26.5 0-48-21.5-48-48V336zm64 16v64h64V352H64zM304 32h96c26.5 0 48 21.5 48 48v96c0 26.5-21.5 48-48 48H304c-26.5 0-48-21.5-48-48V80c0-26.5 21.5-48 48-48zm80 64H320v64h64V96zM256 304c0-8.8 7.2-16 16-16h64c8.8 0 16 7.2 16 16s7.2 16 16 16h32c8.8 0 16-7.2 16-16s7.2-16 16-16s16 7.2 16 16v96c0 8.8-7.2 16-16 16H368c-8.8 0-16-7.2-16-16s-7.2-16-16-16s-16 7.2-16 16v64c0 8.8-7.2 16-16 16H272c-8.8 0-16-7.2-16-16V304zM368 480a16 16 0 1 1 0-32 16 16 0 1 1 0 32zm64 0a16 16 0 1 1 0-32 16 16 0 1 1 0 32z"/>
                </svg>
            `), 
            function() {
                frappe.msgprint("QR Code");
            }
        );
        $("button[data-original-title=Print]").hide();
        if (frm.doc.iqc_item_component) {
            frm.doc.iqc_item_component.forEach(function (row) {
                var child = locals[row.doctype][row.name];
                handleItemGroupChange(frm, row.doctype, row.name);
            });
        }
        cur_frm.fields_dict.iqc_item_component.grid.grid_pagination.page_length = 100;
        cur_frm.refresh_fields('fields');
        if(!frm.doc.__islocal){
            frm.events.purchase_receipt(frm);
        }
    },
    purchase_receipt: function(frm) {
        frappe.call({
            method: 'nj_features.nj_features.doctype.iqc.iqc.get_po_from_pr',
            args: {'pr': frm.doc.purchase_receipt},
            callback: function(r) {
                frm.set_value('purchase_order', r.message.po)
                r.message.item_code.unshift('');
                var options = r.message.item_code.join('\n');
                frm.set_df_property('item_code', 'options', options);
            }
        });
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
                    frm.set_value('base_price',r.message.valuation_rate);
                }
            })
        }
    },
    item_group: function(frm) {
        frappe.call({
            method: 'nj_features.nj_features.doctype.iqc.iqc.set_iqc_child_table',
            args: {'item_group':frm.doc.item_group},
            callback: function(r) {
                r.message.components.forEach(function(row) {
	               var d = frm.add_child('iqc_item_component');
	               frappe.model.set_value(d.doctype, d.name, 'item_group', row.component_name);
	            });
	        frm.refresh_field('iqc_item_component');
            }
        });
    },
// 	before_save: function(frm) {
// 	    if (frm.doc.model && frm.doc.brand) {
//             var new_itm_code = frm.doc.brand + '-' + frm.doc.model;
            
// 	        frappe.call({
//     	        method: 'nj_features.nj_features.doctype.iqc.iqc.get_list_of_variants',
//     	        args: {'item_group': frm.doc.item_group},
//     	        callback: function (r) {
//                     var grid = frm.fields_dict.iqc_item_component.grid;
//                     var rows = grid.grid_rows;
//                     frappe.run_serially([
//                         function() {
//                             for (var i = 0; i < r.message.variants.length; i++) {
//                                 var row = rows[i];
//                                 var columns = row.docfields;
//                                 // console.log("length: ", r.message.variants.length, r, " | j: ", columns.length)
        
//                                 for (var j = 0; j < columns.length; j++) {
//                                     var docfield = cur_frm.fields_dict.iqc_item_component.grid.docfields[j];
//                                     // console.log("docfield: ", docfield.variant ," | variant: ", r.message.variants[i].variant);
        
//                                     // Assuming r.message.variants is an array of variants
//                                     if (docfield.variant == r.message.variants[i].variant) {
//                                         // console.log("Matching variant found in row ", i + 1, " column ", j + 1);
//                                     }
//                                 }
//                             }
//                         }
//                     ])
//     	        }
//     	    });
//     	    //pricing
//     	    frappe.call({
//     	        method: 'nj_features.nj_features.doctype.iqc.iqc.iqc_to_repack_pricing',
//     	        args: {
//     	            'purchase_price': frm.doc.purchase_price,
//     	            'base_price': frm.doc.base_price,
//     	            'repack_itm_price': frm.doc.repack_itm_price || null
//     	        },
//     	        callback: function(r) {
//     	            frm.set_value('original_price', r.message.original_price);
//     	        }
//     	    });
	        
// 	    }
// 	},
  validate: function(frm) {
    var requiredFields = ['purchase_order', 'pr_item', 'purchase_receipt', 'serial_no', 'item_group', 'source_warehouse', 'target_warehouse', 'brand', 'model', 'make', 'repack_item_code'];
    var errorMessages = [];

    for (var i = 0; i < requiredFields.length; i++) {
        var fieldname = requiredFields[i];
        if (!frm.doc[fieldname]) {
            var fieldLabel = frm.fields_dict[fieldname] ? frm.fields_dict[fieldname].df.label : fieldname;
            if (frm.fields_dict[fieldname]) {
                frm.fields_dict[fieldname].$wrapper.addClass('has-error');
            }
            errorMessages.push(fieldLabel);  // Push the field label into the array
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
        frm.fields_dict['error_message'].$input.css('height', '50px');
        frappe.validated = false;
    }

    if ($(frm.layout.wrapper).find('.form-message.red').length > 1) {
        $(frm.layout.wrapper).find('.form-message.red').last().remove();
    }
},

// 	after_save: function (frm) {
//         frappe.call({
//             method: 'nj_features.nj_features.doctype.iqc.iqc.get_list_of_variants',
//             args: { 'item_group': frm.doc.item_group },
//             callback: async function (r) {
//                 console.log("page from call: ", r.message)
//                 var attr_data = {};
//                 async function processRow(index) {
//                     if (index < frm.doc.iqc_item_component.length) {
//                         var filteredData = {};
//                         if(index<r.message.variants.length) {
//                             var itm_parent = r.message.variants[index].variant;
//                         }
//                         console.log("index: ", index, " | itm_parent: ", itm_parent);
//                         var row = frm.doc.iqc_item_component[index];
//                         var child = locals[row.doctype][row.name];
//                         handleItemGroupChange(frm, row.doctype, row.name);
//                         for (var key in child) {
//                             if (key.match(/^variant_\d+$/) && child[key] !== null) {
//                                 var value = child[key];
        
//                                 await new Promise(function (resolve) {
//                                     frappe.call({
//                                         method: 'nj_features.nj_features.doctype.iqc.iqc.get_attribute_parent',
//                                         args: { 'attribute_value': child[key] },
//                                         callback: function (r) {
//                                             var parentValue = r.message[0].attribute_name;
//                                             filteredData[parentValue] = value;
//                                             if(parentValue == itm_parent){
//                                                 attr_data[parentValue] = value;
//                                             }
//                                             resolve();
//                                         }
//                                     });
//                                 });
//                             frappe.model.set_value(row.doctype, row.name, 'attr_data', JSON.stringify(filteredData));
//                             frappe.model.set_value(row.doctype, row.name, 'active', 1)
//                             }
//                         }
//                         await processRow(index + 1);
//                     }
//                 }
//                 await processRow(0);
//                 frm.set_value("attr_data",JSON.stringify(attr_data));
//                 //match item_code
//                 var new_itm_code = frm.doc.brand + '-' + frm.doc.model;
//         	    if(frm.doc.attr_data) {
//         	        frappe.call({
//             	        method: 'erpnext.controllers.item_variant.get_variant',
//             	        args: {
//             	            'template': new_itm_code,
//                             'args': frm.doc.attr_data
//             	        },
//             	        callback: function(r) {
//             	            console.log("from search template: ",r);
//         	                frm.set_value('repack_item_code', r.message);
//             	        }
//             	    });
//         	    } else {
//         	        console.log("args not passed to search variant");
//             	}
//             }
//         });
//     },

    before_submit: function(frm){
        frm.events.validate(frm);
    }
});

frappe.ui.form.on('IQC Child', {
    item_group: function(frm, cdt, cdn) {
        handleItemGroupChange(frm, cdt, cdn);
    }
});

function handleItemGroupChange(frm, cdt, cdn) {
    var row = locals[cdt][cdn];
    frappe.call({
        method: 'nj_features.nj_features.doctype.iqc.iqc.get_list_of_variants',
        args: {'item_group': row.item_group},
        callback: function(r) {
            if (r.message) {
                var variants = r.message.variants;
                var row_len = frm.fields_dict.iqc_item_component.grid.docfields.length;
                for (var i = 0; i < row_len; i++) {
                    var docfield = frm.fields_dict.iqc_item_component.grid.docfields[i];
                    if (i !== 0 && i <= variants.length) {
                        var variant = variants[i - 1].variant;
                        docfield.variant = variant;
                        
                            // var fieldElement = $(`[data-fieldname="${docfield.fieldname}"]`);
                            // fieldElement.attr('title', docfield.variant);
                        
                        fetchOptionsForVariant(docfield, variant, frm, row);
                        refresh_field(docfield);
                    } else if (i > variants.length && i <= row_len) {
                        frm.set_df_property('iqc_item_component', 'read_only', 1, frm.docname, docfield.fieldname, row.name);
                    }
                }
                frm.refresh_field('iqc_item_component');
                
            }
        }
    });
}

function fetchOptionsForVariant(docfield, variant, frm, row) {
    frappe.call({
        method: 'nj_features.nj_features.doctype.iqc.iqc.get_list_of_attributes',
        args: {'variant': variant},
        callback: function(r) {
            if(r.message) {
                var st = frm.set_df_property('iqc_item_component', 'options', r.message.options, frm.docname, docfield.fieldname, row.name);
            }
        }
    });
}
