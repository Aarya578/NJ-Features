frappe.ui.form.on('Material Request Item', {
    post_order_status: function(frm, cdt, cdn) {
        let child = locals[cdt][cdn];
        if (child.post_order_status == "Completed") {
            frappe.user.get_role_profile("Modular Leads/Line Manager").then((result) => {
                if (result) { frappe.model.set_value(cdt, cdn, 'repaired_closed', 1); }
            })
        } else { frappe.model.set_value(cdt, cdn, 'repaired_closed', 0); }
        frm.refresh_field('repaired_closed');
    }
});