// Copyright (c) 2025, NewJaisa - IT Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Auto Stock Entry', {

	setup: function(frm) { fill_work_warehouse(frm) },

	onload: function(frm) {
		$(document).on('keydown', function(event) {
			if (event.ctrlKey && event.shiftKey && event.key === 'B') {
				
				new frappe.ui.Scanner({
					dialog: true,
					multiple: false,
					on_scan: function on_scan(data) {
						if (data && data.result && data.result.text) {
							markAutoStockEntryValueFromScanner(frm, 'serial_no', data.result.text);
							frm.set_value('serial_no', data.result.text);
						}
					}
				});
			}
		})
	},

	refresh: function(frm) {
        $('.primary-action').hide();
		$('[data-fieldname="serial_no"]').focus();
		setupAutoStockEntryScannerOnly(frm, 'serial_no');
	},
serial_no: function(frm) {
	setupAutoStockEntryScannerOnly(frm, 'serial_no');
	if (!isAutoStockEntryValueFromScanner(frm, 'serial_no')) {
		clearAutoStockEntryScannerField(frm, 'serial_no');
		showAutoStockEntryScannerMessage(frm, 'serial_no');
		return;
	}

    if (frm.doc.serial_no) {
		if (isAutoStockEntryDuplicateScan(frm, 'serial_no')) return;
        frappe.call({
            method: 'nj_features.nj_features.doctype.auto_stock_entry.auto_stock_entry.submit_ste',
            args: { serial_no: frm.doc.serial_no, t_warehouse: frm.doc.default_target_warehouse },
            freeze: true,
            freeze_message: `<div style="text-align: center;">
                <i class="fa fa-spinner fa-spin" style="font-size: 24px;"></i> 
                <br>Transferring Stock... Please Wait
            </div>`,
            callback: function(r) {
                if (r && r.message) {
                    frappe.utils.play_sound('submit')
                }
            },
            error: function(err) {
                frappe.utils.play_sound('error')
            }
        })
        frm.set_value('serial_no', '')
        frm.refresh_field('serial_no')
        $('[data-fieldname="serial_no"]').focus();
    }
}
	// serial_no: function(frm) {
	// 	if (frm.doc.serial_no) {
	// 		handleScannerInput(frm, 'serial_no');
	// 		frappe.call({
	// 			method: 'nj_features.nj_features.doctype.auto_stock_entry.auto_stock_entry.submit_ste',
	// 			args: { serial_no: frm.doc.serial_no, t_warehouse: frm.doc.default_target_warehouse },
	// 			freeze: true,
	// 			freeze_message: `<div style="text-align: center;">
	// 				<i class="fa fa-spinner fa-spin" style="font-size: 24px;"></i> 
	// 				<br>Transferring Stock... Please Wait
	// 			</div>`,
	// 			callback: function(r) {
	// 				if (r && r.message) {
	// 					frappe.utils.play_sound('submit')
	// 				}
	// 			},
	// 			error: function(err) {
	// 				frappe.utils.play_sound('error')
	// 			}
	// 		})
	// 		frm.set_value('serial_no', '')
	// 		frm.refresh_field('serial_no')
	// 		$('[data-fieldname="serial_no"]').focus();
	// 	}
	// }
});

function fill_work_warehouse(frm) {
	frappe.call({
		method: 'nj_features.nj_features.doctype.auto_stock_entry.auto_stock_entry.get_work_warehouse',
		callback: function(r) {
			if (r && r.message) {
				frm.set_value('default_target_warehouse', r.message.work_warehouse)
				frm.refresh_field('default_target_warehouse')
			}
		},
		error: function(err) { frappe.utils.play_sound('error') }
	})
}

const AUTO_STOCK_ENTRY_SCANNER_MESSAGE = "Please use the scanner to scan barcode.";
const AUTO_STOCK_ENTRY_SCANNER_MIN_LENGTH = 3;
const AUTO_STOCK_ENTRY_SCANNER_MAX_SCAN_DURATION = 3000;
const AUTO_STOCK_ENTRY_SCANNER_MAX_KEY_GAP = 350;
const AUTO_STOCK_ENTRY_SCANNER_IDLE_DELAY = 600;

