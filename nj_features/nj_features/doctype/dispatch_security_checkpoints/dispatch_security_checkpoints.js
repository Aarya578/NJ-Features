frappe.ui.form.on('Dispatch Security Checkpoints', {
    onload: function(frm) {
        if (frm.doc.docstatus == 0) {
            frm.set_df_property('dispatch_security_child_table', 'cannot_add_rows', true);
            frm.set_df_property('dispatch_security_retutn_table', 'cannot_add_rows', true);
        }
    },
    // after_save(frm) {
    //     frappe.call({
    //         method: "nj_features.nj_features.doctype.dispatch_security_checkpoints.dispatch_security_checkpoints.fsetting_email_in_parent",
    //         args: {
    //             docname: frm.doc.name
    //         },
    //         callback: function (r) {
    //             if (r.message) {
    //                 frm.set_value("dispatch_email", r.message);
    //                 frm.refresh_field("dispatch_email");
    //                 frappe.show_alert({ message: "Dispatch Email Updated", indicator: "green" });
    //             }
    //         }
    //     });
    // },
    refresh: function(frm) {
        setupDispatchScannerOnly(frm, 'scan_serial_no');
        setupDispatchScannerOnly(frm, 'barcode');
        $('.col-lg-2.layout-side-section').hide();
        if (frm.doc.docstatus == 0) {
            $('[data-fieldname="scan_serial_no"]').focus();
        }
    },

    barcode: function(frm) {
        setupDispatchScannerOnly(frm, 'barcode');
        if (!isDispatchValueFromScanner(frm, 'barcode')) {
            clearDispatchScannerField(frm, 'barcode');
            showDispatchScannerMessage(frm, 'barcode');
            return;
        }
		if (frm.doc.barcode) { 
            if (isDispatchDuplicateScan(frm, 'barcode')) return;
			frappe.call({
				method: "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
				args: {  search_value: frm.doc.barcode, raise_exp: 0 },
				callback: function(r) {
					if (r.message) {
						if (r.message.serial_no) {
                            
							frm.set_value('scan_serial_no', r.message.serial_no);
						} else if (r.message.scan) {
							frappe.msgprint("Please Scan the Serial No.");
							frm.set_value('barcode', '');
							frm.set_value('scan_serial_no', '');
						}
						frm.refresh_field("scan_serial_no");
						frm.refresh_field("barcode");
						$('[data-fieldname="barcode"]').focus();
					}
				},
				error: function(r) {
					frappe.msgprint("Error while scanning Serial No.");
					frm.set_value('barcode', '');
					frm.set_value('barcode', '');
					frm.refresh_field("barcode");
					frm.refresh_field("barcode");
					$('[data-fieldname="barcode"]').focus();
				}
			});
		} else {
            frm.set_value('scan_serial_no', '');
            frm.refresh_field("scan_serial_no");
        }
    },

    scan_serial_no: function (frm) {
        setupDispatchScannerOnly(frm, 'scan_serial_no');

        if (frm.doc.scan_serial_no) {
            if (isDispatchDuplicateScan(frm, 'scan_serial_no')) return;
            if (!frm.doc.dispatch_type) {
                frappe.msgprint('Please Select Dispatch Type');
                frm.set_value('scan_serial_no', '');
                frm.refresh_field('scan_serial_no');
            } else if (frm.doc.dispatch_type == 'Sales Order') {
                frappe.call({
                    method: 'nj_features.nj_features.doctype.dispatch_security_checkpoints.dispatch_security_checkpoints.scan_serial_no_data_for_sales',
                    args: { serial_no: frm.doc.scan_serial_no },
                    callback: function (r) {
                        if (r.message) {
                            frm.set_value('scan_serial_no', '');
                            frm.refresh_field('scan_serial_no');
            
                            let exists = false;
                            if (frm.doc.dispatch_security_child_table) {
                                exists = frm.doc.dispatch_security_child_table.some(row => 
                                    row.serial_no === r.message.serial_no
                                );
                            }
            
                            if (!exists) {
                                let dispatch_security_child_table = {
                                    "serial_no": r.message.serial_no,
                                    "item_code": r.message.item_code || 'Not Available',
                                    "sales_invoice": r.message.sales_invoice || 'Not Available',
                                    "sales_order": r.message.sales_order || 'Not Available',
                                    "delivery_note": r.message.delivery_note || 'Not Available',
                                    "si_status": r.message.si_status || 'Not Available',
                                    "dn_status": r.message.dn_status || 'Not Available',
                                    "approved": r.message.approved,
                                    "is_cod" :r.message.is_cod,
                                    "sales_channel": r.message.sales_channel || 'Not Available',
                                    "customer_name": r.message.customer_name || 'Not Available',
                                    "courier_name": r.message.courier_name || 'Not Available',
                                    "tracking_id": r.message.tracking_id || 'Not Available',
                                    "email_id": r.message.email_id || 'Not Available'
                                };
                                frm.add_child("dispatch_security_child_table", dispatch_security_child_table);
                                frm.refresh_field("dispatch_security_child_table");
                            } else {
                                frm.set_value('scan_serial_no', '');
                                frm.refresh_field('scan_serial_no');
                            }
                        } else {
                            frm.set_value('scan_serial_no', '');
                            frm.refresh_field('scan_serial_no');
                        }
                    },
                    error: function (err) {
                        frappe.hide_progress();
                        frappe.msgprint(__('Error occurred while scanning Serial No.', err));
                    }
                });
            }      
        }
    },
    purchase_reciept_name: function(frm) {
        if (frm.doc.purchase_reciept_name){
            frappe.call({
                method: 'nj_features.nj_features.doctype.dispatch_security_checkpoints.dispatch_security_checkpoints.scan_serial_no_data_for_return',
                args: { pr_name: frm.doc.purchase_reciept_name },
                callback: function (r) {
                    if (r.message) {
                        frm.set_value('purchase_reciept_name', '');
                        frm.refresh_field('purchase_reciept_name');
                        
                        let dispatch_security_return_table = {
                            "purchase_invoice": r.message.purchase_invoice || 'Not Available',
                            "pi_status": r.message.pi_status || 'Not Available',
                            "purchase_receipt": r.message.purchase_receipt || 'Not Available',
                            "pr_status": r.message.pr_status || 'Not Available',
                        };
                        
                        frm.add_child("dispatch_security_return_table", dispatch_security_return_table);
                        frm.refresh_field("dispatch_security_return_table");
                    } else {
                        frm.set_value('purchase_reciept_name', '');
                        frm.refresh_field('purchase_reciept_name');
                    }
                },
                error: function(err) {
                    frappe.hide_progress();
                    frappe.msgprint(__('Error occurred while scanning Purchase Reciept Name.', err));
                }
            });
        }
    },
    stock_entry_name: function(frm) {
        if (frm.doc.stock_entry_name) {
            frappe.call({
                method: "nj_features.nj_features.doctype.dispatch_security_checkpoints.dispatch_security_checkpoints.get_item_code_details_for_transfer",
                args: { ste_number: frm.doc.stock_entry_name },
                callback: function(r) {
                    if (r.message) {
                        frm.set_value('stock_entry_name', '');
                        frm.refresh_field('stock_entry_name');
                        frm.clear_table("dispatch_security_stock_entry_table");
                        let errors = [];
                        let has_errors = false;
        
                        if (Array.isArray(r.message)) {
                            r.message.forEach(item => {
                                if (item.error) {
                                    errors.push(item.error);
                                    has_errors = true;
                                } else if (item.item_code) {
                                    let new_row = frm.add_child("dispatch_security_stock_entry_table");
                                    frappe.model.set_value(new_row.doctype, new_row.name, "stock_entry_name", item.parent);
                                    frappe.model.set_value(new_row.doctype, new_row.name, "item_code", item.item_code);
                                    frappe.model.set_value(new_row.doctype, new_row.name, "target_warehouse", item.t_warehouse);
                                    frappe.model.set_value(new_row.doctype, new_row.name, "source_warehouse", item.s_warehouse);
                                    frappe.model.set_value(new_row.doctype, new_row.name, "serial_no_quantity", item.qty);
                                    frappe.model.set_value(new_row.doctype, new_row.name, "serial_no", item.serial_no.replace('\n', ', '));
                                }
                            });
                            frm.refresh_field("dispatch_security_stock_entry_table");
                        }

                        frm.doc.transfer_errors = errors;

                        if (has_errors) {
                            frm.doc.has_transfer_errors = true;
                            frappe.msgprint({
                                title: __('Errors'),
                                message: errors.join('<br>'),
                                indicator: 'red'
                            });
                        } else { frm.doc.has_transfer_errors = false; }
                    }
                },
                error: function(err) {
                    frappe.msgprint(__('Error occurred while scanning Stock Entry Name.', err));
                }
            });
        }
    }
});

