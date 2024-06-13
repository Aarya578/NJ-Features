frappe.ui.form.on('Warehouse', {
    onload: async function(frm) {
        if(frm.doc.default_capacity == 1 && !frm.doc.max_capacity) {
            frappe.db.get_value('NJ Settings', {"doc_type": "Stock Movement", "parameter": "max_capacity"}, "value").then(function(r) {
                if(r.message) {
                    frm.set_value('max_capacity', r.message.value)
                    frm.save()
                } else {
                    frappe.throw("NJ Settings for 'max_capacity' is not defined")
                }
            })
        }
    },
    max_capacity: function(frm) {
        frm.set_value('available_capacity', cur_frm.doc.max_capacity - cur_frm.doc.qty_after_transaction);
        frm.refresh_field('available_capacity');
    },
    default_capacity: function(frm){
        if(frm.doc.default_capacity === 1 && !frm.doc.max_capacity) {
            frappe.db.get_value('NJ Settings', {'doc_type': 'Warehouse', 'parameter': 'default_capacity'}, 'value').then(function(r) {
                if(r.message) {
                    frm.set_value('max_capacity', r.message.value)
                    frm.refresh_field('max_capacity')
                    frm.save();
                } else {
                    frappe.throw("NJ Settings for 'default_capacity' is not defined")
                }
            })
        }
    },
    item_group: function(frm) {
        const hasItemGroup = frm.doc.item_group;
        const hasBrand = frm.doc.brand;
        if (hasItemGroup === "All Item Groups") {
            frm.set_df_property('max_capacity', 'hidden', 1);
            frm.set_df_property('available_capacity', 'hidden', 1);
            frm.set_df_property('brand', 'hidden', 1)
            return;
        }

        // If item_group is set but brand is not set, display max_capacity
        if (hasItemGroup && !hasBrand) {
            frm.set_df_property('max_capacity', 'hidden', 0);
            frm.set_df_property('available_capacity', 'hidden', 0);
        }
        
        else {
            // If both item_group and brand are set, display max_capacity
            frm.set_df_property('max_capacity', 'hidden', 0);
            frm.set_df_property('available_capacity', 'hidden', 0);
        }
    }
});