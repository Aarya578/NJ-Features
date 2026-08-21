frappe.ui.form.on("Request for Quotation Supplier", {
	async supplier(frm, cdt, cdn) {
		const row = locals[cdt][cdn];

		if (!row.supplier) {
			await frm.set_value("email", "");
			return;
		}

		const supplier = row.supplier;
		const { message } = await frappe.db.get_value(
			"Supplier",
			supplier,
			"email_id"
		);
		const emailId = message && message.email_id;

		// Ignore a stale response if the user changed the supplier meanwhile.
		if (locals[cdt][cdn].supplier !== supplier) {
			return;
		}

		if (!emailId) {
			await frm.set_value("email", "");
			frappe.throw(__("Email ID not found for Supplier {0}.", [supplier]));
		}

		await frm.set_value("email", emailId);
	}
});

const RFQ_SUBMIT_OPTIONS = {
	CUSTOMER_QUOTATION: "Customer Quotation",
	VENDOR_DASHBOARD: "Dashboard To The Vendor",
	OTHER: "Other"
};

function get_rfq_suppliers(frm) {
	return (frm.doc.suppliers || [])
		.map((row) => row.supplier)
		.filter((supplier, index, values) => supplier && values.indexOf(supplier) === index);
}

function get_customer_quotation_supplier_rows(frm) {
	return (frm.doc.suppliers || []).filter(
		(row) => row.send_email && row.supplier
	);
}

function has_customer_quotation_links(frm) {
	const rows = get_customer_quotation_supplier_rows(frm);
	return (
		rows.length > 0 &&
		rows.every(
			(row) =>
				row.customer_quotation_link &&
				row.customer_quotation_access &&
				row.link_expires_on
		)
	);
}

function select_rfq_submit_option() {
	return new Promise((resolve) => {
		let selected = false;
		const dialog = new frappe.ui.Dialog({
			title: __("Select RFQ Submission Option"),
			fields: [
				{
					fieldname: "selected_option",
					label: __("Option"),
					fieldtype: "Select",
					options: [
						RFQ_SUBMIT_OPTIONS.CUSTOMER_QUOTATION,
						RFQ_SUBMIT_OPTIONS.VENDOR_DASHBOARD,
						RFQ_SUBMIT_OPTIONS.OTHER
					].join("\n"),
					reqd: 1
				}
			],
			primary_action_label: __("Continue"),
			primary_action(values) {
				selected = true;
				resolve(values.selected_option);
				dialog.hide();
			}
		});

		dialog.onhide = () => {
			if (!selected) {
				resolve(null);
			}
		};

		dialog.show();
	});
}

function generate_rfq_link(frm, config) {
	const suppliers = get_rfq_suppliers(frm);
	if (!suppliers.length) {
		frappe.msgprint(__("Please add at least one Supplier before generating the link."));
		return Promise.resolve(false);
	}

	if (!frm.fields_dict[config.target_field]) {
		frappe.msgprint(
			__("Field {0} was not found in Request for Quotation.", [config.target_field])
		);
		return Promise.resolve(false);
	}

	return new Promise((resolve) => {
		let generated = false;
		const dialog = new frappe.ui.Dialog({
			title: __(config.title),
			fields: [
				{
					fieldname: "supplier",
					label: __("Supplier"),
					fieldtype: "Link",
					options: "Supplier",
					default: suppliers[0],
					reqd: 1,
					get_query() {
						return {
							filters: [["Supplier", "name", "in", suppliers]]
						};
					}
				},
				{
					fieldname: "rfq",
					label: __("RFQ"),
					fieldtype: "Link",
					options: "Request for Quotation",
					default: frm.doc.name,
					description: __(config.rfq_description)
				},
				{
					fieldname: "valid_days",
					label: __("Valid For Days"),
					fieldtype: "Int",
					default: 7,
					reqd: 1
				},
				{
					fieldname: "one_time_use",
					label: __("One Time Use"),
					fieldtype: "Check",
					default: 0
				}
			],
			primary_action_label: __("Generate Link"),
			primary_action(values) {
				if (values.valid_days < 1) {
					frappe.msgprint(__("Valid For Days must be at least 1."));
					return;
				}

				const primaryButton = dialog.get_primary_btn();
				primaryButton.prop("disabled", true);

				frappe.call({
					method: config.method,
					args: {
						source_rfq: frm.doc.name,
						supplier: values.supplier,
						rfq: values.rfq,
						valid_days: values.valid_days,
						one_time_use: values.one_time_use
					},
					freeze: true,
					freeze_message: __("Generating secure link..."),
					callback(response) {
						const data = response.message || {};
						const generatedUrl = data[config.response_key];

						if (!generatedUrl) {
							primaryButton.prop("disabled", false);
							return;
						}

						frm.set_value(config.target_field, generatedUrl).then(() => {
							generated = true;
							resolve(true);
							dialog.hide();
						});
					},
					error() {
						primaryButton.prop("disabled", false);
					}
				});
			}
		});

		dialog.onhide = () => {
			if (!generated) {
				resolve(false);
			}
		};

		dialog.show();
	});
}