const DISPATCH_SCANNER_MESSAGE = "Please use the scanner to scan barcode.";
const DISPATCH_SCANNER_MIN_LENGTH = 3;
const DISPATCH_SCANNER_MAX_SCAN_DURATION = 3000;
const DISPATCH_SCANNER_MAX_KEY_GAP = 350;
const DISPATCH_SCANNER_IDLE_DELAY = 600;

function setupDispatchScannerOnly(frm, fieldname) {
    const field = frm.get_field(fieldname);
    if (!field || !field.$input || frm.doc.docstatus !== 0) return;

    const inputField = field.$input;
    const stateKey = `__dispatch_scanner_${fieldname}`;
    let state = frm[stateKey];

    if (!state) {
        state = frm[stateKey] = {
            chars: "",
            firstKeyTime: 0,
            lastKeyTime: 0,
            manualTimer: null,
            validValue: "",
            validUntil: 0,
            lastMessageAt: 0,
            suppressManualCheck: false,
        };
    }

    inputField.off(`.${stateKey}`);

    inputField.on(`paste.${stateKey}`, function(event) {
        event.preventDefault();
        clearDispatchScannerField(frm, fieldname);
        showDispatchScannerMessage(frm, fieldname);
        return false;
    });

    inputField.on(`beforeinput.${stateKey}`, function(event) {
        const inputType = event.originalEvent && event.originalEvent.inputType;
        if (inputType === "insertFromPaste" || inputType === "insertFromDrop") {
            event.preventDefault();
            clearDispatchScannerField(frm, fieldname);
            showDispatchScannerMessage(frm, fieldname);
            return false;
        }
    });

    inputField.on(`drop.${stateKey}`, function(event) {
        event.preventDefault();
        clearDispatchScannerField(frm, fieldname);
        showDispatchScannerMessage(frm, fieldname);
        return false;
    });

    inputField.on(`contextmenu.${stateKey}`, function(event) {
        event.preventDefault();
        showDispatchScannerMessage(frm, fieldname);
        return false;
    });

    inputField.on(`keydown.${stateKey}`, function(event) {
        const now = Date.now();

        if (state.validValue && now > state.validUntil) {
            state.validValue = "";
            state.validUntil = 0;
        }

        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") {
            event.preventDefault();
            clearDispatchScannerField(frm, fieldname);
            showDispatchScannerMessage(frm, fieldname);
            return false;
        }

        if (event.key === "Enter") {
            const value = inputField.val().trim();
            const isScanner = isDispatchScannerBurst(state, value, now);

            window.clearTimeout(state.manualTimer);
            state.manualTimer = null;

            if (!isScanner) {
                event.preventDefault();
                resetDispatchScannerState(state);
                clearDispatchScannerField(frm, fieldname);
                showDispatchScannerMessage(frm, fieldname);
                return false;
            }

            event.preventDefault();
            acceptDispatchScannerValue(frm, fieldname, value, state);
            return false;
        }

        if (isDispatchScannerControlKey(event)) {
            return true;
        }

        if (event.key.length !== 1) {
            return true;
        }

        if (!state.firstKeyTime) {
            state.firstKeyTime = now;
        }

        if (state.lastKeyTime && now - state.lastKeyTime > DISPATCH_SCANNER_MAX_KEY_GAP) {
            event.preventDefault();
            resetDispatchScannerState(state);
            clearDispatchScannerField(frm, fieldname);
            showDispatchScannerMessage(frm, fieldname);
            return false;
        }

        state.lastKeyTime = now;
        state.chars += event.key;

        window.clearTimeout(state.manualTimer);
        state.manualTimer = window.setTimeout(function() {
            if (state.chars) {
                const value = inputField.val().trim();
                if (isDispatchScannerBurst(state, value)) {
                    acceptDispatchScannerValue(frm, fieldname, value, state);
                } else {
                    resetDispatchScannerState(state);
                    clearDispatchScannerField(frm, fieldname);
                    showDispatchScannerMessage(frm, fieldname);
                }
            }
        }, DISPATCH_SCANNER_IDLE_DELAY);

        return true;
    });

    inputField.on(`input.${stateKey}`, function() {
        if (state.suppressManualCheck) return;

        const value = inputField.val().trim();
        if (!value) return;

        if (state.validValue === value && Date.now() <= state.validUntil) {
            return;
        }

        if (!state.chars) {
            clearDispatchScannerField(frm, fieldname);
            showDispatchScannerMessage(frm, fieldname);
        }
    });
}

