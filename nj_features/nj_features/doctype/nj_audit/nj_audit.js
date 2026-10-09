frappe.ui.form.on('NJ Audit', {
    setup: function(frm) { fill_audit_and_work_warehouse(frm) },

    onload: function(frm) {
        if (frm.doc.docstatus == 0 && !frm.doc.__islocal && frm.doc.__unsaved) {
            frm.set_df_property('nj_audit_items', 'cannot_add_rows', true);
        }
        $('.col-lg-2.layout-side-section').hide();
        frappe.call({
            method: 'nj_features.nj_features.doctype.nj_audit.nj_audit.update_create_permission',
            args: {doctype: cur_frm.doctype, nj_parameter: 'nj_audit_activation_level'},
            callback: function(response) {
                let currentValue = response.message;
                if (currentValue == '1') {
                    $('.primary-action').show();
                } else { $('.primary-action').hide(); }
            }
        });
    },
    
    refresh: function(frm) {
        setupNJAuditScannerOnly(frm, 'barcode');
        if (frm.doc.docstatus == 0) {
            $('[data-fieldname="barcode"]').focus();
        }
    },

    onload_post_render: function(frm) {
        if (frm.doc.docstatus == 0) {
            if (!frm.doc.audit_warehouse) {
                frappe.msgprint("<b>Audit Warehouse</b> is not filled.");
                $('.primary-action').hide();
                frappe.validated = false;
            } else {
                $('.primary-action').show();
                frappe.validated = true;
            }
        }
    },

    barcode: function(frm) {
        setupNJAuditScannerOnly(frm, 'barcode');
        if (!isNJAuditValueFromScanner(frm, 'barcode')) {
            clearNJAuditScannerField(frm, 'barcode');
            showNJAuditScannerMessage(frm, 'barcode');
            return;
        }
        if (frm.doc.barcode) { 
            if (isNJAuditDuplicateScan(frm, 'barcode')) return;
			frappe.call({
				method: "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
				args: {  search_value: frm.doc.barcode },
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
					frm.set_value('scan_serial_no', '');
					frm.set_value('barcode', '');
					frm.refresh_field("scan_serial_no");
					frm.refresh_field("barcode");
					$('[data-fieldname="barcode"]').focus();
				}
			});
		}
    },

    scan_serial_no: function (frm) {
        if (!frm.doc.scan_rack) {
            frm.set_value("scan_serial_no", "");
            frm.refresh_field("scan_serial_no");
            frappe.throw("Please select Rack");
        }
        
        if (frm.doc.scan_serial_no != '' && frm.doc.scan_rack != '') {
            frappe.db.get_value("Serial No", {serial_no: frm.doc.scan_serial_no}, ["name","item_code","item_group", "warehouse", "purchase_rate"], (r) => {
                if (r.name) {
                    let nj_audit_items = {
                        "serial_no": r.name, 
                        "item_code": r.item_code, 
                        "item_group": r.item_group,
                        "s_warehouse": r.warehouse, 
                        "purchase_rate": r.purchase_rate,
                        "t_rack_warehouse": frm.doc.scan_rack,
                        "parent_warehouse": frm.doc.audit_warehouse
                    };
                    frappe.db.get_value('NJ Settings', {'parameter': 'Item Group Check'}, 'value', function(response) {
                        if (response && response.value){
                            if (response.value.includes(nj_audit_items.item_group)) {

                                if (!frm.doc.audit_warehouse) {
                                    frappe.msgprint("<b>Audit Warehouse</b> is not filled.");
                                    $('.primary-action').hide();
                                    frappe.validated = false;
                                    $('[data-fieldname="barcode"]').focus();
                                    return
                                }

                                frm.add_child("nj_audit_items", nj_audit_items);
                                frm.refresh_field("nj_audit_items");
            
                                frm.set_value('serial_no_count', frm.doc.nj_audit_items.length);
                                frm.refresh_field('serial_no_count');
                            }
                            else{
                                frm.set_value("scan_serial_no", "");
                                frm.set_value("barcode", "");
                                frappe.throw("Item Group <b>" + nj_audit_items.item_group + "</b> is not valid");
                            }
                        } else {
                            frappe.throw("NJ Settings: <b>Item Group Check</b> is not configured");
                        }
                    });
                } else {
                    frappe.msgprint("Serial No: "+cur_frm.doc.scan_serial_no+" is not found.")
                }
                frm.set_value("scan_serial_no", "");
                frm.set_value("barcode", "");
            })
        }
        frm.set_value("scan_serial_no", "");
        frm.set_value("barcode", "");
        frm.refresh_field("scan_serial_no");
        frm.refresh_field("barcode");
    },

    scan_rack: function (frm) {
        if(frm.doc.scan_rack != '') {
            frappe.call({
                'method': 'nj_features.nj_features.doctype.nj_audit.nj_audit.get_rack_balance',
                'args': { 'rack_name': frm.doc.scan_rack },
                callback: function(r) {
                    if (r && r.message) {
                        frm.set_value('rack_balance', r.message.serial_count)
                        if (r.message.scan_rack == '')  {
                            let rack = frm.doc.scan_rack
                            frm.set_value('scan_rack', '')
                            frm.refresh_field('rack_balance')
                            frappe.throw("Scanned Warehouse: <b>" + rack + "</b> is not found.");
                            return
                        }
                        frm.set_value('scan_rack', r.message.scan_rack)
                        frm.refresh_field('rack_balance')
                    }
                }
            })
        }
    }
});

