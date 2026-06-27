frappe.pages["inventory_dashboard_"].on_page_load = function(wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "RFQ QC Dashboard",
		single_column: true
	});

	new RFQQCDashboard(page);
};

class RFQQCDashboard {
	constructor(page) {
		this.page = page;
		this.quality_group_by = "manufacturer_model";
		this.quality_rows = [];
		this.make_filters();
		this.make_body();
		this.render_empty_state();
	}

	make_filters() {
		this.supplier_field = this.page.add_field({
			fieldname: "supplier",
			label: __("Select Supplier"),
			fieldtype: "Link",
			options: "Supplier",
			change: () => {
				const supplier = this.supplier_field.get_value();
				if (supplier) {
					this.load_supplier_rfqs(supplier);
				} else {
					this.clear_rfq_field();
					this.render_empty_state();
				}
			}
		});

		this.rfq_field = this.page.add_field({
			fieldname: "rfq",
			label: __("Select RFQ"),
			fieldtype: "Select",
			options: "",
			change: () => {
				const supplier = this.supplier_field.get_value();
				const rfq = this.rfq_field.get_value();
				if (supplier && rfq) {
					this.clear_rfq_mandatory_state();
					this.load_data(supplier, rfq);
				} else if (supplier) {
					this.show_rfq_mandatory_state();
					this.clear_dashboard();
				}
			}
		});

		this.page.set_primary_action(__("Refresh"), () => {
			const supplier = this.supplier_field.get_value();
			const rfq = this.rfq_field.get_value();
			if (!supplier) {
				frappe.msgprint(__("Please select a supplier first."));
				return;
			}
			if (!rfq) {
				this.show_rfq_mandatory_state();
				frappe.msgprint(__("Please select RFQ name."));
				return;
			}
			this.load_data(supplier, rfq);
		});
	}

	make_body() {
		this.add_styles();
		this.$body = $(`
			<div class="rfq-qc-dashboard">
				<div class="rfq-qc-summary"></div>
				<div class="rfq-qc-table"></div>
				<div class="rfq-quality-section"></div>
			</div>
		`).appendTo(this.page.body);
	}

	add_styles() {
		if ($("#rfq-qc-dashboard-style").length) {
			return;
		}

		$(`<style id="rfq-qc-dashboard-style">
			.rfq-qc-dashboard {
				padding: 16px 0;
			}
			.rfq-qc-summary {
				display: grid;
				grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
				gap: 12px;
				margin-bottom: 16px;
			}
			.rfq-qc-card {
				border: 1px solid var(--border-color);
				border-radius: 8px;
				padding: 14px;
				background: var(--card-bg);
			}
			.rfq-qc-card .label {
				color: var(--text-muted);
				font-size: 12px;
				margin-bottom: 6px;
			}
			.rfq-qc-card .value {
				font-size: 24px;
				font-weight: 600;
				line-height: 1.2;
			}
			.rfq-qc-progress {
				height: 8px;
				background: var(--bg-light-gray);
				border-radius: 999px;
				overflow: hidden;
				min-width: 120px;
			}
			.rfq-qc-progress-bar {
				height: 100%;
				background: var(--primary);
			}
			.rfq-qc-empty {
				border: 1px dashed var(--border-color);
				border-radius: 8px;
				color: var(--text-muted);
				padding: 28px;
				text-align: center;
			}
			.rfq-qc-table .table {
				background: var(--card-bg);
			}
			.rfq-quality-section {
				margin-top: 24px;
			}
			.rfq-qc-section-header {
				align-items: center;
				display: flex;
				gap: 16px;
				justify-content: space-between;
				margin-bottom: 12px;
			}
			.rfq-qc-section-title {
				font-size: 16px;
				font-weight: 600;
				margin: 0;
			}
			.rfq-qc-group-control {
				align-items: center;
				display: flex;
				gap: 8px;
			}
			.rfq-qc-group-control label {
				color: var(--text-muted);
				font-size: 12px;
				margin: 0;
				white-space: nowrap;
			}
			.rfq-quality-group-by {
				min-width: 180px;
			}
			.rfq-mandatory-blink .form-control {
				animation: rfq-mandatory-pulse 1s ease-in-out infinite;
				border-color: var(--red-500, #ff5858) !important;
				box-shadow: 0 0 0 1px rgba(255, 88, 88, 0.25);
			}
			@keyframes rfq-mandatory-pulse {
				0%, 100% {
					box-shadow: 0 0 0 1px rgba(255, 88, 88, 0.2);
				}
				50% {
					box-shadow: 0 0 0 4px rgba(255, 88, 88, 0.35);
				}
			}
			.rfq-qc-small {
				color: var(--text-muted);
				font-size: 12px;
				max-width: 360px;
				white-space: normal;
			}
		</style>`).appendTo("head");
	}

