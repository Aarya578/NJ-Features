function extend_listview_settings(doctype, custom_settings) {
    const existing = frappe.listview_settings[doctype] || {};

    Object.keys(custom_settings).forEach(key => {
        const original = existing[key];
        const custom = custom_settings[key];

        if (typeof original === 'function' && typeof custom === 'function') {
            existing[key] = function(...args) {
                original.apply(this, args);
                custom.apply(this, args);
            };
        } else {
            existing[key] = custom;
        }
    });

    frappe.listview_settings[doctype] = existing;
}

document.addEventListener('keydown', function(event) {
    if ((event.ctrlKey && event.shiftKey && (event.key === 'I' || event.key === 'J')) || event.key === 'F12') {
        event.preventDefault(); 
    }
});

$(document).ready(function() {
    $(document.body).addClass('full-width');
    localStorage.setItem('container_fullwidth', true);
    
});

frappe.listview_settings['Non Compliance'] = {
    onload() {
        $('.col-lg-2.layout-side-section').hide();
    }
};

frappe.ui.form.on('Serial No', {
    refresh() {
        $('.col-lg-2.layout-side-section').hide();
    }
});

frappe.ui.form.on('User', {
    refresh() {
        $('.col-lg-2.layout-side-section').hide();
        if (!frappe.user.has_role('Developer') || !frappe.user.has_role('User Access Modification')) {    

            cur_frm.set_df_property('sb1', 'hidden', 1);
            cur_frm.set_df_property('roles', 'hidden', 1);
            cur_frm.set_df_property('roles_html', 'hidden', 1);
            cur_frm.set_df_property('api_access', 'hidden', 1);
            cur_frm.set_df_property('role_profile_name', 'hidden', 1);
            cur_frm.refresh_field('sb1');
            cur_frm.refresh_field('roles');
            cur_frm.refresh_field('roles_html');
            cur_frm.refresh_field('api_access');
            cur_frm.refresh_field('sb_allow_modules');
            cur_frm.refresh_field('role_profile_name');
        
            cur_frm.set_df_property('restrict_ip', 'read_only', 1);
            cur_frm.set_df_property('simultaneous_sessions', 'read_only', 1);

            cur_frm.refresh_field('restrict_ip');
            cur_frm.refresh_field('simultaneous_sessions');
        }
    }
});

frappe.ui.form.on('Department', {
    refresh() {
        $('.col-lg-2.layout-side-section').hide();
    }
});

frappe.listview_settings['Prepared Report'] = {
    onload: function(listview) {
        filters: [['created_by', '=', frappe.session.user_email]],
        listview.refresh();
        $('.col-lg-2.layout-side-section').hide();
    }
};

frappe.provide('frappe.ui.misc');
frappe.ui.misc.about = function() {
    if (!frappe.ui.misc.about_dialog) {
        var d = new frappe.ui.Dialog({title: __('NewJaisa Technologies Limited')});

        var aboutContent = "<div>\
            <p>"+__("Follow us")+"</p>\
            <p><i class='fa fa-globe fa-fw'></i>\
                Website: <a href='https://newjaisa.com' target='_blank'>https://newjaisa.com</a></p>\
            <p><i class='fa fa-instagram fa-fw'></i>\
                Instagram: <a href='https://www.instagram.com/newjaisa/?igshid=MzRlODBiNWFlZA' target='_blank'>https://www.instagram.com/newjaisa</a></p>\
            <p><i class='fa fa-linkedin fa-fw'></i>\
                Linkedin: <a href='https://in.linkedin.com/company/newjaisa' target='_blank'>https://in.linkedin.com/company/newjaisa</a></p>\
            <p><i class='fa fa-facebook fa-fw'></i>\
                Facebook: <a href='https://www.facebook.com/people/NewJaisa-Technologies/100077760237912/' target='_blank'>https://www.facebook.com/people/NewJaisa-Technologies</a></p>\
            <hr>";

        if (frappe.user.has_role('Administrator') || frappe.user.has_role('Developer')) {
            aboutContent += "<h4>Installed Apps</h4>\
            <div id='about-app-versions'>Loading versions...</div>\
            <hr>";
        }

        aboutContent += "<p class='text-muted'>&copy; NewJaisa Technologies Limited </p>\
            </div>";

        $(d.body).html(repl(aboutContent, frappe.app));

        frappe.ui.misc.about_dialog = d;

        frappe.ui.misc.about_dialog.on_page_show = function() {
            if(!frappe.versions) {
                frappe.call({
                    method: "frappe.utils.change_log.get_versions",
                    callback: function(r) {
                        show_versions(r.message);
                    }
                })
            } else {
                show_versions(frappe.versions);
            }
        };

        var show_versions = function(versions) {
            var $wrap = $("#about-app-versions").empty();
            $.each(Object.keys(versions).sort(), function(i, key) {
                var v = versions[key];
                if(v.branch) {
                    var text = $.format('<p><b>{0}:</b> v{1} ({2})<br></p>',
                        [v.title, v.branch_version || v.version, v.branch])
                } else {
                    var text = $.format('<p><b>{0}:</b> v{1}<br></p>',
                        [v.title, v.version])
                }
                $(text).appendTo($wrap);
            });

            frappe.versions = versions;
        }
    }

    frappe.ui.misc.about_dialog.show();
}

