(function () {
    "use strict";

    if (window.njScannerAccess) {
        return;
    }

    const SETTING_PARAMETER = "scanner_access";
    const BYPASS_ROLE = "Scanner Access";
    const MESSAGE = __("Please use the scanner to scan barcode.");
    const MIN_LENGTH = 3;
    const MAX_SCAN_DURATION = 3000;
    const MAX_KEY_GAP = 350;
    const IDLE_DELAY = 600;
    const CACHE_KEY = "nj_scanner_access_enabled";

    const TARGET_DOCTYPES = new Set([
        "Stock Movement",
        "Rack Pick",
        "Purchase Order",
        "Purchase Receipt",
        "Purchase Invoice",
        "Sales Order",
        "Sales Invoice",
        "Delivery Note",
        "Stock Entry",
        "Material Request",
        "Machine Part Changes",
    ]);

    // These DocTypes already contain their own dedicated scanner handlers.
    // Their setup functions check window.njScannerAccess.isEnabled();
    // the generic document listeners must not be added a second time to them.
    const LEGACY_SCANNER_DOCTYPES = new Set([
        "Auto Stock Entry",
        "Dispatch Security Checkpoints",
        "Laptop Box",
        "NJ Audit",
        "NJQCA",
        "Kitting",
        "Non Serialized Quality Inspection",
        "NJ Quality Inspection",
    ]);

    let enabled = false;
    let loaded = false;
    let loadPromise = null;
    let lastMessageAt = 0;
    const states = new WeakMap();

    // Initialize from localStorage cache synchronously to avoid race condition on form render
    try {
        const cached = localStorage.getItem(CACHE_KEY);
        if (cached === "1") {
            enabled = true;
        } else if (cached === "0") {
            enabled = false;
        }
    } catch (e) {}

    function hasScannerBypassRole() {
        if (!window.frappe) return false;
        try {
            if (frappe.user && typeof frappe.user.has_role === "function") {
                if (frappe.user.has_role(BYPASS_ROLE)) {
                    return true;
                }
            }
            if (Array.isArray(frappe.user_roles) && frappe.user_roles.includes(BYPASS_ROLE)) {
                return true;
            }
            if (frappe.boot && frappe.boot.user && Array.isArray(frappe.boot.user.roles)) {
                if (frappe.boot.user.roles.includes(BYPASS_ROLE)) {
                    return true;
                }
            }
        } catch (e) {
            console.warn("[njScannerAccess] Failed to check bypass role:", e);
        }
        return false;
    }

    function isScannerAccessActive() {
        // Report and list views accept typed, pasted, and dropped filter values.
        const route = window.frappe && typeof frappe.get_route === "function"
            ? frappe.get_route() : [];
        if (route.length > 0) {
            const routeType = (route[0] || "").toLowerCase();
            if (["list", "query-report", "workspaces", "tree", "kanban", "dashboard-view", "print"].includes(routeType)) {
                return false;
            }
        }
        // If user has "Scanner Access" role, bypass all scanner restrictions
        if (hasScannerBypassRole()) {
            return false;
        }
        return enabled;
    }

    function showMessage() {
        const now = Date.now();
        if (now - lastMessageAt < 1200) return;
        lastMessageAt = now;

        // Use frappe.msgprint modal popup dialog (exact match with auto_stock_entry)
        if (window.frappe && frappe.msgprint) {
            frappe.msgprint(__(MESSAGE));
        } else if (window.frappe && frappe.show_alert) {
            frappe.show_alert(
                {
                    message: MESSAGE,
                    indicator: "orange",
                },
                3
            );
        }

        if (window.frappe && frappe.utils && frappe.utils.play_sound) {
            try {
                frappe.utils.play_sound("error");
            } catch (e) {}
        }
    }

    function getTargetDoctype(element) {
        const route = window.frappe && typeof frappe.get_route === "function" ? frappe.get_route() : [];
        if (route && route[0] === "Form" && route[1]) {
            return route[1];
        }
        if (element && element.closest) {
            const formElem = element.closest(".form-page, .form-layout, .page-form, [data-page-route^='Form/']");
            if (formElem) {
                const docElem = formElem.closest("[data-doctype]");
                if (docElem) {
                    const dt = docElem.getAttribute("data-doctype");
                    if (dt) return dt;
                }
            }
        }
        if (window.cur_frm && cur_frm.doctype && route && route[0] === "Form") {
            return cur_frm.doctype;
        }
        return "";
    }

    function getFieldname(element) {
        if (!element) return "";
        let fn = element.getAttribute("data-fieldname");
        if (fn) return fn.trim().toLowerCase();

        if (element.closest) {
            const parentControl = element.closest("[data-fieldname]");
            if (parentControl) {
                fn = parentControl.getAttribute("data-fieldname");
                if (fn) return fn.trim().toLowerCase();
            }
        }
        return "";
    }

    function isBarcodeField(doctype, fieldname) {
        if (!fieldname) return false;
        const fn = fieldname.toLowerCase();

        if (doctype === "NJ Quality Inspection") {
            return fn === "encrypted_serial_no";
        }

        if (
            fn === "scan_barcode" ||
            fn === "scan_barcodes" ||
            fn === "barcode" ||
            fn.endsWith("_barcode") ||
            fn.includes("barcode")
        ) {
            return true;
        }

        return false;
    }

    function getBarcodeInput(element) {
        if (!element) return null;
        if (
            element instanceof HTMLInputElement ||
            element instanceof HTMLTextAreaElement
        ) {
            return element;
        }
        if (element.closest) {
            const control = element.closest("[data-fieldname]");
            if (control) {
                const input = control.querySelector("input, textarea");
                if (input) return input;
            }
        }
        return null;
    }

    function isSkippedField(input, doctype, fieldname) {
        const dt = (doctype || (input && getTargetDoctype(input)) || (window.cur_frm && cur_frm.doctype) || "").trim();
        const fn = (fieldname || (input && getFieldname(input)) || "").trim().toLowerCase();

        // In Stock Movement racking workflow, allow copy/paste, typing, and standard inputs
        // for the warehouse field in the racking popup dialog.
        if (dt === "Stock Movement") {
            const transferStatus = (window.cur_frm && cur_frm.doc && cur_frm.doc.transfer_status)
                ? String(cur_frm.doc.transfer_status).toLowerCase()
                : "";
            const isModal = Boolean(input && input.closest && input.closest(".modal, .modal-dialog"));

            if (fn === "t_warehouse" || (isModal && (fn === "warehouse" || fn === "t_warehouse"))) {
                if (!transferStatus || transferStatus === "racking" || isModal) {
                    return true;
                }
            }
        }

        return false;
    }

    function isActualBarcodeInput(target) {
        if (!isScannerAccessActive()) {
            return false;
        }

        const input = getBarcodeInput(target);
        if (!input) {
            return false;
        }

        if (input.readOnly || input.disabled) {
            return false;
        }

        // Never intercept inputs inside filters, search bars, lists, reports, or headers
        if (input.closest && input.closest(".frappe-list, .standard-filter-section, .filter-box, .filter-selector, .list-filters, .filter-area, .search-box, .awesomplete, .search-dialog, .report-filter-area, .report-view, .page-head, .desk-searchbar, .navbar-search")) {
            return false;
        }

        const doctype = getTargetDoctype(input);

        // Skip legacy DocTypes that have their own dedicated scanner handlers
        if (doctype && LEGACY_SCANNER_DOCTYPES.has(doctype)) {
            return false;
        }

        const fieldname = getFieldname(input);
        if (!fieldname) return false;

        // Skip fields explicitly exempted from scanner access restrictions
        if (isSkippedField(input, doctype, fieldname)) {
            return false;
        }

        // If in target doctypes
        if (doctype && TARGET_DOCTYPES.has(doctype)) {
            return isBarcodeField(doctype, fieldname);
        }

        // Universal check: any field named scan_barcode, scan_barcodes, or ending in _barcode
        if (
            fieldname === "scan_barcode" ||
            fieldname === "scan_barcodes" ||
            fieldname === "barcode" ||
            fieldname.endsWith("_barcode")
        ) {
            return true;
        }

        return false;
    }

    function clearInput(input) {
        if (!input) return;
        input.value = "";

        try {
            $(input).val("").trigger("input").trigger("change");
        } catch (e) {}

        input.dispatchEvent(
            new Event("input", {
                bubbles: true,
            })
        );

        input.dispatchEvent(
            new Event("change", {
                bubbles: true,
            })
        );

        try {
            const doctype = getTargetDoctype(input);
            const fieldname = getFieldname(input);
            if (window.cur_frm && cur_frm.doctype === doctype && fieldname) {
                if (cur_frm.fields_dict && cur_frm.fields_dict[fieldname]) {
                    cur_frm.set_value(fieldname, "");
                }
            }
        } catch (e) {}
    }

    function stateFor(input) {
        if (!states.has(input)) {
            states.set(input, {
                chars: "",
                firstKeyTime: 0,
                lastKeyTime: 0,
                timer: null,
                accepted: false,
            });
        }

        return states.get(input);
    }

    function resetState(state) {
        if (!state) return;
        if (state.timer) {
            window.clearTimeout(state.timer);
            state.timer = null;
        }

        state.chars = "";
        state.firstKeyTime = 0;
        state.lastKeyTime = 0;
        state.accepted = false;
    }

    function isScannerBurst(state, value, now) {
        if (!state || !state.firstKeyTime) return false;
        const end = now || state.lastKeyTime || Date.now();
        const duration = end - state.firstKeyTime;
        const val = (value || "").trim();

        return (
            val.length >= MIN_LENGTH &&
            state.chars.length >= MIN_LENGTH &&
            duration >= 0 &&
            duration <= MAX_SCAN_DURATION
        );
    }

    function rejectInput(event, input, state) {
        if (event) {
            try {
                event.preventDefault();
                event.stopImmediatePropagation();
            } catch (e) {}
        }

        resetState(state);
        clearInput(input);
        showMessage();
    }

    function isControlKey(event) {
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
            ].includes(event.key)
        );
    }

    function installHandlers() {
        if (window.__njScannerAccessHandlersInstalled) return;
        window.__njScannerAccessHandlersInstalled = true;

        // Block ContextMenu (Right-click) and show popup modal dialog
        document.addEventListener(
            "contextmenu",
            function (event) {
                if (!isScannerAccessActive()) return;
                const input = getBarcodeInput(event.target);
                if (!input || !isActualBarcodeInput(input)) {
                    return;
                }

                event.preventDefault();
                event.stopImmediatePropagation();

                showMessage();
            },
            true
        );

        // Block Paste and Drop
        ["paste", "drop"].forEach((eventName) => {
            document.addEventListener(
                eventName,
                function (event) {
                    if (!isScannerAccessActive()) return;
                    const input = getBarcodeInput(event.target);
                    if (!input || !isActualBarcodeInput(input)) {
                        return;
                    }

                    event.preventDefault();
                    event.stopImmediatePropagation();

                    clearInput(input);
                    showMessage();
                },
                true
            );
        });

        // Block DragOver to prevent dropping
        document.addEventListener(
            "dragover",
            function (event) {
                if (!isScannerAccessActive()) return;
                const input = getBarcodeInput(event.target);
                if (!input || !isActualBarcodeInput(input)) {
                    return;
                }
                event.preventDefault();
            },
            true
        );

        // Block input via paste or drop before input occurs
        document.addEventListener(
            "beforeinput",
            function (event) {
                if (!isScannerAccessActive()) return;
                const input = getBarcodeInput(event.target);
                if (!input || !isActualBarcodeInput(input)) {
                    return;
                }

                if (
                    event.inputType === "insertFromPaste" ||
                    event.inputType === "insertFromDrop"
                ) {
                    event.preventDefault();
                    event.stopImmediatePropagation();

                    clearInput(input);
                    showMessage();
                }
            },
            true
        );

        // Handle typing and scanner bursts
        document.addEventListener(
            "keydown",
            function (event) {
                if (!isScannerAccessActive()) return;
                const input = getBarcodeInput(event.target);
                if (!input || !isActualBarcodeInput(input)) {
                    return;
                }

                const state = stateFor(input);
                const now = Date.now();

                // Block Ctrl+V / Cmd+V
                if (
                    (event.ctrlKey || event.metaKey) &&
                    event.key &&
                    event.key.toLowerCase() === "v"
                ) {
                    rejectInput(event, input, state);
                    return;
                }

                // Handle Enter (scanner completion or manual enter)
                if (event.key === "Enter") {
                    if (!isScannerBurst(state, input.value, now)) {
                        rejectInput(event, input, state);
                        return;
                    }

                    state.accepted = true;
                    if (state.timer) {
                        window.clearTimeout(state.timer);
                        state.timer = null;
                    }

                    window.setTimeout(() => {
                        resetState(state);
                    }, 100);

                    // Allow normal Enter propagation so Frappe triggers the field change
                    return;
                }

                // Allow Backspace / Delete
                if (event.key === "Backspace" || event.key === "Delete") {
                    resetState(state);
                    return;
                }

                // Allow other control navigation keys
                if (isControlKey(event)) {
                    return;
                }

                // Ignore non-character keys (e.g. CapsLock, F1-F12)
                if (event.key.length !== 1) {
                    return;
                }

                // If key gap exceeds threshold, it is slow/manual typing: reject
                if (
                    state.lastKeyTime &&
                    now - state.lastKeyTime > MAX_KEY_GAP
                ) {
                    rejectInput(event, input, state);
                    return;
                }

                if (!state.firstKeyTime) {
                    state.firstKeyTime = now;
                }

                state.lastKeyTime = now;
                state.chars += event.key;

                if (state.timer) {
                    window.clearTimeout(state.timer);
                }

                // If scanner does not send Enter, accept after idle delay
                state.timer = window.setTimeout(function () {
                    if (isScannerBurst(state, input.value)) {
                        state.accepted = true;

                        try {
                            $(input).trigger("change");
                        } catch (e) {}

                        input.dispatchEvent(
                            new Event("change", {
                                bubbles: true,
                            })
                        );

                        resetState(state);
                    } else if (!state.accepted && input.value) {
                        rejectInput(null, input, state);
                    }
                }, IDLE_DELAY);
            },
            true
        );

        // Catch bypasses where value appeared without keystrokes
        document.addEventListener(
            "input",
            function (event) {
                if (!isScannerAccessActive()) return;
                const input = getBarcodeInput(event.target);
                if (!input || !isActualBarcodeInput(input)) {
                    return;
                }

                const state = stateFor(input);
                if (state.accepted) {
                    return;
                }

                // Value exists but no keydown recorded -> paste/autofill bypass
                if (input.value && !state.chars) {
                    rejectInput(event, input, state);
                }
            },
            true
        );
    }

    function updateSetting(val) {
        const newEnabled = (val === "1" || val === 1 || String(val).trim() === "1");
        enabled = newEnabled;
        loaded = true;
        try {
            localStorage.setItem(CACHE_KEY, enabled ? "1" : "0");
        } catch (e) {}
        return enabled;
    }

    function loadSetting() {
        if (!window.frappe || !frappe.db || !frappe.db.get_value) {
            return Promise.resolve(isScannerAccessActive());
        }

        loadPromise = frappe.db
            .get_value("NJ Settings", { parameter: SETTING_PARAMETER }, "value")
            .then(function (r) {
                const val = (r && r.message && r.message.value !== undefined)
                    ? r.message.value
                    : (r && r.value !== undefined ? r.value : null);
                updateSetting(val);
                return isScannerAccessActive();
            })
            .catch(function (err) {
                console.warn("[njScannerAccess] Failed to fetch setting:", err);
                // Fail open if setting cannot be read
                updateSetting(null);
                return isScannerAccessActive();
            });

        return loadPromise;
    }

    // Some forms copy a resolved Serial No into their barcode field. Remember
    // that value so the field handler can continue without treating it as a
    // fresh scan of the unencrypted label.
    function markResolvedSerial(frm, fieldname, serialNo) {
        frm[`__nj_verified_barcode_${fieldname}`] = {
            serialNo: serialNo,
            expiresAt: Date.now() + 1000,
        };
    }

    function validateSerialBarcode(frm, fieldname, options) {
        const value = frm.doc[fieldname];
        const marker = `__nj_verified_barcode_${fieldname}`;
        if (!value) {
            frm[marker] = null;
            return true;
        }
        if (frm[marker]?.serialNo === value && frm[marker].expiresAt >= Date.now()) {
            frm[marker] = null;
            return true;
        }

        frappe.call({
            method: "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
            args: { search_value: value, raise_exp: options?.raise_exp ?? true },
            callback: function (r) {
                const serialNo = r.message?.serial_no;
                if (!serialNo) {
                    frm.set_value(fieldname, "");
                    frappe.msgprint(__("Please scan a valid Serial No barcode."));
                    return;
                }
                markResolvedSerial(frm, fieldname, serialNo);
                frm.doc[fieldname] = serialNo;
                frm.refresh_field(fieldname);
                frm.trigger(fieldname);
            },
            error: function () {
                frm.set_value(fieldname, "");
            },
        });
        return false;
    }

    // Expose the global API immediately
    window.njScannerAccess = {
        markResolvedSerial: markResolvedSerial,
        validateSerialBarcode: validateSerialBarcode,
        isEnabled: function () {
            return isScannerAccessActive();
        },
        hasBypassRole: function () {
            return hasScannerBypassRole();
        },
        isLoaded: function () {
            return loaded;
        },
        isFieldSkipped: function (doctype, fieldname) {
            return isSkippedField(null, doctype, fieldname);
        },
        isFieldGuarded: function (doctype, fieldname) {
            if (!isScannerAccessActive()) return false;
            if (!fieldname) return false;
            if (isSkippedField(null, doctype, fieldname)) return false;
            if (doctype === "NJ Quality Inspection") {
                return fieldname.toLowerCase() === "encrypted_serial_no";
            }
            if (doctype && LEGACY_SCANNER_DOCTYPES.has(doctype)) return false;
            if (doctype && TARGET_DOCTYPES.has(doctype)) {
                return isBarcodeField(doctype, fieldname);
            }
            return (
                fieldname === "scan_barcode" ||
                fieldname === "scan_barcodes" ||
                fieldname === "barcode" ||
                fieldname.endsWith("_barcode")
            );
        },
        refresh: function () {
            return loadSetting();
        },
        ready: function () {
            return loadPromise || Promise.resolve(isScannerAccessActive());
        },
    };

    // Install document event listeners
    installHandlers();

    // Load setting when Frappe is ready
    if (window.frappe) {
        if (frappe.ready) {
            frappe.ready(function () {
                loadSetting();
            });
        } else {
            loadSetting();
        }

        // Re-check on route change to keep setting in sync
        if (frappe.router && frappe.router.on) {
            frappe.router.on("change", function () {
                loadSetting();
            });
        }
    }

    if (window.$ && $(document).on) {
        $(document).on("page-change", function () {
            loadSetting();
        });
    }
})();
