frappe.ui.form.on('Transaction', {
    scan_barcode: function(frm) {
        if (frm.doc.scan_barcode && (frm.doc.stock_movement == 1 || frm.doc.move_stock == 1)) {
            frappe.call({
                method: "nj_features.api_files.search_for_serial_or_batch_or_barcode_no",
                args: {
                    search_value: frm.doc.scan_barcode
                },
                callback: function(r) {
                    const data = r && r.message;
                    if (data && Object.keys(data).length !== 0) {
                        modify_table_after_scan_override(frm, data);
                    }
                }
            });
        }
        return false;
    }
});


function modify_table_after_scan_override(frm, data) {
    var child_table_data = frm.fields_dict.items.grid.grid_rows_by_docname;
    var child_records = Object.values(child_table_data);
    console.log("len:", child_records.length);
    var last_child_record = child_records[child_records.length - 1].doc;

    if (data.serial_no) {
        last_child_record.serial_no = data.serial_no;
        last_child_record.item_code = data.item_code;
    } else if (data.item_code) {
        last_child_record.item_code = data.item_code;
    }

    // Check if scan_grade should be hidden based on the serial number
    frappe.call({
        method: 'nj_features.api_files.serializer_or_notserializer',
        args: {
            item_code: last_child_record.item_code
        },
        callback: function(response) {
            var has_serial_no = response.message;
            if (has_serial_no === 0) { // Check if non-serializable
                frm.toggle_display(['scan_grade', 'scan_warehouse'], true);
            } else { // Serializable
                frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
            }
        }
    });
}
