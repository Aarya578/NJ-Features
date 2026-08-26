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

        // Repair Category Config: "Default Value" is an Autocomplete
        // whose choices come from the comma-separated "Options" text on
        // that same row -- not a static list. get_data is Autocomplete's
        // per-row equivalent of get_query (which only applies to Link
        // fields).
        //
        // "Options" is deliberately a plain comma-separated Small Text
        // field, not a Table MultiSelect tag input. A Table MultiSelect
        // nested two levels deep (inside a child table's own row) was
        // tried and found to have a real bug in this Frappe version
        // (13.34.0): the grid-row-dialog scopes the field's value to the
        // wrong document, bleeding it up to the top-level Role Profile
        // doc under the same fieldname and crashing on save with
        // "'NoneType' object has no attribute 'options'". This happened
        // regardless of what the field was named (confirmed with two
        // different names), so it's structural, not naming -- Table
        // MultiSelect only works reliably one level deep (e.g. this
        // doctype's own "item_group" field, directly on Role Profile,
        // which has always worked fine). Comma-separated text avoids
        // the bug entirely.
        if (frm.fields_dict['repair_config']) {
            frm.fields_dict['repair_config'].grid.get_field('default_value').get_data = function(doc, cdt, cdn) {
                let row = locals[cdt][cdn];
                let tagged_options = (row.repair_options || '')
                    .split(',')
                    .map(function(v) { return v.trim(); })
                    .filter(function(v) { return !!v; });
                return tagged_options;
            };
        }
        
    },


    // Update filters when department changes
    department: function(frm) {
        frm.trigger('refresh');
    }
});

frappe.ui.form.on('KPI Parameter', {
    target: function(frm, cdt, cdn) {
      let row = locals[cdt][cdn];
      if (row._skip_validation) return;      
      let target_value = String(row.target).replace('%', '').trim();
      let numeric_value = parseFloat(target_value);
      
      if (numeric_value < 1 || numeric_value > 100 || isNaN(numeric_value)) {
        frappe.msgprint(__('Target must be between 1% and 100%'));
        
        row._skip_validation = true;
        frappe.model.set_value(cdt, cdn, 'target', '');
        setTimeout(() => { row._skip_validation = false; }, 0);
      } else {
        row._skip_validation = true;
        frappe.model.set_value(cdt, cdn, 'target', numeric_value + '%');
        setTimeout(() => { row._skip_validation = false; }, 0);
      }
    }
  });

