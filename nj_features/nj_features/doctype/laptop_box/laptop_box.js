frappe.ui.form.on('Laptop Box', {
    onload: function(frm) {
        setupLaptopBoxScannerOnly(frm, 'nj_barcode');
        setupLaptopBoxScannerOnly(frm, 'nj_adaptor_barcode');
        $('[data-fieldname="nj_barcode"]').focus();
    },
    refresh: function(frm) {
        setupLaptopBoxScannerOnly(frm, 'nj_barcode');
        setupLaptopBoxScannerOnly(frm, 'nj_adaptor_barcode');
        $('[data-fieldname="nj_barcode"]').focus();
    },

    nj_barcode: function(frm) {
		setupLaptopBoxScannerOnly(frm, 'nj_barcode');
        if (!isLaptopBoxValueFromScanner(frm, 'nj_barcode')) {
            clearLaptopBoxScannerField(frm, 'nj_barcode');
            showLaptopBoxScannerMessage(frm, 'nj_barcode');
            return;
        }
		if (frm.doc.nj_barcode) { 
            if (isLaptopBoxDuplicateScan(frm, 'nj_barcode')) return;
			frappe.call({
				method: "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
				args: {  search_value: frm.doc.nj_barcode, raise_exp: true },
				callback: function(r) {
					if (r.message) {
						if (r.message.serial_no) {
							setLaptopBoxSerialNoFromScan(frm, r.message.serial_no);
						} else if (r.message.scan) {
							frappe.msgprint("Please Scan the Serial No.");
							frm.set_value('nj_barcode', '');
							frm.set_value('barcode', '');
						}
						frm.refresh_field("nj_barcode");
						frm.refresh_field("barcode");
						$('[data-fieldname="nj_barcode"]').focus();
					}
				},
				error: function(r) {
					frappe.msgprint("Error while scanning Serial No.");
					frm.set_value('barcode', '');
					frm.set_value('nj_barcode', '');
					frm.refresh_field("barcode");
					frm.refresh_field("nj_barcode");
					$('[data-fieldname="nj_barcode"]').focus();
				}
			});
        } else {
            frm.set_value('barcode', '');
        }
    },

    nj_adaptor_barcode: function(frm) {
		setupLaptopBoxScannerOnly(frm, 'nj_adaptor_barcode');
        if (!isLaptopBoxValueFromScanner(frm, 'nj_adaptor_barcode')) {
            clearLaptopBoxScannerField(frm, 'nj_adaptor_barcode');
            showLaptopBoxScannerMessage(frm, 'nj_adaptor_barcode');
            return;
        }
		if (frm.doc.nj_adaptor_barcode) { 
            if (isLaptopBoxDuplicateScan(frm, 'nj_adaptor_barcode')) return;
			frappe.call({
				method: "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
				args: {  search_value: frm.doc.nj_adaptor_barcode, raise_exp: false },
				callback: function(r) {
					if (r.message) {
						if (r.message.serial_no) {
							frm.set_value('adapter_serial_no', r.message.serial_no);
						} else if (r.message.scan) {
							frappe.msgprint("Please Scan the Serial No.");
							frm.set_value('nj_adaptor_barcode', '');
							frm.set_value('adapter_serial_no', '');
						}
						frm.refresh_field("nj_adaptor_barcode");
						frm.refresh_field("adapter_serial_no");
						$('[data-fieldname="nj_adaptor_barcode"]').focus();
					}
				},
				error: function(r) {
					frappe.msgprint("Error while scanning Serial No.");
					frm.set_value('adapter_serial_no', '');
					frm.set_value('nj_adaptor_barcode', '');
					frm.refresh_field("adapter_serial_no");
					frm.refresh_field("nj_adaptor_barcode");
					$('[data-fieldname="nj_adaptor_barcode"]').focus();
				}
			});
		}
    },

    barcode: function(frm) {
        if (!window.njScannerAccess.validateSerialBarcode(frm, 'barcode', {raise_exp: false})) return;

        if (frm.doc.barcode) {
            frappe.call({
                method: 'nj_features.nj_features.api.qr_code.generate_and_save_qrcode',
                args: { data: frm.doc.barcode },
                callback: function(r) {
                    console.log("saved qr code",r);
                },
                error: function(r) {
                    frappe.msgprint("Error while generating QR Code.", r);
                }
            });
            
            frappe.call({
                method: "frappe.client.get",
                args: {
                    doctype: "Serial No",
                    name: frm.doc.barcode, 
                },
	                callback: function(r) {
	                    if (r.message) {
	                        $('.primary-action').show();
	                        let serial_no_data = r.message;
	                        console.log("[Laptop Box MRP] Serial No data", {
	                            serial_no: frm.doc.barcode,
	                            item_code: serial_no_data.item_code,
	                            model: serial_no_data.model,
	                        });

	                        frm.set_value("brand", serial_no_data.brand);  
	                        frm.set_value("model", serial_no_data.model);
                        frm.set_value("bios_serial_no", serial_no_data.bios_serial_no);  
                        frm.set_value("warehouse", serial_no_data.warehouse);  
                        frm.set_value("item_code", serial_no_data.item_code);  

                        if (serial_no_data.is_encrypted == 1) {
                            frm.set_value("qr_code_mapping", serial_no_data.qr_code_mapping);
                        }

                        frappe.call({
                            method: "frappe.client.get",
                            args: {
                                doctype: "Item",
                                name: serial_no_data.item_code,  
                            },
	                            callback: function(item_data) {
	                                if (item_data.message) {
	                                    let item = item_data.message;
	                                    console.log("[Laptop Box MRP] Item data", {
	                                        item_code: serial_no_data.item_code,
	                                        attributes: item.attributes,
	                                    });

	                                    if (item.attributes && item.attributes.length > 0) {
                                        let processor_type = '';
                                        let ram_capacity = '';
                                        let storage_capacity = '';
                                        let laptop_mrp_attribute_map = {};

                                        item.attributes.forEach(function(attr) {
                                            if (attr.attribute == "Processor Type" || attr.attribute == "Processor Type1") {
                                                processor_type = attr.attribute_value;
                                                laptop_mrp_attribute_map.processor = attr;
                                            }
                                            if (attr.attribute == "RAM Capacity" || attr.attribute == "RAM") {
                                                ram_capacity = attr.attribute_value;
                                                laptop_mrp_attribute_map.ram = attr;
                                            }
                                            if (attr.attribute == "Storage Capacity") {
                                                storage_capacity = attr.attribute_value;
                                                laptop_mrp_attribute_map.storage = attr;
                                            }
                                        });

	                                        if (serial_no_data.model) {
	                                            laptop_mrp_attribute_map.model = {
	                                                attribute: "Model",
	                                                attribute_value: serial_no_data.model,
	                                            };
	                                        }

	                                        console.log("[Laptop Box MRP] Selected attributes", {
	                                            processor_type: processor_type,
	                                            ram_capacity: ram_capacity,
	                                            storage_capacity: storage_capacity,
	                                            serial_no_model: serial_no_data.model,
	                                            lookup_attributes: Object.values(laptop_mrp_attribute_map),
	                                        });

	                                        frm.set_value("processor_type", processor_type);
                                        frm.set_value("ram_capacity", ram_capacity);
                                        frm.set_value("storage_capacity", storage_capacity);
                                        setLaptopBoxMRPFromAttributes(frm, Object.values(laptop_mrp_attribute_map));
                                    } else {
                                        frappe.throw("No attributes found in the Item Variant Attribute table.");
                                    }
                                } else {
                                    frappe.throw("Item not found for the scanned Serial No.");
                                }
                            }
                        });
                    } else {
                        frm.set_value("barcode", null);
                        frappe.throw(`Serial No <b>'${frm.doc.barcode}'</b> not found. Please select an existing Serial No.`);
                    }
                },
                error: function() {
                    $('.primary-action').hide();
                    frappe.throw("Error fetching data for the barcode.");
                }
            });
        }
    },

    warehouse: function(frm) {
		frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "work_warehouse", function(r) {
			if (!r.work_warehouse) {
				frappe.msgprint(__('Please Set Work Warehouse in Employee Profile: <b>{0}</b>.', [frappe.session.user]));
			}
			if (r.work_warehouse != frm.doc.warehouse) {
				
				let dialog = new frappe.ui.Dialog({
					title: "Confirm Stock Transfer",
					fields: [
						{
							fieldtype: "HTML",
							fieldname: "message",
							options: `Do you want to transfer stock to your Work Warehouse: ${r.work_warehouse}?`
						}
					],
					static:true,
					primary_action_label: "Yes, Transfer", 
					primary_action: function() {
						let material_transfer_items = [{
							'serial_no': frm.doc.barcode,
							'item_code': frm.doc.item_code,
							't_warehouse': r.work_warehouse,
							's_warehouse': frm.doc.warehouse
						}];
		
						let data = {
							"doctype": frm.doc.doctype,
							"t_warehouse": r.work_warehouse,
							"stock_entry_type": "Material Transfer",
							"reference_serial_no": frm.doc.barcode,
							"material_transfer_items": material_transfer_items
						}

						frappe.call({
							method: 'nj_lib.utils.stock_entry.stock_entry_using_nj_lib',
							args: { 'data': JSON.stringify(data) },
							freeze: true,
                            freeze_message: `<div style="text-align: center;">
								<i class="fa fa-spinner fa-spin" style="font-size: 24px;"></i> 
								<br>Transfering Stock... Please Wait
							</div>`,
							error: function(err) { console.log(err); }
						});

						dialog.hide();
                    },
                    secondary_action_label: "Cancel",
                    secondary_action: function() {
                        $('.primary-action').hide()
                        dialog.hide();
                        $("button[data-original-title=Print]").hide();
                    }
                });
                dialog.show();
			} else { $("button[data-original-title=Print]").show(); }
		})
	},

    // before_save: async function(frm) {
    //     if (frm.doc.barcode) {
    //         frappe.validated=true
    //         let serial_item_group = await frappe.db.get_value('Serial No', {'name': frm.doc.barcode}, 'item_group');
            
    //         if(serial_item_group.message && serial_item_group.message.item_group && serial_item_group.message.item_group=='Laptops' || serial_item_group.message.item_group=='Chromebooks') {
    //             console.log("adapter serial no",frm.doc.adapter_serial_no)
    //             if(!frm.doc.adapter_serial_no) {
    //                 frappe.validated=false
    //                 frappe.throw("Please enter Adapter Serial No");
    //             }
    //         } else { return; }
            
    //         await frappe.call({
    //             method:'nj_features.nj_features.api.qr_code.adapter_repacked_serial_no',
    //             args: { "nj_serial_no": frm.doc.barcode },
    //             callback: function(r) {
    //                 if (r.message) {
    //                     if(r.message!=frm.doc.adapter_serial_no) {
    //                         frappe.validated=false
    //                         frappe.throw("Repacked Adapter Serial No: '" + r.message + "' does not match with the scanned Serial No");
    //                     }
    //                 }
    //             }
    //         })
    //     }
    // }
});

