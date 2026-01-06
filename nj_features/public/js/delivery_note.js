frappe.ui.form.on('Delivery Note', {

    // onload: function(frm) {
    //     const snapmintItem = frm.doc.items.find(item => item.against_sales_order && item.against_sales_order.startsWith("SO-Snapmint-"));
    //     if (snapmintItem) {
    //         frm.set_value("courier_service", "Shiprocket Manifest");
    //         frm.set_df_property("courier_service", "read_only", 1);
    //     }
    // },
    onload: function(frm) {   
        handleScannerInput(frm, 'scan_barcode');
        handleScannerInput(frm, 'scan_barcodes');
        update_gst_tax_type_from_nj_settings(frm);
        // Run only if items exist and linked Sales Order is present
        
        if (frm.doc.docstatus !== 1 && frm.doc.docstatus !== 2 && frm.doc.items && frm.doc.items.length > 0) {
            let first_so = frm.doc.items[0].against_sales_order;
            if (first_so) {
                frappe.call({
                    method: "nj_features.overrides.delivery_note.updating_new_address",
                    args: {
                        sales_order_name: first_so
                    },
                    callback: function(r) {
                        if (r.message) {
                            frm.set_value("shipping_address_name", r.message);
                            frm.refresh_field("shipping_address_name");
                        }
                    }
                });
            }
        }

        
    
    
        // if (!frm.doc.items || frm.doc.items.length === 0 || frm.doc.is_return === 1) return;

        // // Take the first SO reference from child table
        // let so_name = frm.doc.items[0].against_sales_order;
        // if (!so_name) return;

        // frappe.db.get_doc("Sales Order", so_name).then(so_doc => {
        //     // Compare billing address

        //     if (so_doc.customer_address && frm.doc.customer_address !== so_doc.customer_address) {
        //         frm.set_value("customer_address", so_doc.customer_address);
        //     }

        //     // Compare shipping address
        //     if (so_doc.shipping_address_name && frm.doc.shipping_address_name !== so_doc.shipping_address_name) {
        //         frm.set_value("shipping_address_name", so_doc.shipping_address_name);
        //     }
        // });
        let items = frm.doc.items.map(row => ({
            idx: row.idx,
            item_group: row.item_group
        }));

        // frappe.call({
        //     method: "nj_features.overrides.delivery_note.get_item_group_cost_centers",
        //     args: { items: items },
        //     callback: function(r) {
                
        //         if (r.message) {
        //             console.log("Cost centers:===", r.message);
                    
        //             frm.doc.items.forEach(row => {
        //                 if (r.message[row.idx]) {
        //                     frappe.model.set_value(row.doctype, row.name, "cost_center", r.message[row.idx]);

        //                 }
        //                  frm.refresh_field('cost_center');
        //             });
        //         }
        //     }
        // });

    },

    refresh: function(frm) {
        handleScannerInput(frm, 'scan_barcode');
        handleScannerInput(frm, 'scan_barcodes');

        
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__('View'), function() {
                fetchAndDisplayLinks(frm, 'nj_features.overrides.delivery_note.get_link_1', 'Video');
            }).addClass('btn-primary');

            frm.add_custom_button(__('Record'), function() {
                openDjangoUrl(frm.doc.doctype, frm.doc.name);
            }).addClass('btn-primary');
        }

        if (frm.doc.__islocal) {
            frm.set_value("posting_time", frappe.datetime.now_time());
        }

        frm.remove_custom_button(__('Print QR Code'));

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
        }
       if (frm.doc.docstatus === 0) {
    // Hide both first to avoid duplicates on refresh
            frm.clear_custom_buttons();
            
            // Show Critical Log button only if AWB number has NOT been generated AND courier_service is not CriticaLog
            if (!frm.doc.tracking_id && frm.doc.courier_service !== 'CriticaLog') {
                let critical_btn = frm.add_custom_button(__('Critical Log'), function() {
                    frappe.show_alert({ message: __('Generating AWB Number...'), indicator: 'blue' });
                    frappe.call({
                        method: 'nj_features.overrides.delivery_note.send_consignement_data',
                        args: { doc: JSON.stringify(frm.doc) },
                        callback: function(response) {
                            if (response.message) {
                                frappe.call({
                                    method: 'frappe.client.set_value',
                                    args: {
                                        doctype: 'Delivery Note',
                                        name: frm.doc.name,
                                        fieldname: 'courier_service',
                                        value: 'CriticaLog'
                                    },
                                    callback: function() {
                                        frm.reload_doc();
                                        frappe.show_alert({
                                            message: __('AWB Number generated successfully!'),
                                            indicator: 'green'
                                        });
                                    }
                                });
                            }
                        }
                    });
                });
                critical_btn.addClass('btn-primary');
            }
            
            // Show Shiprocket button only if AWB number has NOT been generated AND courier_service is not Shiprocket
            if (!frm.doc.tracking_id && frm.doc.courier_service !== 'Shiprocket') {
                let shiprocket_btn = frm.add_custom_button(__('Shiprocket'), function() {
                    frappe.show_alert({ message: __('Generating AWB Number...'), indicator: 'blue' });
                    frappe.call({
                        method: 'nj_features.overrides.delivery_note.shiprocket_awb_number',
                        args: { doc: JSON.stringify(frm.doc) },
                        callback: function(response) {
                            if (response.message) {
                                // Assuming your method sets courier_service to 'Shiprocket'
                                frm.reload_doc();
                                frappe.show_alert({
                                    message: __('AWB Number generated successfully!'),
                                    indicator: 'green'
                                });
                            }
                        }
                    });
                });
                shiprocket_btn.addClass('btn-primary');
            }
        }

        if (frm.doc.docstatus === 0) {
            let shiprocket_btn = frm.add_custom_button(__('Fetch Shiprocket data'), function() {
                frappe.show_alert({ message: __('Fetching Shiprocket data...'), indicator: 'blue' });
                frappe.call({
                    method: 'nj_features.overrides.delivery_note.fetch_shiprocket_details',
                   args: { doc: JSON.stringify(frm.doc) },
                     callback: function(response) {
                            if (response.message) {
                                // Assuming your method sets courier_service to 'Shiprocket'
                                frm.reload_doc();
                                frappe.show_alert({
                                    message: __('Fetched Shiprocket data successfully!'),
                                    indicator: 'green'
                                });
                            }
                        }
                });
            });
            shiprocket_btn.addClass('btn-primary');
        }

    },
    
    onload_post_render: function(frm) {
        frm.remove_custom_button('Credit Note', 'Create');
        frm.page.remove_inner_button('Credit Note', 'Create');
        $('.btn-group.dropdown-menu a:contains("Credit Note")').parent().remove();
    },


    validate:  function(frm) {
        frappe.call({
            method: "nj_features.overrides.delivery_note.validate_delivery_bios",
            args: { doc: frm.doc },
            callback: function(r) {
                if (r.message && Array.isArray(r.message) && r.message.length > 0) {
                    frappe.msgprint({
                        title: __('Validation Error'),
                        message: r.message.join('<br>'),
                        indicator: 'red'
                    });
                    frappe.validated = false;
                } else { frappe.validated = true; }
            }
        });

       


        frappe.call({
            method: 'nj_features.overrides.delivery_note.update_item_details',
            args: { self: frm.doc },
            callback: function(r) {
                if (r.message) {
                    const { weight, height, length, breadth } = r.message;

                    // Only set values if they are not null or undefined
                    if (weight !== null && weight !== undefined) {
                        frm.set_value('weight', weight);
                    }

                    if (height !== undefined && height !== null) {
                        frm.set_value('height', height);
                    }

                    if (length !== undefined && length !== null) {
                        frm.set_value('length', length);
                    }

                    if (breadth !== undefined && breadth !== null) {
                        frm.set_value('breadth', breadth);
                    }
                    if(cod_amount !== undefined && cod_amount !== null) {
                        frm.set_value('cod_amount', cod_amount);
                    }

                    frm.refresh_fields(['weight', 'height', 'length', 'breadth', 'cod_amount']);
                }
            }
        });

        frappe.call({
            method: "nj_features.overrides.delivery_note.validate_delivery_bios",
            args: { doc: frm.doc },
            callback: function(r) {
                if (r.message && Array.isArray(r.message) && r.message.length > 0) {
                    frappe.msgprint({
                        title: __('Validation Error'),
                        message: r.message.join('<br>'),
                        indicator: 'red'
                    });
                    frappe.validated = false;
                } else {
                    frappe.validated = true;
                }
            }
        });
        // frappe.call({
        //     method: 'nj_features.overrides.delivery_note.fetch_cod_amount',
        //     args: {
        //         doc_name: frm.doc.name 
        //     },
        //     callback: function(r) {
        //         if (r.message) {
        //             const { cod_amount, is_cod, payment_received } = r.message;
        //             console.log("meassage=======",r.message);
                    

        //             // Set cod_amount field
        //             if (cod_amount !== undefined && cod_amount !== null) {
                        
        //                 frm.set_value('cod_amount', cod_amount.toString());
        //             }

        //             // ✅ Condition 1: COD checked & Payment received → Surface
        //             if (is_cod && payment_received) {
        //                 console.log("mode_of_transfer",frm.doc.mode_of_transfer);                    
        //                 frm.set_value('mode_of_transfer', 'Surface');
        //             }
        //             // ✅ Condition 2: Only COD checked → COD Surface
        //             else if (is_cod && !payment_received) {
        //                 console.log("mode_of_transfer",frm.doc.mode_of_transfer);                        
        //                 frm.set_value('mode_of_transfer', 'COD Surface');
        //             }
        //             // ✅ Condition 3: COD not checked → Surface
        //             else {
        //                 console.log("mode_of_transfer",frm.doc.mode_of_transfer);                         
        //                 frm.set_value('mode_of_transfer', 'Surface');
        //             }
                    
        //             frm.refresh_field('cod_amount');
        //             frm.refresh_field('mode_of_transfer');
        //         }
        //     }
        // });

    },
    scan_barcodes: function (cur_frm) {
        handleScannerInput(cur_frm, 'scan_barcodes');
        cur_frm.set_value('scan_barcodes', cur_frm.doc.scan_barcodes.trim());
        if (cur_frm.doc.scan_barcodes) {
            
            frappe.call({
                method: "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
                args: {  search_value: cur_frm.doc.scan_barcodes, raise_exp: 1 },
                callback: function(r) {
                    const data = r && r.message;
                    
                    if (r.message.scan === 1) {
                        if(cur_frm.doc.transfer_status == "Stock Accept") {
                            cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], true);
                        } else if (cur_frm.doc.transfer_status == "Racking") {
                            cur_frm.toggle_display(['scan_grade'], true);
                        }

                        $('[data-fieldname="scan_grade"]').focus();
                    } else {
                        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
                    }
    
                    if(r.message.serial_no) {
                        modify_table_after_scan(cur_frm, data)

                        frappe.call({
                            method: "nj_features.nj_features.doctype.stock_movement.stock_movement.get_grades_from_part_list",
                            args: { search_value: r.message.serial_no },
                    
                        });
                    }
                }
            });
        }
        return false;
    },
    scan_barcode: function (cur_frm) {
        handleScannerInput(cur_frm, 'scan_barcode');

        cur_frm.set_value('scan_barcode', cur_frm.doc.scan_barcode.trim());
        if (cur_frm.doc.scan_barcode) {
            
            frappe.call({
                method: "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
                args: {  search_value: cur_frm.doc.scan_barcode, raise_exp: 1 },
                callback: function(r) {
                    const data = r && r.message;
                    
                    if (r.message.scan === 1) {
                        if(cur_frm.doc.transfer_status == "Stock Accept") {
                            cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], true);
                        } else if (cur_frm.doc.transfer_status == "Racking") {
                            cur_frm.toggle_display(['scan_grade'], true);
                        }

                        $('[data-fieldname="scan_grade"]').focus();
                    } else {
                        cur_frm.toggle_display(['scan_grade', 'scan_warehouse'], false);
                    }
    
                    if(r.message.serial_no) {
                        modify_table_after_scans(cur_frm, data)

                        frappe.call({
                            method: "nj_features.nj_features.doctype.stock_movement.stock_movement.get_grades_from_part_list",
                            args: { search_value: r.message.serial_no },
                    
                        });
                    }
                }
            });
        }
        return false;
    },


    before_submit: async function(frm) {
        await frappe.call({
            method:'nj_features.overrides.delivery_note.allow_to_save',
            args: {
                "doc": frm.doc
            },
            callback: function(r) {
                if (r.message) {
                    if(r.message!="pass") {
                        frappe.validated=false
                        frappe.throw(r.message);

                    }else{
                        frappe.validated=true
                    }
                }
            }
        })

    },
  
    // after_save: function(frm) {
    //     if (!frm.doc.supplier_address_name || frm.doc.supplier_address_name === '' || frm.doc.supplier_address_name === undefined) {
    //         frm.set_value('shipping_address_name', frm.doc.customer_address);
    //         frm.refresh_field('shipping_address_name');
    //     }
    // },
    after_save: function(frm) {
         // frappe.call({
        //     method: 'nj_features.overrides.delivery_note.total_item_group_sum',
        //     args: {
        //         doc: JSON.stringify(frm.doc)
        //     },
        //     callback: function(r) {
        //         console.log("Full response:", r);
        //         if (r.message) {
        //             console.log("Response message:", r.message);
        //             if (r.message.item_group_qty !== undefined) {
        //                 console.log("item_group_qty received:", r.message.item_group_qty);
                        
        //                 // Set the value and save the document
        //                 frm.set_value('item_group_qty', r.message.item_group_qty);
        //                 frm.refresh_field('item_group_qty');
                        
        //                 // Save the document to persist the changes
        //                 // frm.save();
        //             } else {
        //                 console.log("item_group_qty not found in response");
        //             }
        //         } else {
        //             console.log("No message in response");
        //         }
        //     },
        //     error: function(r) {
        //         console.log("Error in frappe call:", r);
        //     }
        // });
        frappe.call({
            method: "nj_features.overrides.delivery_note.setting_dispatch_address",
            args: { doc: frm.doc },
            callback: function(r) {
                    if (r.message) {
                        frm.set_value("dispatch_address_name", r.message);
                    }
                }
        });
        // frappe.call({
        //     method: 'nj_features.overrides.delivery_note.fetch_cod_amount',
        //     args: {
        //         doc_name: frm.doc.name 
        //     },
        //     callback: function(r) {
        //         if (r.message) {
        //             const { cod_amount, is_cod, payment_received } = r.message;

        //             // Set cod_amount field
        //             if (cod_amount !== undefined && cod_amount !== null) {
        //                 frm.set_value('cod_amount', cod_amount.toString());
        //             }

        //             // ✅ Condition 1: COD checked & Payment received → Surface
        //             if (is_cod && payment_received) {
        //                 frm.set_value('mode_of_transfer', 'Surface');
        //             }
        //             // ✅ Condition 2: Only COD checked → COD Surface
        //             else if (is_cod && !payment_received) {
        //                 frm.set_value('mode_of_transfer', 'COD Surface');
        //             }
        //             // ✅ Condition 3: COD not checked → Surface
        //             else {
        //                 frm.set_value('mode_of_transfer', 'Surface');
        //             }

        //             frm.refresh_field('cod_amount');
        //             frm.refresh_field('mode_of_transfer');
        //         }
        //     }
        // });


        // frappe.call({
        //     method: "nj_features.overrides.delivery_note.set_mode_of_transport_based_on_order",
        //     args: { doc_name: frm.doc.name },
        //     callback(r) {
        //         console.log("measaeg========",r.message);
                
        //         if (!r.message || !r.message.mode_of_transfer) return;
        //                         console.log("measaeg========",r.message);


        //         frm.set_value("mode_of_transfer", r.message.mode_of_transfer);
        //         // frm.refresh_field("mode_of_transfer");
        //     }
        // });
       
        if (!frm.doc.shipping_address_name && frm.doc.customer_address) {
            frm.set_value('shipping_address_name', frm.doc.customer_address);
            frm.refresh_field('shipping_address_name');
        }
    },

    
    // courier_service: function(frm) {
    //     frappe.call({
    //         method: "nj_features.overrides.delivery_note.set_tracking_id_for_delivery_note",
    //         args: { doc: frm.doc },
    //         callback: function(r) {
    //             if (r.message === true) {
    //                 frm.set_df_property('tracking_id', 'reqd', 0);
    //             } else {
    //                 frm.set_df_property('tracking_id', 'reqd', 1);
    //             }
    //         }
    //     });
    // },
    // fetch_cod: function(frm) {
    //     let first_so = frm.doc.items.find(item => item.against_sales_order)?.against_sales_order;
    //     if (first_so) {
    //         frappe.call({
    //             method: "nj_features.overrides.delivery_note.get_cod_amount",
    //             args: { so_name: first_so },
    //             callback: function(res) {
    //                 if (res.message) {
    //                     frm.set_value("cod_amount", res.message.cod_amount); 
    //                     frm.set_value("shopify_order_id", res.message.order_id); 
    //                 }
    //             }
    //         });
    //     }
    // }
});
function update_gst_tax_type_from_nj_settings(frm) {
    console.log("updating============================");
    
  if (!frm.doc.taxes || !frm.doc.taxes.length) return;

    frappe.db.get_value(
        "NJ Settings",
        { parameter: "taxe_account_heads" },
        "value"
    ).then(r => {
        const csv = r?.message?.value;
        console.log("message=========",r.message);
        
        if (!csv) return;

        const account_heads = csv
            .split(',')
            .map(v => v.trim());

        frm.doc.taxes.forEach(tax => {
            if (
                tax.charge_type === "Actual" &&
                tax.account_head &&
                account_heads.includes(tax.account_head.trim())
            ) {
                // 🔥 THIS IS THE FIX
                frappe.model.set_value(
                    tax.doctype,
                    tax.name,
                    "charge_type",
                    "On Net Total"
                );
            }
        });

        // Recalculate after updates
        frm.cscript.calculate_taxes_and_totals();
    });
}

