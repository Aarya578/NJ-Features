frappe.provide("erpnext.buying");
{% include 'erpnext/public/js/controllers/buying.js' %};

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

const purchaseOrderValidation = erpnext.buying.PurchaseOrderController.extend({
    close_purchase_order: function(){

        frappe.call({
            method: 'nj_features.nj_features.doctype.purchase_order.check_billed_and_closed_amount',
            args: {'purchase_order': cur_frm.doc.name, 'po_grand_total': cur_frm.doc.grand_total},
            callback: function(r) {
                console.log('check_billed_and_closed_amount: ', r.message);
                let closedAmount = r.message.total_closed_amount
                let billedAmount = r.message.total_billed_amount
                let toleranceAmount = r.message.tolerance_amount
                if (closedAmount + toleranceAmount >= billedAmount) {
                    console.log("Yes", closedAmount + toleranceAmount ,">=", billedAmount);
                    erpnext.buying.PurchaseOrderController.prototype.close_purchase_order.call(me);
                } else {
                    console.log("No",closedAmount + toleranceAmount ," <> ", billedAmount);
                    frappe.throw("PO cannot be closed because 'Received Amount: " + closedAmount + 
                    "' <= 'Billed Amount: " + billedAmount + "'.");
                }
            }
        })
        // var me = this;
        // frappe.db.get_list('NJ Settings', {
        //     filters: {'module': 'NJ Features', 'doc_type': 'Purchase Order'},
        //     fields: ['parameter', 'value'],
        // }).then(doc => {
        //     console.log("NJ Settings", doc);
        //     for (let i = 0; i < doc.length; i++) {
        //         let parameter = doc[i].parameter;
        //         let value = doc[i].value;
                
        //         window[parameter] = value;
                
        //         console.log(parameter, value);
        //     }
        //     let toleranceAmount = flt(cur_frm.doc.grand_total, 6) * (flt(purchase_receipt_value, 6)/100)
        //     let billedAmount = flt(cur_frm.doc.grand_total, 6) * (flt(cur_frm.doc.per_billed, 6)/100)
        //     let receivedAmount = flt(cur_frm.doc.grand_total, 6) * (flt(cur_frm.doc.per_received, 6)/100)
        //     console.log("Grand Total: ", cur_frm.doc.grand_total);
        //     console.log("toleranceAmount: ", toleranceAmount, "[ ",cur_frm.doc.grand_total ," x ",purchase_receipt_value,"% ]");
        //     console.log("billedAmount: ", billedAmount, "[ ",cur_frm.doc.grand_total ," x ",cur_frm.doc.per_billed,"% ]");
        //     console.log("receivedAmount: ", receivedAmount, "[ ",cur_frm.doc.grand_total ," x ",cur_frm.doc.per_received,"% ]");
        //     if (receivedAmount + toleranceAmount >= billedAmount) {
        //         console.log("Yes", receivedAmount + toleranceAmount ,">", billedAmount);
        //         // this._super();
        //         erpnext.buying.PurchaseOrderController.prototype.close_purchase_order.call(me);
        //     } else {
        //         console.log("No",receivedAmount + toleranceAmount ," <> ", billedAmount);
        //         frappe.throw("PO can not be Closed because 'Received Amount' is <= 'Billed Amount'.");
        //     }
        // }).catch(err => {
        //     console.error(err);
        // });
    }
});

$.extend(cur_frm.cscript, new purchaseOrderValidation({frm: cur_frm}));