frappe.provide('frappe.user');

$.extend(frappe.user, {
    get_role_profile: function(user_role_profile = null) {
        return new Promise(function(resolve, reject) {
            frappe.db.get_value('Employee', {'user_id': frappe.session.user, 'status': 'Active'}, 'role_profile', function(result) {
                if (result && result.role_profile !== undefined) {

                    if (user_role_profile !== null) {
                        if (result.role_profile === user_role_profile) {
                            resolve(true);
                        } else { resolve(false); }
                    } else { resolve(result.role_profile); }
                } else { resolve(null); }
            });
        });
    }
});

// Zoom function in scanner
frappe.provide("frappe.ui");

frappe.ui.Scanner = class Scanner {
	constructor(options) {
		this.dialog = null;
		this.handler = null;
		this.options = options;
		this.is_alive = false;
		this.scan_area_id = null;

		this.zoomStep = 0.2;
		this.lastZoom = 1.0;
		this.maxZoom = 10.0;
		this.minZoom = 1.0;

		this.autoZooming = false;
		this.autoZoomAllowed = true;
		this.zoomUnsupportedAlertShown = false;

		if (!("multiple" in this.options)) {
			this.options.multiple = false;
		}

		if (options.container) {
			this.$scan_area = $(options.container);
			this.scan_area_id = frappe.dom.set_unique_id(this.$scan_area);
		}

		if (options.dialog) {
			this.dialog = this.make_dialog();
			this.dialog.show();
		}
	}

	make_dialog() {
		let me = this;
		let dialog = new frappe.ui.Dialog({
			title: __("Scan QR Code"),
			fields: [{ fieldtype: "HTML", fieldname: "scan_area" }],
			on_page_show() {
				me.$scan_area = dialog.get_field("scan_area").$wrapper;
				me.$scan_area.addClass("barcode-scanner");
				me.scan_area_id = frappe.dom.set_unique_id(me.$scan_area);
				me.scan();
			},
			on_hide() {
				me.stop_scan();
			}
		});
		return dialog;
	}

	scan() { this.load_lib().then(() => this.start_scan()); }

	start_scan() {
		if (!this.handler) { this.handler = new Html5Qrcode(this.scan_area_id); }

		const config = {
			fps: 10,
			qrbox: 250,
			experimentalFeatures: { useBarCodeDetectorIfSupported: true },
			rememberLastUsedCamera: true,
			supportedScanTypes: window.Html5QrcodeScanType
				? [Html5QrcodeScanType.SCAN_TYPE_CAMERA]
				: undefined,
			videoConstraints: {
				facingMode: "environment",
				focusMode: "continuous"
			}
		};

		this.handler
			.start(
				{ facingMode: "environment", focusMode: "continuous" },
				config,
				(decodedText, decodedResult) => {
					this.autoZooming = false;
					this.autoZoomAllowed = false;

					if (this.options.on_scan) {
						try {
							this.options.on_scan(decodedResult);
						} catch (err) {
							frappe.show_alert({ message: err, indicator: "red" }, 2);
						}
					}

					if (!this.options.multiple) {
						this.stop_scan();
						this.hide_dialog();
					}
				},
				(errorMessage) => {
					if (
						this.autoZoomAllowed &&
						!this.autoZooming &&
						errorMessage.includes("No MultiFormat Readers")
					) {
						this.autoZooming = true;
						this.tryZoomUntilDecode();
					}
				}
			)
			.then(() => {
				this.is_alive = true;
				this.enablePinchZoom(`#${this.scan_area_id}`);
			})
			.catch((err) => {
				this.is_alive = false;
				this.hide_dialog();
				frappe.show_alert({
					message: "Scanner error: " + err,
					indicator: "red"
				}, 2);
			});
	}

	async tryZoomUntilDecode() {
		const interval = 1000;
		while (this.autoZooming && this.autoZoomAllowed && this.lastZoom < this.maxZoom) {
			await new Promise((r) => setTimeout(r, interval));
			this.lastZoom = Math.min(this.lastZoom + this.zoomStep, this.maxZoom);
			this.applyZoom(this.lastZoom);
		}
		this.autoZooming = false;
	}

	applyZoom(zoomLevel) {
		const video = document.querySelector(`#${this.scan_area_id} video`);
		if (!video || !video.srcObject) return;

		const track = video.srcObject.getVideoTracks()[0];
		if (track && typeof track.getCapabilities === "function") {
			const capabilities = track.getCapabilities();

			if (!capabilities.zoom) {
				if (!this.zoomUnsupportedAlertShown) {
					this.zoomUnsupportedAlertShown = true;
					frappe.show_alert({
						message: "Zoom not supported on this device.",
						indicator: "red"
					}, 10);
				}
				return;
			}

			track
				.applyConstraints({ advanced: [{ zoom: zoomLevel }] })
				.catch((err) =>
					frappe.show_alert({
						message: "Zoom failed: " + err,
						indicator: "red"
					}, 2)
				);
		}
	}

	enablePinchZoom(selector) {
		const el = document.querySelector(selector);
		if (!el) return;

		let evCache = [];
		let prevDiff = -1;

		el.style.touchAction = "none";

		el.onpointerdown = (ev) => { evCache.push(ev); };

		el.onpointermove = (ev) => {
			const index = evCache.findIndex((e) => e.pointerId === ev.pointerId);
			if (index >= 0) evCache[index] = ev;

			if (evCache.length === 2) {
				this.autoZoomAllowed = false;
				this.autoZooming = false;

				const dx = evCache[0].clientX - evCache[1].clientX;
				const dy = evCache[0].clientY - evCache[1].clientY;
				const curDiff = Math.sqrt(dx * dx + dy * dy);

				if (prevDiff > 0) {
					if (curDiff > prevDiff) {
						this.lastZoom = Math.min(this.lastZoom + this.zoomStep, this.maxZoom);
						this.applyZoom(this.lastZoom);
					} else if (curDiff < prevDiff) {
						this.lastZoom = Math.max(this.lastZoom - this.zoomStep, this.minZoom);
						this.applyZoom(this.lastZoom);
					}
				}
				prevDiff = curDiff;
			}
		};

		const clearCache = (ev) => {
			evCache = evCache.filter((e) => e.pointerId !== ev.pointerId);
			if (evCache.length < 2) prevDiff = -1;
		};

		el.onpointerup = clearCache;
		el.onpointercancel = clearCache;
		el.onpointerout = clearCache;
		el.onpointerleave = clearCache;
	}

	stop_scan() {
		if (this.handler && this.is_alive) {
			this.handler.stop().then(() => {
				this.is_alive = false;
				if (this.$scan_area) {
					this.$scan_area.empty();
				}
				this.hide_dialog();
			});
		}
	}

	hide_dialog() { this.dialog && this.dialog.hide(); }

	load_lib() {
		return new Promise((resolve) => {
			if (typeof Html5QrcodeScanType === "undefined") {
				window.Html5QrcodeScanType = {
					SCAN_TYPE_CAMERA: 2,
					SCAN_TYPE_FILE: 1
				};
			}

			frappe.require(
				"/assets/frappe/node_modules/html5-qrcode/dist/html5-qrcode.min.js",
				() => { resolve(); }
			);
		});
	}
};