function fill_audit_and_work_warehouse(frm) {
    
    frappe.call({
        method: 'nj_features.nj_features.doctype.nj_audit.nj_audit.get_work_and_audit_warehouse',
        callback: function(r) {
            if (r && r.message) {
                let data = r.message
                if(!frm.doc.audit_interval){
                    frm.set_value('audit_interval',data.audit_interval)
                    frm.refresh_field('audit_interval')
                }
                if(!frm.doc.audit_warehouse){
                    frm.set_value('audit_warehouse',data.audit_warehouse)
                    frm.refresh_field('audit_warehouse')
                }
                if(!frm.doc.work_warehouse){
                    frm.set_value('work_warehouse',data.work_warehouse)
                    frm.refresh_field('work_warehouse')
                }
                if (frm.doc.audit_warehouse && !frm.doc.stock_balance) {
                    frm.set_value('stock_balance',data.stock_balance)
                    frm.refresh_field('stock_balance')
                }
            }
        }
    });
}

function initializeGridListeners(frm) {
    frm.fields_dict['nj_audit_items'].grid.on('refresh', function() {
        frm.fields_dict['nj_audit_items'].grid.wrapper.on('click', '.grid-remove-rows', function() {
            handleRowRemoval(frm);
        });
    });
}

function handleRowRemoval(frm) {
    let selectedRows = frm.fields_dict['nj_audit_items'].grid.get_selected_children();
    
    if (selectedRows.length > 0) {
        let accept_rows = frm.doc.accept_rows || "";
        let accept_rows_array = accept_rows.split(',').filter(idx => !selectedRows.some(row => row.idx.toString() === idx));
        frm.set_value('accept_rows', accept_rows_array.join(','));
    }
}

const NJ_AUDIT_SCANNER_MESSAGE = "Please use the scanner to scan barcode.";
const NJ_AUDIT_SCANNER_MIN_LENGTH = 3;
const NJ_AUDIT_SCANNER_MAX_SCAN_DURATION = 3000;
const NJ_AUDIT_SCANNER_MAX_KEY_GAP = 350;
const NJ_AUDIT_SCANNER_IDLE_DELAY = 600;

