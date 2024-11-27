// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Inward', {
    onload: function(frm) {
        warehouse_info(frm);
    },
    
    refresh(frm) {
        $('.col-lg-2.layout-side-section').hide();
        
        if (cur_frm.doc.docstatus == 0) {
            frm.events.purchase_receipt(frm);
            if (!cur_frm.doc.purchase_receipt) {
                $('[data-fieldname="purchase_receipt"]').focus();
            } else {
                $('[data-fieldname="brand"]').focus();
            }

            frm.set_query('purchase_receipt', function() {
                return {
                    filters: { "docstatus": ['=', 1] }
                };
            });

            frm.add_custom_button(__('Submit & Next'), function() {
                submitAndNext(frm);
            }).addClass('btn-primary');

            if (frm.doc.brand && frm.doc.model && !frm.doc.item_template) {
                get_item_template(frm)
            }

            if (frm.doc.item_template) {
                frm.set_df_property('item_template', 'read_only', 1);
            }
        }

        if (frm.doc.docstatus == 1) {

            frm.add_custom_button(__('Print QR Code'), function() {
                var docname = encodeURIComponent(frm.doc.name);
                var format = "Inward Barcode";
                var print_trigger = 1;
    
                frappe.call({
                    method: 'nj_features.nj_features.api.qr_code.generate_and_save_qrcode',
                    args: { data: frm.doc.name }
                });
    
                window.open(frappe.urllib.get_full_url("/printview?" +
                "doctype=" + encodeURIComponent("Inward") +
                "&name=" + docname + "&trigger_print=" + print_trigger +
                "&format=" + format + "&no_letterhead=0" +
                "&_lang=" + (frappe.boot.lang || "en")));
                    
            }).addClass('btn-primary');
        }
    },

    purchase_receipt: function(frm) {
        if (cur_frm.doc.purchase_receipt) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.inward.inward.get_item_list_from_pr',
                args: {'pr': frm.doc.purchase_receipt},
                callback: function(r) {
                    if (r.message) {
                        
                        if (r.message.length == 1) {
                            frm.set_value('item_code', r.message[0])
                            frm.set_df_property('item_code', 'read_only', 1);
                        } else {
                            var itemCodes = r.message.map(function(item) {
                                return item;
                            });

                            var options = itemCodes.join('\n');
                            frm.set_df_property('item_code', 'options', options);
    
                            $('[data-fieldname="serial_no"]').focus().closest('.control-input').css({
                                'border-radius': '0.25rem',
                                'border': '2px solid rgba(173, 216, 230, 0.7)'
                            });
                            
                            frappe.show_alert({
                                message: __('Select Item Code(s)'),
                                indicator: 'green'
                            });
                        }
                    } else {
                        frm.set_df_property('item_code', 'options', '');
                    }
                }
            });
        }
    },

    item_template: function(frm) {
        if (frm.doc.item_template) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.inward.inward.get_repack_item_code',
                args: {'item_template': frm.doc.item_template},
                callback: function(r) {
                    if (r.message.repack_item_code) {
                        frm.set_value('repack_item_code', r.message.repack_item_code)
                    } else {
                        frm.set_value('repack_item_code', '')
                        frappe.msgprint("Item Code is not found for brand: <b>"+frm.doc.brand+"</b>, model: <b>"+frm.doc.model+"</b> with unknown attribute. Please contact <b>NPD Team</b>.")
                        frappe.validated = false
                    }
                }
            })
            frm.refresh_field("repack_item_code")
        }
    },

    item_group: function (frm) {
        frappe.db.get_value('NJ Settings', {'parameter': 'inward_allowed_item_groups'}, function(r) {
            if (r && r.message) {
                var allowed_item_groups = r.message;
                if (allowed_item_groups && allowed_item_groups.includes(frm.doc.item_group)) {
                    frm.set_df_property('item_code', 'read_only', 0);
                }
            }
        });
    },

    item_code: function(frm) {
        if (frm.doc.item_code) {
            if (cur_frm.doc.purchase_receipt) {
                frappe.call({
                    method: 'nj_features.nj_features.doctype.inward.inward.get_stock_data_from_pr',
                    args: {'pr': frm.doc.purchase_receipt, 'item_code': frm.doc.item_code},
                    callback: function(r) {
                        if (r.message) {
                            var result = r.message.result;
                            var serialNo = r.message.serial_no;
                            var itemGroup = r.message.item_group;
                            var batch_no =r.message.result.batch_no;

                            if(result) {
                                cur_frm.set_value('base_rate', result.incoming_rate);
                                cur_frm.set_value('source_warehouse', result.warehouse);
                            }
                            if (serialNo) {
                                cur_frm.set_value('serial_no', serialNo);
                            }
                            if (itemGroup) {
                                cur_frm.set_value('item_group', itemGroup);
                            }
                            if(batch_no){
                                cur_frm.set_value('batch_no', batch_no);
                            }
                        }
                    }
                });
            }
        }
    },

    before_save: function(frm) {
        if (!frm.doc.serial_no) {
            frappe.msgprint("Serial number generation failed. Document cannot be saved.");
            frappe.validated = false;
        }
    },

    model: function(frm) {
        if (frm.doc.model) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.inward.inward.fetch_model_description',
                args: { 'model': frm.doc.model },
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
        if (frm.doc.model && frm.doc.brand) {
            get_item_template(frm)
        }
    }
});

