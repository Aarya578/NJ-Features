frappe.ui.form.on('Purchase Receipt', {
    onload: function(frm) {
        frappe.db.get_value('Employee', {'user_id': frappe.session.user_email}, ['name', 'work_warehouse'], function(r) {
            if (!r.name) {
                frappe.msgprint('Employee not found for user: <strong>'+frappe.session.user_email+'</strong>. Please mail us at <strong><a href="mailto:itsupport@newjaisa.com">itsupport@newjaisa.com</a></strong> to create an employee.');
                return;
            }
            if (!r.work_warehouse) {
                frappe.msgprint('Work Warehouse does not exist for Employee: <strong>'+frappe.session.user_email+'</strong>.');
                return;
            } else {
                cur_frm.set_value('set_warehouse', r.work_warehouse)
            }
        })
    }
});

// Barcode printing
frappe.ui.form.on('Purchase Receipt Item', {

    print: function(frm, cdt, cdn) {
        var child_doc = locals[cdt][cdn];
        console.log("child_doc", child_doc);
        frappe.call({
            method: 'nj_features.api_files.print_barcode',
            args: {
                doc: child_doc
            },
            callback: function(r) {
                frappe.model.set_value(cdt, cdn, 'serial_no', r.message);
                
            }
        });
        if(child_doc.serial_no) {
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