function setupNJAuditScannerOnly(frm, fieldname) {
    if (!window.njScannerAccess || !window.njScannerAccess.isEnabled()) return;
    const field = frm.get_field(fieldname);
    if (!field || !field.$input || frm.doc.docstatus !== 0) return;

    const inputField = field.$input;
    const stateKey = `__nj_audit_scanner_${fieldname}`;
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
        clearNJAuditScannerField(frm, fieldname);
        showNJAuditScannerMessage(frm, fieldname);
        return false;
    });

    inputField.on(`beforeinput.${stateKey}`, function(event) {
        const inputType = event.originalEvent && event.originalEvent.inputType;
        if (inputType === "insertFromPaste" || inputType === "insertFromDrop") {
            event.preventDefault();
            clearNJAuditScannerField(frm, fieldname);
            showNJAuditScannerMessage(frm, fieldname);
            return false;
        }
    });

    inputField.on(`drop.${stateKey}`, function(event) {
        event.preventDefault();
        clearNJAuditScannerField(frm, fieldname);
        showNJAuditScannerMessage(frm, fieldname);
        return false;
    });

    inputField.on(`contextmenu.${stateKey}`, function(event) {
        event.preventDefault();
        showNJAuditScannerMessage(frm, fieldname);
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
            clearNJAuditScannerField(frm, fieldname);
            showNJAuditScannerMessage(frm, fieldname);
            return false;
        }

        if (event.key === "Enter") {
            const value = inputField.val().trim();
            const isScanner = isNJAuditScannerBurst(state, value, now);

            window.clearTimeout(state.manualTimer);
            state.manualTimer = null;

            if (!isScanner) {
                event.preventDefault();
                resetNJAuditScannerState(state);
                clearNJAuditScannerField(frm, fieldname);
                showNJAuditScannerMessage(frm, fieldname);
                return false;
            }

            event.preventDefault();
            acceptNJAuditScannerValue(frm, fieldname, value, state);
            return false;
        }

        if (isNJAuditScannerControlKey(event)) {
            return true;
        }

        if (event.key.length !== 1) {
            return true;
        }

        if (!state.firstKeyTime) {
            state.firstKeyTime = now;
        }

        if (state.lastKeyTime && now - state.lastKeyTime > NJ_AUDIT_SCANNER_MAX_KEY_GAP) {
            event.preventDefault();
            resetNJAuditScannerState(state);
            clearNJAuditScannerField(frm, fieldname);
            showNJAuditScannerMessage(frm, fieldname);
            return false;
        }

        state.lastKeyTime = now;
        state.chars += event.key;

        window.clearTimeout(state.manualTimer);
        state.manualTimer = window.setTimeout(function() {
            if (state.chars) {
                const value = inputField.val().trim();
                if (isNJAuditScannerBurst(state, value)) {
                    acceptNJAuditScannerValue(frm, fieldname, value, state);
                } else {
                    resetNJAuditScannerState(state);
                    clearNJAuditScannerField(frm, fieldname);
                    showNJAuditScannerMessage(frm, fieldname);
                }
            }
        }, NJ_AUDIT_SCANNER_IDLE_DELAY);

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
            clearNJAuditScannerField(frm, fieldname);
            showNJAuditScannerMessage(frm, fieldname);
        }
    });
}

function isNJAuditScannerBurst(state, value, now = Date.now()) {
    if (!value || state.chars.length < NJ_AUDIT_SCANNER_MIN_LENGTH) return false;

    const lastKeyTime = state.lastKeyTime || now;
    const totalDuration = lastKeyTime - state.firstKeyTime;
    const lastKeyGap = now - lastKeyTime;

    return (
        totalDuration >= 0 &&
        totalDuration <= NJ_AUDIT_SCANNER_MAX_SCAN_DURATION &&
        lastKeyGap <= NJ_AUDIT_SCANNER_IDLE_DELAY
    );
}

function acceptNJAuditScannerValue(frm, fieldname, value, state) {
    state.validValue = value;
    state.validUntil = Date.now() + 3000;
    resetNJAuditScannerTyping(state);

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

function isNJAuditValueFromScanner(frm, fieldname) {
    if (!window.njScannerAccess || !window.njScannerAccess.isEnabled()) return true;
    const value = (frm.doc[fieldname] || "").trim();
    const state = frm[`__nj_audit_scanner_${fieldname}`];
    if (!value) return true;

    return Boolean(
        state &&
        state.validValue === value &&
        Date.now() <= state.validUntil
    );
}

function isNJAuditDuplicateScan(frm, fieldname) {
    const value = (frm.doc[fieldname] || "").trim();
    if (!value) return false;

    const stateKey = `__nj_audit_scanner_${fieldname}`;
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

function clearNJAuditScannerField(frm, fieldname) {
    const state = frm[`__nj_audit_scanner_${fieldname}`];
    if (state) {
        state.suppressManualCheck = true;
        resetNJAuditScannerState(state);
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

function showNJAuditScannerMessage(frm, fieldname) {
    const stateKey = `__nj_audit_scanner_${fieldname}`;
    const state = frm[stateKey] || {};
    const now = Date.now();

    if (state.lastMessageAt && now - state.lastMessageAt < 1200) return;

    state.lastMessageAt = now;
    frm[stateKey] = state;
    frappe.msgprint(__(NJ_AUDIT_SCANNER_MESSAGE));
}

function isNJAuditScannerControlKey(event) {
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

function resetNJAuditScannerState(state) {
    window.clearTimeout(state.manualTimer);
    state.manualTimer = null;
    state.validValue = "";
    state.validUntil = 0;
    resetNJAuditScannerTyping(state);
}

function resetNJAuditScannerTyping(state) {
    state.chars = "";
    state.firstKeyTime = 0;
    state.lastKeyTime = 0;
}

frappe.ui.form.on('NJ Audit Items', {
    nj_audit_items_remove: function(frm, cdt, cdn) {
        frm.set_value('serial_no_count', frm.doc.nj_audit_items.length);
        frm.refresh_field('serial_no_count');
    }
})
