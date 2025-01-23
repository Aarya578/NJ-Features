frappe.ui.form.on('NJ Production Planning', {
    refresh: function(frm) {
        console.log('Refreshing...');
    },

    department: function(frm) {
        if (frm.doc.department && frm.doc.department.trim() !== "") {
            frappe.call({
                method: "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.get_department_details",
                args: {
                    doc: frm.doc
                },
                callback: function(r) {
                    if (r.message) {
                        console.log("Department details:", r.message);

                        let data = r.message;

                        frm.clear_table('nj_production_planning_child');

                        data.forEach(function(item) {
                            console.log("item -------------- 22", item);
                            
                            let child = frm.add_child('nj_production_planning_child');
                            child.model = item.item_model ? item.item_model.toUpperCase() : '';
                            child.processor = item.processor_type ? item.processor_type.toUpperCase() : '';
                            child.ram = item.ram_capacity ? item.ram_capacity.toUpperCase() : '';
                            child.ssd = item.storage_capacity ? item.storage_capacity.toUpperCase() : '';
                            child.sales_rate = 0.0;
                            child.inward_inventory = item.inwarded_qty ? item.inwarded_qty : 0.0;
                            child.forward_inventory = item.forwarded_qty ? item.forwarded_qty : 0.0;
                            child.days_of_inventory = null;
                            child.to_make = 0.0;
                        });

                        frm.refresh_field('nj_production_planning_child');
                    }
                }
            });
        }
    }
});