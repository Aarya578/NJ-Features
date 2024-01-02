// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('IQC', {
    onload: function(frm) {
        frm.get_field('iqc_item_component').grid.cannot_add_rows = true;
        $('.col-lg-2.layout-side-section').hide();
    },
    refresh: function(frm) {
        if (frm.doc.iqc_item_component) {
            frm.doc.iqc_item_component.forEach(function (row) {
                var child = locals[row.doctype][row.name];
                handleItemGroupChange(frm, row.doctype, row.name);
            });
        }
        cur_frm.fields_dict.iqc_item_component.grid.grid_pagination.page_length = 100;
        cur_frm.refresh_fields('fields');
    },
    purchase_receipt: function(frm) {
        frappe.call({
            method: 'nj_features.nj_features.doctype.iqc.iqc.get_po_from_pr',
            args: {'pr': frm.doc.purchase_receipt},
            callback: function(r) {
                console.log("get_po_from_pr: ",r)
                frm.set_value('purchase_order', r.message.po)
                frm.set_df_property('item_code','options', r.message.item_code)
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
            // frappe.call({
            //     method: 'nj_features.nj_features.doctype.iqc.iqc.get_base_rate',
            //     args: {'serial_no': frm.doc.serial_no},
            //     callback: function(r) {
            //         console.log("base price: ", r.message)
            //         frm.set_value('base_price',r.message)
            //     }
            // })
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
// 	        if(new_itm_code) {
// 	            frappe.db.get_value('Item', {'item_code': new_itm_code}, 'valuation_rate', function (r) {
// 	                if(r && r.valuation_rate) {
// 	                    console.log('valuation_rate: ',r.valuation_rate)
// 	                    frm.set_value('repack_itm_price', r.valuation_rate);
// 	                }
// 	            });
// 	        }
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
//     	            console.log("original_price: ", r.message);
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
                    // Log the fieldname to the console for debugging
                    console.log('Fieldname found:', fieldname);
                    frm.fields_dict[fieldname].$wrapper.addClass('has-error');
                } else {
                    // Log the fieldname to the console for debugging
                    console.log('Fieldname not found:', fieldname);
                }
                errorMessages.push(__("{0}", [fieldLabel]));
            }
        }
    
        if (errorMessages.length > 0) {
            var errorMessageString = errorMessages.join(', ') + " not filled";
            
            var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
            $(frm.wrapper).find('.form-message.blue').remove();
            $(frm.layout.wrapper).prepend(errorDiv);
            frm.set_value('error_message', errorMessageString);
            frm.set_df_property('error_section_section', 'hidden', 0);
            frm.fields_dict['error_message'].$input.css('height', '50px');
            frappe.validated = false;
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
//     }
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
