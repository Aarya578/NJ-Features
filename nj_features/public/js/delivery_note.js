frappe.ui.form.on('Delivery Note', {
   
    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Print QR Code'), function() {
                var docname = encodeURIComponent(frm.doc.name);
                var format = "Delivery Note Barcode";
                var print_trigger = 1;
                
                window.open(frappe.urllib.get_full_url("/printview?" +
                    "doctype=" + encodeURIComponent("Delivery Note") +
                    "&name=" + docname +
                    "&trigger_print=" + print_trigger +
                    "&format=" + format +
                    "&no_letterhead=0" +
                    "&_lang=" + (frappe.boot.lang || "en")));
            }).addClass('btn-primary');
        } else {
            frm.remove_custom_button(__('Print QR Code'));
        }
        console.log("inside delivery note=============================");
        
    }
    
});

