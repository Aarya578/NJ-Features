frappe.pages["purchase-plan-combos"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Purchase Plan Combos"),
		single_column: true,
	});

	new PurchasePlanCombos(page);
};

class PurchasePlanCombos {
	constructor(page) {
		this.page = page;
		this.render();
		this.load_rows();
	}

	render() {
		this.add_styles();
		this.page.main.html(`
			<div class="purchase-plan-combos">
				<div class="purchase-plan-table-wrap">
					<table class="purchase-plan-table" aria-label="${__("Purchase Plan Combos")}">
						<thead>
							<tr>
								<th class="group-product col-price">${__("Price (₹K)")}</th>
								<th class="group-product col-brand">${__("Brand")}</th>
								<th class="group-product col-model">${__("Model")}</th>
								<th class="group-product col-processor">${__("Processor")}</th>
								<th class="group-product col-touch">${__("Touch")}</th>
								<th class="group-product col-usage">${__("Usage")}</th>
								<th class="group-product col-size">${__("Size")}</th>
								<th class="group-stock col-example">${__("Example models")}</th>
								<th class="group-stock col-processor-sih">${__("Processors >5 SIH")}</th>
								<th class="group-stock col-model-sih">${__("Models SIH >5")}</th>
								<th class="group-stock vertical">${__("SIH - SO")}</th>
								<th class="status-green vertical">${__("Green")}</th>
								<th class="status-light-green vertical">${__("Light Green")}</th>
								<th class="status-yellow vertical">${__("Yellow")}</th>
								<th class="status-red vertical">${__("Red")}</th>
								<th class="status-grey vertical">${__("Gry")}</th>
								<th class="status-other vertical">${__("Other")}</th>
								<th class="group-stock vertical">${__("RTS - SO")}</th>
								<th class="group-stock vertical">${__(">20 Mtd")}</th>
								<th class="group-stock vertical">${__("Not Mapped")}</th>
								<th class="group-stock vertical">${__("RR")}</th>
								<th class="group-stock vertical">${__("Prchse")}</th>
								<th class="group-stock vertical">${__("PO")}</th>
								<th class="group-stock vertical">${__("DOI")}</th>
								<th class="group-stock vertical">${__("Action")}</th>
								<th class="group-stock vertical">${__("Unknown")}</th>
								<th class="group-stock vertical">${__("NO Ram/Disk")}</th>
								<th class="group-stock vertical">${__("Light Green")}</th>
								<th class="group-stock vertical">${__("Yellow")}</th>
								<th class="group-stock vertical">${__("Red")}</th>
								<th class="group-stock vertical">${__("Light Green")}</th>
								<th class="group-stock vertical">${__("Yellow")}</th>
								<th class="group-stock vertical">${__("Red")}</th>
								<th class="group-stock vertical">${__("Partwait")}</th>
								<th class="group-stock vertical">${__("Allocation")}</th>
								<th class="group-stock vertical">${__("Net purchase")}</th>
								<th class="group-stock vertical">${__("Item-group")}</th>
								<th class="group-stock vertical">${__("Ready")}</th>
								<th class="group-stock vertical">${__("Open SO")}</th>
								<th class="group-stock vertical">${__("RTS Open SO")}</th>
								<th class="group-stock vertical">${__("SIH Open SO")}</th>
								<th class="group-stock vertical">${__("↑ Target days")}</th>
								<th class="group-stock vertical">${__("10")}</th>
								<th class="group-stock vertical">${__("15")}</th>
								<th class="group-stock vertical">${__("20")}</th>
								<th class="group-stock vertical">${__("25")}</th>
								<th class="group-stock vertical">${__("30")}</th>
								<th class="group-stock vertical">${__("↑ Seed qty")}</th>
								<th class="group-stock vertical">${__("Primary SIH")}</th>
								<th class="group-stock vertical">${__("Substitute SIH")}</th>
								<th class="group-stock vertical">${__("Substitute %")}</th>
								<th class="group-stock vertical">${__("Primary Ready")}</th>
								<th class="group-stock vertical">${__("Substitute Ready")}</th>
							</tr>
						</thead>
						<tbody>
							<tr class="purchase-plan-message-row">
								<td colspan="53">${__("Loading Product Sufficiency Plan...")}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		`);
		this.$table = this.page.main.find(".purchase-plan-table");
		this.total_columns = this.$table.find("thead th").length;
	}