document.addEventListener("DOMContentLoaded", function () {

    frappe.call({
        method: "frappe.client.get_value",
        args: {
            doctype: "NJ Settings", // or your actual doctype name if it's not NJ Settings
            filters: {
                parameter: "allow_department_check",
                module: "HR",
                doc_type: "Department"
            },
            fieldname: "value"
        },
        callback: function(r) {
            if (!r.exc && r.message) {
                const allowCheck = cint(r.message.value);
                if (allowCheck === 1) {
                    show_login_popup();
                }
            }
        }
    });

    if (document.getElementById("network-indicator")) return;

    const html = `
        <div id="network-indicator" style="
            position: fixed;
            bottom: 20px;
            left: 20px;
            background: rgba(0, 0, 0, 0.85);
            color: white;
            padding: 12px 16px;
            border-radius: 8px;
            font-family: sans-serif;
            font-size: 13px;
            z-index: 9999;
            display: flex;
            flex-direction: column;
            gap: 6px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.4);
            cursor: grab;
        ">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span id="network-icon">📶</span>
                <span id="network-text">Checking network...</span>
            </div>
            <div id="network-extra" style="font-size: 12px; color: #ccc;"></div>
            <button id="run-speed-test" style="
                margin-top: 4px;
                padding: 4px 8px;
                background: #2196F3;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                cursor: pointer;
            ">Run Speed Test</button>
        </div>
    `;

    const container = document.createElement("div");
    container.innerHTML = html;
    document.body.appendChild(container);

    const css = `
        .status-good {
            color: #4CAF50;
            font-weight: bold;
        }
        .status-warning {
            color: #FF9800;
            font-weight: bold;
        }
        .status-bad {
            color: #F44336;
            font-weight: bold;
        }
        .status-unknown {
            color: #9E9E9E;
            font-style: italic;
        }
    `;
    const style = document.createElement("style");
    style.innerText = css;
    document.head.appendChild(style);

    function updateNetworkIndicator() {
        const icon = document.getElementById("network-icon");
        const text = document.getElementById("network-text");

        if (!navigator.onLine) {
            icon.textContent = "❌";
            icon.className = "status-bad";
            text.textContent = "Offline";
            return;
        }

        if (!("connection" in navigator)) {
            icon.textContent = "❓";
            icon.className = "status-unknown";
            text.textContent = "Network info not supported";
            return;
        }

        const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
        const type = conn.effectiveType || "unknown";
        const downlink = conn.downlink || 0;

        let statusClass = "status-unknown";
        let statusIcon = "❓";
        let qualityLabel = "Unknown";

        if (type === "slow-2g" || type === "2g") {
            statusClass = "status-bad";
            statusIcon = "🛑";
            qualityLabel = "Very Poor";
        } else if (type === "3g") {
            if (downlink < 0.5) {
                statusClass = "status-bad";
                statusIcon = "🛑";
                qualityLabel = "Poor 3G";
            } else if (downlink < 1.5) {
                statusClass = "status-warning";
                statusIcon = "⚠️";
                qualityLabel = "Moderate 3G";
            } else {
                statusClass = "status-good";
                statusIcon = "📶";
                qualityLabel = "Good 3G";
            }
        } else if (type === "4g") {
            if (downlink < 1) {
                statusClass = "status-bad";
                statusIcon = "⚠️";
                qualityLabel = "Poor (Slow 4G)";
            } else if (downlink < 5) {
                statusClass = "status-warning";
                statusIcon = "⚠️";
                qualityLabel = "Moderate 4G";
            } else {
                statusClass = "status-good";
                statusIcon = "📶";
                qualityLabel = "Good 4G";
            }
        } else if (type === "5g") {
            if (downlink < 10) {
                statusClass = "status-warning";
                statusIcon = "⚠️";
                qualityLabel = "Moderate 5G";
            } else {
                statusClass = "status-good";
                statusIcon = "🚀";
                qualityLabel = "Excellent 5G";
            }
        }

        icon.textContent = statusIcon;
        icon.className = statusClass;
        text.textContent = `${type.toUpperCase()} - ${downlink.toFixed(1)} Mbps (${qualityLabel})`;
    }

    async function runSpeedTest() {
        const output = document.getElementById("network-extra");
        const testUrl = "https://localnjpulse.newjaisa.com/files/test_file"; // Change this to your actual test file URL
        const start = performance.now();

        output.textContent = "Running speed test...";

        try {
            const response = await fetch(testUrl, { cache: "no-cache" });
            const reader = response.body.getReader();
            let bytesReceived = 0;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                bytesReceived += value.length;
            }

            const end = performance.now();
            const duration = (end - start) / 1000;
            const bits = bytesReceived * 8;
            const mbps = (bits / duration / 1024 / 1024).toFixed(2);

            output.textContent = `Speed Test: ${mbps} Mbps`;
        } catch (e) {
            output.textContent = "Speed test failed.";
        }
    }

    document.getElementById("run-speed-test").addEventListener("click", runSpeedTest);

    updateNetworkIndicator();
    setInterval(updateNetworkIndicator, 10000);
    window.addEventListener("online", updateNetworkIndicator);
    window.addEventListener("offline", updateNetworkIndicator);

    // === Draggable logic ===
    const dragElement = document.getElementById("network-indicator");
    let isDragging = false;
    let offsetX = 0;
    let offsetY = 0;

    dragElement.addEventListener("mousedown", function (e) {
        isDragging = true;
        offsetX = e.clientX - dragElement.getBoundingClientRect().left;
        offsetY = e.clientY - dragElement.getBoundingClientRect().top;
        dragElement.style.cursor = "move";
    });

    document.addEventListener("mousemove", function (e) {
        if (isDragging) {
            dragElement.style.left = `${e.clientX - offsetX}px`;
            dragElement.style.top = `${e.clientY - offsetY}px`;
            dragElement.style.bottom = "auto";
            dragElement.style.right = "auto";
        }
    });

    document.addEventListener("mouseup", function () {
        isDragging = false;
        dragElement.style.cursor = "grab";
    });
});


