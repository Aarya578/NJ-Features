frappe.provide("erpnext.buying");
{% include 'erpnext/public/js/controllers/buying.js' %};

frappe.ui.form.on('Purchase Order', {
    onload(frm) {
        $('.col-lg-2.layout-side-section').hide();
    },
    
    refresh(frm) {
        if (frm.doc.has_warranty == 0 && frm.doc.docstatus == 0) {
            frm.set_value('warranty_days', 0);
        }
    },

    validate: function(frm) {
        var postingDate = frm.doc.transaction_date;
        var numberOfDays = frm.doc.warranty_days;
        var warrantyDate = frappe.datetime.add_days(postingDate, numberOfDays);

        cur_frm.set_value('warrenty_till_date', warrantyDate)
    }
});

const purchaseOrderValidation = erpnext.buying.PurchaseOrderController.extend({
    close_purchase_order: function(){

        frappe.call({
            method: 'nj_features.nj_features.doctype.purchase_order.check_billed_and_closed_amount',
            args: {'purchase_order': cur_frm.doc.name, 'po_grand_total': cur_frm.doc.grand_total},
            callback: function(r) {
                console.log('check_billed_and_closed_amount: ', r.message);
                let closedAmount = r.message.total_closed_amount ?? 0.0
                let billedAmount = r.message.total_billed_amount ?? 0.0
                let toleranceAmount = r.message.tolerance_amount
                let diffAmount = closedAmount - billedAmount
                if (closedAmount == 0 && billedAmount == 0) {
                    console.log("No, closedAmount is ",closedAmount," and billedAmount is ", billedAmount);
                    frappe.throw("PO cannot be closed because both 'Closed Amount' and 'Billed Amount' are 0.0. Instead you can cancel the PO.");
                }// (diffAmount + toleranceAmount) >= -1 &&  - Removed
                if ((diffAmount + toleranceAmount) <= 1) {
                    console.log("Yes, Closed Amount: ", closedAmount + toleranceAmount ," <= Billed Amount: ", billedAmount);
                    erpnext.buying.PurchaseOrderController.prototype.close_purchase_order.call(me);
                } else {
                    console.log("No",closedAmount + toleranceAmount ," <> ", billedAmount);
                    frappe.throw("PO cannot be closed because 'Closed Amount: " + closedAmount + 
                    "' > 'Billed Amount: " + billedAmount + "'.");
                }
            }
        });
    }
});

$.extend(cur_frm.cscript, new purchaseOrderValidation({frm: cur_frm}));