frappe.ui.form.on('Purchase Receipt', {
    onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        if (frm.doc.docstatus == 0) {
            var user_email = frappe.session.user
            frappe.db.get_value('Employee', {'user_id': user_email, 'status': 'Active'}, 'work_warehouse').then(function(r) {

                if (r.message && r.message.work_warehouse) {

                    frm.set_value('set_warehouse', r.message.work_warehouse)

                    frm.doc.items.forEach(function(item) {
                        frappe.db.get_list('NJ Settings', {
                            filters: {'doc_type':'Warehouse', 'module':'NJ Features'},
                            fields: ['parameter', 'value']
                        }).then(function(result) {
                            result.forEach(function(setting) {
        
                                if (setting.parameter === item.item_group) {
                                    item.warehouse = setting.value;
                                }
                            });
                        });
        
                    });
                } else {
                    frappe.throw("Work Warehouse is not set for <b>User: "+user_email+"</b>. Please mail us at <strong><a href='mailto:itsupport@newjaisa.com'>itsupport@newjaisa.com</a></strong> to create an employee.")
                }
            });
        }
        frm.refresh_field("items")


        // let items = frm.doc.items.map(row => ({
        //     idx: row.idx,
        //     item_group: row.item_group
        // }));

        // frappe.call({
        //     method: "nj_features.overrides.purchase_receipt.get_item_group_cost_centers",
        //     args: { items: items },
        //     callback: function(r) {
                
        //         if (r.message) {
        //             console.log("Cost centers:===", r.message);
                    
        //             frm.doc.items.forEach(row => {
        //                 if (r.message[row.idx]) {
        //                     frappe.model.set_value(row.doctype, row.name, "cost_center", r.message[row.idx]);

        //                 }
        //                  frm.refresh_field('cost_center');
        //             });
        //         }
        //     }
        // });
    },

    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {

            frm.add_custom_button(__('Print QR Code'), function() {
                var docname = encodeURIComponent(frm.doc.name);
                var format = "Purchase Receipt Barcode";
                var print_trigger = 1;
                
                window.open(frappe.urllib.get_full_url("/printview?" +
                    "doctype=" + encodeURIComponent("Purchase Receipt") +
                    "&name=" + docname +
                    "&trigger_print=" + print_trigger +
                    "&format=" + format +
                    "&no_letterhead=0" +
                    "&_lang=" + (frappe.boot.lang || "en")));
            }).addClass('btn-primary');

        } else {
            frm.remove_custom_button('Print Barcode');
        }
    }
});

// Barcode printing
frappe.ui.form.on('Purchase Receipt Item', {
    // serial_no: function(frm, cdt, cdn) {
    //     var child_doc = locals[cdt][cdn];
    //     if (child_doc.serial_no && child_doc.serial_no.startsWith("NJ-")) {
    //         frappe.msgprint("Manually entered serial numbers cannot start with 'NJ-'");
    //         return;
    //     }
    // },
    print: function(frm, cdt, cdn) {

        var child_doc = locals[cdt][cdn];
        
        if(frm.doc.docstatus == 0){
            frappe.call({
                method: 'nj_features.nj_features.api.qr_code.print_barcode',
                args: {
                    doc: child_doc
                },
                callback: function(r) {
                    
                    if (r.message.serial_no) {
                        frappe.model.set_value(cdt, cdn, 'serial_no', r.message.serial_no);
                    }
                    if (r.message.truncated_item_code) {
                        frappe.model.set_value(cdt, cdn, 'truncated_item_code', r.message.truncated_item_code);
                    }
                    if (r.message.decoded_item_code) {
                        frappe.model.set_value(cdt, cdn, 'decoded_item_code', r.message.decoded_item_code);
                    }
                }
            });
        }

        if((child_doc.qr_code_mapping || child_doc.truncated_item_code) && frm.doc.docstatus == 1) {
            let objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
                                        "doctype=" + encodeURIComponent("Purchase Receipt Item") +
                                        "&name=" + encodeURIComponent(child_doc.name) +
                                        "&trigger_print=1" +
                                        "&format=" + "PR Item Barcode" +
                                        "&qr_code_name=" + child_doc.decoded_item_code +
                                        "&no_letterhead=1" +
                                        "&_lang=en"
                                    ));
        }
    }
});