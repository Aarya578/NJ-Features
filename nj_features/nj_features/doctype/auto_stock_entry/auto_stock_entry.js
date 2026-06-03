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
		handleScannerInput(frm, 'serial_no');
	},
serial_no: function(frm) {
    if (frm.doc.serial_no) {
        // Add manual entry prevention to the serial_no field
        const serialNoField = frm.get_field('serial_no');
        if (serialNoField && serialNoField.$input) {
            // Prevent paste
            serialNoField.$input.on('paste', function (e) {
                e.preventDefault();
                frappe.msgprint(__('❌ Paste is disabled. Please use a barcode scanner.'));
                $(this).val('');
            });

            // Prevent context menu (right-click)
            serialNoField.$input.on('contextmenu', function (e) {
                e.preventDefault();
                return false;
            });

            // Allow all keyboard input - scanner will work naturally
            // Only show error if user tries to type slowly (manual entry)
            let lastKeyTime = 0;
            let manualEntryDetected = false;
            
            serialNoField.$input.on('keydown', function (e) {
                // Allow Enter key (scanner termination)
                if (e.key === "Enter") {
                    manualEntryDetected = false;
                    return true;
                }
                
                // Allow navigation and control keys
                if (e.ctrlKey || e.metaKey || 
                    e.key === 'Tab' || e.key === 'ArrowLeft' || 
                    e.key === 'ArrowRight' || e.key === 'ArrowUp' || 
                    e.key === 'ArrowDown' || e.key === 'Delete' || 
                    e.key === 'Backspace') {
                    return true;
                }
                
                const currentTime = new Date().getTime();
                
                // If time between keystrokes is more than 200ms, it's likely manual typing
                if (currentTime - lastKeyTime > 200 && lastKeyTime !== 0) {
                    manualEntryDetected = true;
                }
                
                lastKeyTime = currentTime;
                return true;
            });

            serialNoField.$input.on('input', function () {
                if (manualEntryDetected) {
                    frappe.msgprint(__('❌ Manual entry is not allowed. Please use a barcode scanner.'));
                    $(this).val('');
                    manualEntryDetected = false;
                }
                
                lastKeyTime = 0;
            });
        }

        // Your existing functionality
        handleScannerInput(frm, 'serial_no');
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