frappe.ui.form.on('Purchase Invoice', {

    proof_image: function(frm) {
        const file_url = frm.doc.proof_image;
        if (!file_url) return;

        const allowed_ext = ['pdf', 'jpg', 'jpeg', 'png', 'webp'];
        const ext = file_url.split('.').pop().toLowerCase();
        if (!allowed_ext.includes(ext)) {
            frappe.msgprint('Please upload a PDF or image file (jpg, png, webp, pdf).');
            return;
        }

        frappe.show_progress('Reading invoice...', 30, 100, 'Extracting data using AI');

        frappe.call({
            method: 'nj_features.nj_features.api.invoice_ocr.extract_invoice_data',
            args: { file_url: file_url },
            callback: function(r) {
                frappe.hide_progress();

                if (!r.message || r.message._source === 'manual') {
                    frappe.msgprint({
                        title: 'Could not read invoice',
                        message: r.message?._error || 'Please fill details manually.',
                        indicator: 'orange'
                    });
                    return;
                }

                const data = r.message;
                const source = data._source === 'openai' ? 'AI (GPT-4o)' : 'OCR (Tesseract)';
                let filled = [];

                // ── Header fields ──────────────────────────

                if (data.supplier_invoice_no) {
                    frm.set_value('bill_no', data.supplier_invoice_no);
                    filled.push('Invoice No');
                }

                if (data.supplier_invoice_date) {
                    frm.set_value('bill_date', data.supplier_invoice_date);
                    filled.push('Date');
                }

                if (data.supplier_gstin) {
                    frm.set_value('supplier_gst_no', data.supplier_gstin);
                    frm.set_value('supplier_gstin', data.supplier_gstin);
                    filled.push('GST No');
                }

                if (data.gst_category) {
                    frm.set_value('gst_category', data.gst_category);
                    filled.push('GST Category');
                }

                if (data.invoice_copy) {
                    frm.set_value('invoice_copy', data.invoice_copy);
                    filled.push('Invoice Copy');
                }

                // ── Items from Purchase Order ───────────────
                if (data.po_items && data.po_items.length > 0) {

                    const existing_items = frm.doc.items || [];
                    const has_items = existing_items.some(i => i.item_code);

                    if (!has_items) {
                        frm.clear_table('items');

                        data.po_items.forEach(function(po_item) {
                            const qty        = flt(po_item.qty) || 1;
                            const rate       = flt(po_item.rate) || 0;
                            const amt        = qty * rate;
                            const uom        = po_item.uom || 'Nos';
                            const conv       = flt(po_item.conversion_factor) || 1;
                            const stock_qty  = qty * conv;

                            let row_data = {
                                item_code:                  po_item.item_code,
                                item_name:                  po_item.item_name,
                                description:                po_item.description || po_item.item_name,
                                gst_hsn_code:               po_item.hsn_code || '',
                                qty:                        qty,
                                received_qty:               qty,
                                stock_qty:                  stock_qty,
                                rejected_qty:               0,
                                uom:                        uom,
                                stock_uom:                  uom,
                                conversion_factor:          conv,
                                rate:                       rate,
                                amount:                     amt,
                                base_rate:                  rate,
                                base_amount:                amt,
                                net_rate:                   rate,
                                net_amount:                 amt,
                                base_net_rate:              rate,
                                base_net_amount:            amt,
                                price_list_rate:            rate,
                                base_price_list_rate:       rate,
                            };

                            if (po_item.warehouse) {
                                row_data.warehouse = po_item.warehouse;
                            }
                            if (po_item.purchase_order) {
                                row_data.purchase_order = po_item.purchase_order;
                                row_data.po_detail      = po_item.purchase_order_item;
                            }

                            frm.add_child('items', row_data);
                        });

                        frm.refresh_field('items');
                        filled.push(`${data.po_items.length} item(s) from PO`);

                    } else {
                        setTimeout(() => {
                            frappe.show_alert({
                                message: `PO ${data.purchase_order_no} found — items already in table.`,
                                indicator: 'blue'
                            }, 5);
                        }, 1000);
                    }

                } else if (data.purchase_order_no && (!data.po_items || data.po_items.length === 0)) {
                    setTimeout(() => {
                        frappe.show_alert({
                            message: `PO ${data.purchase_order_no} found but no items available.`,
                            indicator: 'orange'
                        }, 5);
                    }, 1000);
                }

                // ── Final alert ────────────────────────────
                if (filled.length > 0) {
                    frappe.show_alert({
                        message: `Auto-filled via ${source}: ${filled.join(', ')}`,
                        indicator: 'green'
                    }, 7);
                } else {
                    frappe.show_alert({
                        message: 'Invoice read but no fields could be extracted. Please fill manually.',
                        indicator: 'orange'
                    }, 5);
                }

                frm.dirty();
            },
            error: function() {
                frappe.hide_progress();
                frappe.msgprint({
                    title: 'OCR Error',
                    message: 'Service error. Please fill details manually.',
                    indicator: 'red'
                });
            }
        });
    }
});