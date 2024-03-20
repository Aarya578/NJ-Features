frappe.ui.form.on('Purchase Receipt', {
    onload: function(frm) {
        if (frm.doc.docstatus == 0) {
            $('.col-lg-2.layout-side-section').hide();
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
        
        if(!child_doc.serial_no && frm.doc.docstatus == 0 || child_doc.serial_no){
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
        if(child_doc.serial_no || child_doc.truncated_item_code) {
            console.log("print for already existed serial_no -------------");
            var objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
                                                    "doctype=" + encodeURIComponent("Purchase Receipt") +
                                                    "&name=" + encodeURIComponent(cur_frm.doc.name) +
                                                    "&trigger_print=1" +
                                                    "&format=" + "Purchase Receipt Barcode" +
                                                    "&no_letterhead=1" +
                                                    "&_lang=en" 
                                                    // "&count=" + name
                                                ));
        }
    }
});