function show_login_verification_popup(user) {
    // Create overlay to freeze background
    const overlay = document.createElement("div");
    overlay.id = "login-block-overlay";
    overlay.style.position = "fixed";
    overlay.style.top = "0";
    overlay.style.left = "0";
    overlay.style.width = "100vw";
    overlay.style.height = "100vh";
    overlay.style.backgroundColor = "rgba(0, 0, 0, 0.4)";
    overlay.style.zIndex = "1039"; // Must be below modal
    overlay.style.pointerEvents = "auto";
    overlay.style.backdropFilter = "blur(2px)";
    document.body.appendChild(overlay);

    // Create modal dialog with static backdrop
    const dialog = new frappe.ui.Dialog({
        title: "🔐 Verify Department & Role",
        fields: [
            {
                label: "Department",
                fieldname: "department",
                fieldtype: "Link",
                options: "Department",
                reqd: 1,
                onchange: function () {
                    const selected_department = dialog.get_value("department");

                    // Clear previous Role Profile selection
                    dialog.set_value("role_profile", "");

                    // Set dynamic get_query to call Python method
                    dialog.fields_dict.role_profile.get_query = function () {
                        return {
                            query: "nj_features.overrides.employee.get_filtered_role_profiles",
                            filters: {
                                department: selected_department
                            }
                        };
                    };
                }
            },
            {
                label: "Role Profile",
                fieldname: "role_profile",
                fieldtype: "Link",
                options: "Role Profile",
                reqd: 1
            },
            {
                label: "Department Under",
                fieldname: "department_under",
                fieldtype: "Select",
                options: "\nDesktop\nLaptop\nManagement",
                reqd: 1
            }
        ],
        static: 1,
        primary_action_label: "Submit",
        primary_action(values) {
            console.log("🔍 Submitted values:", values);

            frappe.call({
                method: "nj_features.overrides.employee.validate_employee_department_and_role",
                args: {
                    user: user,
                    department: values.department,
                    role_profile: values.role_profile,
                    department_under: values.department_under
                },
                callback: (r) => {
                    if (r.message === true || r.message?.True === true) {
                        frappe.show_alert("✅ Department and Role matched.");
                        dialog.hide();
                        document.getElementById("login-block-overlay")?.remove();
                    } else if (r.message?.error) {
                        frappe.msgprint({
                            title: __("Cannot Change Department"),
                            message: r.message.error,
                            indicator: 'red'
                        });
                    } else if (r.message?.False) {
                        frappe.show_alert("✅ Department and Role updated successfully.");
                        dialog.hide();
                        document.getElementById("login-block-overlay")?.remove();
                    }

                    popUpWorkInventory();
                }
            });
        },
        no_cancel_button: true
    }, {
        backdrop: 'static',  // disable click-out close
        keyboard: false      // disable ESC close
    });

    dialog.show();
}


