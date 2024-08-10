frappe.ui.form.on('NJ Audit', {
    onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        frm.set_df_property('nj_audit_items', 'cannot_add_rows', true);

        frm.fields_dict['nj_audit_items'].grid.wrapper.on('click', '.grid-remove-rows', function() {
            let selectedRows = frm.fields_dict['nj_audit_items'].grid.get_selected_children();
            selectedRows.forEach(row => {
                let accept_rows = frm.doc.accept_rows || "";
                let accept_rows_array = accept_rows.split(',').filter(idx => idx !== row.idx.toString());
                frm.set_value('accept_rows', accept_rows_array.join(','));
            });
        });

		fill_audit_and_work_warehouse(frm)
    },

    refresh: function() { $('[data-fieldname="scan_serial_no"]').focus(); },

    onload_post_render: function(frm) {
        if (!frm.doc.work_warehouse || !frm.doc.audit_warehouse) { fill_audit_and_work_warehouse(frm) }
    },

    validate: function(frm) {
        if (frm.doc.accept_rows) { frappe.throw(`<b>Rows : ${frm.doc.accept_rows}</b> Material Transfer is not happened`); }
    },

    scan_serial_no: function(frm) {
        if (frm.doc.scan_serial_no) {
            frappe.call({
                method: 'nj_features.nj_features.doctype.nj_audit.nj_audit.get_scanned_serial_no_data',
                args: {'serial_no': frm.doc.scan_serial_no},
                callback: function(r) {
                    if (r && r.message) {
                        let data = r.message;
                        let child_row = {}
    
                        data.forEach(function(entry) { 
                            child_row = frm.add_child('nj_audit_items', entry);
                        });
                        frm.refresh_field("nj_audit_items");
                        
                        let isAccepted = frm.doc.audit_warehouse === data[0]?.parent_warehouse;
                        console.log("isAccepted", isAccepted);
                        
                        frappe.meta.get_docfield('NJ Audit Items', 'accept', frm.doc.name).hidden = !isAccepted;
                        console.log("idx", child_row, data[0]?.parent_warehouse);
                        
                        if (isAccepted) {
                            if (!frm.doc.accept_rows) {
                                frm.set_value('accept_rows', `${child_row.idx},`);
                            } else {
                                let accept_row_data = frm.doc.accept_rows + child_row.idx;
                                frm.set_value('accept_rows', `${accept_row_data},`);
                            }
                        }

                        frm.set_value('scan_serial_no', '');
                    } else {
                        frappe.throw(`Serial No: <b>${frm.doc.scan_serial_no}</b> is not found!`);
                    }
                    frm.refresh_field('accept_rows');
                    $('[data-fieldname="scan_serial_no"]').focus();
                },
                error: function(err) {
                    console.error("Error in frappe call:", err);
                }
            });
        }
        frm.set_value('scan_serial_no', '');
    }    
});

frappe.ui.form.on('NJ Audit Items', {
    accept: function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        let work_warehouse = frm.doc.work_warehouse;
        let stock_entry_items = [{
            'item_code': child.item_code,
            'basic_rate': child.purchase_rate,
            'serial_no': child.serial_no
        }];

        let data = {
            "serial_no": child.serial_no,
            "stock_entry_type": "Material Transfer",
            "t_warehouse": work_warehouse,
            "series": "STRC-.YYYY.-.MM.-",
            "reference_serial_no": child.serial_no,
            "doctype": frm.doc.doctype,
            "stock_entry_for_material_transfer_or_repack_items": stock_entry_items
        };

        frappe.call({
            method: 'nj_lib.utils.stock_entry.stock_entry_using_nj_lib',
            args: { 'data': JSON.stringify(data) },
            callback: function(r) {
                if (child.parent_warehouse != cur_frm.doc.audit_warehouse) {
                    frappe.model.set_value(cdt, cdn, 'warehouse', cur_frm.doc.work_warehouse);
                    frm.set_df_property('nj_audit_items', 'hidden', 1, frm.docname, 'accept', cdn);

                    let accept_row_data = frm.doc.accept_rows;
                    let split_data = accept_row_data.split(',');
                    if (split_data.includes(child.idx.toString())) {
                        let result = split_data.filter(item => item !== child.idx.toString()).join(",");
                        frm.set_value('accept_rows', result);
                    }
                    frm.refresh_field('accept_rows');
                    frm.refresh_field('nj_audit_items');
                }
            },
            error: function(err) { console.log(err); }
        });
    },
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
            }
        }
    });
}