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

        // Repair Category Config: "Options" is a plain comma-separated
        // Small Text field, and "Default Value" is a plain Data field --
        // deliberately NOT dynamic/interactive widgets (Table MultiSelect
        // for Options, Autocomplete-with-custom-get_data for Default
        // Value). Both were tried and found unreliable in this Frappe
        // version (13.34.0) specifically inside a child table's own row:
        // - Table MultiSelect nested two levels deep bled its value onto
        //   the top-level Role Profile doc on save, crashing with
        //   "'NoneType' object has no attribute 'options'" (happened
        //   under two different field names, so it's structural, not
        //   naming -- Table MultiSelect only works reliably one level
        //   deep, e.g. this doctype's own "item_group" field, directly
        //   on Role Profile, which has always worked fine).
        // - Autocomplete's get_data, even made defensive against the
        //   inline-grid-vs-expanded-row-panel calling difference, still
        //   left typed input not sticking at all in the expanded panel.
        // Plain text fields have no such widget-level behavior to break,
        // and are reliable in both the inline grid and the expanded row
        // panel. The trade-off is no auto-suggest dropdown on Default
        // Value -- its description just asks the user to match one of
        // the Options manually.
        
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

