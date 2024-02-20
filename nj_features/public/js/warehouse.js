frappe.ui.form.on('Warehouse', {
    onload: async function(frm) {
        if(frm.doc.default_capacity == 1 && !frm.doc.max_capacity) {
            frappe.db.get_value('NJ Settings', {"doc_type": "Stock Movement", "parameter": "max_capacity"}, "value").then(function(r) {
                frm.set_value('max_capacity', r.message.value)
                frm.save()
            })
        }
        await updateMaxcap(frm);
    },
    max_capacity: function(frm) {
        frm.set_value('available_capacity', cur_frm.doc.max_capacity - cur_frm.doc.qty_after_transaction);
        frm.refresh_field('available_capacity');
    },
    qty_after_transaction: function(frm) {
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
            frm.set_df_property('brand', 'hidden', 1);

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

async function updateMaxcap(frm) {
    const isGroup = frm.doc.is_group === 1;
    console.log("frm",frm.doc)

    // console.log("hasItemGroup",hasItemGroup)
    // Store the original value of max_capacity when the form loads
    frm.original_max_capacity = frm.doc.max_capacity;

    if (!isGroup) {
        

        try {
            const result = await frappe.db.get_list('Stock Ledger Entry', {
                filters: {
                    warehouse: cur_frm.doc.name
                },
                fields: ['name', 'qty_after_transaction'],
                order_by: 'posting_date desc, posting_time desc',
                limit: 1
            });

            if (result && result.length > 0) {
                const qtyAfterTransaction = result[0].qty_after_transaction;

                // Set the item code to the qty_after_transaction field
                frm.set_value('qty_after_transaction', qtyAfterTransaction);
                frm.refresh_field('qty_after_transaction');

                // Retrieve the max_capacity value from the Warehouse document
                const res = await frappe.db.get_value('Warehouse', cur_frm.doc.name, 'max_capacity');

                const maxCapacity = res.message.max_capacity;
                const availableCapacity = maxCapacity - qtyAfterTransaction;

                // Set the available_capacity field
                frm.set_value('available_capacity', availableCapacity);
                frm.refresh_field('available_capacity');
            } else {
                // Stock ledger data is not found, set available_capacity to max_capacity
                const res = await frappe.db.get_value('Warehouse', cur_frm.doc.name, 'max_capacity');
                const maxCapacity = res.message.max_capacity;

                // Set the available_capacity field to max_capacity
                frm.set_value('available_capacity', maxCapacity);
                frm.refresh_field('available_capacity');
            }
        } catch (err) {
            console.log(err);
        }
        
    }
}