const LAPTOP_BOX_SCANNER_MESSAGE = "Please use the scanner to scan barcode.";
const LAPTOP_BOX_SCANNER_MIN_LENGTH = 3;
const LAPTOP_BOX_SCANNER_MAX_SCAN_DURATION = 3000;
const LAPTOP_BOX_SCANNER_MAX_KEY_GAP = 350;
const LAPTOP_BOX_SCANNER_IDLE_DELAY = 600;

function setLaptopBoxSerialNoFromScan(frm, serialNo) {
    // Duplicate Laptop Box serial validation is temporarily disabled to allow reuse.
    // frappe.db.get_value("Laptop Box", { barcode: serialNo }, "name").then(function(r) {
    //     const existingName = r.message && r.message.name;

    //     if (existingName && existingName !== frm.doc.name) {
    //         frappe.msgprint(
    //             __(
    //                 "Serial No <b>{0}</b> is already used in Laptop Box <b>{1}</b>.",
    //                 [serialNo, existingName]
    //             )
    //         );
    //         frm.set_value("nj_barcode", "");
    //         frm.set_value("barcode", "");
    //         frm.refresh_field("nj_barcode");
    //         frm.refresh_field("barcode");
    //         $('[data-fieldname="nj_barcode"]').focus();
    //         return;
    //     }

    //     frm.set_value("barcode", serialNo);
    // });
    window.njScannerAccess.markResolvedSerial(frm, 'barcode', serialNo);
    frm.set_value("barcode", serialNo);
}

