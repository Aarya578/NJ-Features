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

frappe.ui.form.on("Request for Quotation", {
	before_submit(frm) {
		if (frm.doc.rfq_dashboard_link) {
			return;
		}

		const suppliers = (frm.doc.suppliers || [])
			.map((row) => row.supplier)
			.filter((supplier, index, values) => supplier && values.indexOf(supplier) === index);

		if (!suppliers.length) {
			frappe.validated = false;
			frappe.msgprint(__("Please add at least one Supplier before submitting the RFQ."));
			return;
		}

		if (!frm.fields_dict.rfq_dashboard_link) {
			frappe.validated = false;
			frappe.msgprint(__("Field RFQ Dashboard Link (rfq_dashboard_link) was not found."));
			return;
		}

		return new Promise((resolve) => {
			let linkGenerated = false;
			frappe.validated = false;

			const dialog = new frappe.ui.Dialog({
				title: __("Generate RFQ Dashboard Link"),
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
						description: __("Optional. Leave blank to allow all RFQs for the selected supplier.")
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
						method: "nj_features.overrides.request_for_quotation.generate_dashboard_link_before_submit",
						args: {
							source_rfq: frm.doc.name,
							supplier: values.supplier,
							rfq: values.rfq,
							valid_days: values.valid_days,
							one_time_use: values.one_time_use
						},
						freeze: true,
						freeze_message: __("Generating secure dashboard link..."),
						callback(response) {
							const data = response.message || {};
							if (!data.dashboard_url) {
								primaryButton.prop("disabled", false);
								return;
							}

							frm.set_value("rfq_dashboard_link", data.dashboard_url).then(() => {
								linkGenerated = true;
								frappe.validated = false;
								resolve();
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
				if (!linkGenerated) {
					frappe.validated = false;
					resolve();
				}
			};

			dialog.show();
		});
	}
});
