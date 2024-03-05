frappe.ui.form.on('Purchase Receipt', {
    onload: function(frm) {
        frappe.db.get_value('Employee', {'user_id': frappe.session.user_email}, ['name', 'work_warehouse'], function(r) {
            console.log("emp: ", r);
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

frappe.ui.form.on('Purchase Receipt', {
    
    validate: function(frm) {
        for (let i = 0; i < frm.doc.items.length; i++) {
            let item = frm.doc.items[i];
            if (item.serial_no) {
                if (item.serial_no.split('\n').length < item.qty) {
                    let remainingSerials = item.qty - item.serial_no.split('\n').length;
                    for (let j = 0; j < remainingSerials; j++) {
                        createSerialNo(frm, item);
                    }
                }
            } else {
                for (let k = 0; k < item.qty; k++) {
                    createSerialNo(frm, item);
                }
            }
        }
    },

    on_submit: function(frm) {
        frm.add_custom_button(__('Print All Barcodes'), function() {
            var name = prompt("Please enter the number of copies required for all Serial Numbers:");
            if (name) {
                for (let i = 0; i < cur_frm.doc.items.length; i++) {
                    var new_var = cur_frm.doc.items[i].serial_no;
                    var new_list = new_var.split("\n");
                    printAllSerialNumbers(i, new_list, name); 
                }
            } else {
                frappe.throw("Barcode Print has been cancelled for all Serial Numbers.");
            }
        }).addClass('btn-primary');

        var new_list = [];
        for (let i = 0; i < cur_frm.doc.items.length; i++) {
            var new_var = cur_frm.doc.items[i].serial_no;
            new_list = new_var.split("\n");
            printSerialNumbers(i, new_list);
        }
    }
    
});

function printAllSerialNumbers(i, new_list, name) {
    frappe.confirm(
        "Barcode for Serial Numbers <strong>" + new_list + "</strong> for Item: <strong>" + cur_frm.doc.items[i].item_code + "</strong> will be Printed.<br>" + "Proceed to Print Page?",
        function() {
            if (name) {
                var res;
                var com;
                frappe.call({
                    method: "nj_features.api_files.get_max_cop",
                    args: {
                        item_code: cur_frm.doc.items[i].item_code,
                        serial_no: new_list,
                        print_cpy: name
                    },
                    callback: function(response) {
                        if (response.message) {
                            console.log(response);
                            var max_cop = response.message[0];
                            var prf = "Purchase Receipt Barcode";
                            console.log("max_copy: " + max_cop + " | req. copy:" + name);

                            if (name > max_cop) {
                                frappe.prompt([{
                                        fieldname: 'reason',
                                        label: 'Reason',
                                        fieldtype: 'Link',
                                        reqd: 1,
                                        options: 'Master Reasons'
                                    },
                                    {
                                        fieldname: 'comment',
                                        label: 'Comment',
                                        fieldtype: 'Small Text',
                                        reqd: 1
                                    }
                                ], function(values) {
                                    res = values.reason;
                                    com = values.comment;
                                    frappe.call({
                                        method: "nj_features.api_files.create_reason_copy",
                                        args: {
                                            item_code: cur_frm.doc.items[i].item_code,
                                            serial_no: new_list,
                                            name: cur_frm.doc.name,
                                            copies: name,
                                            reason: res,
                                            comment: com,
                                            doctype: "Purchase Receipt"
                                        },
                                        callback: function(response) {
                                            if (response.message) {
                                                var objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
                                                    "doctype=" + encodeURIComponent("Purchase Receipt") +
                                                    "&name=" + encodeURIComponent(cur_frm.doc.name) +
                                                    "&trigger_print=1" +
                                                    "&format=" + prf +
                                                    "&no_letterhead=1" +
                                                    "&_lang=en" +
                                                    "&count=" + name
                                                )); // end print link
                                            } else {
                                                console.log("Not in document");
                                                var objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
                                                    "doctype=" + encodeURIComponent("Purchase Receipt") +
                                                    "&name=" + encodeURIComponent(cur_frm.doc.name) +
                                                    "&trigger_print=1" +
                                                    "&format=" + prf +
                                                    "&no_letterhead=1" +
                                                    "&_lang=en" +
                                                    "&count=" + name
                                                )); // end print link
                                            }
                                        }
                                    });

                                }, 'Excess Printing of QR Code detected for Serial NO : ' + new_list);
                            } else {
                                var objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
                                    "doctype=" + encodeURIComponent("Purchase Receipt") +
                                    "&name=" + encodeURIComponent(cur_frm.doc.name) +
                                    "&trigger_print=1" +
                                    "&format=" + prf +
                                    "&no_letterhead=1" +
                                    "&_lang=en" +
                                    "&count=" + name
                                )); // end print link
                            }
                        }
                    }
                });
            } else {
                frappe.throw("Barcode Print has been cancelled for all Serial Numbers.");
            }
        },
        function() {
            // No button action
            // Do nothing or handle the rejection case
        },
        'Confirmation',
        ['Print', 'No']
    );
}



