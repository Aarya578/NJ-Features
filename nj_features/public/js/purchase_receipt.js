frappe.ui.form.on('Purchase Receipt', {
    onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        if (frm.doc.docstatus == 0) {
            frappe.db.get_value('Employee', {'user_id': frappe.session.user_email}, ['name', 'work_warehouse'], function(r) {
                if (!r.name) {
                    frappe.msgprint('Employee not found for user: <strong>'+frappe.session.user_email+'</strong>. Please mail IT Infra Team at <strong><a href="mailto:itinfra@newjaisa.com">itinfra@newjaisa.com</a></strong> to create an employee.');
                    return;
                }
                if (!r.work_warehouse) {
                    frappe.msgprint('Work Warehouse does not exist for Employee: <strong>'+frappe.session.user_email+'</strong>.');
                    return;
                } else {
                    cur_frm.set_value('set_warehouse', r.work_warehouse)
                }
            });
        }
    },
    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Print Barcode'), function() {
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
        console.log("child_doc=============", child_doc);
        
        if(!child_doc.serial_no && frm.doc.docstatus == 0){
            console.log("print for not existed in serial no ")
            frappe.call({
                method: 'nj_features.api_files.print_barcode',
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
                }
            });
        }
        if((child_doc.serial_no || child_doc.truncated_item_code) && frm.doc.docstatus == 1) {
            console.log("print for already existed serial_no -------------");
            let objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
                                                    "doctype=" + encodeURIComponent("Purchase Receipt Item") +
                                                    "&name=" + encodeURIComponent(child_doc.name) +
                                                    "&trigger_print=1" +
                                                    "&format=" + "PR Item Barcode" +
                                                    "&no_letterhead=1" +
                                                    "&_lang=en"
                                                ));
        }
    }
});