function show_login_popup() {
    const user = frappe.session?.user;
    console.log("🔍 User:", user);

    if (!user || user === "Guest" || user === "Administrator") return;

    const currentPath = window.location.pathname;
    const isAppRoot = currentPath.endsWith("/app");

    console.log("🔍 Current path:", currentPath);

    // if (!isAppRoot) {
    //     console.log("🔕 Not in /app route, skipping popup.");
    //     return;
    // }

    const today = frappe.datetime.get_today();

    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Activity Log",
            fields: ["name"],
            filters: {
                user: user,
                operation: "Login", status: "Success",
                creation: [">=", today + " 00:00:00"]
            },
        },
        callback: (r) => {
            console.log("🔍 User login activity:", r.message);

            if (!r.message || r.message.length <= 1) {
                console.log("🚨 No login today — show popup.");
                show_login_verification_popup(user);
            } else {
                console.log("✅ User already logged in today — no popup.");
            }
        }
    });
}
// function popUpWorkInventory() {
//     const dialog = new frappe.ui.Dialog({
//         title: __('Work Warehouse Inventory'),
//         fields: [
//             {
//                 label: __('Scan Barcode'),
//                 fieldname: 'scan_barcode',
//                 fieldtype: 'Data',
//                 options: 'Barcode',
//                 in_list_view: 1,
//             },
//             { fieldtype: 'Section Break' },
//             {
//                 fieldname: "work_warehouse_inventory",
//                 fieldtype: "Table",
//                 in_place_edit: true,
//                 fields: [
//                     {
//                         label: __('Sr. No.'),
//                         fieldname: 'sr_no',
//                         fieldtype: 'Int',
//                         read_only: 1,
//                         in_list_view: 1,
//                         columns: 1
//                     },
//                     {
//                         label: __('Item Code'),
//                         fieldname: 'item_code',
//                         fieldtype: 'Link',
//                         reqd: 1,
//                         options: 'Item',
//                         in_list_view: 1,
//                         read_only: 1,
//                         columns: 3
//                     },
//                     {
//                         label: __('Serial No'),
//                         fieldname: 'serial_no',
//                         fieldtype: 'Link',
//                         options: 'Serial No',
//                         in_list_view: 1,
//                         columns: 2
//                     },
//                     {
//                         label: __('Warehouse'),
//                         fieldname: 'warehouse',
//                         fieldtype: 'Link',
//                         options: 'Warehouse',
//                         in_list_view: 1,
//                         columns: 2
//                     },
//                     {
//                         label: __('Yes'),
//                         fieldname: 'yes',
//                         fieldtype: 'Check',
//                         default: 0,
//                         in_list_view: 1,
//                         columns: 1
//                     },
//                     {
//                         label: __('User Activity'),
//                         fieldname: 'user_activity',
//                         fieldtype: 'Select',
//                         options: '\nLog In\nLog Out',
//                         default: 'Log In',
//                         read_only: 1
//                     }
//                 ]
//             }
//         ],
//         size: 'extra-large',
//         primary_action_label: __('Submit'),
//         static: true,
//         primary_action: function () {
//             const values = dialog.get_values();
//             if (values && values.work_warehouse_inventory && values.work_warehouse_inventory.length > 0) {
//                 frappe.call({
//                     method: 'frappe.client.save',
//                     args: {
//                         doc: {
//                             doctype: 'Daily Individual Report',
//                             work_warehouse_inventory: values.work_warehouse_inventory,
//                             created_by: frappe.session.user
//                         }
//                     },
//                     callback: function (r) {
//                         if (!r.exc) {
//                             frappe.call({
//                                 method: 'frappe.client.submit',
//                                 args: { doc: r.message },
//                                 callback: function (r) {
//                                     if (!r.exc) {
//                                         frappe.msgprint(__('Report submitted successfully.'));
//                                         dialog.hide();
//                                     }
//                                 }
//                             });
//                         }
//                     }
//                 });
//             } else {
//                 frappe.msgprint(__('Please scan at least one item before submitting.'));
//             }
//         }
//     });

//     // Disable paste and manual typing helper
//     function disablePaste(inputField) {
//         // Disable right-click context menu
//         inputField.on('contextmenu', function(event) {
//             event.preventDefault();
//         });

//         // Disable Ctrl + V (paste) event
//         inputField.on('keydown', function(event) {
//             if (event.ctrlKey && (event.key === 'v' || event.key === 'V')) {
//                 event.preventDefault();
//                 frappe.msgprint(__('Paste is disabled. Please use barcode scanner.'));
//             }
//         });

