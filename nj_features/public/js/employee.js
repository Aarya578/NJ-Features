frappe.ui.form.on('Employee', {
    refresh(frm) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        frm.set_df_property('company', 'hidden', 1)
        frm.set_df_property('naming_series', 'hidden', 1)
        frm.refresh_field('naming_series')
        // if(frm.)
    },
    before_save(frm) {
        frappe.call({
            method: 'nj_features.nj_features.doctype.employee.create_user_and_warehouse',
            args: {'self': frm.doc},
            callback: function(r) {
                console.log("Employee",r)
            }
        })
    }
});

// var elementToHide = document.querySelector('[data-fieldname="naming_series"]');
// elementToHide.style.display = "none";