function isDispatchScannerBurst(state, value, now = Date.now()) {
    if (!value || state.chars.length < DISPATCH_SCANNER_MIN_LENGTH) return false;

    const lastKeyTime = state.lastKeyTime || now;
    const totalDuration = lastKeyTime - state.firstKeyTime;
    const lastKeyGap = now - lastKeyTime;

    return (
        totalDuration >= 0 &&
        totalDuration <= DISPATCH_SCANNER_MAX_SCAN_DURATION &&
        lastKeyGap <= DISPATCH_SCANNER_IDLE_DELAY
    );
}

function acceptDispatchScannerValue(frm, fieldname, value, state) {
    state.validValue = value;
    state.validUntil = Date.now() + 3000;
    resetDispatchScannerTyping(state);

    const setValue = frm.set_value(fieldname, value);
    const triggerField = function() {
        frm.trigger(fieldname);
    };

    if (setValue && setValue.then) {
        setValue.then(triggerField);
    } else {
        triggerField();
    }
}

function isDispatchValueFromScanner(frm, fieldname) {
    const value = (frm.doc[fieldname] || "").trim();
    const state = frm[`__dispatch_scanner_${fieldname}`];
    if (!value) return true;

    return Boolean(
        state &&
        state.validValue === value &&
        Date.now() <= state.validUntil
    );
}

