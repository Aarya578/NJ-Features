frappe.ui.form.on('Employee', {
    refresh(frm) {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        frm.set_df_property('company', 'hidden', 1);
    },
    validate(frm) {

        frappe.call({
            method: 'nj_features.nj_features.doctype.employee.create_user_and_warehouse',
            args: {'self': frm.doc},
            callback: function(r) {
                if (r && r.message) {
                    if (r.message.status) {
                        frappe.throw("Employee status is <b>" + r.message.status + "</b>");
                    } else {
                        Object.keys(r.message).forEach(row => {
                            frm.set_value(row, r.message[row]);
                            frm.refresh_field(row);
                        });
                    }
                }
            }
        });
    }
});