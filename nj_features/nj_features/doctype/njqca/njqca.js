// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt

const genScoreMap = {
    "CORE I3": 0.1,
    "CORE I4": 0.2,
    "CORE I5": 0.3,
    "CORE I7": 0.4,
    "CORE I8": 0.5,
    "CORE I9": 0.6,
    "CORE I10": 0.7,
    "CORE I11": 0.8,
    "CELERON(R) CPU": 0.9,
    "DUAL-CORE CPU": 0.10,
    "ATOM X5 CPU": 0.11,
    "XEON(R) E": 0.12,
    "PRO A10": 0.13,
    "GEN INTEL(R)": 0.14,
    "RYZEN 5": 0.15,
    "A8 PRO": 0.16,
    "A10 PRO": 0.17,
    "A6-6310 APU": 0.18,
    "RYZEN 7": 0.19,
    "A6-9225 RADEON": 0.20,
    "PENTIUM(R) CPU": 0.21,
    "PRO A6": 0.22,
    "A10-5750M APU": 0.23,
    "A6-7310 APU": 0.24,
};

const brandScoreMap = {
    "Lenovo": 1,
    "HP": 2,
    "Dell": 3
};
frappe.ui.form.on('NJQCA', {
    onload: function(frm) { 
        
        if (frm.doc.manufacturer_model && frm.doc.docstatus == 0) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_sudden_drop',
                args: { 'parent_name': frm.doc.name, 
                    "item_group":frm.doc.item_group,
                    "manufacturer_model":frm.doc.manufacturer_model
                 },
                callback: function(r) {
                    if (r.message) { 
                        frm.set_value( 'sudden_drop', r.message); 
                        frm.refresh_field('sudden_drop');
                    }
                }
            })
        }

         if (frm.doc.docstatus === 0 && frm.doc.item_group=="Laptops") {
            frappe.call({
                method: "nj_features.nj_features.doctype.njqca.njqca.get_item_group_mapping",
                args: {
                    parent: frm.doc.name
                },
                callback: function (r) {
                    if (r.message && Array.isArray(r.message)) {
                        r.message.forEach(row => {
                            const score = genScoreMap[row.variant_6?.trim()?.toUpperCase()] || 0;

                            frm.add_child('njqca_result_parameters', {
                                parameter: "laptop_gen",
                                value: row.variant_6,
                                item_group: "BODY C",
                                score: score
                            });
                        });
                        frm.refresh_field('njqca_result_parameters');
                    }

                    const brand = frm.doc.brand;
                    const brandScore = brandScoreMap[brand];

                    if (brandScore) {
                        frm.add_child('njqca_result_parameters', {
                            parameter: "Brand",
                            value: brand,
                            item_group: "BODY C",
                            score: brandScore
                        });
                        frm.refresh_field('njqca_result_parameters');
                    }
                }
            });
        }
    },
    
    refresh: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        $(frm.layout.wrapper).find('.form-message.red').remove();
        frm.get_field('njqca_item_component').grid.cannot_add_rows = true;
        frm.get_field('njqca_result_parameters').grid.cannot_add_rows = true;
        frm.get_field('njqca_laptop_processors').grid.cannot_add_rows = true;
        frm.refresh_field('njqca_item_component');
        frm.refresh_field('njqca_result_parameters');
        frm.refresh_field('njqca_laptop_processors');
        
        if (frm.doc.docstatus == 0) {
            trigger_serial_no(frm);
            frm.events.power_on();
            handleScannerInput(frm, 'serial_no');

            frm.set_query("inspection_type", () => { return { filters: { "active": 1 } }; });

            frm.set_query("rfq_id", () => { return { filters: { "docstatus": 1 } }; });
            
            frm.set_query("manual_repack_item_code", function() {
                var filters = {
                    disabled: 0, has_variants: 0,
                    end_of_life : ['>', frappe.datetime.get_today()],
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

            if (!frappe.user.has_role('Ops Manager') && frm.doc.item_group == 'Laptops') {
				let $fieldWrapper = frm.fields_dict['manual_repack_item_code'].$wrapper;

				$fieldWrapper.find('input').attr('disabled', true);

				let $inputArea = $fieldWrapper.find('.control-input');
				$inputArea.css('position', 'relative');

				let fogOverlay = $(`
					<div class="fog-overlay" style="
						position: absolute;
						top: 0;
						left: 0;
						width: 100%;
						height: 100%;
						background: rgba(255, 255, 255, 0.3);
						z-index: 5;
						border-radius: 4px;
						pointer-events: none;">
					</div>
				`);
				$inputArea.append(fogOverlay);

				let lockIcon = $(`
					<i class="fa fa-lock" style="
						position: absolute;
						right: 10px;
						top: 50%;
						transform: translateY(-50%);
						font-size: 16px;
						color: #fff;
						z-index: 6;">
					</i>
				`);
				$inputArea.append(lockIcon);
			}
        }
    },

	onload_post_render: async function(frm) {
        if (frm.doc.docstatus == 0) {

            if (!frm.doc.manual_repack_item_code && frm.doc.item_code) {
                frm.set_value('manual_repack_item_code', frm.doc.item_code);
                frm.refresh_field('manual_repack_item_code');
            }

            if (!frm.doc.inspection_type) {
                await frappe.call({
                    method: 'nj_features.nj_features.doctype.njqca.njqca.get_inspection_type',
                    callback: function(r) {
                        frm.set_value('inspection_type', r.message);
                        cur_frm.refresh_field('inspection_type');
                    }
                })
            }

            if (frm.doc.inspection_type && frm.doc.item_group == 'BATTERY') {
                frappe.call({
                    method: 'nj_features.nj_features.doctype.njqca.njqca.get_battery_serialno',
                    args: { 
                        "bios_serial_no": frm.doc.bios_serialno, 
                        "inspection_type":frm.doc.inspection_type,
                        "creation_date":frm.doc.creation
                    },
                    callback: function(r) {
                        if (r.message) { 
                            frm.set_value( 'battery_serial_no', r.message); 
                            frm.refresh_field('battery_serial_no');
                        }
                    }
                })
            }

            if (!frm.doc.__islocal) { get_model(frm.doc.manufacturer_model); }

        }
	},
    
    validate: function(frm) {
        var selectedModel = frm.doc.model;
        var selectedBrand = frm.doc.brand;
        var selectedItemGroup = frm.doc.item_group;

        if (selectedModel && selectedBrand && selectedItemGroup == "Laptops") {
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.check_for_mis_config',
                args: { 'doc': frm.doc },
                callback: function(r) {
                    if (r.message) {
                        let updated = false;
        
                        // Loop through existing rows to check if parameter exists
                        frm.doc.njqca_result_parameters.forEach(function(row) {
                            if (row.parameter === r.message.parameter) {
                                row.value = r.message.value;
                                row.item_group = r.message.item_group;
                                row.score = r.message.score;
                                updated = true;
                            }
                        });
        
                        // If not found, add a new child row
                        if (!updated) {
                            var child = frappe.model.add_child(frm.doc, "njqca_result_parameters");
                            frappe.model.set_value(child.doctype, child.name, 'parameter', r.message.parameter);
                            frappe.model.set_value(child.doctype, child.name, 'value', r.message.value);
                            frappe.model.set_value(child.doctype, child.name, 'item_group', r.message.item_group);
                            frappe.model.set_value(child.doctype, child.name, 'score', r.message.score);
                        }
        
                        frm.refresh_field("njqca_result_parameters");
                    }
                }
            });
        }
        
        if (selectedModel && selectedItemGroup == "Laptops") {
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.update_performance_criteria',
                args: { 'doc': frm.doc },
                callback: function(r) {
                    if (!r || !r.message) {
                        return;
                    }

                    if (r && r.message.error) {
                        frappe.msgprint({
                            title: __("Error"),
                            message: r.message.error,
                            indicator: "red"
                        });
                        frappe.validated = false;
                    } else if (r.message) {
                        
                        let existingRow = null;
        
                        (frm.doc.njqca_result_parameters || []).forEach(row => {
                            if (row.parameter === r.message.parameter) {
                                existingRow = row;
                            }
                        });
        
                        if (existingRow) {
                            frappe.model.clear_doc(existingRow.doctype, existingRow.name);
                        }
        
                        var child = frappe.model.add_child(frm.doc, "njqca_result_parameters");
                        frappe.model.set_value(child.doctype, child.name, 'parameter', r.message.parameter);
                        frappe.model.set_value(child.doctype, child.name, 'value', r.message.value);
                        frappe.model.set_value(child.doctype, child.name, 'item_group', r.message.item_group);
                        frappe.model.set_value(child.doctype, child.name, 'score', r.message.score);
                        
                        frm.refresh_field("njqca_result_parameters");
                    }
                }
            });
        }
        var requiredFields = ['serial_no', 'item_group', 'brand', 'manufacturer_model', 'model'];

        if (frm.doc.rfq_id !== '' && frm.doc.rfq_id !== null && frm.doc.rfq_id !== undefined) { requiredFields.push('warehouse'); }
        
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
        
        if ((frm.doc.rfq_id === '' || frm.doc.rfq_id === null || frm.doc.rfq_id === undefined) && frm.doc.item_group != "Laptop RAM") {

            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.after_save_njqca',
                args: { 'docname': frm.doc.name, 'brand': frm.doc.brand, 'model': frm.doc.model, 'qi_type':frm.doc.qi_type },
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
        }
    },

    rfq_id: function(frm) {
        if (frm.doc.rfq_id !== '' && frm.doc.rfq_id !== null && frm.doc.rfq_id !== undefined) {

            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_item_code_from_rfq_id',
                args: { 'rfq_id': frm.doc.rfq_id },
                callback: function(r) {
                    if (r.message && r.message.length > 0) {
                        frm.set_df_property('item_code', 'read_only', 0);
                        frm.set_value('item_code', '');

                        if (r.message.length === 1) {
                            frm.set_value('item_code', r.message[0].item_code);
                            frm.set_df_property('item_code', 'read_only', 1);
                        } else {
                            frm.set_query("item_code", function() { 
                                return { filters: { "name": ["in", r.message.map(item => item.item_code)] } }; 
                            });
                        }
                        frm.set_df_property('serial_no', 'read_only', 1); 
                        frm.refresh_field('serial_no');
                        
                    } else {
                        frappe.msgprint(__('No items found for this RFQ.'));
                    }
                    frm.refresh_field('item_code');
                }
            })
        } else {
            frm.set_df_property('serial_no', 'read_only', 0); 
            frm.refresh_field('serial_no');
        }
    },
    before_submit: async function(frm) {
        await frappe.call({
            method: 'nj_features.nj_features.doctype.njqca.njqca.get_sudden_drop',
            args: { 'parent_name': frm.doc.name, "item_group":frm.doc.item_group,
                "manufacturer_model":frm.doc.manufacturer_model
             },
            callback: function(r) {
                if (r.message) { 
                    frappe.db.set_value(frm.doctype, frm.doc.name, 'sudden_drop', r.message); 
                    frm.refresh_field('sudden_drop');
                }
            }
        })
        
        if(frm.doc.item_group=="BATTERY"){
            frappe.validated=true;
            await frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_bdt_status',
                args: { 'doc': frm.doc },
                callback: function(r) {
                    if(r.message){
                        let newRow = frappe.model.add_child(frm.doc, "njqca_result_parameters");
                        if(r.message == "Pass"){
                            frm.set_value('bdt_status', "Pass");
                            frappe.db.set_value(frm.doctype, frm.doc.name, 'bdt_status', r.message);
                            frm.refresh_field('bdt_status');
                            frappe.model.set_value(newRow.doctype, newRow.name, 'parameter', "BDT_status");
                            frappe.model.set_value(newRow.doctype, newRow.name, 'value', r.message);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', "BATTERY");
                            frappe.model.set_value(newRow.doctype, newRow.name, 'score', "0");
                        }else if(r.message == "Fail"){
                            frm.set_value('bdt_status', "Fail");
                            frappe.db.set_value(frm.doctype, frm.doc.name, 'bdt_status', r.message);
                            frm.refresh_field('bdt_status');
                            frappe.model.set_value(newRow.doctype, newRow.name, 'parameter', "BDT_status");
                            frappe.model.set_value(newRow.doctype, newRow.name, 'value', r.message);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', "BATTERY");
                            frappe.model.set_value(newRow.doctype, newRow.name, 'score', "41");
                        }else{
                            frappe.validated=false;
                            frappe.throw(r.message);
                        }
                    }else{
                        frappe.validated=false;
                        frappe.throw("Error while getting BDT Status");
                    }
                    frm.refresh_field("njqca_result_parameters");
                }
            })
        }

        // return new Promise((resolve, reject) => {
        //     let tablesToCheck = [
        //         'njqca_laptop_ram', 'njqca_laptop_processors', 
        //         'njqca_display', 'njqca_adaptor', 'njqca_laptop_storage'
        //     ];
        //     let mismatches = [];
        //     let i = 0;

        //     tablesToCheck.forEach((table) => {
        //         frm.doc[table].forEach((row) => {
                    
        //             if (!row.calculated_item_code || row.calculated_item_code.trim() === "") {
        //                 mismatches.push(`<br><b>${++i}.</b> The calculated item code is missing for an entry in <b>${table}</b>.`);
        //             } else if (row.calculated_item_code !== row.fetched_item_code) {
        //                 mismatches.push(`<br><b>${++i}.</b> The <b>fetched item code: ${row.fetched_item_code}</b> is different from the <b>calculated item code: ${row.calculated_item_code}</b>.`);
        //             }

        //             // Added condition: If fetched_item_code is filled but calculated_item_code is empty, throw an error
        //             if (row.fetched_item_code && (!row.calculated_item_code || row.calculated_item_code.trim() === "")) {
        //                 frappe.throw(`The fetched item code is present, but the calculated item code is missing for an entry in <b>${table}</b>. Please contact the NPD team.`);
        //             }
                    
        //         });
        //     });
    
        //     if (mismatches.length > 0) {
        //         let mismatchMessage = mismatches.join('<br>');
        //         frappe.confirm(
        //             `<b>The following issues were found:</b><br><br>${mismatchMessage}<br><br>Do you agree to change all mismatched or missing item codes?`,
        //             () => { resolve(); },
        //             () => { reject(); }
        //         );
        //     } else { resolve(); }

        // }).then(() => {
        //     if (frm.doc.automated_repack_item != frm.doc.repack_item_code) {
        //         frappe.validated = false; 
        //         frappe.confirm(
        //             `<b>Automated Item Code: ${frm.doc.automated_repack_item}</b> <br> <b>Repack Item Code: ${frm.doc.repack_item_code}</b> are not the same.<br>Are you sure you want to Submit?`, 
        //             () => {
        //                 frappe.confirm( "Are you sure you want to proceed with submitting this form with the current item codes?",
        //                     () => {
        //                         frappe.validated = true;
        //                         frm.save('Submit');
        //                     },
        //                     () => { frm.set_value('repack_item_code', ''); }
        //                 );
        //             },
        //             () => { frm.set_value('repack_item_code', ''); }
        //         );
        //     }
    
        //     return false;
        // });
    },

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
        if (frm.doc.serial_no) {
            if (frm.doc.rfq_id === '' || frm.doc.rfq_id === null || frm.doc.rfq_id === undefined) { trigger_serial_no(frm); } 
        } else {
            frm.set_value('warehouse', '')
            frm.refresh_field('warehouse')
        }

        if(!frappe.user.has_role("NJ IQC Manager") && frm.doc.serial_no && frm.doc.serial_no.trim() !== '' && (frm.doc.rfq_id === '' || frm.doc.rfq_id === null || frm.doc.rfq_id === undefined)){
            cur_frm.set_df_property('serial_no', 'read_only', 1);
        }
    },
    battery_serial_no: function(frm) {
        handleScannerInput(frm, 'battery_serial_no');
        if (frm.doc.battery_serial_no) {
            if (frm.doc.rfq_id === '' || frm.doc.rfq_id === null || frm.doc.rfq_id === undefined) {
                frappe.call({
                    method: 'nj_features.nj_features.doctype.njqca.njqca.get_info_from_battery_serial_no',
                    args: { 'doc': frm.doc },
                    callback: function(r) {
                        Object.keys(r.message).forEach(field => {
                            frm.set_value(field, r.message[field]);
                            cur_frm.refresh_field(field);
                        });
                    }
                })
            } 
        } else {
            frm.set_value('warehouse', '')
            frm.refresh_field('warehouse')
        }
    },

    manufacturer_model: function(frm) {
        if (frm.doc.manufacturer_model) { get_model(frm.doc.manufacturer_model); }
    },

    inspection_type: function(frm) {
        if (frm.doc.inspection_type ) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.set_is_defective',
                args: { 'inspection_type': frm.doc.inspection_type },
                callback: function(r) {
                    if (r && r.message  && r.message=="1") {
                        frm.set_value('qi_type', 'is_defective');
                    }
                }
            })
        }
    },

    warehouse: async function(frm) {
        if (frm.doc.warehouse && (frm.doc.serial_no || frm.doc.battery_serial_no) && (frm.doc.rfq_id === '' || frm.doc.rfq_id === null || frm.doc.rfq_id === undefined)) {
            let ware = frm.doc.warehouse;    
            let employeeData = await frappe.db.get_value('Employee', {
                'user_id': frappe.session.user_email, 'status': 'Active'
            }, 'work_warehouse');
    
            const workWarehouse = employeeData?.message?.work_warehouse;    
            if (!workWarehouse) {
                frappe.msgprint(`Work Warehouse is not set for employee: ${frappe.session.user_email}. Please mail to <b>IT Infra Team</b> at <strong><a href="mailto:itinfra@newjaisa.com">itinfra@newjaisa.com</a></strong> to create an employee.`);
            } else if (workWarehouse !== ware) {
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
                        }
                    ],
                    static: true,
                    primary_action_label: "Yes, Transfer", 
                    primary_action: function() {
                        let scannedSerialNo = dialog.get_value("serial_num");
                        let frm_serial_no="";
                        if(frm.doc.item_group!="BATTERY"){
                           frm_serial_no= frm.doc.serial_no;
                        }
                        else{
                            frm_serial_no= frm.doc.battery_serial_no;
                        }
                        if (scannedSerialNo.toLowerCase() != frm_serial_no.toLowerCase()) {
                            $('.primary-action').hide();
                            frappe.msgprint({
                                title: 'Serial Number Mismatch',
                                message: `The scanned serial number ${scannedSerialNo} does not match the available serial number ${frm.doc.serial_no}. Please try again.`,
                            });
                            dialog.hide();
                            return;
                        }
    
                        let material_transfer_items = [{
                            'serial_no': frm_serial_no,
                            'item_code': frm.doc.item_code,
                            't_warehouse': workWarehouse,
                            's_warehouse': frm.doc.warehouse
                        }];
                        
                        let data = {
                            "doctype": frm.doc.doctype,
                            "serial_no": frm_serial_no,
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
                                if (response && response.message) {
                                    $('.primary-action').show();
                                    frm.set_value('warehouse', workWarehouse);
                                    frm.refresh_field('warehouse');
                                }
                            },
                            error: function(err) { 
                                console.error(err);
                                $('.primary-action').hide();
                            }
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
        }
    },
    
    model: function(frm) {
        var selectedModel = frm.doc.model;
        var selectedBrand = frm.doc.brand;
        var selectedItemGroup = frm.doc.item_group;

        if (selectedModel && selectedBrand && cur_frm.doc.serial_no && selectedItemGroup!='BATTERY' && (frm.doc.rfq_id === '' || frm.doc.rfq_id === null || frm.doc.rfq_id === undefined)) {
            
            frappe.db.get_value('Serial No', {'serial_no': cur_frm.doc.serial_no}, 'model', function(r) {

                if (!r.model && selectedItemGroup.toLowerCase() != "battery" && selectedItemGroup.toLowerCase() != "laptop ram") {
                    frappe.throw(`Model is not filled in Serial no: <b>${cur_frm.doc.serial_no}</b>. Please contact the NPD Team.`);
                }

                if(selectedModel && selectedModel != r.model && selectedItemGroup && selectedItemGroup == "Laptops"){
                    frappe.confirm('Model in SerialNo and NJQCA are Different. Do you want to change the part list?',
                        () => {
                            frappe.call({
                                method: 'nj_features.nj_features.doctype.njqca.njqca.model_change_for_serial_no',
                                args: { 'newmodel': frm.doc.model, 'serial_no': frm.doc.serial_no },
                                callback: function(r) {
                                    if(r.message.status === 'success'){
                                        var base_url = frappe.urllib.get_base_url();
                                        var serial_no_link = `${base_url}/app/serial-no/${cur_frm.doc.serial_no}`;
                                        frappe.msgprint(`Part List and Model is updated for Serial No : <strong><a href='${serial_no_link}'>${cur_frm.doc.serial_no}</a></strong> has been submitted successfully.`);
                                    }
                                    else if(r.message.status === 'failed'){ $('.primary-action').hide() }
                                }
                            });
                        }, () => {
                            if (selectedModel == r.model) {
                                $('.primary-action').show() 
                            } else { $('.primary-action').hide() }
                         })
                }
            })
        }

        if (selectedItemGroup != "BATTERY" && selectedItemGroup != "Laptop RAM") {
            get_item_template(selectedModel, selectedBrand, selectedItemGroup)
        }

        frm.refresh_field('item_template');
    },

    item_template: function(frm) {
        if (frm.doc.item_template && frm.doc.power_on == 'Yes' && frm.doc.item_group!="BATTERY") {
            processItemTemplate(frm);
        }
        // else if(frm.doc.item_template && frm.doc.power_on == 'Yes' &&frm.doc.item_group=="BATTERY") {
        //    frappe.call({
        //        method: 'nj_features.nj_features.doctype.njqca.njqca.get_battery_auto_item_code',
        //        args: { "name": frm.doc.name, "item_template": frm.doc.item_template, "manufacturer_model": frm.doc.manufacturer_model },
        //        callback: function(r) {
        //             if(r.message){
        //                 frm.set_value('manual_repack_item_code', r.message);
        //                 frm.refresh_field('item_template');
        //             }
        //         }
        //    })
        // }
    },
    before_save: function(frm) {
        if (frm.doc.name && frm.doc.item_template && frm.doc.item_group=="Laptops") {
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.check_ram_speed',
                args: { 'njqca_name': frm.doc.name, 'item_template': frm.doc.item_template },
                callback: function(r) {
                    if (r.message) { 
                        let newRow = frappe.model.add_child(frm.doc, "njqca_result_parameters");
                        if(r.message == "PASS"){
                            frappe.model.set_value(newRow.doctype, newRow.name, 'parameter', "IW_Speed_Match");
                            frappe.model.set_value(newRow.doctype, newRow.name, 'value', r.message);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', "Laptop RAM");
                            frappe.model.set_value(newRow.doctype, newRow.name, 'score', "0");
                        }else if(r.message == "FAIL"){
                            frappe.model.set_value(newRow.doctype, newRow.name, 'parameter', "IW_Speed_Match");
                            frappe.model.set_value(newRow.doctype, newRow.name, 'value', r.message);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', "Laptop RAM");
                            frappe.model.set_value(newRow.doctype, newRow.name, 'score', "41");
                        }
                    }
                }
            })
        }

        if(frm.doc.item_group == "Laptops" && frm.doc.serial_no !=""){

        frappe.call({
            method: 'nj_features.nj_features.api.api_files.get_battery_status',
            args: { "serial_no": frm.doc.serial_no,"bios_serialno": frm.doc.bios_serialno ,"manufacturer_model": frm.doc.manufacturer_model },
            callback: function(r) {
                if(r.message){
                    let newRow = frappe.model.add_child(frm.doc, "njqca_result_parameters");
                    if(r.message == "PASS"){
                        frappe.model.set_value(newRow.doctype, newRow.name, 'parameter', "Battery_status");
                        frappe.model.set_value(newRow.doctype, newRow.name, 'value', r.message);
                        frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', "BATTERY");
                        frappe.model.set_value(newRow.doctype, newRow.name, 'score', "0");
                    }else if(r.message == "FAIL"){
                        frappe.model.set_value(newRow.doctype, newRow.name, 'parameter', "Battery_status");
                        frappe.model.set_value(newRow.doctype, newRow.name, 'value', r.message);
                        frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', "BATTERY");
                        frappe.model.set_value(newRow.doctype, newRow.name, 'score', "42");
                    }else if(r.message == "Report Not found"){
                        frappe.model.set_value(newRow.doctype, newRow.name, 'parameter', "Battery_status");
                        frappe.model.set_value(newRow.doctype, newRow.name, 'value', r.message);
                        frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', "BATTERY");
                        frappe.model.set_value(newRow.doctype, newRow.name, 'score', "41");
                    }
                }
                frm.refresh_field("njqca_result_parameters");
            }
        })
        }
    },

    item_code: function(frm) {
        if (frm.doc.item_code != '' && (frm.doc.rfq_id !== '' && frm.doc.rfq_id !== null && frm.doc.rfq_id !== undefined)) {
            frappe.call({
                method: 'nj_features.nj_features.api.qr_code.create_serial_no',
                args: { 'item_code': frm.doc.item_code, "rfq": true },
                callback: function(r) {
                    if (r.message) { frm.set_value('serial_no', r.message); }
                }
            })
        }
        if( frm.doc.item_group === "Laptop RAM" && frm.doc.item_code && frm.doc.item_code !== ""){
            frappe.call({
                method: 'nj_features.nj_features.doctype.njqca.njqca.get_item_code_for_ram',
                args: { 'item_code': frm.doc.item_code,'njqca_name':frm.doc.name },
                callback: function(r) {
                    if (r.message) { 
                        frm.set_value('repack_item_code', r.message);
                        frm.set_value('manual_repack_item_code', r.message);
                        frm.refresh_field('repack_item_code');
                        frm.refresh_field('manual_repack_item_code');
                    }
                }
            })
        }
    }
});