function setLaptopBoxMRPFromAttributes(frm, attributes) {
    const laptopMrpAttributes = (attributes || []).filter(function(attr) {
        return attr.attribute && attr.attribute_value;
    });

    console.log("[Laptop Box MRP] Starting laptop_value lookups", laptopMrpAttributes);

    if (!laptopMrpAttributes.length) {
        console.log("[Laptop Box MRP] No attributes available for MRP. Setting laptop_mrp to 0.");
        frm.set_value("laptop_mrp", 0);
        return;
    }

    const laptopValueCalls = laptopMrpAttributes.map(function(attr) {
        return getLaptopBoxAttributeValue(attr).then(function(laptopValue) {
            return flt(laptopValue);
        });
    });

    Promise.all(laptopValueCalls).then(function(values) {
        const totalLaptopValue = values.reduce(function(total, value) {
            return total + value;
        }, 0);
        const laptopMrp = flt(totalLaptopValue * 2.1, getLaptopBoxCurrencyPrecision(frm));

        console.log("[Laptop Box MRP] Final calculation", {
            values: values,
            total_laptop_value: totalLaptopValue,
            multiplier: 2.1,
            laptop_mrp: laptopMrp,
        });

        frm.set_value("laptop_mrp", laptopMrp);
        frm.refresh_field("laptop_mrp");
    }).catch(function(error) {
        console.error("[Laptop Box MRP] Error while calculating laptop_mrp", error);
        frappe.msgprint(__("Unable to calculate Laptop MRP. Please check Item Attribute Value laptop_value setup."));
    });
}

