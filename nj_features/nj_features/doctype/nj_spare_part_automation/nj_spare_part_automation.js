// Copyright (c) 2026, NewJaisa - IT Team and contributors
// For license information, please see license.txt

function toggle_generated_fields(frm) {
	const is_generated = frm.doc.status === "Generated";
	const is_error = frm.doc.status === "Error";

	// These two fields should always be visible
	const always_visible_fields = [
		"item_code",
		"status"
	];

	// These fields should be visible only after Generate Info is completed
	const generated_fields = [
		"item_name",
		"brand",
		"model",
		"item_group",
		"generic_item_group",
		"generated_description",
		"specifications",
		"scraped_fru_number",
		"image_1",
		"image_2",
		"image_3",
		"image_4",
		"image_5",
		"raw_response"
	];

	always_visible_fields.forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.toggle_display(fieldname, true);
		}
	});

	generated_fields.forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.toggle_display(fieldname, is_generated);
		}
	});

	// Show error log only if status is Error
	if (frm.fields_dict["error_log"]) {
		frm.toggle_display("error_log", is_error);
	}
}

frappe.ui.form.on("NJ Spare Part Automation", {
	onload(frm) {
		toggle_generated_fields(frm);
	},

	refresh(frm) {
		toggle_generated_fields(frm);

		frm.add_custom_button(__("Generate Info"), function () {
			if (!frm.doc.item_code) {
				frappe.msgprint(__("Please select Item Code first."));
				return;
			}

			frm.save().then(() => {
				frappe.call({
					method: "nj_features.nj_features.doctype.nj_spare_part_automation.nj_spare_part_automation.generate_info",
					args: {
						docname: frm.doc.name
					},
					freeze: true,
					freeze_message: __("Generating spare part description and specifications..."),
					callback: function (r) {
						if (!r.exc) {
							frappe.msgprint(__("Generated successfully."));

							frm.reload_doc().then(() => {
								toggle_generated_fields(frm);
							});
						}
					}
				});
			});
		});
	}
});