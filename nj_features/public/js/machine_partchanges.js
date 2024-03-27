// frappe.ui.form.on('Machine Part Changes', {
//     refresh: function(frm, cdt, cdn) {
//         frm.fields_dict.remove_component.grid.get_field("print").get_query = function(doc, cdt, cdn) {
//             return {
//                 filters: {
//                     "item_code": doc.item_code
//                 }
//             };
//         };

//         if (!frm.custom_print_all_button_added) {
//             // Find the element where you want to prepend the button (in this case, the column headers area)
//             var columnHeadersArea = frm.fields_dict["remove_component"].grid.wrapper.find('.grid-heading-row');

//             // Create the button element
//             var printAllButton = $('<button class="btn btn-primary btn-xs btn-custom print-all">Print All</button>');

//             printAllButton.on('click', function() {
//                 console.log("print all button is trigeered ")
//                 frappe.confirm(
//                     'Do you want to generate serial numbers for all items?',
//                     function() {
//                         // Loop through each row in the grid
//                         frm.doc.remove_component.forEach(function(row) {
//                             if (!row.serial_no) {
//                                 // Check if the item is serialized
//                                 frappe.call({
//                                     method: 'nj_features.api_files.serializer_or_notserializer',
//                                     args: {
//                                         item_code: row.component
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
//                                                         if (!serial_no_response.exc && serial_no_response.message) {
//                                                             // Set the serial number for the row
//                                                             frappe.model.set_value(row.doctype, row.name, 'serial_no', serial_no_response.message);

//                                                             // Generate and save barcode for the new serial number
//                                                             frappe.call({
//                                                                 method: 'nj_features.nj_features.doctype.inward.inward.generate_and_save_barcode',
//                                                                 args: {
//                                                                     serial_no: serial_no_response.message
//                                                                 },
//                                                                 callback: function(barcode_response) {
//                                                                     if (!barcode_response.exc) {
//                                                                         frappe.msgprint('Barcode generated and saved.');
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
//                             }
//                         });
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

// // frappe.ui.form.on('Component Remove', {
// //     // ... (other event listeners)

// //     print: function(frm, cdt, cdn) {
// //         console.log("print button is triggered");
// //         var child_doc = locals[cdt][cdn];
// //         console.log("child_doc", child_doc);

// //         // Fetch the item code from the component
// //         var item_code = child_doc.component;
// //         console.log("item_code", item_code);

// //         // Check if the item is serialized and if it has a serial number
// //         frappe.call({
// //             method: 'nj_features.api_files.serializer_or_notserializer',
// //             args: {
// //                 item_code: item_code
// //             },
// //             callback: function(r) {
// //                 if (!r.exc) {
// //                     var has_serial_no = r.message;
// //                     if (has_serial_no) {
// //                         // Item is serialized
// //                         console.log("serialized item_code ");
// //                         if (!child_doc.serial_no) {
// //                             // If no serial number exists, generate one
// //                             console.log("item_code doesnot contain serial_no ");
// //                             var item_group=child_doc.item_group
// //                             console.log("item_group-----",item_group)
// //                             let d = frappe.confirm(
// //                                `Do you want to generate serial number for this: ${item_group}?`,
// //                                     () => {
// //                                         frappe.call({
// //                                             method: 'nj_features.nj_features.doctype.inward.inward.create_serial_no',
// //                                             args: {
// //                                                 item_group: item_group
// //                                             },
// //                                             callback: function(serial_no_response) {
// //                                                 console.log("serial_no_response",serial_no_response)
// //                                                 if (!serial_no_response.exc && serial_no_response.message) {
// //                                                     console.log("serial_no_response.message------serial_no",serial_no_response.message)
// //                                                     frappe.model.set_value(cdt, cdn,'serial_no', serial_no_response.message);
            
