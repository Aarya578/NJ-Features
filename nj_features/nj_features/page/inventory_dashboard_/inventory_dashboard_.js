frappe.pages["inventory_dashboard_"].on_page_load = function(wrapper) {
	frappe.require(
		[
			"/assets/nj_features/js/rfq_dashboard_renderer.js",
			"/assets/nj_features/css/rfq_dashboard_shared.css"
		],
		() => {
			const page = frappe.ui.make_app_page({
				parent: wrapper,
				title: "RFQ QC Dashboard",
				single_column: true
			});

			new RFQQCDashboard(page);
		}
	);
};

class RFQQCDashboard {
	constructor(page) {
		this.page = page;
		this.makeFilters();
		this.makeBody();
		this.renderer.showMessage(__("Select a supplier to generate the RFQ QC dashboard."));
	}

	makeFilters() {
		this.supplierField = this.page.add_field({
			fieldname: "supplier",
			label: __("Select Supplier"),
			fieldtype: "Link",
			options: "Supplier",
			change: () => {
				const supplier = this.supplierField.get_value();
				if (supplier) {
					this.loadSupplierRfqs(supplier);
				} else {
					this.clearRfqField();
					this.renderer.showMessage(
						__("Select a supplier to generate the RFQ QC dashboard.")
					);
				}
			}
		});

		this.rfqField = this.page.add_field({
			fieldname: "rfq",
			label: __("Select RFQ"),
			fieldtype: "Select",
			options: "",
			change: () => {
				const supplier = this.supplierField.get_value();
				const rfq = this.rfqField.get_value();

				if (supplier && rfq) {
					this.clearRfqMandatoryState();
					this.loadData(supplier, rfq);
				} else if (supplier) {
					this.showRfqMandatoryState();
					this.renderer.showMessage(__("Please select RFQ name to generate dashboard."));
				}
			}
		});

		this.page.add_inner_button(__("Create RFQ Engine"), () => {
			this.createRfqEngine();
		});

		this.page.set_primary_action(__("Refresh"), () => {
			const supplier = this.supplierField.get_value();
			const rfq = this.rfqField.get_value();

			if (!supplier) {
				frappe.msgprint(__("Please select a supplier first."));
				return;
			}

			if (!rfq) {
				this.showRfqMandatoryState();
				frappe.msgprint(__("Please select RFQ name."));
				return;
			}

			this.loadData(supplier, rfq);
		});
	}

	makeBody() {
		this.addControlStyles();
		this.body = document.createElement("div");
		this.page.body.append(this.body);
		this.renderer = new RFQDashboardRenderer(this.body);
	}

	addControlStyles() {
		if (document.getElementById("rfq-dashboard-control-style")) {
			return;
		}

		const style = document.createElement("style");
		style.id = "rfq-dashboard-control-style";
		style.textContent = `
			.rfq-mandatory-blink .form-control {
				animation: rfq-mandatory-pulse 1s ease-in-out infinite;
				border-color: var(--red-500, #ff5858) !important;
				box-shadow: 0 0 0 1px rgba(255, 88, 88, 0.25);
			}
			@keyframes rfq-mandatory-pulse {
				0%, 100% { box-shadow: 0 0 0 1px rgba(255, 88, 88, 0.2); }
				50% { box-shadow: 0 0 0 4px rgba(255, 88, 88, 0.35); }
			}
		`;
		document.head.append(style);
	}

	loadSupplierRfqs(supplier) {
		this.clearRfqField();
		this.renderer.clear();

		frappe.call({
			method: "nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_.get_supplier_rfqs",
			args: { supplier },
			callback: (response) => {
				const rfqs = response.message || [];

				if (!rfqs.length) {
					frappe.msgprint(__("No RFQ name found for this supplier."));
					this.renderer.showMessage(__("No RFQ name found for this supplier."));
					return;
				}

				this.rfqField.df.options = ["", ...rfqs.map((row) => row.name)].join("\n");
				this.rfqField.refresh();
				this.rfqField.set_value("");
				this.showRfqMandatoryState();
				this.renderer.showMessage(__("Please select RFQ name to generate dashboard."));
			}
		});
	}

	loadData(supplier, rfq) {
		this.renderer.showLoading();

		frappe.call({
			method: "nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_.get_supplier_rfq_dashboard",
			args: { supplier, rfq },
			callback: (response) => {
				this.renderer.render(response.message || {});
			}
		});
	}

	createRfqEngine() {
		const supplier = this.supplierField.get_value();
		const rfq = this.rfqField.get_value();

		if (!supplier) {
			frappe.msgprint(__("Please select a supplier first."));
			return;
		}

		if (!rfq) {
			this.showRfqMandatoryState();
			frappe.msgprint(__("Please select RFQ name."));
			return;
		}

		frappe.call({
			method: "nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_.create_rfq_price_estimation_engine",
			args: { supplier, rfq },
			freeze: true,
			freeze_message: __("Creating RFQ Price Estimation Engine..."),
			callback: (response) => {
				const data = response.message || {};
				if (data.name) {
					frappe.set_route("Form", "RFQ Price Estimation Engine", data.name);
				}
			}
		});
	}

	clearRfqField() {
		this.rfqField.df.options = "";
		this.rfqField.refresh();
		this.rfqField.set_value("");
		this.clearRfqMandatoryState();
	}

	showRfqMandatoryState() {
		this.rfqField.$wrapper.addClass("rfq-mandatory-blink");
	}

	clearRfqMandatoryState() {
		this.rfqField.$wrapper.removeClass("rfq-mandatory-blink");
	}
}
