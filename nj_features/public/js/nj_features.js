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
    // show_login_popup();
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
                reqd: 1
            },
            {
                label: "Role Profile",
                fieldname: "role_profile",
                fieldtype: "Link",
                options: "Role Profile",
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
                    role_profile: values.role_profile
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
                }
            });
        },
        no_cancel_button: true // hides cancel button
    }, { 
        backdrop: 'static', // Prevent closing on overlay click
        keyboard: false    // Prevent closing with ESC key
    });

    dialog.show();
}

function show_login_popup() {
    const user = frappe.session?.user;
    console.log("🔍 User:", user);

    if (!user || user === "Guest") return;

    const currentPath = window.location.pathname;
    const isAppRoot = currentPath.endsWith("/app");

    console.log("🔍 Current path:", currentPath);

    if (!isAppRoot) {
        console.log("🔕 Not in /app route, skipping popup.");
        return;
    }

    const today = frappe.datetime.get_today();

    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Activity Log",
            fields: ["name"],
            filters: {
                user: user,
                operation: "Login",
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