	load_rows() {
		frappe.call({
			method: "nj_features.nj_features.page.purchase_plan_combos.purchase_plan_combos.get_product_sufficiency_plan",
			callback: (response) => this.render_rows(response.message || []),
			error: () => this.render_message(__("Unable to load Product Sufficiency Plan.")),
		});
	}

	render_rows(rows) {
		if (!rows.length) {
			this.render_message(__("No Product Sufficiency Plan rows found in Logistics Settings."));
			return;
		}

		const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
		const empty_cells = Math.max(this.total_columns - 10, 0);
		const html = rows.map((row) => `
			<tr>
				<td>${escape(row.price)}</td>
				<td>${escape(row.brand)}</td>
				<td>${escape(row.model)}</td>
				<td>${escape(row.processor)}</td>
				<td>${escape(row.touch)}</td>
				<td>${escape(row.usage)}</td>
				<td>${escape(row.size)}</td>
				<td>${escape(row.example_models)}</td>
				<td>${escape(row.processors_sih)}</td>
				<td>${escape(row.models_sih)}</td>
				${"<td></td>".repeat(empty_cells)}
			</tr>
		`).join("");

		this.$table.find("tbody").html(html);
	}

	render_message(message) {
		this.$table.find("tbody").html(`
			<tr class="purchase-plan-message-row">
				<td colspan="${this.total_columns}">${frappe.utils.escape_html(message)}</td>
			</tr>
		`);
	}

	add_styles() {
		if (document.getElementById("purchase-plan-combos-styles")) {
			return;
		}

		$("<style>", {
			id: "purchase-plan-combos-styles",
			text: `
				.purchase-plan-combos {
					padding: 15px;
				}

				.purchase-plan-table-wrap {
					background: var(--card-bg, #fff);
					border: 1px solid var(--border-color, #d1d8dd);
					border-radius: var(--border-radius-md, 6px);
					overflow-x: auto;
					width: 100%;
				}

				.purchase-plan-table {
					border-collapse: separate;
					border-spacing: 0;
					min-width: 1640px;
					width: 100%;
				}

				.purchase-plan-table th {
					border-bottom: 3px solid var(--border-color, #d1d8dd);
					color: #fff;
					font-size: 12px;
					font-weight: 700;
					height: 82px;
					line-height: 1.15;
					padding: 10px 8px;
					text-align: left;
					vertical-align: middle;
					white-space: nowrap;
				}

				.purchase-plan-table .group-product { background: #7e1647; }
				.purchase-plan-table .group-stock { background: #117daf; }
				.purchase-plan-table .status-green { background: #70ad47; }
				.purchase-plan-table .status-light-green { background: #a9d18e; color: #111; }
				.purchase-plan-table .status-yellow { background: #ffe699; color: #111; }
				.purchase-plan-table .status-red { background: #e06666; }
				.purchase-plan-table .status-grey { background: #d9d9d9; color: #111; }
				.purchase-plan-table .status-other { background: #f2f2f2; color: #111; }

				.purchase-plan-table .vertical {
					min-width: 36px;
					padding: 6px 4px;
					text-align: center;
					width: 36px;
					writing-mode: vertical-rl;
					transform: rotate(180deg);
				}

				.purchase-plan-table .col-price { min-width: 76px; white-space: normal; }
				.purchase-plan-table .col-brand { min-width: 70px; }
				.purchase-plan-table .col-model { min-width: 88px; }
				.purchase-plan-table .col-processor { min-width: 105px; }
				.purchase-plan-table .col-touch,
				.purchase-plan-table .col-usage,
				.purchase-plan-table .col-size { min-width: 58px; }
				.purchase-plan-table .col-example { min-width: 175px; }
				.purchase-plan-table .col-processor-sih { min-width: 210px; }
				.purchase-plan-table .col-model-sih { min-width: 175px; }

				.purchase-plan-table tbody td {
					background: var(--card-bg);
					border-bottom: 1px solid var(--border-color, #d1d8dd);
					color: var(--text-color, #171717);
					height: 42px;
					padding: 8px;
					white-space: nowrap;
				}

				.purchase-plan-table tbody tr:nth-child(even) td {
					background: var(--control-bg);
				}

				.purchase-plan-table .purchase-plan-message-row td {
					color: var(--text-muted, #6c7680);
					height: 90px;
					text-align: center;
				}

				@media (max-width: 767px) {
					.purchase-plan-combos { padding: 10px 0; }
				}
			`,
		}).appendTo("head");
	}
}
