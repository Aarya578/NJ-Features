frappe.ui.form.on("Item Attribute Value", {
    laptop_value: function(frm, cdt, cdn) {
        set_item_attribute_value_updated_info(frm, cdt, cdn);
    },

    desktop_value: function(frm, cdt, cdn) {
        set_item_attribute_value_updated_info(frm, cdt, cdn);
    }
});

function set_item_attribute_value_updated_info(frm, cdt, cdn) {
    frappe.model.set_value(
        cdt,
        cdn,
        "updated_by_",
        frappe.session.user
    );

    frappe.model.set_value(
        cdt,
        cdn,
        "updated_on",
        frappe.datetime.now_date()
    );
}
