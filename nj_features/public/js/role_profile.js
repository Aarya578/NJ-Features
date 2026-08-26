frappe.ui.form.on('Role Profile', {
    refresh: function(frm) {
        // Frappe's automatic dependent-doctype preload fetches metadata
        // for a form's own doctype and its direct child tables, but does
        // not reliably reach a Table MultiSelect field nested INSIDE a
        // child table row (Repair Category Config -> its own "Options"
        // field -> Repair Category Option Link). Without this, the grid
        // can throw "Cannot read properties of undefined (reading
        // 'fields')" the first time that column tries to render, because
        // frappe.get_meta('Repair Category Option Link') comes back
        // undefined. Forcing the fetch here guarantees it's cached
        // before the grid needs it, regardless of load order.
        frappe.model.with_doctype('Repair Category Option Link');
        frappe.model.with_doctype('Repair Category Option');

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
        // whose choices are the Options tagged on that same row -- not
        // a static list. get_data is Autocomplete's per-row equivalent
        // of get_query (which only applies to Link fields).
        //
        // The tag field itself is named "repair_options" (not "options")
        // deliberately -- a nested Table MultiSelect field literally
        // named "options" was found to collide with Frappe's own
        // internal use of that property name during grid-row-dialog
        // save, corrupting the parent Role Profile document with a
        // spurious top-level "options" key and crashing on save with
        // "'NoneType' object has no attribute 'options'". Renaming the
        // field resolved it; the label is still "Options" in the UI.
        if (frm.fields_dict['repair_config']) {
            frm.fields_dict['repair_config'].grid.get_field('default_value').get_data = function(doc, cdt, cdn) {
                let row = locals[cdt][cdn];
                let tagged_options = (row.repair_options || [])
                    .map(function(r) { return r.option; })
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

