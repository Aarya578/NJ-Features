frappe.listview_settings["RFQ Dashboard Access"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Generate Dashboard Link"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Generate RFQ Dashboard Link"),
				fields: [
					{
						fieldname: "supplier",
						label: __("Supplier"),
						fieldtype: "Link",
						options: "Supplier",
						reqd: 1,
						change() {
							dialog.set_value("rfq", "");
						}
					},
					{
						fieldname: "rfq",
						label: __("RFQ"),
						fieldtype: "Link",
						options: "Request for Quotation",
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

					frappe.call({
						method: "nj_features.nj_features.doctype.rfq_dashboard_access.rfq_dashboard_access.generate_access_link",
						args: values,
						freeze: true,
						freeze_message: __("Generating secure dashboard link..."),
						callback(response) {
							const data = response.message || {};

							if (!data.dashboard_url) {
								return;
							}

							dialog.hide();
							listview.refresh();

							const dashboard_url = frappe.utils.escape_html(data.dashboard_url);
							const expires_on = frappe.datetime.str_to_user(data.expires_on);

							frappe.msgprint({
								title: __("Dashboard Link Generated"),
								indicator: "green",
								message: `
									<p>${__("Copy and send this link to the customer:")}</p>
									<p>
										<input
											type="text"
											class="form-control"
											value="${dashboard_url}"
											readonly
											onclick="this.select()"
										>
									</p>
									<p>${__("Expires On")}: ${frappe.utils.escape_html(expires_on)}</p>
								`
							});
						}
					});
				}
			});

			dialog.show();
		});
	}
};