function printSerialNumbers(i, new_list) {
    frappe.confirm(
        "Barcode for Serial Numbers <strong>" + new_list + "</strong> for Item: <strong>" + cur_frm.doc.items[i].item_code + "</strong> will be Printed.<br>" + "Proceed to Print Page?",
        function() {
            for (let j = 0; j < new_list.length; j++) {
                var name = prompt("Please enter the number of copies required for Serial No: " + new_list[j]);
                if (name) {
                    // var copy_rqd = name;
                    var res;
                    var com;
                    frappe.call({
                        method: "nj_features.api_files.get_max_cop",
                        args: {
                            item_code: cur_frm.doc.items[i].item_code,
                            serial_no: new_list[j],
                            print_cpy: name
                        },
                        callback: function(response) {
                            if (response.message) {
                                console.log(response);
                                var max_cop = response.message[0];
                                var prf = response.message[1];
                                console.log("max_copy: " + max_cop + " | req. copy:" + name);

                                if (name > max_cop) {
                                    frappe.prompt([{
                                        fieldname: 'reason',
                                        label: 'Reason',
                                        fieldtype: 'Link',
                                        reqd: 1,
                                        options: 'Master Reasons'
                                    },
                                    {
                                        fieldname: 'comment',
                                        label: 'Comment',
                                        fieldtype: 'Small Text',
                                        reqd: 1
                                    }
                                    ], function(values) {
                                        res = values.reason;
                                        com = values.comment;
                                        frappe.call({
                                            method: "nj_features.api_files.create_reason_copy",
                                            args: {
                                                item_code: cur_frm.doc.items[i].item_code,
                                                serial_no: new_list[j],
                                                name: cur_frm.doc.name,
                                                copies: name,
                                                reason: res,
                                                comment: com,
                                                doctype: "Purchase Receipt"
                                            },
                                            callback: function(response) {
                                                if (response.message) {
                                                    console.log("reason Created");
                                                    var objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
                                                        "doctype=" + encodeURIComponent("Serial No") +
                                                        "&name=" + encodeURIComponent(new_list[j]) +
                                                        "&trigger_print=1" +
                                                        "&format=" + prf +
                                                        "&no_letterhead=1" +
                                                        "&_lang=en" +
                                                        "&count=" + name
                                                    )); // end print link
                                                } else {
                                                    console.log("Not in document");
                                                    var objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
                                                        "doctype=" + encodeURIComponent("Serial No") +
                                                        "&name=" + encodeURIComponent(new_list[j]) +
                                                        "&trigger_print=1" +
                                                        "&format=" + prf +
                                                        "&no_letterhead=1" +
                                                        "&_lang=en" +
                                                        "&count=" + name
                                                    )); // end print link
                                                }
                                            }
                                        });

                                    }, 'Excess Printing of QR Code detected for Serial NO : ' + new_list[j]);
                                } else {
                                    var objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
                                        "doctype=" + encodeURIComponent("Serial No") +
                                        "&name=" + encodeURIComponent(new_list[j]) +
                                        "&trigger_print=1" +
                                        "&format=" + prf +
                                        "&no_letterhead=1" +
                                        "&_lang=en" +
                                        "&count=" + name
                                    )); // end print link
                                }
                            }
                        }
                    });
                } else {
                    frappe.throw("Barcode Print has been cancelled for Serial No: <strong>"+new_list[j]+"</strong>.");
                }
            }
        },
        function() {
            // No button action
            // Do nothing or handle the rejection case
        },
        'Confirmation',
        ['Print', 'No']
    );
}

