frappe.ui.form.on('NJ Audit', {
    onload: function(frm) {
        if (frm.doc.docstatus == 0 && !frm.doc.__islocal && frm.doc.__unsaved) {
            // frm.fields_dict['nj_audit_items'].grid.wrapper.on('click', '.grid-remove-rows', function() {
            //     let selectedRows = frm.fields_dict['nj_audit_items'].grid.get_selected_children();
            //     selectedRows.forEach(row => {
            //         let accept_rows = frm.doc.accept_rows || "";
            //         let accept_rows_array = accept_rows.split(',').filter(idx => idx !== row.idx.toString());
            //         frm.set_value('accept_rows', accept_rows_array.join(','));
            //     });
            // });
            // initializeGridListeners(frm)
            frm.set_df_property('nj_audit_items', 'cannot_add_rows', true);
        }
    },
    
    refresh: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        if (frm.doc.docstatus == 0) {
            $('[data-fieldname="scan_serial_no"]').focus();
        }
    },

    onload_post_render: function(frm) {
        if ((!frm.doc.work_warehouse || !frm.doc.audit_warehouse) && frm.doc.docstatus == 0) { 
            fill_audit_and_work_warehouse(frm)
        }
    },

    scan_serial_no: function (frm) {
        if (!frm.doc.scan_rack) {
            frm.set_value("scan_serial_no", "");
            frm.refresh_field("scan_serial_no");
            frappe.throw("Please select Rack");
        }
        
        if (frm.doc.scan_serial_no != '' && frm.doc.scan_rack != '') {
            frappe.db.get_value("Serial No", {serial_no: frm.doc.scan_serial_no}, ["name","item_code", "warehouse", "purchase_rate"], (r) => {
                if (r) {
                    let nj_audit_items = {
                        "serial_no": r.name, 
                        "item_code": r.item_code, 
                        "s_warehouse": r.warehouse, 
                        "purchase_rate": r.purchase_rate,
                        "t_rack_warehouse": frm.doc.scan_rack
                    };
                    frm.add_child("nj_audit_items", nj_audit_items);
                    frm.refresh_field("nj_audit_items");

                    frm.set_value('serial_no_count', frm.doc.nj_audit_items.length);
                    frm.refresh_field('serial_no_count');

                    frm.set_value("scan_serial_no", "");
                    frm.refresh_field("scan_serial_no");
                }
            })
        }
    }

    // scan_serial_no: function(frm) {
    //     if (frm.doc.scan_serial_no) {
    //         frappe.call({
    //             method: 'nj_features.nj_features.doctype.nj_audit.nj_audit.get_scanned_serial_no_data',
    //             args: {
    //                 'serial_no': frm.doc.scan_serial_no,
    //                 'audit_warehouse': frm.doc.audit_warehouse
    //             },
    //             callback: function(r) {
    //                 console.log("r.message----",r)
    //                 if (r && r.message) {
    //                     let data = r.message;
    //                     let child_row = {}
    
    //                     data.forEach(function(entry) { 
    //                         child_row = frm.add_child('nj_audit_items', entry);
    //                     });
    //                     frm.set_value('serial_no_count', frm.doc.nj_audit_items.length);
    //                     frm.refresh_field('serial_no_count');
                        
    //                     frm.refresh_field("nj_audit_items");
                        
    //                     let isAccept = frm.doc.audit_warehouse != data[0]?.parent_warehouse;
                        
    //                     if (isAccept) {
    //                         if (!frm.doc.accept_rows) {
    //                             frm.set_value('accept_rows', `${child_row.idx},`);
    //                         } else {
    //                             let accept_row_data = frm.doc.accept_rows + child_row.idx;
    //                             frm.set_value('accept_rows', `${accept_row_data},`);
    //                         }
    //                     }
    //                 } 
    //                 else { frappe.throw(`erial No: <b>${frm.doc.scan_serial_no}</b> is not found!`); }
                    
    //                 frm.refresh_field('accept_rows');
    //                 $('[data-fieldname="scan_serial_no"]').focus();
    //             },
    //             error: function(err) { console.error("Error in frappe call:", err); }
    //         });
    //     }
    //     frm.set_value('scan_serial_no', '');
    // }
    
});

