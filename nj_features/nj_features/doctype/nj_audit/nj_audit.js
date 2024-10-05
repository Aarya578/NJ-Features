frappe.ui.form.on('NJ Audit', {
    onload: function(frm) {
        if (frm.doc.docstatus == 0 && !frm.doc.__islocal && frm.doc.__unsaved) {
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
            frappe.db.get_value("Serial No", {serial_no: frm.doc.scan_serial_no}, ["name","item_code","item_group", "warehouse", "purchase_rate"], (r) => {
                if (r.name) {
                    let nj_audit_items = {
                        "serial_no": r.name, 
                        "item_code": r.item_code, 
                        "item_group": r.item_group,
                        "s_warehouse": r.warehouse, 
                        "purchase_rate": r.purchase_rate,
                        "t_rack_warehouse": frm.doc.scan_rack,
                        "parent_warehouse": frm.doc.audit_warehouse
                    };
                    frappe.db.get_value('NJ Settings', {'parameter': 'Item Group Check'}, 'value', function(response) {
                        if (response && response.value){
                            if (response.value.includes(nj_audit_items.item_group)) {
                                frm.add_child("nj_audit_items", nj_audit_items);
                                frm.refresh_field("nj_audit_items");
            
                                frm.set_value('serial_no_count', frm.doc.nj_audit_items.length);
                                frm.refresh_field('serial_no_count');
                            }
                            else{
                                frm.set_value("scan_serial_no", "");
                                frappe.throw("Item Group <b>" + nj_audit_items.item_group + "</b> is not valid");
                            }
                        } else {
                            frappe.throw("NJ Settings: <b>Item Group Check</b> is not configured");
                        }
                    });
                } else {
                    frappe.msgprint("Serial No: "+cur_frm.doc.scan_serial_no+" is not found.")
                }
                frm.set_value("scan_serial_no", "");
                frm.refresh_field("scan_serial_no");
            })
        }
    },

    scan_rack: function (frm) {
        if (frm.doc.scan_rack != '') {
            frappe.db.get_value('Warehouse', { 'name': frm.doc.scan_rack }, 'name', function(r) {
                if (r.name != frm.doc.scan_rack) {
                    frm.set_value("scan_rack", r.name);
                    frm.refresh_field("scan_rack");
                }
            })
        }
        if(frm.doc.scan_rack) {
            frappe.call({
                'method': 'nj_features.nj_features.doctype.nj_audit.nj_audit.get_rack_balance',
                'args': {
                    'rack_name': frm.doc.scan_rack
                },
                callback: function(r) {
                    if (r && r.message) {
                        frm.set_value('rack_balance', r.message)
                        frm.refresh_field('rack_balance')
                    }
                    else{
                        frm.set_value('rack_balance', 0)
                        frm.refresh_field('rack_balance')
                    }
                }
            })
        }
    },

    after_save: function(frm) {
        frappe.call({
            'method': 'nj_features.nj_features.doctype.nj_audit.nj_audit.move_all_stock',
            'args': {'self': frm.doc },
            callback: function(r) {
                if (r && r.message) {
                    update_nj_audit_items(frm)
                }
            }
        })
    }
});

function update_nj_audit_items(frm) {
    frm.doc.nj_audit_items.forEach(function(item) {
        if (item.s_warehouse !== item.t_rack_warehouse) {
            frappe.model.set_value(item.doctype, item.name, 's_warehouse', item.t_rack_warehouse);
        }
    });
    
    frm.refresh_field('nj_audit_items');
    frm.save()
}

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
                    frm.set_value('stock_balance',data.stock_balance)
                    frm.refresh_field('stock_balance')
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