// //                                                     // Generate and save barcode for the new serial number
// //                                                     frappe.call({
// //                                                         method: 'nj_features.nj_features.doctype.inward.inward.generate_and_save_barcode',
// //                                                         args: {
// //                                                             serial_no: serial_no_response.message
// //                                                         },
// //                                                         callback: function(barcode_response) {
// //                                                             if (!barcode_response.exc) {
// //                                                                 frappe.msgprint('Barcode generated and saved.');
// //                                                                 // printBarcodes(frm )
// //                                                                 printBarcode(child_doc.serial_no)
// //                                                             } else {
// //                                                                 frappe.msgprint('Error generating barcode.');
// //                                                             }
// //                                                         }
// //                                                     });
                                                   
// //                                                 } else {
// //                                                     frappe.msgprint('Error generating serial number.');
// //                                                 }
// //                                             }
// //                                         });
// //                                     },
// //                                     () => {
// //                                         $('.primary-action').hide()
// //                                     }
// //                                 );
                          
                                
// //                         } else {
// //                             console.log("serialized item_code with serial number ", child_doc.serial_no);
// //                             // Do something if the component has a serial number
// //                             printBarcode(frm)
// //                         }
// //                     } else {
// //                         frappe.throw("for Non serialized item_code cannot generate serial_no");
// //                         // Do something if the item is not serialized
// //                         $('.grid-remove_component-row .fa-print').hide();   
// //                         frm.set_df_property(cdt,cdn,'serial_no', 'read_only', 1);
                       
// //                     }
// //                 }
// //             }
            
// //         });
        
        
// //     }
    
// // });

// // function printBarcode(serialNo) {
// //     frappe.call({
// //         method: "frappe.www.printview.get_html_and_style",
// //         args: {
// //             doc: {
// //                 "doctype": "Machine Part Changes",
// //                 "name": cur_frm.doc.name,
// //                 "serial_no": serialNo
// //             },
// //             print_format: "Machine Part Barcode",
// //             no_letterhead: 1,
// //             trigger_print: 1,
// //             _lang: "en-US"
// //         },
// //         callback: function(r) {
// //             var print_view_html = r.message.html;

// //             // Open the print view in a popup window
// //             var popupWindow = window.open("", "_blank", "width=800,height=600,top=100,left=100");
// //             popupWindow.document.write(print_view_html);
// //             setTimeout(function() {
// //                 popupWindow.print();
// //             }, 1000); // Adjust the delay time as needed
        
// //         }
// //     });
// // }











// // // // // / Barcode printing

// frappe.ui.form.on('Component Remove', {
//     // serial_no: function(frm, cdt, cdn) {
//     //     var child_doc = locals[cdt][cdn];
//     //     if (child_doc.serial_no && child_doc.serial_no.startsWith("NJ-")) {
//     //         frappe.msgprint("Manually entered serial numbers cannot start with 'NJ-'");
//     //         return;
//     //     }
//     // },
//     print: function(frm, cdt, cdn) {
//         var child_doc = locals[cdt][cdn];
//         console.log("child_doc=============", child_doc);
        
//         if(frm.doc.docstatus == 0){
//             console.log("print for not existed in serial no ")
//             frappe.call({
//                 method: 'nj_features.api_files.print_barcode',
//                 args: {
//                     doc: child_doc
//                 },
//                 callback: function(r) {
//                     if (r.message.serial_no) {
//                         frappe.model.set_value(cdt, cdn, 'serial_no', r.message.serial_no);
//                     }
//                     if (r.message.truncated_item_code) {
//                         frappe.model.set_value(cdt, cdn, 'truncated_item_code', r.message.truncated_item_code);
//                     }
//                 }
//             });
//         }
//         if((child_doc.serial_no || child_doc.truncated_item_code) && frm.doc.docstatus == 1) {
//             console.log("print for already existed serial_no -------------");
//             let objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
//                                                     "doctype=" + encodeURIComponent("Purchase Receipt Item") +
//                                                     "&name=" + encodeURIComponent(child_doc.name) +
//                                                     "&trigger_print=1" +
//                                                     "&format=" + "PR Item Barcode" +
//                                                     "&no_letterhead=1" +
//                                                     "&_lang=en"
//                                                 ));
//         }
//     }
// });