frappe.ui.form.on('Packed Item', {

    serial_no: function(frm, cdt, cdn) {
        if (!frm.doc.name || frm.doc.__islocal) {  
            frappe.msgprint({
                title: __('Save Required'),
                message: __('Please save the document before entering the Serial Number.'),
                indicator: 'red'
            });
            frappe.model.set_value(cdt, cdn, 'serial_no', ''); 
        }
    }
});

function fetchAndDisplayLinks(frm, method, type) {
    frappe.call({
        method: method,
        args: { 'name': frm.doc.name },
        callback: function(r) {
            var links = r.message;
            if (links && links.length > 0) {
                var dialog = new frappe.ui.Dialog({
                    title: __('Preview')
                });

                var contentContainer = document.createElement('div');
                for (var i = 0; i < links.length; i++) {
                    var link = links[i].linked_data;
                    var buttonLabel = type + ' ' + (i + 1);
                    var button = document.createElement('button');
                    button.textContent = buttonLabel;
                    button.setAttribute('data-link-url', link);
                    button.classList.add('btn', 'btn-primary', 'preview-button', 'margin-right');
                    button.style.marginRight = '10px';
                    button.style.marginBottom = '10px';
                    button.addEventListener('click', function() {
                        var linkUrl = this.getAttribute('data-link-url');
                        window.open(linkUrl, '_blank');
                    });
                    contentContainer.appendChild(button);
                }
                
                dialog.body.appendChild(contentContainer);
                dialog.show();
            } else {
                frappe.msgprint(__('No ' + type.toLowerCase() + ' links found.'));
            }
        }
    });
}
// for items
function modify_table_after_scans(frm, data) {
    let cur_grid = frm.fields_dict.items.grid;

    if (!data.item_code) return;

    // Check if matching item_code exists in items
    let matching_item = frm.doc.items.find(d => d.item_code === data.item_code);

    if (!matching_item) {
        // No matching item_code → show error and stop
        frappe.msgprint({
            title: __('Item Code Mismatch'),
            message: __('Scanned Serial No item code does not match with any Item Code in the table'),
            indicator: 'red'
        });
        cur_frm.set_value('scan_barcode', '');
        return;
    }

    // MATCH FOUND → update only this row
    let row = matching_item;

    // Duplicate serial number check
    if (row.serial_no && row.serial_no.split('\n').includes(data.serial_no)) {
        frappe.show_alert({
            message: __('Serial Number already exists for this Item'),
            indicator: 'orange'
        });
        cur_frm.set_value('scan_barcode', '');
        return;
    }

    // Add serial_no in NEW LINE (no comma separation)
    if (data.serial_no) {
        if (row.serial_no) {
            row.serial_no = row.serial_no + '\n' + data.serial_no;
        } else {
            row.serial_no = data.serial_no;
        }
    }

    // DO NOT INCREASE QTY → remove qty logic completely
    // Just update the row
    frappe.model.set_value(row.doctype, row.name, {
        serial_no: row.serial_no
    });

    show_scan_message(row.idx, row.item_code);
    cur_frm.refresh_field('items');
    cur_frm.set_value('scan_barcode', '');
}

