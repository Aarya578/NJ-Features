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