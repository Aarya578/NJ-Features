frappe.ui.form.on('NJ Production Planning', {
    refresh: function(frm) {
        frm.page.wrapper.find('button:contains("To Make")').addClass('btn-primary');
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
                        let data = r.message;
                        frm.clear_table('nj_production_planning_child');
                        console.log('r -------------- ', data);
                        data.forEach(function(item) {
                            let child = frm.add_child('nj_production_planning_child');
                            child.model = item.model ? item.model.toUpperCase() : '';
                            child.processor = item.processor_type ? item.processor_type.toUpperCase() : '';
                            child.ram = item.ram_capacity ? item.ram_capacity.toUpperCase() : '';
                            child.ssd = item.storage_capacity ? item.storage_capacity.toUpperCase() : '';
                            child.sales_rate = item.sales_rate ? item.sales_rate : 0.0;
                            child.inward_inventory = item.inwarded_qty ? item.inwarded_qty : 0.0;
                            child.forward_inventory = item.forwarded_qty ? item.forwarded_qty : 0.0;
                            child.days_of_inventory = item.DOI ? item.DOI : 0.0;
                            child.to_make = item.to_make ? item.to_make : 0.0;
                        });

                        frm.refresh_field('nj_production_planning_child');
                    }
                }
            });
        }else{
            frm.clear_table("'nj_production_planning_child");
        }
    },

    to_make: function(frm) {
        if (!frm.doc.name || frm.is_new()) {
            frappe.msgprint({
                title: __('Error'),
                message: __('You need to save the document first.'),
                indicator: 'red'
            });
            frappe.validated = false;
            return;
        }
    
        frappe.call({
            method: "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.calculate_to_make",
            args: {
                doc: frm.doc
            },
            callback: function(r) {
                if (r.message) {
                    let data = r.message;
    
                    // Sort data in descending order based on 'to_make' value
                    data.sort((a, b) => (b.to_make || 0) - (a.to_make || 0));
    
                    frm.clear_table('nj_production_planning_child');
                    console.log('Sorted Data -------------- ', data);
    
                    data.forEach(function(item) {
                        console.log("Processor -------- ", item.processor);
                        let child = frm.add_child('nj_production_planning_child');
                        child.model = item.model ? item.model.toUpperCase() : '';
                        child.processor = item.processor ? item.processor.toUpperCase() : '';
                        child.ram = item.ram ? item.ram.toUpperCase() : '';
                        child.ssd = item.ssd ? item.ssd.toUpperCase() : '';
                        child.sales_rate = item.sales_rate ? item.sales_rate : 0.0;
                        child.inward_inventory = item.inward_inventory ? item.inward_inventory : 0.0;
                        child.forward_inventory = item.forward_inventory ? item.forward_inventory : 0.0;
                        child.days_of_inventory = item.days_of_inventory ? item.days_of_inventory : 0.0;
                        child.to_make = item.to_make ? item.to_make : 0.0;
                    });
    
                    frm.refresh_field('nj_production_planning_child');
                }
            }
        });
    }
    
});