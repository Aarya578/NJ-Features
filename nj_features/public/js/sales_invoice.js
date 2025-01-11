frappe.ui.form.on('Sales Invoice', {
    refresh: function(frm) {
        handleScannerInput(frm, 'scan_barcode');
    },
    scan_barcode: function(frm) {
        handleScannerInput(frm, 'scan_barcode');
    }
});

// frappe.ui.form.on('Sales Invoice Item', {
//     // Triggered when the serial_no field in any row is updated
//     serial_no: function(frm, cdt, cdn) {
//         const child = locals[cdt][cdn];  // Get the current child row

//         // Call your custom function with the current serial_no value
//         handleScannerInput(frm, child.serial_no);
//     },

//     // Event triggered when a row is rendered in the child table
//     items_on_form_rendered: function(frm, cdt, cdn) {
//         const child = locals[cdt][cdn];  // Get the current child row

//         // Perform logic or call a function if needed when the row is rendered
//         handleScannerInput(frm, child.serial_no);
//     }
// });
