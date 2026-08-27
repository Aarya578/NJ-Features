frappe.ui.form.on('Repair Category Option', {
    refresh: function(frm) {
        // Known Frappe (this site is on v13.34.0) Table MultiSelect
        // "create a new record" quick-entry bug: typing a brand-new tag
        // into a multiselect that already has other tags selected can
        // pre-fill this dialog's Option Value field with a garbled join
        // of the ALREADY-SELECTED tag objects instead of just the text
        // that was typed -- e.g. "[object Object],[object Object]S".
        //
        // Rather than patching Frappe's internal multiselect/quick-entry
        // control (deep framework internals, version-specific, risky to
        // rely on), this defensively detects that exact garbage pattern
        // the moment the quick-entry form renders and clears it, so the
        // user can just type the real value. This never fires on a
        // legitimately typed value, since no real option name would
        // ever contain the literal substring "[object Object]".
        if (frm.doc.option_value && frm.doc.option_value.indexOf('[object Object]') !== -1) {
            frappe.model.set_value(frm.doctype, frm.docname, 'option_value', '');
            frm.refresh_field('option_value');
            frappe.show_alert({
                message: __('Cleared an invalid auto-filled value — please type the option name.'),
                indicator: 'orange'
            }, 5);
        }
    }
});