function fill_audit_and_work_warehouse(frm) {
    
    frappe.call({
        method: 'nj_features.nj_features.doctype.nj_audit.nj_audit.get_work_and_audit_warehouse',
        callback: function(r) {
            if (r && r.message) {
                let data = r.message
                if(!frm.doc.audit_interval){
                    frm.set_value('audit_interval',data.audit_interval)
                    frm.refresh_field('audit_interval')
                }
                if(!frm.doc.audit_warehouse){
                    frm.set_value('audit_warehouse',data.audit_warehouse)
                    frm.refresh_field('audit_warehouse')
                }
                if(!frm.doc.work_warehouse){
                    frm.set_value('work_warehouse',data.work_warehouse)
                    frm.refresh_field('work_warehouse')
                }
                if (frm.doc.audit_warehouse && !frm.doc.stock_balance) {
                    frappe.call({
                        method: 'nj_features.nj_features.doctype.nj_audit.nj_audit.get_stock_balance',
                        args: {audit_warehouse: frm.doc.audit_warehouse},
                        callback: function(r) {
                            frm.set_value('stock_balance',r.message)
                            frm.refresh_field('stock_balance')
                        }
                    });
                }
            }
        }
    });
}

function initializeGridListeners(frm) {
    frm.fields_dict['nj_audit_items'].grid.on('refresh', function() {
        frm.fields_dict['nj_audit_items'].grid.wrapper.on('click', '.grid-remove-rows', function() {
            handleRowRemoval(frm);
        });
    });
}

function handleRowRemoval(frm) {
    let selectedRows = frm.fields_dict['nj_audit_items'].grid.get_selected_children();
    
    if (selectedRows.length > 0) {
        let accept_rows = frm.doc.accept_rows || "";
        let accept_rows_array = accept_rows.split(',').filter(idx => !selectedRows.some(row => row.idx.toString() === idx));
        frm.set_value('accept_rows', accept_rows_array.join(','));
    }
}

frappe.ui.form.on('NJ Audit Items', {
    nj_audit_items_remove: function(frm, cdt, cdn) {
        frm.set_value('serial_no_count', frm.doc.nj_audit_items.length);
        frm.refresh_field('serial_no_count');
    }
})
// frappe.ui.form.on('NJ Audit Items', {
//     accept: function(frm, cdt, cdn) {
//         let child = locals[cdt][cdn];
//         let work_warehouse = frm.doc.work_warehouse;
//         let stock_entry_items = [{
//             'item_code': child.item_code,
//             'basic_rate': child.purchase_rate,
//             'serial_no': child.serial_no
//         }];
//         let data = {
//             "serial_no": child.serial_no,
//             "stock_entry_type": "Material Transfer",
//             "t_warehouse": work_warehouse,
//             "series": "STRC-.YYYY.-.MM.-",
//             "reference_serial_no": child.serial_no,
//             "doctype": frm.doc.doctype,
//             "stock_entry_for_material_transfer_or_repack_items": stock_entry_items
//         };
//         frappe.call({
//             method: 'nj_lib.utils.stock_entry.stock_entry_using_nj_lib',
//             args: { 'data': JSON.stringify(data) },
//             callback: function(r) {
//                 if (child.parent_warehouse != cur_frm.doc.audit_warehouse) {
//                     frappe.model.set_value(cdt, cdn, 'warehouse', cur_frm.doc.work_warehouse);
//                     frm.set_df_property('nj_audit_items', 'hidden', 1, frm.docname, 'accept', cdn);
//                     let accept_row_data = frm.doc.accept_rows;
//                     let split_data = accept_row_data.split(',');
//                     if (split_data.includes(child.idx.toString())) {
//                         let result = split_data.filter(item => item !== child.idx.toString()).join(",");
//                         frm.set_value('accept_rows', result);
//                     }
//                     frm.refresh_field('accept_rows');
//                     frm.refresh_field('nj_audit_items');
//                 }
//             },
//             error: function(err) { console.log(err); }
//         });
//     },
// });