function createSerialNo(frm, item) {
    frappe.call({
        method: 'nj_features.api_files.create_serial_no',
        args: {
            item_code: item.item_code,
        },
        callback: function(response) {
            if (response && response.message) {
                console.log("\ncreate serial no: ", response.message);
                let newSerialNo = response.message;
                if (item.serial_no) {
                    item.serial_no += '\n' + newSerialNo;
                } else {
                    item.serial_no = newSerialNo;
                }
                refresh_field('items');
            } else {
                frappe.msgprint('Error generating serial number.');
            }
        },
        error: function(err) {
            frappe.msgprint('Error generating serial number: ' + err.message);
        }
    });
}


// frappe.ui.form.on('Purchase Receipt', {
// 	validate: function(frm) {
//         for (let i = 0; i < frm.doc.items.length; i++) {
//             let item = frm.doc.items[i];
//             if (item.serial_no && item.serial_no.split('\n').length < item.qty) {
//                 let remainingSerials = item.qty - item.serial_no.split('\n').length;
//                 for (let j = 0; j < remainingSerials; j++) {
//                     createSerialNo(frm, item);
//                 }
//             } else {
//                 for (let k = 0; k < item.qty; k++) {
//                     createSerialNo(frm, item);
//                 }
//             }
//         }
//     },
    
//     refresh: function(frm) {
//         console.log("submit");
//         var new_list = [];
//         for (let i = 0; i < cur_frm.doc.items.length; i++) {
//         var new_var = cur_frm.doc.items[i].serial_no;
//             new_list = new_var.split("\n");
//             frappe.confirm(
//             "Barcode for Serial Numbers <strong>" + new_list + "</strong> for Item: <strong>" + cur_frm.doc.items[i].item_code + "</strong> will be Printed.<br>" + "Proceed to Print Page?",
//             function() {
//                 console.log("\n\nafter list: ", new_list.length);
//                 for (let j = 0; j < new_list.length; j++) {
//                 var name = prompt("Please enter the number of copies required for Serial No: " + new_list[j]);
//                 if (name) {
//                     var copy_rqd = name;
//                     var res;
//                     var com;
//                     frappe.call({
//                     method: "nj_features.api_files.get_max_cop",
//                     args: {
//                         item_code: cur_frm.doc.items[i].item_code,
//                         serial_no: new_list[j],
//                         print_cpy: name
//                     },
//                     callback: function(response) {
//                         if (response.message) {
//                         console.log(response);
//                         var max_cop = response.message[0];
//                         // var weight = response.message[1];
//                         // var height = response.message[2];
//                         var prf = response.message[1];
//                         console.log("re " + max_cop + " " + name);