	load_supplier_rfqs(supplier) {
		this.clear_rfq_field();
		this.clear_dashboard();

		frappe.call({
			method: "nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_.get_supplier_rfqs",
			args: { supplier },
			callback: (response) => {
				const rfqs = response.message || [];
				if (!rfqs.length) {
					frappe.msgprint(__("No RFQ name found for this supplier."));
					this.render_empty_state(__("No RFQ name found for this supplier."));
					return;
				}

				this.set_rfq_options(rfqs);
				this.show_rfq_mandatory_state();
				this.render_empty_state(__("Please select RFQ name to generate dashboard."));
			}
		});
	}

	load_data(supplier, rfq) {
		this.$body.find(".rfq-qc-summary").html(this.get_loading_html());
		this.$body.find(".rfq-quality-section").empty();

		frappe.call({
			method: "nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_.get_supplier_rfq_dashboard",
			args: { supplier, rfq },
			callback: (response) => {
				this.render_dashboard(response.message || {});
			}
		});
	}

	render_dashboard(data) {
		this.render_summary(data);
		this.render_table(data.rows || []);
		this.render_quality_table(data.quality_rows || []);
	}

	render_summary(data) {
		const cards = [
			{ label: __("Total RFQs"), value: this.format_count(data.total_rfqs || 0) },
			{ label: __("RFQ Qty"), value: this.format_number(data.total_qty || 0) },
			{ label: __("NJQCA Submitted"), value: this.format_count(data.total_submitted || 0) },
			{ label: __("Completion"), value: `${this.format_number(data.completion_percent || 0)}%` }
		];

		const html = cards.map((card) => `
			<div class="rfq-qc-card">
				<div class="label">${frappe.utils.escape_html(card.label)}</div>
				<div class="value">${frappe.utils.escape_html(String(card.value))}</div>
			</div>
		`).join("");

		this.$body.find(".rfq-qc-summary").html(html);
	}

	render_table(rows) {
		if (!rows.length) {
			this.$body.find(".rfq-qc-table").html(`
				<div class="rfq-qc-empty">
					${__("No submitted NJQCA data found for this supplier.")}
				</div>
			`);
			return;
		}

		const html = `
			<div class="table-responsive">
				<table class="table table-bordered">
					<thead>
						<tr>
							<th>${__("Items")}</th>
							<th class="text-right">${__("Qty")}</th>
							<th class="text-right">${__("Submitted")}</th>
							<th>${__("Completion")}</th>
						</tr>
					</thead>
					<tbody>
						${rows.map((row) => this.get_row_html(row)).join("")}
					</tbody>
				</table>
			</div>
		`;

		this.$body.find(".rfq-qc-table").html(html);
	}

	render_quality_table(rows) {
		if (rows) {
			this.quality_rows = rows;
		}

		const quality_rows = this.quality_rows || [];

		if (!quality_rows.length) {
			this.$body.find(".rfq-quality-section").html(`
				${this.get_quality_header_html()}
				<div class="rfq-qc-empty">
					${__("No Grade B, Grade C, or Grade D readings found for this supplier.")}
				</div>
			`);
			this.bind_quality_group_by();
			return;
		}

		const columns = this.get_quality_columns();
		const sorted_rows = this.get_sorted_quality_rows(quality_rows);
		let previous_spec_key = "";
		let previous_primary_value = "";
		const html = `
			${this.get_quality_header_html()}
			<div class="table-responsive">
				<table class="table table-bordered">
					<thead>
						<tr>
							<th>${columns.primary_label}</th>
							<th>${columns.secondary_label}</th>
							<th>${__("Grade")}</th>
							<th class="text-right">${__("Count")}</th>
							<th>${__("Serial Nos")}</th>
							<th>${__("Processor Type")}</th>
							<th>${__("RAM Capacity")}</th>
							<th>${__("Storage Capacity")}</th>
						</tr>
					</thead>
					<tbody>
						${sorted_rows.map((row) => {
							const spec_key = this.get_quality_spec_key(row);
							const primary_value = row[columns.primary_field] || "";
							const show_specs = spec_key !== previous_spec_key;
							const show_primary_value = primary_value !== previous_primary_value;
							previous_spec_key = spec_key;
							previous_primary_value = primary_value;
							return this.get_quality_row_html(row, columns, show_specs, show_primary_value);
						}).join("")}
					</tbody>
				</table>
			</div>
		`;

		this.$body.find(".rfq-quality-section").html(html);
		this.bind_quality_group_by();
	}

	get_quality_header_html() {
		return `
			<div class="rfq-qc-section-header">
				<div class="rfq-qc-section-title">${__("Grade B/C/D Quality Summary")}</div>
				<div class="rfq-qc-group-control">
					<label>${__("Group By")}</label>
					<select class="form-control input-sm rfq-quality-group-by">
						<option value="manufacturer_model" ${this.quality_group_by === "manufacturer_model" ? "selected" : ""}>
							${__("Manufacturer Model")}
						</option>
						<option value="item_group" ${this.quality_group_by === "item_group" ? "selected" : ""}>
							${__("Item Group")}
						</option>
					</select>
				</div>
			</div>
		`;
	}

