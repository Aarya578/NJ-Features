(function (global) {
	class RFQDashboardRenderer {
		constructor(root) {
			this.root = root;
			this.qualityGroupBy = "manufacturer_model";
			this.qualityRows = [];
			this.ensureStructure();
		}

		translate(text) {
			return typeof global.__ === "function" ? global.__(text) : text;
		}

		escape(value) {
			if (global.frappe && frappe.utils && frappe.utils.escape_html) {
				return frappe.utils.escape_html(value == null ? "" : String(value));
			}

			const element = document.createElement("div");
			element.textContent = value == null ? "" : String(value);
			return element.innerHTML;
		}

		format(value, decimals) {
			if (typeof global.format_number === "function") {
				return global.format_number(value || 0, null, decimals);
			}

			return Number(value || 0).toLocaleString(undefined, {
				minimumFractionDigits: decimals,
				maximumFractionDigits: decimals
			});
		}

		ensureStructure() {
			this.root.classList.add("rfq-shared-dashboard");

			if (!this.root.querySelector(".rfq-dashboard-summary")) {
				this.root.innerHTML = `
					<div class="rfq-dashboard-summary"></div>
					<div class="rfq-dashboard-items"></div>
					<div class="rfq-dashboard-quality"></div>
				`;
			}

			this.summary = this.root.querySelector(".rfq-dashboard-summary");
			this.items = this.root.querySelector(".rfq-dashboard-items");
			this.quality = this.root.querySelector(".rfq-dashboard-quality");
		}

		render(data) {
			this.renderSummary(data || {});
			this.renderItems((data && data.rows) || []);
			this.qualityRows = (data && data.quality_rows) || [];
			this.renderQuality();
		}

		renderSummary(data) {
			const cards = [
				{
					label: this.translate("Total RFQs"),
					value: this.format(data.total_rfqs, 0)
				},
				{
					label: this.translate("RFQ Qty"),
					value: this.format(data.total_qty, 2)
				},
				{
					label: this.translate("NJQCA Submitted"),
					value: this.format(data.total_submitted, 0)
				},
				{
					label: this.translate("Completion"),
					value: `${this.format(data.completion_percent, 2)}%`
				}
			];

			this.summary.innerHTML = cards
				.map(
					(card) => `
						<div class="rfq-dashboard-card">
							<div class="rfq-dashboard-card-label">${this.escape(card.label)}</div>
							<div class="rfq-dashboard-card-value">${this.escape(card.value)}</div>
						</div>
					`
				)
				.join("");
		}

		renderItems(rows) {
			if (!rows.length) {
				this.items.innerHTML = this.getMessageHtml(
					this.translate("No submitted NJQCA data found for this supplier.")
				);
				return;
			}

			this.items.innerHTML = `
				<div class="table-responsive">
					<table class="table table-bordered">
						<thead>
							<tr>
								<th>${this.translate("Items")}</th>
								<th class="text-right">${this.translate("Qty")}</th>
								<th class="text-right">${this.translate("Submitted")}</th>
								<th>${this.translate("Completion")}</th>
							</tr>
						</thead>
						<tbody>
							${rows.map((row) => this.getItemRowHtml(row)).join("")}
						</tbody>
					</table>
				</div>
			`;
		}

		getItemRowHtml(row) {
			const percent = Number(row.completion_percent || 0);
			const progressWidth = Math.min(Math.max(percent, 0), 100);

			return `
				<tr>
					<td><div class="rfq-dashboard-small">${this.escape(row.item_codes)}</div></td>
					<td class="text-right">${this.format(row.total_qty, 2)}</td>
					<td class="text-right">${this.format(row.submitted_count, 0)}</td>
					<td>
						<div class="rfq-dashboard-progress-wrap">
							<div class="rfq-dashboard-progress">
								<div class="rfq-dashboard-progress-bar"
									style="width: ${progressWidth}%"></div>
							</div>
							<span>${this.format(percent, 2)}%</span>
						</div>
					</td>
				</tr>
			`;
		}

		renderQuality() {
			const header = this.getQualityHeaderHtml();

			if (!this.qualityRows.length) {
				this.quality.innerHTML =
					header +
					this.getMessageHtml(
						this.translate("No Grade B, Grade C, or Grade D readings found for this supplier.")
					);
				this.bindQualityGroupBy();
				return;
			}

			const columns = this.getQualityColumns();
			const rows = this.getSortedQualityRows(columns);
			let previousSpecKey = "";
			let previousPrimaryValue = "";

			this.quality.innerHTML = `
				${header}
				<div class="table-responsive">
					<table class="table table-bordered">
						<thead>
							<tr>
								<th>${columns.primaryLabel}</th>
								<th>${columns.secondaryLabel}</th>
								<th>${this.translate("Grade")}</th>
								<th class="text-right">${this.translate("Count")}</th>
								<th>${this.translate("Serial Nos")}</th>
								<th>${this.translate("Processor Type")}</th>
								<th>${this.translate("RAM Capacity")}</th>
								<th>${this.translate("Storage Capacity")}</th>
							</tr>
						</thead>
						<tbody>
							${rows
								.map((row) => {
									const specKey = this.getQualitySpecKey(row);
									const primaryValue = row[columns.primaryField] || "";
									const showSpecs = specKey !== previousSpecKey;
									const showPrimaryValue = primaryValue !== previousPrimaryValue;
									previousSpecKey = specKey;
									previousPrimaryValue = primaryValue;
									return this.getQualityRowHtml(
										row,
										columns,
										showSpecs,
										showPrimaryValue
									);
								})
								.join("")}
						</tbody>
					</table>
				</div>
			`;

			this.bindQualityGroupBy();
		}

		getQualityHeaderHtml() {
			return `
				<div class="rfq-dashboard-section-header">
					<h3>${this.translate("Grade B/C/D Quality Summary")}</h3>
					<div class="rfq-dashboard-group-control">
						<label>${this.translate("Group By")}</label>
						<select class="form-control input-sm rfq-dashboard-group-by">
							<option value="manufacturer_model"
								${this.qualityGroupBy === "manufacturer_model" ? "selected" : ""}>
								${this.translate("Manufacturer Model")}
							</option>
							<option value="item_group"
								${this.qualityGroupBy === "item_group" ? "selected" : ""}>
								${this.translate("Item Group")}
							</option>
						</select>
					</div>
				</div>
			`;
		}

		bindQualityGroupBy() {
			const field = this.quality.querySelector(".rfq-dashboard-group-by");
			if (!field) {
				return;
			}

			field.addEventListener("change", (event) => {
				this.qualityGroupBy = event.currentTarget.value;
				this.renderQuality();
			});
		}

		getQualityColumns() {
			if (this.qualityGroupBy === "item_group") {
				return {
					primaryField: "item_group",
					primaryLabel: this.translate("Item Group"),
					secondaryField: "manufacturer_model",
					secondaryLabel: this.translate("Manufacturer Model")
				};
			}

			return {
				primaryField: "manufacturer_model",
				primaryLabel: this.translate("Manufacturer Model"),
				secondaryField: "item_group",
				secondaryLabel: this.translate("Item Group")
			};
		}

		getSortedQualityRows(columns) {
			return [...this.qualityRows].sort((first, second) => {
				const firstPrimary = String(first[columns.primaryField] || "").toLowerCase();
				const secondPrimary = String(second[columns.primaryField] || "").toLowerCase();
				const firstSecondary = String(first[columns.secondaryField] || "").toLowerCase();
				const secondSecondary = String(second[columns.secondaryField] || "").toLowerCase();

				if (firstPrimary !== secondPrimary) {
					return firstPrimary.localeCompare(secondPrimary);
				}

				if ((second.item_group_count || 0) !== (first.item_group_count || 0)) {
					return (second.item_group_count || 0) - (first.item_group_count || 0);
				}

				return firstSecondary.localeCompare(secondSecondary);
			});
		}

		getQualitySpecKey(row) {
			return [
				row.manufacturer_model || "",
				row.processor_type || "",
				row.ram_capacity || "",
				row.storage_capacity || ""
			].join("::");
		}

		getQualityRowHtml(row, columns, showSpecs, showPrimaryValue) {
			return `
				<tr>
					<td>${showPrimaryValue ? this.escape(row[columns.primaryField]) : ""}</td>
					<td>${this.escape(row[columns.secondaryField])}</td>
					<td>${this.escape(row.grade)}</td>
					<td class="text-right">${this.format(row.item_group_count, 0)}</td>
					<td><div class="rfq-dashboard-small">${this.escape(row.serial_nos)}</div></td>
					<td>${showSpecs ? this.escape(row.processor_type) : ""}</td>
					<td>${showSpecs ? this.escape(row.ram_capacity) : ""}</td>
					<td>${showSpecs ? this.escape(row.storage_capacity) : ""}</td>
				</tr>
			`;
		}

		getMessageHtml(message) {
			return `<div class="rfq-dashboard-message">${this.escape(message)}</div>`;
		}

		showMessage(message) {
			this.summary.innerHTML = "";
			this.items.innerHTML = this.getMessageHtml(message);
			this.quality.innerHTML = "";
		}

		showLoading() {
			this.summary.innerHTML = `
				<div class="rfq-dashboard-card">
					<div class="rfq-dashboard-card-label">${this.translate("Loading")}</div>
					<div class="rfq-dashboard-card-value">${this.translate("Please wait")}</div>
				</div>
			`;
			this.items.innerHTML = "";
			this.quality.innerHTML = "";
		}

		clear() {
			this.summary.innerHTML = "";
			this.items.innerHTML = "";
			this.quality.innerHTML = "";
			this.qualityRows = [];
		}
	}

	global.RFQDashboardRenderer = RFQDashboardRenderer;
})(window);
