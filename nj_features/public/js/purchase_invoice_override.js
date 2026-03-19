console.log("purchase_invoice_override.js loaded");

frappe.ui.form.on("Purchase Invoice", {
    proof_image: function(frm) {
        console.log("PI OCR triggered", frm.doc.name, frm.doc.proof_image);

        if (!frm.doc.proof_image) return;

        frappe.call({
            method: "nj_features.nj_features.nj_features.api.invoice_ocr.extract_invoice_data",
            args: {
                file_url: frm.doc.proof_image
            },
            freeze: true,
            freeze_message: __("Reading invoice..."),
            callback: function(r) {
                console.log("PI OCR success", r);

                if (!r.message) {
                    frappe.msgprint(__("No OCR data returned."));
                    return;
                }

                const data = r.message;

                if (data._error) {
                    frappe.msgprint({
                        title: __("OCR Notice"),
                        message: data._error,
                        indicator: "orange"
                    });
                }

                if (data.supplier_invoice_no) {
                    frm.set_value("bill_no", data.supplier_invoice_no);
                }

                if (data.supplier_invoice_date) {
                    frm.set_value("bill_date", data.supplier_invoice_date);
                }

                if (data.supplier_gstin) {
                    if (frm.fields_dict.supplier_gstin) {
                        frm.set_value("supplier_gstin", data.supplier_gstin);
                    }
                    if (frm.fields_dict.supplier_gst_no) {
                        frm.set_value("supplier_gst_no", data.supplier_gstin);
                    }
                }

                if (data.grand_total && frm.fields_dict.bill_amount) {
                    frm.set_value("bill_amount", data.grand_total);
                }

                if (data.po_items && Array.isArray(data.po_items) && data.po_items.length) {
                    frm.clear_table("items");

                    data.po_items.forEach(row => {
                        let child = frm.add_child("items");
                        child.item_code = row.item_code;
                        child.item_name = row.item_name;
                        child.description = row.description;
                        child.qty = row.qty;
                        child.rate = row.rate;
                        child.amount = row.amount;
                        child.uom = row.uom;
                        child.stock_uom = row.stock_uom;
                        child.conversion_factor = row.conversion_factor;
                        child.warehouse = row.warehouse;
                        child.purchase_order = row.purchase_order;
                        child.po_detail = row.purchase_order_item;
                        child.gst_hsn_code = row.hsn_code;
                    });

                    frm.refresh_field("items");
                }

                if (data._source) {
                    frappe.show_alert({
                        message: __("Invoice data extracted via {0}", [data._source]),
                        indicator: "green"
                    });
                }
            },
            error: function(r) {
                console.log("PI OCR error", r);
                frappe.msgprint({
                    title: __("OCR Failed"),
                    message: __("Could not extract invoice data automatically. Please fill manually."),
                    indicator: "red"
                });
            }
        });
    }
});