//         // Disable mouse middle-click paste
//         inputField.on('mousedown', function(event) {
//             if (event.button === 1) { // Middle mouse button
//                 event.preventDefault();
//             }
//         });
//     }

//     // Restrict manual typing (already present logic)
// function handleScannerInput(dialog, fieldname) {
//     const field = dialog.get_field(fieldname);
//     if (field && field.$input) {
//         let keyPressCount = 0;
//         let keyPressStartTime = 0;
//         let scannerInputActive = false;

//         field.$input.on('keydown', function (e) {
//             // Allow only Enter key (scanner suffix)
//             if (e.key === "Enter") {
//                 scannerInputActive = false;
//                 keyPressCount = 0;
//                 return true;
//             }

//             const now = Date.now();

//             // Reset session if too long between keys
//             if (now - keyPressStartTime > 500) {
//                 keyPressCount = 0;
//                 keyPressStartTime = now;
//                 scannerInputActive = false;
//             }

//             keyPressCount++;

//             // First keystroke → assume scanner until proven otherwise
//             if (keyPressCount === 1) {
//                 keyPressStartTime = now;
//                 this.lastKeyTime = now;
//                 scannerInputActive = true;
//                 return true;
//             }

//             const timeDiff = now - this.lastKeyTime;

//             // If within scanner speed (≤ 50ms per char) → allow
//             if (timeDiff <= 50 || scannerInputActive) {
//                 this.lastKeyTime = now;
//                 return true;
//             }

//             // Otherwise → BLOCK manual entry
//             e.preventDefault();
//             frappe.msgprint(__('❌ Manual entry is not allowed. Please use a barcode scanner.'));
//             return false;
//         });

//         // Block paste again (safety)
//         field.$input.on('paste', function (e) {
//             e.preventDefault();
//             frappe.msgprint(__('❌ Paste is disabled. Please use a barcode scanner.'));
//         });

//         // Reset when field cleared
//         field.$input.on('input', function () {
//             if ($(this).val() === '') {
//                 keyPressCount = 0;
//                 scannerInputActive = false;
//             }
//         });

//         // Extra: disable right-click & middle-click paste
//         disablePaste(field.$input);
//     }
// }


//     // Barcode scanning logic
//     function handleBarcodeScanning(dialog) {
//         const scanField = dialog.get_field('scan_barcode');
//         if (scanField && scanField.$input) {
//             scanField.$input.on('change keyup', function (e) {
//                 if (e.keyCode && e.keyCode !== 13) return;
                
//                 const barcodeValue = $(this).val().trim();
//                 if (!barcodeValue) return;

//                 const tableData = dialog.fields_dict.work_warehouse_inventory.df.data;
//                 let matchFound = false;
//                 let matchedRowData = null;

//                 for (let i = 0; i < tableData.length; i++) {
//                     const row = tableData[i];
//                     if (row.serial_no && row.serial_no.toString().trim().toLowerCase() === barcodeValue.toLowerCase()) {
//                         row.yes = 1;
//                         matchFound = true;
//                         matchedRowData = row;
//                         break;
//                     }
//                 }

//                 if (matchFound && matchedRowData) {
//                     dialog.fields_dict.work_warehouse_inventory.grid.refresh();
//                     frappe.msgprint({
//                         title: __('✅ Serial No Matched'),
//                         message: __(`<strong>Row #${matchedRowData.sr_no}</strong><br>
//                                     Serial No: <strong>${barcodeValue}</strong><br>
//                                     Item Code: ${matchedRowData.item_code}<br>
//                                     Warehouse: ${matchedRowData.warehouse}<br>
//                                     <span style="color: green;">✅ Yes Checked Successfully!</span>`),
//                         indicator: 'green'
//                     });
//                 } else {
//                     frappe.msgprint({
//                         title: __('❌ No Match Found'),
//                         message: __(`Serial No: <strong>${barcodeValue}</strong> not found in the table.<br>
//                                     Please scan the next serial number.`),
//                         indicator: 'red'
//                     });
//                 }

//                 $(this).val('');
//                 setTimeout(() => { $(this).focus(); }, 100);
//             });

//             scanField.$input.on('keydown', function (e) {
//                 if (e.keyCode === 13) {
//                     e.preventDefault();
//                     $(this).trigger('keyup');
//                     return false;
//                 }
//             });
//         }
//     }

//     // Load data
//     frappe.call({
//         method: 'nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.get_serial_no_data',
//         callback: function (r) {
//             if (!r.exc && r.message) {
//                 dialog.fields_dict.work_warehouse_inventory.df.data = [];
//                 dialog.fields_dict.work_warehouse_inventory.refresh();

//                 r.message.forEach(function (row, index) {
//                     dialog.fields_dict.work_warehouse_inventory.df.data.push({
//                         sr_no: index + 1,
//                         item_code: row.item_code || '',
//                         serial_no: row.serial_no || '',
//                         warehouse: row.warehouse || '',
//                         yes: 0,
//                         user_activity: 'Log In'
//                     });
//                 });

//                 dialog.fields_dict.work_warehouse_inventory.grid.refresh();

