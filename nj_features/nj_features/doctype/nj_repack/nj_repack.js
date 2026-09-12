frappe.ui.form.on('NJ Repack', {

    serial_no: function(frm) {

        // If Serial No is cleared
        if (!frm.doc.serial_no) {
            frm.set_value('current_item_code', '');
            frm.clear_table('current_attributes');
            frm.refresh_field('current_attributes');
            return;
        }

        // Step 1: Get Item Code from Serial No
        frappe.call({
            method: 'frappe.client.get_value',
            args: {
                doctype: 'Serial No',
                filters: {
                    name: frm.doc.serial_no
                },
                fieldname: ['item_code']
            },

            callback: function(r) {

                if (!r.message || !r.message.item_code) {

                    frm.set_value('current_item_code', '');

                    frm.clear_table('current_attributes');
                    frm.refresh_field('current_attributes');

                    frappe.msgprint(
                        'Item Code not found for Serial No: ' +
                        frm.doc.serial_no
                    );

                    return;
                }

                let item_code = r.message.item_code;

                // Set Current Item Code
                frm.set_value('current_item_code', item_code);

                // Step 2: Get Item including variant attributes
                frappe.call({
                    method: 'frappe.client.get',
                    args: {
                        doctype: 'Item',
                        name: item_code
                    },

                    callback: function(item_response) {

                        if (!item_response.message) {
                            return;
                        }

                        let item = item_response.message;

                        // Clear old attributes
                        frm.clear_table('current_attributes');

                        // Copy Item.attributes into NJ Repack
                        (item.attributes || []).forEach(function(attr) {

                            let row = frm.add_child('current_attributes');

                            row.variant_of = item.variant_of;
                            row.attribute = attr.attribute;
                            row.attribute_value = attr.attribute_value;
                        });

                        frm.refresh_field('current_attributes');
                    }
                });
            }
        });
    }
});