function get_item_template(frm) {
    frm.set_value('repack_item_code', '');
    frappe.call({
        method: 'nj_features.nj_features.doctype.inward.inward.create_serial_no_and_get_item_code',
        args: {
            "item_group": frm.doc.item_group,
            "brand": frm.doc.brand,
            "model": frm.doc.model,
            "serial_no": frm.doc.serial_no
        },
        callback: function (r) {
            if (r.message.serial_no && !frm.doc.serial_no) {
                frm.set_value('serial_no', r.message.serial_no);
                frm.refresh_field('serial_no');
            }
            if (r.message.item_template) {
                cur_frm.set_df_property('item_template', 'read_only', 0);
                var template_list = r.message.item_template;
                if (Array.isArray(template_list) && template_list.length > 0) {
                    cur_frm.set_value('item_template', '');
                    if (template_list.length == 1) {
                        cur_frm.set_value('item_template', template_list[0].name);
                        cur_frm.set_df_property('item_template', 'read_only', 1);

                        $('[data-fieldname="item_template"]').closest('.control-input-wrapper').css({
                            'border-radius': '0.25rem',
                            'border': '2px solid rgba(173, 216, 230, 0.5)'
                        });

                        var selectedOption = template_list[0].name;
                        var wizard_list = r.message.wizard_list || [];

                        if (wizard_list.includes(selectedOption)) {
                            $('[data-fieldname="item_template"]').closest('.control-input-wrapper').css('border-color', 'green');
                        } else {
                            $('[data-fieldname="item_template"]').closest('.control-input-wrapper').css('border-color', 'red');
                        }

                        frm.trigger("item_template");
                    } else {
                        var wizard_list = r.message.wizard_list || [];
                        let options = template_list.map(function (item) {
                            return item.name;
                        });

                        cur_frm.set_df_property('item_template', 'options', options);
                        $('[data-fieldname="item_template"]').focus().closest('.control-input-wrapper').css({
                            'border-radius': '0.25rem',
                            'border': '2px solid rgba(173, 216, 230, 0.5)'
                        });

                        frm.fields_dict.item_template.$input.on('change', function () {
                            var selectedOption = $(this).val();
                            $('[data-fieldname="item_template"]').closest('.control-input-wrapper').css('border-color', 'rgba(173, 216, 230, 0.5)');
                            if (wizard_list.includes(selectedOption)) {
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
                }
            } else {
                frappe.msgprint(__("Item Template is not found using <b>Brand: {0}</b>,<br><b>Model: {1}</b>,<br><b>Item Group: {2}</b>.<br>Please contact <b>NPD Team.</b>", [frm.doc.brand, frm.doc.model, frm.doc.item_group]));
                frappe.validated = false;
            }
        }
    });
}

function warehouse_info(frm) {
    if(frm.doc.docstatus == 0){
        let userEmail = frappe.session.user_email;
        frappe.db.get_value('Employee', {'user_id': userEmail, 'status': 'Active'}, ['name', 'work_warehouse'], function(response) {
            if (!response.name) {
                frappe.msgprint('Employee with <strong>'+userEmail+'</strong> not found. Please mail us at <strong><a href="mailto:itsupport@newjaisa.com">itsupport@newjaisa.com</a></strong> to create an employee.');
                return;
            }
            if (response.work_warehouse) {
                frm.set_value('target_warehouse', response.work_warehouse);
            } else {
                frappe.msgprint('Work Warehouse does not exist.');
            }
            frm.set_df_property('target_warehouse', 'read_only', 1);
        });
    }
}

function submitAndNext(frm) {
    frm.save('Submit', function(r) {
        if (!r.exc) {
            let new_inward = frappe.model.copy_doc(frm.doc)
            new_inward.serial_no = ''
            new_inward.model = ''
            new_inward.brand = ''
            frappe.set_route('Form', 'Inward', new_inward.name);
        } else {
            frappe.throw('Error submitting document:', r.exc);
        }
    });
}