//                 setTimeout(function () {
//                     handleScannerInput(dialog, "scan_barcode");
//                     handleBarcodeScanning(dialog);
//                     dialog.get_field('scan_barcode').$input.focus();
//                 }, 500);
//             } else {
//                 frappe.msgprint({
//                     title: __('Error'),
//                     message: __('Failed to load serial number data. Please try again.'),
//                     indicator: 'red'
//                 });
//             }
//         }
//     });

//     dialog.onhide = function() {
//         console.log('Dialog closed');
//     };

//     dialog.show();
// }

function popUpWorkInventory() {
    const dialog = new frappe.ui.Dialog({
        title: __('Work Warehouse Inventory'),
        fields: [
            {
                label: __('Scan Barcode'),
                fieldname: 'scan_barcode',
                fieldtype: 'Data',
                options: 'Barcode',
                in_list_view: 1,
            },
            { fieldtype: 'Section Break' },
            {
                fieldname: "work_warehouse_inventory",
                fieldtype: "Table",
                in_place_edit: true,
                fields: [
                    {
                        label: __('Sr. No.'),
                        fieldname: 'sr_no',
                        fieldtype: 'Int',
                        read_only: 1,
                        in_list_view: 1,
                        columns: 1
                    },
                    {
                        label: __('Item Code'),
                        fieldname: 'item_code',
                        fieldtype: 'Link',
                        reqd: 1,
                        options: 'Item',
                        in_list_view: 1,
                        read_only: 1,
                        columns: 1
                    },
                    {
                        label: __('Serial No'),
                        fieldname: 'serial_no',
                        fieldtype: 'Link',
                        options: 'Serial No',
                        in_list_view: 1,
                        columns: 2
                    },
                    {
                        label: __('Warehouse'),
                        fieldname: 'warehouse',
                        fieldtype: 'Link',
                        options: 'Warehouse',
                        in_list_view: 1,
                        columns: 2
                    },
                    {
                        label: __('Age'),
                        fieldname: 'age',
                        fieldtype: 'Int',
                        in_list_view: 1,
                        columns: 1
                    },
                    {
                        label: __('Yes'),
                        fieldname: 'yes',
                        fieldtype: 'Check',
                        default: 0,
                        read_only: 1,
                        in_list_view: 1,
                        columns: 1
                        
                    },
                    {
                        label: __('User Activity'),
                        fieldname: 'user_activity',
                        fieldtype: 'Select',
                        options: '\nLog In\nLog Out',
                        default: 'Log In',
                        read_only: 1
                    }
                ]
            }
        ],
        
        size: 'extra-large',
        primary_action_label: __('Submit'),
        static: true,
        primary_action: function () {
            const values = dialog.get_values();
            if (values && values.work_warehouse_inventory && values.work_warehouse_inventory.length > 0) {
                // Check if all "Yes" are checked
                const unchecked = values.work_warehouse_inventory.filter(row => !row.yes);

                if (unchecked.length > 0) {
                    // Show custom confirmation popup
                    frappe.confirm(
                        __("Some serial numbers are unchecked. Do you want to rescan or submit anyway?"),
                        function () {
                            // ✅ Submit Anyway
                            submitReport(values, dialog);
                        },
                        function () {
                            // ❌ Rescan → keep dialog open
                            frappe.msgprint(__('Please rescan the unchecked rows before submitting.'));
                        }
                    );
                } else {
                    // All checked → submit directly
                    submitReport(values, dialog);
                }
            } else {
                frappe.msgprint(__('Please scan at least one item before submitting.'));
            }
        }
    });

    // helper: save + submit report
    function submitReport(values, dialog) {
        frappe.call({
            method: 'frappe.client.save',
            args: {
                doc: {
                    doctype: 'Daily Individual Report',
                    work_warehouse_inventory: values.work_warehouse_inventory,
                    created_by: frappe.session.user
                }
            },
            callback: function (r) {
                if (!r.exc) {
                    frappe.call({
                        method: 'frappe.client.submit',
                        args: { doc: r.message },
                        callback: function (r) {
                            if (!r.exc) {
                                frappe.msgprint(__('Report submitted successfully.'));
                                dialog.hide();
                            }
                        }
                    });
                }
            }
        });
    }

    // Disable paste and manual typing helper
    function disablePaste(inputField) {
        inputField.on('contextmenu', e => e.preventDefault());
        inputField.on('keydown', function (event) {
            if (event.ctrlKey && (event.key === 'v' || event.key === 'V')) {
                event.preventDefault();
                frappe.msgprint(__('Paste is disabled. Please use barcode scanner.'));
            }
        });
        inputField.on('mousedown', function (event) {
            if (event.button === 1) event.preventDefault();
        });
    }

    // Restrict manual typing
    function handleScannerInput(dialog, fieldname) {
        const field = dialog.get_field(fieldname);
        if (field && field.$input) {
            let keyPressCount = 0;
            let keyPressStartTime = 0;
            let scannerInputActive = false;

            field.$input.on('keydown', function (e) {
                if (e.key === "Enter") {
                    scannerInputActive = false;
                    keyPressCount = 0;
                    return true;
                }

                const now = Date.now();
                if (now - keyPressStartTime > 500) {
                    keyPressCount = 0;
                    keyPressStartTime = now;
                    scannerInputActive = false;
                }

                keyPressCount++;
                if (keyPressCount === 1) {
                    keyPressStartTime = now;
                    this.lastKeyTime = now;
                    scannerInputActive = true;
                    return true;
                }

                const timeDiff = now - this.lastKeyTime;
                if (timeDiff <= 50 || scannerInputActive) {
                    this.lastKeyTime = now;
                    return true;
                }

                e.preventDefault();
                frappe.msgprint(__('❌ Manual entry is not allowed. Please use a barcode scanner.'));
                return false;
            });

            field.$input.on('paste', function (e) {
                e.preventDefault();
                frappe.msgprint(__('❌ Paste is disabled. Please use a barcode scanner.'));
            });

            field.$input.on('input', function () {
                if ($(this).val() === '') {
                    keyPressCount = 0;
                    scannerInputActive = false;
                }
            });

            disablePaste(field.$input);
        }
    }

    // Barcode scanning logic
    function handleBarcodeScanning(dialog) {
        const scanField = dialog.get_field('scan_barcode');
        if (scanField && scanField.$input) {
            scanField.$input.on('change keyup', function (e) {
                if (e.keyCode && e.keyCode !== 13) return;

                const barcodeValue = $(this).val().trim();
                if (!barcodeValue) return;

                const tableData = dialog.fields_dict.work_warehouse_inventory.df.data;

                for (let i = 0; i < tableData.length; i++) {
                    const row = tableData[i];
                    if (row.serial_no && row.serial_no.toString().trim().toLowerCase() === barcodeValue.toLowerCase()) {
                        row.yes = 1; 
                        break;
                    }
                }

                dialog.fields_dict.work_warehouse_inventory.grid.refresh();
                $(this).val('');
                setTimeout(() => { $(this).focus(); }, 100);
            });

            scanField.$input.on('keydown', function (e) {
                if (e.keyCode === 13) {
                    e.preventDefault();
                    $(this).trigger('keyup');
                    return false;
                }
            });
        }
    }
    function makeCheckboxesReadOnly() {
        // Wait for the grid to be rendered
        setTimeout(() => {
            const grid = dialog.fields_dict.work_warehouse_inventory.grid;
            if (grid && grid.grid_rows) {
                grid.grid_rows.forEach(row => {
                    const checkbox = row.$wrapper ? row.$wrapper.find('input[data-fieldname="yes"]') : null;
                    if (checkbox && checkbox.length) {
                        // Make checkbox read-only and change cursor style
                        checkbox.prop('disabled', true);
                        checkbox.css('cursor', 'not-allowed');
                        
                        // Also disable the label if it exists
                        const label = row.$wrapper ? row.$wrapper.find('label[for="' + checkbox.attr('id') + '"]') : null;
                        if (label && label.length) {
                            label.css('cursor', 'not-allowed');
                        }
                    }
                });
            }
        }, 1000);
    }

    // Load serial number data
    frappe.call({
        method: 'nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.get_serial_no_data',
        callback: function (r) {
            if (!r.exc && r.message) {
                dialog.fields_dict.work_warehouse_inventory.df.data = [];
                dialog.fields_dict.work_warehouse_inventory.refresh();
                r.message.forEach(function (row, index) {
                    dialog.fields_dict.work_warehouse_inventory.df.data.push({
                        sr_no: index + 1,
                        item_code: row.item_code || '',
                        serial_no: row.serial_no || '',
                        warehouse: row.warehouse || '',
                        age: row.Age || '',
                        yes: 0,
                        user_activity: 'Log In'
                    });
                });

                dialog.fields_dict.work_warehouse_inventory.grid.refresh();

                setTimeout(function () {
                    handleScannerInput(dialog, "scan_barcode");
                    handleBarcodeScanning(dialog);
                    dialog.get_field('scan_barcode').$input.focus();
                    makeCheckboxesReadOnly();
                }, 500);
            } else {
                frappe.msgprint({
                    title: __('Error'),
                    message: __('Failed to load serial number data. Please try again.'),
                    indicator: 'red'
                });
            }
        }
    });

    dialog.onhide = function () {
        console.log('Dialog closed');
    };

    // 🚫 Block ESC key close
    $(document).on('keydown.restrictEsc', function (e) {
        if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            frappe.msgprint(__('❌ You cannot close this popup with ESC.'));
        }
    });

    // Remove ESC restriction when dialog is hidden (to avoid affecting other dialogs)
    dialog.onhide = function() {
        $(document).off('keydown.restrictEsc');
        console.log('Dialog closed');
    };

    dialog.show();
}

function toggle_checkboxes(field) {
    let row = $(field).closest('.grid-row');
    let yes_field = row.find('input[data-fieldname="yes"]');
    let no_field = row.find('input[data-fieldname="no"]');

    if ($(field).is(':checked')) {
        if (field.dataset.fieldname === 'yes') {
            no_field.prop('checked', false).change();
        } else {
            yes_field.prop('checked', false).change();
        }
    } else {
        if (!yes_field.is(':checked') && !no_field.is(':checked')) {
            if (field.dataset.fieldname === 'yes') {
                no_field.prop('checked', true).change();
            } else {
                yes_field.prop('checked', true).change();
            }
        }
    }
}
