frappe.ui.form.on('Role Profile', {
    refresh: function(frm) {
        frm.fields_dict['productivity_profile_table'].grid.get_field('target_profile').get_query = function(doc, cdt, cdn) {
            let department = doc.department;
            
            if (!department) {
                return {
                    filters: {
                        'name': ['=', 'no_match_will_be_found_123456789']
                    }
                };
            } else {
                return {
                    filters: {
                        'department': department
                    }
                };
            }
        };
    },
    
    // Update filters when department changes
    department: function(frm) {
        frm.trigger('refresh');
    }
});