// for packed items
function modify_table_after_scan(frm, data) {
    let cur_grid = frm.fields_dict.packed_items.grid;

    if (!data.item_code) return;

    // Check if matching item_code exists in packed_items
    let matching_item = frm.doc.packed_items.find(d => d.item_code === data.item_code);

    if (!matching_item) {
        // No matching item_code → show error and stop
        frappe.msgprint({
            title: __('Item Code Mismatch'),
            message: __('Scanned Serial No item code does not match with any Item Code in the table'),
            indicator: 'red'
        });
        cur_frm.set_value('scan_barcodes', '');
        return;
    }
    
    // MATCH FOUND → update only this row
    let row = matching_item;
    
    // Duplicate serial number check
    if (row.serial_no && row.serial_no.split('\n').includes(data.serial_no)) {
        frappe.show_alert({
            message: __('Serial Number already exists for this Item'),
            indicator: 'orange'
        });
        cur_frm.set_value('scan_barcodes', '');
        return;
    }

    // Add serial_no in NEW LINE (no comma separation)
    if (data.serial_no) {
        if (row.serial_no) {
            row.serial_no = row.serial_no + '\n' + data.serial_no;
        } else {
            row.serial_no = data.serial_no;
        }
    }

    // DO NOT INCREASE QTY → remove qty logic completely
    // Just update the row
    frappe.model.set_value(row.doctype, row.name, {
        serial_no: row.serial_no
    });

    show_scan_message(row.idx, row.item_code);
    cur_frm.refresh_field('packed_items');
    cur_frm.set_value('scan_barcodes', '');
}
// for items
function set_scanned_values(row_to_modify, data) {
    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'Item',
            name: data.item_code
        },
        callback: function(response) {
            let item_details = response.message;
            let quantity = data.qty ? data.qty : 1;
            
            let values = {
                item_code: data.item_code,
                s_warehouse: data.warehouse,
                qty: quantity,
                transfer_qty: 1
            };

            if (data.serial_no) {
                values.serial_no = data.serial_no;
            }
            
            frappe.model.set_value(row_to_modify.doctype, row_to_modify.name, values);
            cur_frm.refresh_field('items');
            cur_frm.set_value('scan_barcode', '');
        }
    });
}
// for packed items
function set_scanned_values(row_to_modify, data) {
    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'Item',
            name: data.item_code
        },
        callback: function(response) {
            let item_details = response.message;
            let quantity = data.qty ? data.qty : 1;
            
            let values = {
                item_code: data.item_code,
                s_warehouse: data.warehouse,
                qty: quantity,
                transfer_qty: 1
            };
            
            if (data.serial_no) {
                values.serial_no = data.serial_no;
            }

            frappe.model.set_value(row_to_modify.doctype, row_to_modify.name, values);
            cur_frm.refresh_field('packed_items');
            cur_frm.set_value('scan_barcodes', '');
        }
    });
}
function show_scan_message(idx, exist = null) {
    if (!exist) {
        frappe.show_alert({
            message: __('Row #{0}: Item added', [idx]),
            indicator: 'green'
        });
    }
}

function autofill_warehouse(child_table, warehouse_field, warehouse) {
    if (warehouse && child_table && child_table.length) {
        let doctype = child_table[0].doctype;
        $.each(child_table || [], function(i, item) {
            frappe.model.set_value(doctype, item.name, warehouse_field, warehouse);
        });
    }
}

// Function to open the Django URL directly with the DN number
function openDjangoUrl(doctype,dn_number) {
    // Construct the URL by embedding the dn_number in it
    // let url = `https://njpulse.newjaisa.com/upload/${dn_number}/`;
    frappe.db.get_value("NJ Settings",{"parameter":"video_prefix"},"value").then((prefix)=>{
        let url = `${prefix.message.value}${doctype}/${dn_number}/`;
        window.open(url, '_blank');
    })
}
