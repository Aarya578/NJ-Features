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
					this.load_data(supplier);
				} else {
					this.render_empty_state();
				}
			}
		});

		this.page.set_primary_action(__("Refresh"), () => {
			const supplier = this.supplier_field.get_value();
			if (!supplier) {
				frappe.msgprint(__("Please select a supplier first."));
				return;
			}
			this.load_data(supplier);
		});
	}

	make_body() {
		this.add_styles();
		this.$body = $(`
			<div class="rfq-qc-dashboard">
				<div class="rfq-qc-summary"></div>
				<div class="rfq-qc-table"></div>
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
			.rfq-qc-small {
				color: var(--text-muted);
				font-size: 12px;
				max-width: 360px;
				white-space: normal;
			}
		</style>`).appendTo("head");
	}

	load_data(supplier) {
		this.$body.find(".rfq-qc-summary").html(this.get_loading_html());
		this.$body.find(".rfq-qc-table").empty();

		frappe.call({
			method: "nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_.get_supplier_rfq_dashboard",
			args: { supplier },
			callback: (response) => {
				this.render_dashboard(response.message || {});
			}
		});
	}

	render_dashboard(data) {
		this.render_summary(data);
		this.render_table(data.rows || []);
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
							<th>${__("RFQ")}</th>
							<th>${__("Items")}</th>
							<th class="text-right">${__("Qty")}</th>
							<th class="text-right">${__("Submitted")}</th>
							<th>${__("Completion")}</th>
							<th>${__("Serial Nos")}</th>
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

	get_row_html(row) {
		const percent = row.completion_percent || 0;

		return `
			<tr>
				<td>
					<a href="/app/request-for-quotation/${encodeURIComponent(row.rfq)}">
						${frappe.utils.escape_html(row.rfq || "")}
					</a>
					<div class="rfq-qc-small">${frappe.utils.escape_html(row.status || "")}</div>
				</td>
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
				<td><div class="rfq-qc-small">${frappe.utils.escape_html(row.serial_nos || "")}</div></td>
			</tr>
		`;
	}

	render_empty_state() {
		if (!this.$body) {
			return;
		}

		this.$body.find(".rfq-qc-summary").empty();
		this.$body.find(".rfq-qc-table").html(`
			<div class="rfq-qc-empty">
				${__("Select a supplier to generate the RFQ QC dashboard.")}
			</div>
		`);
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
