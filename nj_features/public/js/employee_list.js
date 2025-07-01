frappe.require("/assets/nj_features/js/nj_features.js", function () {
    extend_listview_settings('Employee', {
        onload: function (listview) {
            if (frappe.user.has_role('Developer')) {
                const label = __('Disable Qty Check');

                listview.page.add_inner_button(label, function () {
                    frappe.db.get_value("NJ Settings", { parameter: "disable_qty_check" }, ["value", "name"]).then((r) => {
                        const { value, name } = r.message || {};
                        
                        if (value == "0") {
                            frappe.db.set_value("NJ Settings", name, "value", "1").then(() => {
                                setButtonState(true);
                                frappe.show_alert({
                                    message: __('Qty Check has been de-activated successfully.'),
                                    indicator: 'red'
                                });
                            });
                        } else {
                            frappe.db.set_value("NJ Settings", name, "value", "0").then(() => {
                                setButtonState(false);
                                frappe.show_alert({
                                    message: __('Qty Check has been activated successfully.'),
                                    indicator: 'green'
                                });
                            });
                        }
                    });
                });

                frappe.db.get_value("NJ Settings", { parameter: "disable_qty_check" }, ["value"]).then((r) => {
                    const value = r.message?.value;
                    setButtonState(value === 1);
                });

                function setButtonState(isDisabled) {
                    const $btn = $(`[data-label="${encodeURIComponent(label)}"]`);
                    if ($btn.length) {
                        $btn.toggleClass('btn-danger', isDisabled);
                    }
                }
            }
        },

        refresh: function () {
            $('span.sidebar-toggle-btn').hide();
            $('.col-lg-2.layout-side-section').hide();
        }
    });
});