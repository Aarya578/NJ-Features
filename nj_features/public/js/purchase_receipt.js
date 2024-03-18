frappe.ui.form.on('Purchase Receipt', {
    onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        frappe.db.get_value('Employee', {'user_id': frappe.session.user_email}, ['name', 'work_warehouse'], function(r) {
            if (!r.name) {
                frappe.msgprint('Employee not found for user: <strong>'+frappe.session.user_email+'</strong>. Please mail IT Infra Team at <strong><a href="mailto:itsupport@newjaisa.com">itsupport@newjaisa.com</a></strong> to create an employee.');
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
    serial_no: function(frm, cdt, cdn) {
        var child_doc = locals[cdt][cdn];
        if (child_doc.serial_no && child_doc.serial_no.startsWith("NJ-")) {
            frappe.msgprint("Manually entered serial numbers cannot start with 'NJ-'");
            return;
        }
    },
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

// frappe.ui.form.on('Purchase Receipt', {
//     refresh: function(frm) {
//         if (!frm.custom_print_all_button_added) {
//             // Find the element where you want to prepend the button (in this case, the column headers area)
//             var columnHeadersArea = frm.fields_dict["items"].grid.wrapper.find('.grid-heading-row');

//             // Create the button element
//             var printAllButton = $('<button class="btn btn-primary btn-xs btn-custom print-all">Print All</button>');

//             printAllButton.on('click', function() {
//                 console.log("print all button is triggered ");
//                 frappe.confirm(
//                     'Do you want to generate serial numbers for all items?',
//                     function() {
//                         var serialNumbers = []; // Array to store serial numbers
//                         // Loop through each row in the grid
//                         frm.doc.items.forEach(function(row) {
//                             if (!row.serial_no) {
//                                 // Check if the item is serialized
//                                 frappe.call({
//                                     method: 'nj_features.api_files.serializer_or_notserializer',
//                                     args: {
//                                         item_code: row.item_code
//                                     },
//                                     callback: function(r) {
//                                         if (!r.exc && r.message) {
//                                             // Item is serialized
//                                             if (!row.serial_no) {
//                                                 // If no serial number exists, generate one
//                                                 frappe.call({
//                                                     method: 'nj_features.nj_features.doctype.inward.inward.create_serial_no',
//                                                     args: {
//                                                         item_group: row.item_group
//                                                     },
//                                                     callback: function(serial_no_response) {
//                                                         console.log("serial_no_response--------",serial_no_response)
//                                                         if (!serial_no_response.exc && serial_no_response.message || serial_no_response) {
//                                                             // Set the serial number for the row
//                                                             frappe.model.set_value(row.doctype, row.name, 'serial_no', serial_no_response.message);

//                                                             // Add serial number to the array
//                                                             serialNumbers.push(serial_no_response.message);
//                                                             // Generate and save barcode for the new serial number
//                                                             frappe.call({
//                                                                 method: 'nj_features.qr_code.generate_and_save_qrcode',
//                                                                 args: {
//                                                                     data: serial_no_response.message
//                                                                 },
//                                                                 callback: function(barcode_response) {
//                                                                     if (!barcode_response.exc) {
//                                                                         // Print barcode for each generated serial number
//                                                                         frappe.msgprint('QR Code generated and saved.');
//                                                                     } else {
//                                                                         frappe.msgprint('Error generating barcode.');
//                                                                     }
//                                                                 }
//                                                             });
//                                                         } else {
//                                                             frappe.msgprint('Error generating serial number.');
//                                                         }
//                                                     }
//                                                 });
//                                             }
//                                         }
//                                     }
//                                 });
//                             } else {
//                                 // Serial number exists, add to the array
//                                 serialNumbers.push(row.serial_no);
//                                 // Generate and save barcode for existing serial number
//                                 frappe.call({
//                                     method: 'nj_features.qr_code.generate_and_save_qrcode',
//                                     args: {
//                                         data: row.serial_no
//                                     },
//                                     callback: function(barcode_response) {
//                                         if (!barcode_response.exc) {
//                                             // Print barcode for each existing serial number
//                                             frappe.msgprint('QR Code generated and saved.');
//                                         } else {
//                                             frappe.msgprint('Error generating barcode.');
//                                         }
//                                     }
//                                 });
//                             }
//                         });

//                         // Open print format after processing all items
//                         printBarcode(serialNumbers);
//                     },
//                     function() {
//                         // Do nothing if the user cancels
//                     }
//                 );
//             });

//             // Wrap the button in a div to match the structure of the column headers
//             var buttonWrapper = $('<div class="col grid-static-col col-xs-2" data-fieldname="print_all" data-fieldtype="Button" title="Print All"></div>');
//             buttonWrapper.append(printAllButton);

//             // Add the button to the column headers area
//             columnHeadersArea.prepend(buttonWrapper);

//             // Set the flag to indicate that the button has been added
//             frm.custom_print_all_button_added = true;
//         }
//     }
// });

// // Function to open print format with all serial numbers
// function printBarcode(serialNumbers) {
//     // Open print format with all serial numbers
//     var objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
//         "doctype=" + encodeURIComponent("Purchase Receipt") +
//         "&name=" + encodeURIComponent(cur_frm.doc.name) +
//         "&trigger_print=1" +
//         "&format=" + "Purchase Receipt Barcode" +
//         "&no_letterhead=1" +
//         "&_lang=en" +
//         "&serial_numbers=" + encodeURIComponent(serialNumbers.join('\n')))); // Pass serial numbers as a parameter
//     console.log("objWindowOpenResult-----", objWindowOpenResult);
// }