function trigger_serial_no(frm) {
    if ((cur_frm.doc.serial_no || cur_frm.doc.bios_serialno) && cur_frm.doc.power_on == 'Yes' && cur_frm.doc.item_group!='BATTERY' && (frm.doc.rfq_id === '' || frm.doc.rfq_id === null || frm.doc.rfq_id === undefined)) {
        console.log("trigger_serial_no");
        
        frappe.call({
            method: 'nj_features.nj_features.doctype.njqca.njqca.get_info_from_serial_no',
            args: { 'doc': frm.doc },
            callback: function(r) {
                Object.keys(r.message).forEach(field => {
                    frm.set_value(field, r.message[field]);
                    cur_frm.refresh_field(field);
                });
            }
        });
    }
}

function processItemTemplate(frm) {
    if (frm.doc.njqca_item_component && frm.doc.power_on == 'Yes') {
        frappe.call({
            method: 'nj_features.nj_features.doctype.njqca.njqca.get_part_mapping',
            args: {'doc': frm.doc, 'item_template': frm.doc.item_template},
            callback: function (r) {
                if (r.message.error) {
                    frappe.show_alert({
                        message:__("<b>Error " + r.message.error + "</b>"),
                        indicator:'red'
                    }, 10);
                } 

                if (r.message) {
                    
                    if (typeof r.message === 'string') {
                        try {
                            r.message = JSON.parse(r.message);
                        } catch (e) {
                            console.error("Failed to parse message:", e);
                        }
                    }

                    if (r.message.repack_item_code !== undefined && r.message.repack_item_code !== null) {
                        if (r.message.repack_item_code.error) {
                            frappe.utils.play_sound("error");
                            var errorMessageString = 'Repack Item code not found: ' + r.message.repack_item_code.error;
                            var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                            $(frm.layout.wrapper).find('.form-message.red').remove();
                            $(frm.layout.wrapper).prepend(errorDiv);
                            frappe.show_alert({
                                message: errorMessageString,
                                indicator: 'red'
                            }, 10)
                        } else {
                            frm.set_value('repack_item_code', r.message.repack_item_code);
                            frm.set_value('manual_repack_item_code', r.message.repack_item_code);
                        }
                    }
                    frm.refresh_fields(['repack_item_code', 'manual_repack_item_code', 'njqca_result_parameters']);

                    const partData = r.message.part_data;

                    frm.doc.njqca_item_component.forEach(row => {
                        const part = partData.find(p => p.name === row.name && p.response !== 'error');
                        if (part) {
                            frappe.model.set_value(row.doctype, row.name, 'part_item_code', part.part_item_code);
                            frappe.model.set_value(row.doctype, row.name, 'attr_data', JSON.stringify(part.attr_data));
                        }
                    });
                }
                
                if (r.message.part_data ) {
                    
                    const partData = r.message.part_data;

                    frm.clear_table("njqca_laptop_ram");
                    frm.clear_table("njqca_laptop_processors");
                    frm.clear_table("njqca_laptop_storage")
                    
                    partData.forEach(row => {
                        if (row.item_group === "Laptop RAM") {
                            
                            let newRow = frappe.model.add_child(frm.doc, "njqca_laptop_ram");
                            show_checkbutton_ram(frm)
                            frappe.model.set_value(newRow.doctype, newRow.name, 'ram_type', row.attr_data["RAM Type"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'ram_capacity', row.attr_data["RAM Capacity"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'ram_speed', row.attr_data["RAM Speed"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'grade', row.attr_data["Grade"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'calculated_item_code', row.part_item_code);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'fetched_item_code', row.fetched_item_code);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', row.item_group);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_template', row.item_template);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'reference_row_name', row.name);
                            
                        }else if(row.item_group === "Laptop Processors"){
                            
                            let newRow = frappe.model.add_child(frm.doc, "njqca_laptop_processors");
                            show_checkbutton_processors(frm)
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', row.item_group);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'calculated_item_code', row.part_item_code);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'fetched_item_code', row.fetched_item_code);                         
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_template', row.item_template);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'processor_type', row.attr_data["Processor Type"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'grade', row.attr_data["Grade"]);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'reference_row_name', row.name);
                        
                        }else if(row.item_group === "LAPTOP STORAGE"){
                            
                            let newRow = frappe.model.add_child(frm.doc, "njqca_laptop_storage");
                            show_checkbutton_storage(frm);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'item_group', row.item_group);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'calculated_item_code', row.part_item_code);
                            frappe.model.set_value(newRow.doctype, newRow.name, 'fetched_item_code', row.fetched_item_code);        
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
            }
        });
    }
}

function get_item_template(model, brand, item_group) {
    frappe.call({
        method: 'nj_features.nj_features.doctype.njqca.njqca.get_njqca_item_template',
        args: { 'model': model, 'brand': brand, 'item_group': item_group },
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
            args: { item_template: item_templates, args: adaptor_properties },
            callback: function(r) {
                if (r.message) {
                    if (r.message.error) {
                        frappe.utils.play_sound("error");
                        var errorMessageString = 'Item code not found: ' + r.message.error;
                        var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                        $(frm.layout.wrapper).find('.form-message.red').remove();
                        $(frm.layout.wrapper).prepend(errorDiv);
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', '');
                        frappe.show_alert({
                            message:__("Item code not found: <b> " + r.message.error + "</b>"),
                            indicator:'red'
                        }, 5);
                    } else {
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
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
            args: { item_template: item_template, args: storage_properties },
            callback: function(r) {
                if (r.message) {
                    if (r.message.error) {
                        frappe.utils.play_sound("error");
                        var errorMessageString = 'Item code not found: ' + r.message.error;
                        var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                        $(frm.layout.wrapper).find('.form-message.red').remove();
                        $(frm.layout.wrapper).prepend(errorDiv);
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', '');
                        frappe.show_alert({
                            message:__("Item code not found: <b> " + r.message.error + "</b>"),
                            indicator:'red'
                        }, 5);
                    } else {
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
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
    }
}

function generateProcessorItemCode(frm, cdt, cdn, child) {
    const item_template = child.item_template;
    const row_name = child.reference_row_name;

    let processor_type = child.processor_type;
    let grade = child.grade;

    const processor_properties = [{ "Processor Type": processor_type, "Grade": grade }];

    if (processor_type && grade) {
        frappe.call({
            method: "nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value",
            args: { item_template: item_template, args: processor_properties },
            callback: function(r) {
                if (r.message) {
                    if (r.message.error) {
                        frappe.utils.play_sound("error");
                        var errorMessageString = 'Item code not found: ' + r.message.error;
                        var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                        $(frm.layout.wrapper).find('.form-message.red').remove();
                        $(frm.layout.wrapper).prepend(errorDiv);
                        frappe.show_alert({
                            message:__("Item code not found: <b> " + r.message.error + "</b>"),
                            indicator:'red'
                        }, 5);
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', '');
                    } else {
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
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
            args: { item_template: item_template, args: display_properties },
            callback: function(r) {
                if (r.message) {
                    if (r.message.error) {
                        frappe.utils.play_sound("error");
                        var errorMessageString = 'Item code not found: ' + r.message.error;
                        var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                        $(frm.layout.wrapper).find('.form-message.red').remove();
                        $(frm.layout.wrapper).prepend(errorDiv);
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', '');
                        frappe.show_alert({
                            message:__("Item code not found: <b> " + r.message.error + "</b>"),
                            indicator:'red'
                        }, 5);
                    } else {
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
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
            args: { item_template: item_template, args: ram_properties },
            callback: function(r) {
                if (r.message) {
                    if (r.message.error) {
                        frappe.utils.play_sound("error");
                        var errorMessageString = 'Item code not found: ' + r.message.error;
                        var errorDiv = $('<div class="form-message red"></div>').html(errorMessageString);
                        $(frm.layout.wrapper).find('.form-message.red').remove();
                        $(frm.layout.wrapper).prepend(errorDiv);
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', '');
                        frappe.show_alert({
                            message:__("Item code not found: <b> " + r.message.error + "</b>"),
                            indicator:'red'
                        }, 5);
                    } else {
                        frappe.model.set_value(cdt, cdn, 'calculated_item_code', r.message);
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
    }
}

// - Not used replaced by pop-up
// function set_options_for_attribute_fields_in_child(frm, grid) {
//     let selectFields = [];
    
//     $.each(grid.grid_rows, function(i, row) {
//         $.each(row.columns, function(j, field) {
//             if (field.df.fieldtype === 'Select') {
//                 selectFields.push({
//                     fieldname: field.df.fieldname,
//                     rowname: row.doc.name,
//                     label: field.df.label
//                 });
//             }
//         });
//     });

//     frappe.call({
//         method: "nj_features.nj_features.doctype.njqca.njqca.get_item_attributes",
//         args: { selected_fields: selectFields },
//         callback: function(r) {
//             if (r.message) {
//                 $.each(r.message, function(i, field) {
//                     frm.set_df_property(grid.df.fieldname, 'options', field.options, frm.docname, field.fieldname, field.rowname);
//                     frm.refresh_field(grid.df.fieldname);
//                 });
//             }
//         }
//     });
// }


frappe.ui.form.on('NJQCA Display', {
    njqca_display_add: function(frm, cdt, cdn) {
        frm.fields_dict['njqca_display'].grid.refresh();
        setTimeout(() => show_checkbutton_display(frm), 300);
    },
    check_button: async function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        let item_group = child.item_group;
        let grid = frm.get_field(child.parentfield);

        let d = new frappe.ui.Dialog({
            title: 'Edit Display Attributes',
            fields: [
                { label: 'Model', fieldname: 'model', fieldtype: 'Select', options: ['Loading...'], default: child.model || '', reqd: 1 },
                { label: 'Display Tech', fieldname: 'display_tech', fieldtype: 'Select', options: ['Loading...'], default: child.display_tech || '', reqd: 1 },
                { label: 'Display PIN Type', fieldname: 'display_pin_type', fieldtype: 'Select', options: ['Loading...'], default: child.display_pin_type || '', reqd: 1 },
                { label: 'Display Size', fieldname: 'display_size', fieldtype: 'Select', options: ['Loading...'], default: child.display_size || '', reqd: 1 },
                { label: 'Resolution', fieldname: 'resolution', fieldtype: 'Select', options: ['Loading...'], default: child.resolution || '', reqd: 1 },
                { label: 'Thickness', fieldname: 'thickness', fieldtype: 'Select', options: ['Loading...'], default: child.thickness || '', reqd: 1 },
                { label: 'Display Bracket', fieldname: 'display_bracket', fieldtype: 'Select', options: ['Loading...'], default: child.display_bracket || '', reqd: 1 },
                { label: 'Grade', fieldname: 'grade', fieldtype: 'Select', options: ['Loading...'], default: child.grade || '', reqd: 1 },
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
                    args: { label: attributeName,template: frm.doc.item_template,item_group: item_group },
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

function fetch_item_template_disp_adp(frm, item_group, callback) {
    frappe.call({
        method: "nj_features.nj_features.doctype.njqca.njqca.get_serial_no_attribute_data",
        args: { serial_no: frm.doc.serial_no, item_group: item_group },
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                callback(r.message[0].item_template);
            } else { console.warn("No item template found."); }
        },
        error: function(err) { console.error("API Error:", err); }
    });
}

frappe.ui.form.on('NJQCA Adaptor', {

    njqca_adaptor_add: function(frm, cdt, cdn) {
        frm.fields_dict['njqca_adaptor'].grid.refresh();
        setTimeout(() => show_checkbutton_adaptor(frm), 300);
    },

    check_button: async function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        let item_group = "Laptop Adaptors";
        let grid = frm.get_field(child.parentfield);

        let d = new frappe.ui.Dialog({
            title: 'Edit Adaptor Attributes',
            fields: [
                { label: 'Brand', fieldname: 'brand', fieldtype: 'Select', options: ['Loading...'], default: child.brand || '', reqd: 1 },
                { label: 'Wattage Capacity', fieldname: 'wattage_capacity', fieldtype: 'Select', options: ['Loading...'], default: child.wattage_capacity || '', reqd: 1 },
                { label: 'Adapter Pin Type', fieldname: 'adapter_pin_type', fieldtype: 'Select', options: ['Loading...'], default: child.adapter_pin_type || '', reqd: 1 },
                { label: 'Grade', fieldname: 'grade', fieldtype: 'Select', options: ['Loading...'], default: child.grade || '', reqd: 1 },
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
                    args: { label: attributeName,template: frm.doc.item_template,item_group: item_group },
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

        // Define the detailed relationships between interfaces and lengths
        const relationshipMap = {
            'interfaces': {
                'SATA': ['2.5'],
                'M.2 NVME': ['2242', '2280'],
                'M.2 SATA': ['2242', '2230'],
                'M.2 PCI': ['2280'],
                'M.SATA': ['2242']
            },
            'lengths': {
                '2.5': ['SATA'],
                '2242': ['M.2 NVME', 'M.2 SATA','M.SATA'],
                '2280': ['M.2 NVME', 'M.2 PCI'],
                '2230': ['M.2 SATA']
            }
        };

        // Define the filtered options for both SSD and HDD with the relationships
        const storage_filters = {
            'SSD': {
                interfaces: ['SATA', 'M.2 NVME', 'M.2 SATA', 'M.2 PCI' ,'M.SATA'],
                lengths: ['2280', '2242', '22110', '2.5']
            },
            'HDD': {
                interfaces: ['SATA'],
                lengths: ['2.5']
            }
        };

        // Helper function to update field options based on selections
        const updateFieldOptions = (sourceField, targetField) => {
            const sourceValue = d.get_value(sourceField);
            const storageType = d.get_value('storage_type');
            
            // First apply storage type filter to get the base options
            let baseOptions = [];
            if (targetField === 'storage_interface') {
                baseOptions = storage_filters[storageType]?.interfaces || [];
            } else if (targetField === 'storage_length') {
                baseOptions = storage_filters[storageType]?.lengths || [];
            }
            
            // Then apply the relationship filter if a source value is selected
            if (sourceValue) {
                let relationshipKey = sourceField === 'storage_interface' ? 'interfaces' : 'lengths';
                let allowedValues = relationshipMap[relationshipKey][sourceValue] || [];
                
                // Intersection of base options and relationship-allowed options
                let filteredOptions = baseOptions.filter(option => allowedValues.includes(option));
                d.set_df_property(targetField, 'options', filteredOptions);
                
                // Auto-select if only one option and field is empty
                if (filteredOptions.length === 1 && !d.get_value(targetField)) {
                    d.set_value(targetField, filteredOptions[0]);
                }
                
                // Clear value if not in filtered list
                const currentValue = d.get_value(targetField);
                if (currentValue && !filteredOptions.includes(currentValue)) {
                    d.set_value(targetField, '');
                }
            } else {
                // If no source value, just use the storage type filter
                d.set_df_property(targetField, 'options', baseOptions);
            }
        };

        let d = new frappe.ui.Dialog({
            title: 'Laptop Storage Attributes',
            fields: [
                {
                    label: 'Storage Type',
                    fieldname: 'storage_type',
                    fieldtype: 'Select',
                    options: ['Loading...'],
                    default: child.storage_type || '',
                    reqd: !child.storage_type,
                    read_only: !!child.storage_type,
                    change: function() {
                        const storageType = d.get_value('storage_type');
                        if (storageType) {
                            // Reset both fields to apply new storage type filters
                            const interfaceValue = d.get_value('storage_interface');
                            const lengthValue = d.get_value('storage_length');
                            
                            // Set base options first
                            if (storage_filters[storageType]) {
                                d.set_df_property('storage_interface', 'options', 
                                    storage_filters[storageType].interfaces);
                                d.set_df_property('storage_length', 'options', 
                                    storage_filters[storageType].lengths);
                            }
                            
                            // Then apply relationship filters if values exist
                            if (interfaceValue) {
                                updateFieldOptions('storage_interface', 'storage_length');
                            }
                            if (lengthValue) {
                                updateFieldOptions('storage_length', 'storage_interface');
                            }
                        }
                    }
                },
                {
                    label: 'Storage Interface',
                    fieldname: 'storage_interface',
                    fieldtype: 'Select',
                    options: ['Loading...'],
                    default: child.storage_interface || '',
                    reqd: !child.storage_interface,
                    read_only: !!child.storage_interface,
                    change: function() {
                        updateFieldOptions('storage_interface', 'storage_length');
                    }
                },
                {
                    label: 'Storage Capacity',
                    fieldname: 'storage_capacity',
                    fieldtype: 'Select',
                    options: ['Loading...'],
                    default: child.storage_capacity || '',
                    reqd: !child.storage_capacity,
                    read_only: !!child.storage_capacity
                },
                {
                    label: 'Storage Length',
                    fieldname: 'storage_length',
                    fieldtype: 'Select',
                    options: ['Loading...'],
                    default: child.storage_length || '',
                    reqd: !child.storage_length,
                    read_only: !!child.storage_length,
                    change: function() {
                        updateFieldOptions('storage_length', 'storage_interface');
                    }
                },
                {
                    label: 'Grade',
                    fieldname: 'grade',
                    fieldtype: 'Select',
                    options: ['Loading...'],
                    default: child.grade || '',
                    reqd: !child.grade,
                    read_only: false
                }
            ],
            primary_action_label: 'Save',
            primary_action(values) {
                Object.keys(values).forEach(fieldname => {
                    if (values[fieldname]) {
                        frm.set_df_property(grid.df.fieldname, 'options', values[fieldname], frm.docname, fieldname, cdn);
                        frappe.model.set_value(cdt, cdn, fieldname, values[fieldname]);
                    }
                });
                frm.refresh_field(grid.df.fieldname);
                generateStorageItemCode(frm, cdt, cdn, child);
                d.hide();
            }
        });

        const fieldToAttribute = {
            'storage_type': 'Storage Type',
            'storage_interface': 'Storage Interface',
            'storage_capacity': 'Storage Capacity',
            'storage_length': 'Storage Length',
            'grade': 'Grade'
        };

        // Load options for all fields
        for (const [fieldname, attributeName] of Object.entries(fieldToAttribute)) {
            try {
                // For interface and length, we'll apply the filters later
                if (fieldname !== 'storage_interface' && fieldname !== 'storage_length') {
                    let options = await get_options(attributeName);
                    d.set_df_property(fieldname, 'options', options);
                }
                
                // Set existing values
                if (child[fieldname]) {
                    d.set_value(fieldname, child[fieldname]);
                }
            } catch (error) {
                console.error(`Error loading options for ${fieldname}:`, error);
            }
        }

        // Initialize storage type options
        try {
            let storageTypeOptions = await get_options('Storage Type');
            d.set_df_property('storage_type', 'options', storageTypeOptions);
            
            // Apply storage type filters
            if (child.storage_type) {
                d.set_value('storage_type', child.storage_type);
                
                if (storage_filters[child.storage_type]) {
                    // Set interface options based on storage type
                    d.set_df_property('storage_interface', 'options', 
                        storage_filters[child.storage_type].interfaces);
                    
                    // Set length options based on storage type
                    d.set_df_property('storage_length', 'options', 
                        storage_filters[child.storage_type].lengths);
                }
            } else {
                // If no storage type yet, just load all options
                let interfaceOptions = await get_options('Storage Interface');
                let lengthOptions = await get_options('Storage Length');
                
                d.set_df_property('storage_interface', 'options', interfaceOptions);
                d.set_df_property('storage_length', 'options', lengthOptions);
            }
        } catch (error) {
            console.error('Error initializing storage type options:', error);
        }

        // Apply bidirectional filtering based on existing values
        if (child.storage_interface) {
            d.set_value('storage_interface', child.storage_interface);
            updateFieldOptions('storage_interface', 'storage_length');
        }
        
        if (child.storage_length) {
            d.set_value('storage_length', child.storage_length);
            updateFieldOptions('storage_length', 'storage_interface');
        }

        d.show();
    
        async function get_options(attributeName) {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "nj_features.nj_features.doctype.njqca.njqca.get_options_for_label",
                    args: { label: attributeName,template: frm.doc.item_template,item_group: item_group },
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

// Helper function to determine if fields should be required
function shouldBeRequired(child) {
    return !child.fetched_item_code || 
           (child.fetched_item_code && child.calculated_item_code && 
            child.fetched_item_code !== child.calculated_item_code);
}

// Function to validate mandatory fields for the entire form
function validate_mandatory_fields(frm) {
    if (!frm.doc.njqca_laptop_storage) return;

    frm.doc.njqca_laptop_storage.forEach((row, idx) => {
        if (shouldBeRequired(row)) {
            ['storage_type', 'storage_interface', 'storage_capacity', 'storage_length', 'grade'].forEach(field => {
                frm.fields_dict.njqca_laptop_storage.grid.grid_rows[idx].doc[field] = 
                    frm.fields_dict.njqca_laptop_storage.grid.grid_rows[idx].doc[field] || '';
                
                frm.fields_dict.njqca_laptop_storage.grid.grid_rows[idx].toggle_reqd(
                    field, true
                );
            });
        }
    });
}

frappe.ui.form.on('NJQCA Laptop Ram', {

    check_button: async function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        let item_group = child.item_group;
        let grid = frm.get_field(child.parentfield);
    
        let d = new frappe.ui.Dialog({
            title: 'Laptop RAM Attributes',
            fields: [
                { 
                    label: 'RAM Type', fieldname: 'ram_type', fieldtype: 'Select', 
                    options: ['Loading...'], default: child.ram_type || '', 
                    reqd: !child.ram_type, read_only: !!child.ram_type 
                },
                { 
                    label: 'RAM Capacity', fieldname: 'ram_capacity', fieldtype: 'Select', 
                    options: ['Loading...'], default: child.ram_capacity || '', 
                    reqd: !child.ram_capacity, read_only: !!child.ram_capacity
                },
                { 
                    label: 'RAM Speed', fieldname: 'ram_speed', fieldtype: 'Select', 
                    options: ['Loading...'], default: child.ram_speed || '', 
                    reqd: !child.ram_speed, 
                    read_only: !!child.ram_speed && child.ram_speed !== "UNKNOWN SPEED" 
                },
                { 
                    label: 'Grade', fieldname: 'grade', fieldtype: 'Select', 
                    options: ['Loading...'], default: child.grade || '', 
                    reqd: !child.grade, read_only: false // Grade is always editable
                },
            ],
            primary_action_label: 'Save',
            primary_action(values) {
                Object.keys(values).forEach(fieldname => {
                    if (values[fieldname]) {
                        frm.set_df_property(grid.df.fieldname, 'options', values[fieldname], frm.docname, fieldname, cdn);
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
                    args: { label: attributeName ,
                        template: frm.doc.item_template,
                        item_group: item_group
                    },
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

    njqca_laptop_processor_add: function(frm, cdt, cdn) {
      
        frm.fields_dict['njqca_laptop_processor'].grid.refresh();

        setTimeout(() => show_checkbutton_processors(frm), 300);
    },
    check_button: async function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        let item_group = child.item_group;
        let grid = frm.get_field(child.parentfield);
    
        let d = new frappe.ui.Dialog({
            title: 'Processor Attributes',
            fields: [
                { 
                    label: 'Processor Type', fieldname: 'processor_type', fieldtype: 'Select', 
                    options: ['Loading...'], default: child.processor_type || '', 
                    reqd: !child.processor_type, read_only: !!child.processor_type 
                },
                { 
                    label: 'Grade', fieldname: 'grade', fieldtype: 'Select', 
                    options: ['Loading...'], default: child.grade || '', 
                    reqd: !child.grade, read_only: false 
                },
            ],
            primary_action_label: 'Save',
            primary_action(values) {
                Object.keys(values).forEach(fieldname => {
                    if (values[fieldname]) {
                        frm.set_df_property(grid.df.fieldname, 'options', values[fieldname], frm.docname, fieldname, cdn);
                        frappe.model.set_value(cdt, cdn, fieldname, values[fieldname]);
                    }
                });
    
                frm.refresh_field(grid.df.fieldname);
    
                fetch_item_template_disp_adp(frm, item_group, function(item_template_data) {
                    frappe.model.set_value(cdt, cdn, 'item_template', 'LAPTOP PROCESSOR');
                    frm.refresh_field(grid.df.fieldname);
                    generateProcessorItemCode(frm, cdt, cdn, child);
                });
    
                d.hide();
            }
        });
    
        const fieldToAttribute = {
            'processor_type': 'Processor Type', 'grade': 'Grade'
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
                    args: { label: attributeName,template: frm.doc.item_template,item_group: item_group },
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

function show_checkbutton_adaptor(frm) {
    
    frm.fields_dict['njqca_adaptor'].$wrapper.find('.grid-body .rows .grid-row').each(function(i, item) {
        let $row = $(item);
        let $checkButtonCell = $row.find('[data-fieldname="check_button"]');

        $checkButtonCell.empty();

        $checkButtonCell.append(
            `<button class='btn btn-primary btn-xs check-button'
                     style='padding: 2px 10px;
                            font-size: 12px;
                            line-height: 1.5;
                            border-radius: 3px;
                            background-color: #589ffc;
                            border: none;
                            margin-left: 15px;
                            width: auto;
                            min-width: 50px;'>Check</button>`
        );

        $checkButtonCell.find('.check-button').click(function() {
            let cdn = $row.attr('data-name');
            let cdt = frm.fields_dict['njqca_adaptor'].grid.doctype;
            frm.script_manager.trigger('check_button', cdt, cdn);
        });
    });
}


function show_checkbutton_display(frm) {
    
    frm.fields_dict['njqca_display'].$wrapper.find('.grid-body .rows .grid-row').each(function(i, item) {
        let $row = $(item);
        let $checkButtonCell = $row.find('[data-fieldname="check_button"]');

        $checkButtonCell.empty();

        $checkButtonCell.append(
            `<button class='btn btn-primary btn-xs check-button'
                     style='padding: 2px 10px;
                            font-size: 12px;
                            line-height: 1.5;
                            border-radius: 3px;
                            background-color: #589ffc;
                            border: none;
                            margin-left: 15px;
                            width: auto;
                            min-width: 50px;'>Check</button>`
        );

        $checkButtonCell.find('.check-button').click(function() {
            let cdn = $row.attr('data-name');
            let cdt = frm.fields_dict['njqca_display'].grid.doctype;
            frm.script_manager.trigger('check_button', cdt, cdn);
        });
    });
}

function show_checkbutton_processors(frm) {
    
    frm.fields_dict['njqca_laptop_processors'].$wrapper.find('.grid-body .rows .grid-row').each(function(i, item) {
        let $row = $(item);
        let $checkButtonCell = $row.find('[data-fieldname="check_button"]');

        $checkButtonCell.empty();

        $checkButtonCell.append(
            `<button class='btn btn-primary btn-xs check-button'
                     style='padding: 2px 10px;
                            font-size: 12px;
                            line-height: 1.5;
                            border-radius: 3px;
                            background-color: #589ffc;
                            border: none;
                            margin-left: 15px;
                            width: auto;
                            min-width: 50px;'>Check</button>`
        );

        $checkButtonCell.find('.check-button').click(function() {
            let cdn = $row.attr('data-name');
            let cdt = frm.fields_dict['njqca_laptop_processors'].grid.doctype;
            frm.script_manager.trigger('check_button', cdt, cdn);
        });
    });
}

function show_checkbutton_ram(frm) {
    
    frm.fields_dict['njqca_laptop_ram'].$wrapper.find('.grid-body .rows .grid-row').each(function(i, item) {
        let $row = $(item);
        let $checkButtonCell = $row.find('[data-fieldname="check_button"]');

        $checkButtonCell.empty();

        $checkButtonCell.append(
            `<button class='btn btn-primary btn-xs check-button'
                     style='padding: 2px 10px;
                            font-size: 12px;
                            line-height: 1.5;
                            border-radius: 3px;
                            background-color: #589ffc;
                            border: none;
                            margin-left: 15px;
                            width: auto;
                            min-width: 50px;'>Check</button>`
        );

        $checkButtonCell.find('.check-button').click(function() {
            let cdn = $row.attr('data-name');
            let cdt = frm.fields_dict['njqca_laptop_ram'].grid.doctype;
            frm.script_manager.trigger('check_button', cdt, cdn);
        });
    });
}

function show_checkbutton_storage(frm) {
    
    frm.fields_dict['njqca_laptop_storage'].$wrapper.find('.grid-body .rows .grid-row').each(function(i, item) {
        let $row = $(item);
        let $checkButtonCell = $row.find('[data-fieldname="check_button"]');

        $checkButtonCell.empty();

        $checkButtonCell.append(
            `<button class='btn btn-primary btn-xs check-button'
                     style='padding: 2px 10px;
                            font-size: 12px;
                            line-height: 1.5;
                            border-radius: 3px;
                            background-color: #589ffc;
                            border: none;
                            margin-left: 15px;
                            width: auto;
                            min-width: 50px;'>Check</button>`
        );

        $checkButtonCell.find('.check-button').click(function() {
            let cdn = $row.attr('data-name');
            let cdt = frm.fields_dict['njqca_laptop_storage'].grid.doctype;
            frm.script_manager.trigger('check_button', cdt, cdn);
        });
    });
}