function isDispatchDuplicateScan(frm, fieldname) {
    const value = (frm.doc[fieldname] || "").trim();
    if (!value) return false;

    const stateKey = `__dispatch_scanner_${fieldname}`;
    const state = frm[stateKey] || {};
    const now = Date.now();

    if (state.lastProcessedValue === value && now - state.lastProcessedAt < 1000) {
        return true;
    }

    state.lastProcessedValue = value;
    state.lastProcessedAt = now;
    frm[stateKey] = state;
    return false;
}

function clearDispatchScannerField(frm, fieldname) {
    const state = frm[`__dispatch_scanner_${fieldname}`];
    if (state) {
        state.suppressManualCheck = true;
        resetDispatchScannerState(state);
    }

    frm.set_value(fieldname, "");
    frm.refresh_field(fieldname);

    const field = frm.get_field(fieldname);
    if (field && field.$input) {
        field.$input.val("");
        field.$input.focus();
    }

    if (state) {
        window.setTimeout(function() {
            state.suppressManualCheck = false;
        }, 0);
    }
}

function showDispatchScannerMessage(frm, fieldname) {
    const stateKey = `__dispatch_scanner_${fieldname}`;
    const state = frm[stateKey] || {};
    const now = Date.now();

    if (state.lastMessageAt && now - state.lastMessageAt < 1200) return;

    state.lastMessageAt = now;
    frm[stateKey] = state;
    frappe.msgprint(__(DISPATCH_SCANNER_MESSAGE));
}

function isDispatchScannerControlKey(event) {
    return (
        event.ctrlKey ||
        event.metaKey ||
        event.altKey ||
        [
            "Tab",
            "Shift",
            "Control",
            "Alt",
            "Meta",
            "Escape",
            "ArrowLeft",
            "ArrowRight",
            "ArrowUp",
            "ArrowDown",
            "Home",
            "End",
            "Backspace",
            "Delete",
        ].includes(event.key)
    );
}

function resetDispatchScannerState(state) {
    window.clearTimeout(state.manualTimer);
    state.manualTimer = null;
    state.validValue = "";
    state.validUntil = 0;
    resetDispatchScannerTyping(state);
}

function resetDispatchScannerTyping(state) {
    state.chars = "";
    state.firstKeyTime = 0;
    state.lastKeyTime = 0;
}
