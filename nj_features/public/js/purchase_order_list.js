frappe.listview_settings['Purchase Order'] = {
    onload: function(listview) {

        listview.page.add_action_item(__('Re-Open Selected'), function() {
            const selected = listview.get_checked_items();
            selected.forEach(doc => {
                if (doc.status === "Closed" && doc.docstatus == 1) {
                    frappe.call({
                        method: "erpnext.buying.doctype.purchase_order.purchase_order.update_status",
                        args: {
                            status: 'Submitted',
                            name: doc.name
                        },
                        callback: function(r) {
                            doc.status = 'Submitted';
                            listview.refresh();
                            frappe.show_alert(__('Purchase Order {0} has been resumed.', [doc.name]));
                        }
                    });
                }
            });
        });

        listview.page.add_action_item(__('Close Selected'), function() {
            const selected = listview.get_checked_items();
            selected.forEach(doc => {
                if ( doc.docstatus == 1) {
                    frappe.call({
                        method: 'nj_features.overrides.purchase_order.check_billed_and_closed_amount',
                        args: {'purchase_order': doc.name, 'po_grand_total': doc.grand_total},
                        callback: function(r) {

                            let closedAmount = r.message.total_closed_amount ?? 0.0
                            let billedAmount = r.message.total_billed_amount ?? 0.0
                            let toleranceAmount = r.message.tolerance_amount
                            let diffAmount = closedAmount - billedAmount

                            if (closedAmount == 0 && billedAmount == 0) {
                                console.log("No, closedAmount is ",closedAmount," and billedAmount is ", billedAmount);
                                frappe.throw("PO cannot be closed because both 'Closed Amount' and 'Billed Amount' are 0.0. Instead you can cancel the PO.");
                            }
                            if ((diffAmount + toleranceAmount) <= 1) {
                                console.log("Yes, Closed Amount: ", closedAmount + toleranceAmount ," <= Billed Amount: ", billedAmount);
                                frappe.call({
                                    method: "erpnext.buying.doctype.purchase_order.purchase_order.update_status",
                                    args: {
                                        status: 'Closed',
                                        name: doc.name
                                    },
                                    callback: function(r) {
                                        doc.status = 'Closed';
                                        listview.refresh();
                                        frappe.show_alert(__('Purchase Order {0} has been closed.', [doc.name]));
                                    }
                                });
                            } else {
                                console.log("No",closedAmount + toleranceAmount ," <> ", billedAmount);
                                frappe.throw("PO cannot be closed because 'Closed Amount: " + closedAmount + 
                                "' > 'Billed Amount: " + billedAmount + "'.");
                            }
                        }
                    });
                }
            });
        });
    }
};