	bind_quality_group_by() {
		this.$body.find(".rfq-quality-group-by").on("change", (event) => {
			this.quality_group_by = event.currentTarget.value;
			this.render_quality_table();
		});
	}

	get_quality_columns() {
		if (this.quality_group_by === "item_group") {
			return {
				primary_field: "item_group",
				primary_label: __("Item Group"),
				secondary_field: "manufacturer_model",
				secondary_label: __("Manufacturer Model")
			};
		}

		return {
			primary_field: "manufacturer_model",
			primary_label: __("Manufacturer Model"),
			secondary_field: "item_group",
			secondary_label: __("Item Group")
		};
	}

	get_sorted_quality_rows(rows) {
		const columns = this.get_quality_columns();

		return [...rows].sort((first, second) => {
			const first_primary = (first[columns.primary_field] || "").toLowerCase();
			const second_primary = (second[columns.primary_field] || "").toLowerCase();
			const first_secondary = (first[columns.secondary_field] || "").toLowerCase();
			const second_secondary = (second[columns.secondary_field] || "").toLowerCase();

			if (first_primary !== second_primary) {
				return first_primary.localeCompare(second_primary);
			}

			if ((second.item_group_count || 0) !== (first.item_group_count || 0)) {
				return (second.item_group_count || 0) - (first.item_group_count || 0);
			}

		return first_secondary.localeCompare(second_secondary);
		});
	}

	get_quality_spec_key(row) {
		return [
			row.manufacturer_model || "",
			row.processor_type || "",
			row.ram_capacity || "",
			row.storage_capacity || ""
		].join("::");
	}

	get_quality_row_html(row, columns, show_specs, show_primary_value) {
		return `
			<tr>
				<td>${this.get_quality_cell_value(row, columns.primary_field, show_primary_value)}</td>
				<td>${frappe.utils.escape_html(row[columns.secondary_field] || "")}</td>
				<td>${frappe.utils.escape_html(row.grade || "")}</td>
				<td class="text-right">${this.format_count(row.item_group_count || 0)}</td>
				<td><div class="rfq-qc-small">${frappe.utils.escape_html(row.serial_nos || "")}</div></td>
				<td>${show_specs ? frappe.utils.escape_html(row.processor_type || "") : ""}</td>
				<td>${show_specs ? frappe.utils.escape_html(row.ram_capacity || "") : ""}</td>
				<td>${show_specs ? frappe.utils.escape_html(row.storage_capacity || "") : ""}</td>
			</tr>
		`;
	}

	get_quality_cell_value(row, fieldname, show_value) {
		if (!show_value) {
			return "";
		}

		return frappe.utils.escape_html(row[fieldname] || "");
	}

	get_row_html(row) {
		const percent = row.completion_percent || 0;

		return `
			<tr>
				<td><div class="rfq-qc-small">${frappe.utils.escape_html(row.item_codes || "")}</div></td>
				<td class="text-right">${this.format_number(row.total_qty || 0)}</td>
				<td class="text-right">${this.format_count(row.submitted_count || 0)}</td>
				<td>
					<div class="d-flex align-items-center" style="gap: 8px;">
						<div class="rfq-qc-progress">
							<div class="rfq-qc-progress-bar" style="width: ${Math.min(percent, 100)}%;"></div>
						</div>
						<span>${this.format_number(percent)}%</span>
					</div>
				</td>
			</tr>
		`;
	}

	render_empty_state() {
		const message = arguments.length ? arguments[0] : __("Select a supplier to generate the RFQ QC dashboard.");

		if (!this.$body) {
			return;
		}

		this.$body.find(".rfq-qc-summary").empty();
		this.$body.find(".rfq-quality-section").empty();
		this.$body.find(".rfq-qc-table").html(`
			<div class="rfq-qc-empty">
				${message}
			</div>
		`);
	}

	clear_dashboard() {
		this.$body.find(".rfq-qc-summary").empty();
		this.$body.find(".rfq-qc-table").empty();
		this.$body.find(".rfq-quality-section").empty();
	}

	clear_rfq_field() {
		if (!this.rfq_field) {
			return;
		}

		this.rfq_field.df.options = "";
		this.rfq_field.refresh();
		this.rfq_field.set_value("");
		this.clear_rfq_mandatory_state();
	}

	set_rfq_options(rfqs) {
		this.rfq_field.df.options = ["", ...rfqs.map((row) => row.name)].join("\n");
		this.rfq_field.refresh();
		this.rfq_field.set_value("");
	}

	show_rfq_mandatory_state() {
		this.rfq_field.$wrapper.addClass("rfq-mandatory-blink");
	}

	clear_rfq_mandatory_state() {
		this.rfq_field.$wrapper.removeClass("rfq-mandatory-blink");
	}

	get_loading_html() {
		return `
			<div class="rfq-qc-card">
				<div class="label">${__("Loading")}</div>
				<div class="value">${__("Please wait")}</div>
			</div>
		`;
	}

	format_number(value) {
		return format_number(value, null, 2);
	}

	format_count(value) {
		return format_number(value, null, 0);
	}
}
