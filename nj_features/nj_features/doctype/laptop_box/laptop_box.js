
// frappe.ui.form.on('Laptop Box', {
//     barcode: function(frm) {
//         if (frm.doc.barcode) {
//             frappe.call({
//                 method: "frappe.client.get",
//                 args: {
//                     doctype: "Serial No",
//                     filters: { name: frm.doc.barcode },
//                 },
//                 callback: function(r) {
//                     if (r.message) {
//                         let serial_no_data = r.message;

//                         // Fetch the Item document based on item_code from Serial No
//                         frappe.call({
//                             method: "frappe.client.get",
//                             args: {
//                                 doctype: "Item",
//                                 name: serial_no_data.item_code,  // Get item code from Serial No
//                             },
//                             callback: function(item_data) {
//                                 if (item_data.message) {
//                                     let item = item_data.message;

//                                     // Debug: Log all attributes in the child table
//                                     console.log("Item Variant Attributes:", item.attributes);

//                                     // Loop through the child table 'Item Variant Attribute'
//                                     if (item.attributes && item.attributes.length > 0) {
//                                         let processor_type = '';
//                                         let ram_capacity = '';  // Renaming for clarity
//                                         let storage_capacity = '';

//                                         item.attributes.forEach(function(attr) {
//                                             // Check the exact names of attributes
//                                             if (attr.attribute == "Processor Type") {
//                                                 processor_type = attr.attribute_value;
//                                             }
//                                             if (attr.attribute == "RAM Capacity" || attr.attribute == "RAM Capacity") {
//                                                 // Add alternate RAM field names here for flexibility
//                                                 ram_capacity = attr.attribute_value;
//                                             }
//                                             if (attr.attribute == "Storage Capacity") {
//                                                 storage_capacity = attr.attribute_value;
//                                             }
//                                         });

//                                         // Set the fetched values in the Laptop Box form
//                                         frm.set_value("processor_type", processor_type);
//                                         frm.set_value("ram_capacity", ram_capacity);  // Using ram_capacity now
//                                         frm.set_value("storage_capacity", storage_capacity);
//                                     } else {
//                                         frappe.throw("No attributes found in Item Variant Attribute table.");
//                                     }
//                                 } else {
//                                     frappe.throw("Item not found for the scanned Serial No.");
//                                 }
//                             }
//                         });
//                     } else {
//                         frm.set_value("barcode", null);
//                         frappe.throw(`Serial No <b>'${frm.doc.barcode}'</b> not found. Please select an existing Serial No.`);
//                     }
//                 },
//                 error: function() {
//                     frappe.throw("Error fetching data for the barcode.");
//                 }
//             });
//         }
//     }
// });
frappe.ui.form.on('Laptop Box', {
    barcode: function(frm) {
        frappe.call({
            method: 'nj_features.qr_code.generate_and_save_qrcode',
            args: { data: frm.doc.barcode }
        });

        if (frm.doc.barcode) {
            frappe.call({
                method: "frappe.client.get",
                args: {
                    doctype: "Serial No",
                    name: frm.doc.barcode, 
                },
                callback: function(r) {
                    if (r.message) {
                        let serial_no_data = r.message;

                        frm.set_value("brand", serial_no_data.brand);  
                        frm.set_value("model", serial_no_data.model);  

                       

                        frappe.call({
                            method: "frappe.client.get",
                            args: {
                                doctype: "Item",
                                name: serial_no_data.item_code,  
                            },
                            callback: function(item_data) {
                                if (item_data.message) {
                                    let item = item_data.message;

                                    console.log("Item Variant Attributes:", item.attributes);

                                    if (item.attributes && item.attributes.length > 0) {
                                        let processor_type = '';
                                        let ram_capacity = '';
                                        let storage_capacity = '';

                                        item.attributes.forEach(function(attr) {
                                            if (attr.attribute == "Processor Type") {
                                                processor_type = attr.attribute_value;
                                            }
                                            if (attr.attribute == "RAM Capacity" || attr.attribute == "RAM") {
                                                ram_capacity = attr.attribute_value;
                                            }
                                            if (attr.attribute == "Storage Capacity") {
                                                storage_capacity = attr.attribute_value;
                                            }
                                        });

                                        frm.set_value("processor_type", processor_type);
                                        frm.set_value("ram_capacity", ram_capacity);
                                        frm.set_value("storage_capacity", storage_capacity);
                                    } else {
                                        frappe.throw("No attributes found in the Item Variant Attribute table.");
                                    }
                                } else {
                                    frappe.throw("Item not found for the scanned Serial No.");
                                }
                            }
                        });
                    } else {
                        frm.set_value("barcode", null);
                        frappe.throw(`Serial No <b>'${frm.doc.barcode}'</b> not found. Please select an existing Serial No.`);
                    }
                },
                error: function() {
                    frappe.throw("Error fetching data for the barcode.");
                }
            });
        }
    }
});