//                         if (name > max_cop) {
//                             console.log("-------Reason---------");
//                             frappe.prompt([{
//                                 fieldname: 'reason',
//                                 label: 'Reason',
//                                 fieldtype: 'Link',
//                                 reqd: 1,
//                                 options: 'Master Reasons'
//                             },
//                             {
//                                 fieldname: 'comment',
//                                 label: 'Comment',
//                                 fieldtype: 'Small Text',
//                                 reqd: 1
//                             }
//                             ], function(values) {
//                             res = values.reason;
//                             com = values.comment;
//                             frappe.call({
//                                 method: "nj_features.api_files.create_reason_copy",
//                                 args: {
//                                 item_code: cur_frm.doc.items[i].item_code,
//                                 serial_no: new_list[j],
//                                 name: cur_frm.doc.name,
//                                 copies: name,
//                                 reason: res,
//                                 comment: com,
//                                 doctype: "Purchase Receipt"
//                                 },
//                                 callback: function(response) {
//                                 if (response.message) {
//                                     console.log("reason Created");
//                                     var objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
//                                     "doctype=" + encodeURIComponent("Purchase Receipt") +
//                                     "&name=" + encodeURIComponent(new_list[j]) +
//                                     "&serial_no=" + encodeURIComponent(new_list[j]) +
//                                     "&trigger_print=1" +
//                                     "&format=" + prf +
//                                     "&no_letterhead=1" +
//                                     // "&width=" + weight +
//                                     // "&height=" + height +
//                                     "&_lang=en" +
//                                     "&count=" + name
//                                     )); // end print link
//                                 } else {
//                                     console.log("Not in document");
//                                     var objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
//                                     "doctype=" + encodeURIComponent("Serial No") +
//                                     "&name=" + encodeURIComponent(new_list[j]) +
//                                     "&serial_no=" + encodeURIComponent(new_list[j]) +
//                                     "&trigger_print=1" +
//                                     "&format=" + prf +
//                                     "&no_letterhead=1" +
//                                     // "&width=" + weight +
//                                     // "&height=" + height +
//                                     "&_lang=en" +
//                                     "&count=" + name
//                                     )); // end print link
//                                 }
//                                 }
//                             });

//                             }, 'Excess Printing of QR Code detected for Serial NO : ' + new_list[j]);
//                         } else {
//                             var objWindowOpenResult = window.open(frappe.urllib.get_full_url("/printview?" +
//                             "doctype=" + encodeURIComponent("Serial No") +
//                             "&name=" + encodeURIComponent(new_list[j]) +
//                             "&serial_no=" + encodeURIComponent(new_list[j]) +
//                             "&trigger_print=1" +
//                             "&format=" + prf +
//                             "&no_letterhead=1" +
//                             // "&width=" + weight +
//                             // "&height=" + height +
//                             "&_lang=en" +
//                             "&count=" + name
//                             )); // end print link
//                         }
//                         }
//                     }
//                     });
//                 } else {
//                     frappe.throw(" QR Print has been cancelled");
//                 }
//                 }
//             },
//             function() {
//                 // No button action
//                 // Do nothing or handle the rejection case
//             },
//             'Confirmation',
//             ['Print', 'No']
//             );
//         }
//     }
// });

// function createSerialNo(frm, item) {
//     frappe.call({
//         method: 'nj_features.api_files.create_serial_no',
//         args: {
//             item_code: item.item_code,
//         },
//         callback: function(response) {
//             if (response && response.message) {
//                 console.log("\ncreate serial no: ", response.message);
//                 let newSerialNo = response.message;
//                 if (item.serial_no) {
//                     item.serial_no += '\n' + newSerialNo;
//                 } else {
//                     item.serial_no = newSerialNo;
//                 }
//                 refresh_field('items');
//             } else {
//                 frappe.msgprint('Error generating serial number.');
//             }
//         },
//         error: function(err) {
//             frappe.msgprint('Error generating serial number: ' + err.message);
//         }
//     });
// }

// frappe.ui.form.on('Purchase Receipt', {
//   on_submit: function(frm) {
//       console.log("submit");
//       var new_list = [];

//       for (let i = 0; i < cur_frm.doc.items.length; i++) {
//           var new_var = cur_frm.doc.items[i].serial_no;
//           new_list = new_var.split("\n");
//           var mac_cop;
//           for (let j = 0; j < new_list.length; j++) {
//               frappe.call({
//                   method: "nj_features.api_files.print_api",
//                   args: {
//                       serial_no: new_list[j],
//                   },
//                   callback: function(response) {
//                       if (response.message) {
//                         console.log(response);
//                         var max_cop = response.message;
//                         console.log("re");
//                         }
//                     }
//                 })
//             }
//         }     
//     }
// });
