// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Daily Individual Report', {
	
	onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();	
	},
    refresh: function(frm) {
        // Add event listeners to the child table fields
        frm.fields_dict['work_warehouse_inventory'].grid.wrapper.on('change', 'input[data-fieldname="yes"]', function() {
            toggle_checkboxes(this);
        });

        frm.fields_dict['work_warehouse_inventory'].grid.wrapper.on('change', 'input[data-fieldname="no"]', function() {
            toggle_checkboxes(this);
        });
    }
});

function toggle_checkboxes(field) {
    let row = $(field).closest('.grid-row');
    let yes_field = row.find('input[data-fieldname="yes"]');
    let no_field = row.find('input[data-fieldname="no"]');
    
    if ($(field).is(':checked')) {
        if (field.dataset.fieldname === 'yes') {
            no_field.prop('checked', false).change();
        } else {
            yes_field.prop('checked', false).change();
        }
    }
}