function getLaptopBoxAttributeValue(attr) {
    const parents = getLaptopBoxAttributeParents(attr.attribute);

    return parents.reduce(function(promise, parent) {
        return promise.then(function(value) {
            if (value !== null && value !== undefined) {
                return value;
            }

            return frappe.call({
                method: "nj_features.nj_features.doctype.laptop_box.laptop_box.get_item_attribute_laptop_value",
                args: {
                    parent: parent,
                    attribute_value: attr.attribute_value,
                },
            }).then(function(r) {
                const laptopValue = r.message;
                console.log("[Laptop Box MRP] laptop_value result", {
                    parent: parent,
                    attribute_value: attr.attribute_value,
                    response: r,
                    laptop_value: laptopValue,
                });
                return laptopValue !== null && laptopValue !== undefined ? laptopValue : null;
            });
        });
    }, Promise.resolve(null));
}

function getLaptopBoxAttributeParents(attribute) {
    const parentMap = {
        "Processor Type": ["Processor Type1", "Processor Type"],
        "Processor Type1": ["Processor Type1", "Processor Type"],
        "RAM": ["RAM Capacity", "RAM"],
        "RAM Capacity": ["RAM Capacity", "RAM"],
        "Storage Capacity": ["Storage Capacity"],
        "Model": ["Model"],
    };

    return parentMap[attribute] || [attribute];
}

function getLaptopBoxCurrencyPrecision(frm) {
    const df = frappe.meta.get_docfield(frm.doctype, "laptop_mrp", frm.doc.name);
    return parseInt(df && df.precision, 10) || 2;
}