function setupAutoStockEntryScannerOnly(frm, fieldname) {
	const field = frm.get_field(fieldname);
	if (!field || !field.$input || frm.doc.docstatus !== 0) return;

	const inputField = field.$input;
	const stateKey = `__auto_stock_entry_scanner_${fieldname}`;
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
		clearAutoStockEntryScannerField(frm, fieldname);
		showAutoStockEntryScannerMessage(frm, fieldname);
		return false;
	});

	inputField.on(`beforeinput.${stateKey}`, function(event) {
		const inputType = event.originalEvent && event.originalEvent.inputType;
		if (inputType === "insertFromPaste" || inputType === "insertFromDrop") {
			event.preventDefault();
			clearAutoStockEntryScannerField(frm, fieldname);
			showAutoStockEntryScannerMessage(frm, fieldname);
			return false;
		}
	});

	inputField.on(`drop.${stateKey}`, function(event) {
		event.preventDefault();
		clearAutoStockEntryScannerField(frm, fieldname);
		showAutoStockEntryScannerMessage(frm, fieldname);
		return false;
	});

	inputField.on(`contextmenu.${stateKey}`, function(event) {
		event.preventDefault();
		showAutoStockEntryScannerMessage(frm, fieldname);
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
			clearAutoStockEntryScannerField(frm, fieldname);
			showAutoStockEntryScannerMessage(frm, fieldname);
			return false;
		}

		if (event.key === "Enter") {
			const value = inputField.val().trim();
			const isScanner = isAutoStockEntryScannerBurst(state, value, now);

			window.clearTimeout(state.manualTimer);
			state.manualTimer = null;

			if (!isScanner) {
				event.preventDefault();
				resetAutoStockEntryScannerState(state);
				clearAutoStockEntryScannerField(frm, fieldname);
				showAutoStockEntryScannerMessage(frm, fieldname);
				return false;
			}

			event.preventDefault();
			acceptAutoStockEntryScannerValue(frm, fieldname, value, state);
			return false;
		}

		if (isAutoStockEntryScannerControlKey(event)) {
			return true;
		}

		if (event.key.length !== 1) {
			return true;
		}

		if (!state.firstKeyTime) {
			state.firstKeyTime = now;
		}

		if (state.lastKeyTime && now - state.lastKeyTime > AUTO_STOCK_ENTRY_SCANNER_MAX_KEY_GAP) {
			event.preventDefault();
			resetAutoStockEntryScannerState(state);
			clearAutoStockEntryScannerField(frm, fieldname);
			showAutoStockEntryScannerMessage(frm, fieldname);
			return false;
		}

		state.lastKeyTime = now;
		state.chars += event.key;

		window.clearTimeout(state.manualTimer);
		state.manualTimer = window.setTimeout(function() {
			if (state.chars) {
				const value = inputField.val().trim();
				if (isAutoStockEntryScannerBurst(state, value)) {
					acceptAutoStockEntryScannerValue(frm, fieldname, value, state);
				} else {
					resetAutoStockEntryScannerState(state);
					clearAutoStockEntryScannerField(frm, fieldname);
					showAutoStockEntryScannerMessage(frm, fieldname);
				}
			}
		}, AUTO_STOCK_ENTRY_SCANNER_IDLE_DELAY);

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
			clearAutoStockEntryScannerField(frm, fieldname);
			showAutoStockEntryScannerMessage(frm, fieldname);
		}
	});
}

function isAutoStockEntryScannerBurst(state, value, now = Date.now()) {
	if (!value || state.chars.length < AUTO_STOCK_ENTRY_SCANNER_MIN_LENGTH) return false;

	const lastKeyTime = state.lastKeyTime || now;
	const totalDuration = lastKeyTime - state.firstKeyTime;
	const lastKeyGap = now - lastKeyTime;

	return (
		totalDuration >= 0 &&
		totalDuration <= AUTO_STOCK_ENTRY_SCANNER_MAX_SCAN_DURATION &&
		lastKeyGap <= AUTO_STOCK_ENTRY_SCANNER_IDLE_DELAY
	);
}

function acceptAutoStockEntryScannerValue(frm, fieldname, value, state) {
	state.validValue = value;
	state.validUntil = Date.now() + 3000;
	resetAutoStockEntryScannerTyping(state);

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

function markAutoStockEntryValueFromScanner(frm, fieldname, value) {
	const stateKey = `__auto_stock_entry_scanner_${fieldname}`;
	const state = frm[stateKey] || {};

	state.validValue = (value || "").trim();
	state.validUntil = Date.now() + 3000;
	frm[stateKey] = state;
}

function isAutoStockEntryValueFromScanner(frm, fieldname) {
	const value = (frm.doc[fieldname] || "").trim();
	const state = frm[`__auto_stock_entry_scanner_${fieldname}`];
	if (!value) return true;

	return Boolean(
		state &&
		state.validValue === value &&
		Date.now() <= state.validUntil
	);
}

function isAutoStockEntryDuplicateScan(frm, fieldname) {
	const value = (frm.doc[fieldname] || "").trim();
	if (!value) return false;

	const stateKey = `__auto_stock_entry_scanner_${fieldname}`;
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

function clearAutoStockEntryScannerField(frm, fieldname) {
	const state = frm[`__auto_stock_entry_scanner_${fieldname}`];
	if (state) {
		state.suppressManualCheck = true;
		resetAutoStockEntryScannerState(state);
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

function showAutoStockEntryScannerMessage(frm, fieldname) {
	const stateKey = `__auto_stock_entry_scanner_${fieldname}`;
	const state = frm[stateKey] || {};
	const now = Date.now();

	if (state.lastMessageAt && now - state.lastMessageAt < 1200) return;

	state.lastMessageAt = now;
	frm[stateKey] = state;
	frappe.msgprint(__(AUTO_STOCK_ENTRY_SCANNER_MESSAGE));
}

function isAutoStockEntryScannerControlKey(event) {
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

function resetAutoStockEntryScannerState(state) {
	window.clearTimeout(state.manualTimer);
	state.manualTimer = null;
	state.validValue = "";
	state.validUntil = 0;
	resetAutoStockEntryScannerTyping(state);
}

function resetAutoStockEntryScannerTyping(state) {
	state.chars = "";
	state.firstKeyTime = 0;
	state.lastKeyTime = 0;
}
