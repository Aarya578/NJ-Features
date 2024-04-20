frappe.ui.form.on('Purchase Order', {
    onload(frm) {
        $('.col-lg-2.layout-side-section').hide();
    },
    refresh(frm) {
        frm.events.has_warranty(frm)
    },
    has_warranty: function(frm) {
        if (frm.doc.has_warranty == 0 && frm.doc.docstatus == 0) {
            frm.set_value('warranty_days', 0);
        }
    },
    validate: function(frm) {
        // Get the posting date and number of days from the form
        var postingDate = frm.doc.transaction_date; // Assuming the field name is 'posting_date'
        var numberOfDays = frm.doc.warranty_days; // Assuming the field name is 'number_of_days'

        var warrantyDate = frappe.datetime.add_days(postingDate, numberOfDays);
        cur_frm.set_value('warrenty_till_date', warrantyDate)
    }
});