function setupLaptopBoxScannerOnly(frm, fieldname) {
    if (!window.njScannerAccess || !window.njScannerAccess.isEnabled()) return;
    const field = frm.get_field(fieldname);
    if (!field || !field.$input || frm.doc.docstatus !== 0) return;

    const inputField = field.$input;
    const stateKey = `__laptop_box_scanner_${fieldname}`;
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
        clearLaptopBoxScannerField(frm, fieldname);
        showLaptopBoxScannerMessage(frm, fieldname);
        return false;
    });

    inputField.on(`beforeinput.${stateKey}`, function(event) {
        const inputType = event.originalEvent && event.originalEvent.inputType;
        if (inputType === "insertFromPaste" || inputType === "insertFromDrop") {
            event.preventDefault();
            clearLaptopBoxScannerField(frm, fieldname);
            showLaptopBoxScannerMessage(frm, fieldname);
            return false;
        }
    });

    inputField.on(`drop.${stateKey}`, function(event) {
        event.preventDefault();
        clearLaptopBoxScannerField(frm, fieldname);
        showLaptopBoxScannerMessage(frm, fieldname);
        return false;
    });

    inputField.on(`contextmenu.${stateKey}`, function(event) {
        event.preventDefault();
        showLaptopBoxScannerMessage(frm, fieldname);
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
            clearLaptopBoxScannerField(frm, fieldname);
            showLaptopBoxScannerMessage(frm, fieldname);
            return false;
        }

        if (event.key === "Enter") {
            const value = inputField.val().trim();
            const isScanner = isLaptopBoxScannerBurst(state, value, now);

            window.clearTimeout(state.manualTimer);
            state.manualTimer = null;

            if (!isScanner) {
                event.preventDefault();
                resetLaptopBoxScannerState(state);
                clearLaptopBoxScannerField(frm, fieldname);
                showLaptopBoxScannerMessage(frm, fieldname);
                return false;
            }

            event.preventDefault();
            acceptLaptopBoxScannerValue(frm, fieldname, value, state);
            return false;
        }

        if (isLaptopBoxScannerControlKey(event)) {
            return true;
        }

        if (event.key.length !== 1) {
            return true;
        }

        if (!state.firstKeyTime) {
            state.firstKeyTime = now;
        }

        if (state.lastKeyTime && now - state.lastKeyTime > LAPTOP_BOX_SCANNER_MAX_KEY_GAP) {
            event.preventDefault();
            resetLaptopBoxScannerState(state);
            clearLaptopBoxScannerField(frm, fieldname);
            showLaptopBoxScannerMessage(frm, fieldname);
            return false;
        }

        state.lastKeyTime = now;
        state.chars += event.key;

        window.clearTimeout(state.manualTimer);
        state.manualTimer = window.setTimeout(function() {
            if (state.chars) {
                const value = inputField.val().trim();
                if (isLaptopBoxScannerBurst(state, value)) {
                    acceptLaptopBoxScannerValue(frm, fieldname, value, state);
                } else {
                    resetLaptopBoxScannerState(state);
                    clearLaptopBoxScannerField(frm, fieldname);
                    showLaptopBoxScannerMessage(frm, fieldname);
                }
            }
        }, LAPTOP_BOX_SCANNER_IDLE_DELAY);

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
            clearLaptopBoxScannerField(frm, fieldname);
            showLaptopBoxScannerMessage(frm, fieldname);
        }
    });
}

function isLaptopBoxScannerBurst(state, value, now = Date.now()) {
    if (!value || state.chars.length < LAPTOP_BOX_SCANNER_MIN_LENGTH) return false;

    const lastKeyTime = state.lastKeyTime || now;
    const totalDuration = lastKeyTime - state.firstKeyTime;
    const lastKeyGap = now - lastKeyTime;

    return (
        totalDuration >= 0 &&
        totalDuration <= LAPTOP_BOX_SCANNER_MAX_SCAN_DURATION &&
        lastKeyGap <= LAPTOP_BOX_SCANNER_IDLE_DELAY
    );
}

function acceptLaptopBoxScannerValue(frm, fieldname, value, state) {
    state.validValue = value;
    state.validUntil = Date.now() + 3000;
    resetLaptopBoxScannerTyping(state);

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

function isLaptopBoxValueFromScanner(frm, fieldname) {
    if (!window.njScannerAccess || !window.njScannerAccess.isEnabled()) return true;
    const value = (frm.doc[fieldname] || "").trim();
    const state = frm[`__laptop_box_scanner_${fieldname}`];
    if (!value) return true;

    return Boolean(
        state &&
        state.validValue === value &&
        Date.now() <= state.validUntil
    );
}

function isLaptopBoxDuplicateScan(frm, fieldname) {
    const value = (frm.doc[fieldname] || "").trim();
    if (!value) return false;

    const stateKey = `__laptop_box_scanner_${fieldname}`;
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

function clearLaptopBoxScannerField(frm, fieldname) {
    const state = frm[`__laptop_box_scanner_${fieldname}`];
    if (state) {
        state.suppressManualCheck = true;
        resetLaptopBoxScannerState(state);
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

function showLaptopBoxScannerMessage(frm, fieldname) {
    const stateKey = `__laptop_box_scanner_${fieldname}`;
    const state = frm[stateKey] || {};
    const now = Date.now();

    if (state.lastMessageAt && now - state.lastMessageAt < 1200) return;

    state.lastMessageAt = now;
    frm[stateKey] = state;
    frappe.msgprint(__(LAPTOP_BOX_SCANNER_MESSAGE));
}

function isLaptopBoxScannerControlKey(event) {
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

function resetLaptopBoxScannerState(state) {
    window.clearTimeout(state.manualTimer);
    state.manualTimer = null;
    state.validValue = "";
    state.validUntil = 0;
    resetLaptopBoxScannerTyping(state);
}

function resetLaptopBoxScannerTyping(state) {
    state.chars = "";
    state.firstKeyTime = 0;
    state.lastKeyTime = 0;
}