function generate_customer_quotation_links(frm) {
	const supplierRows = get_customer_quotation_supplier_rows(frm);
	if (!supplierRows.length) {
		frappe.msgprint(__("Select Send Email for at least one supplier."));
		return Promise.resolve(false);
	}

	const missingEmailRow = supplierRows.find((row) => !row.email_id);
	if (missingEmailRow) {
		frappe.msgprint(
			__("Email Address is required for Supplier {0}.", [missingEmailRow.supplier])
		);
		return Promise.resolve(false);
	}

	return new Promise((resolve) => {
		let generated = false;
		const dialog = new frappe.ui.Dialog({
			title: __("Generate Customer Quotation Links"),
			fields: [
				{
					fieldname: "valid_days",
					label: __("Valid For Days"),
					fieldtype: "Int",
					default: 7,
					reqd: 1
				},
				{
					fieldname: "one_time_use",
					label: __("One Time Use"),
					fieldtype: "Check",
					default: 0
				}
			],
			primary_action_label: __("Generate Links"),
			async primary_action(values) {
				if (values.valid_days < 1) {
					frappe.msgprint(__("Valid For Days must be at least 1."));
					return;
				}

				const primaryButton = dialog.get_primary_btn();
				primaryButton.prop("disabled", true);

				try {
					const response = await frappe.call({
						method:
							"nj_features.nj_features.doctype.rfq_customer_quotation_access.rfq_customer_quotation_access.generate_customer_quotation_links",
						args: {
							source_rfq: frm.doc.name,
							valid_days: values.valid_days,
							one_time_use: values.one_time_use
						},
						freeze: true,
						freeze_message: __("Generating supplier quotation links...")
					});

					const links = (response.message && response.message.links) || [];
					if (!links.length) {
						primaryButton.prop("disabled", false);
						return;
					}

					for (const link of links) {
						const row = (frm.doc.suppliers || []).find(
							(supplierRow) => supplierRow.name === link.row_name
						);
						if (!row) {
							continue;
						}
						await frappe.model.set_value(
							row.doctype,
							row.name,
							"customer_quotation_link",
							link.quotation_url
						);
						await frappe.model.set_value(
							row.doctype,
							row.name,
							"customer_quotation_access",
							link.access_name
						);
						await frappe.model.set_value(
							row.doctype,
							row.name,
							"link_expires_on",
							link.expires_on
						);
					}
					await frm.set_value(
						"lead_date",
						frappe.datetime.add_days(frappe.datetime.get_today(), 3)
					);

					generated = true;
					resolve(true);
					dialog.hide();
				} catch (error) {
					primaryButton.prop("disabled", false);
				}
			}
		});

		dialog.onhide = () => {
			if (!generated) {
				resolve(false);
			}
		};

		dialog.show();
	});
}

async function handle_rfq_before_submit(frm) {
	if (!frm.fields_dict.user_selected_option) {
		frappe.validated = false;
		frappe.msgprint(
			__("Field User Selected Option (user_selected_option) was not found.")
		);
		return;
	}

	let selectedOption = frm.doc.user_selected_option;
	if (!selectedOption) {
		frappe.validated = false;
		selectedOption = await select_rfq_submit_option();

		if (!selectedOption) {
			return;
		}

		await frm.set_value("user_selected_option", selectedOption);
	}

	if (selectedOption === RFQ_SUBMIT_OPTIONS.OTHER) {
		frappe.validated = true;
		return;
	}

	if (selectedOption === RFQ_SUBMIT_OPTIONS.CUSTOMER_QUOTATION) {
		if (has_customer_quotation_links(frm)) {
			frappe.validated = true;
			return;
		}

		frappe.validated = false;
		if (await generate_customer_quotation_links(frm)) {
			frappe.validated = false;
			frappe.msgprint(__("Customer links are generated."));
		}
		return;
	}

	if (selectedOption === RFQ_SUBMIT_OPTIONS.VENDOR_DASHBOARD) {
		if (frm.doc.rfq_dashboard_link) {
			frappe.validated = true;
			return;
		}

		frappe.validated = false;
		await generate_rfq_link(frm, {
			title: "Generate RFQ Dashboard Link",
			target_field: "rfq_dashboard_link",
			response_key: "dashboard_url",
			method:
				"nj_features.overrides.request_for_quotation.generate_dashboard_link_before_submit",
			rfq_description: "Optional. Leave blank to allow all RFQs for the selected supplier."
		});
		return;
	}

	frappe.validated = false;
	frappe.msgprint(__("Please select a valid RFQ submission option."));
}

frappe.ui.form.on("Request for Quotation", {
	before_submit(frm) {
		return handle_rfq_before_submit(frm);
	}
});
