frappe.pages["rfq-dashboard-comparison"].on_page_load = function(wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("RFQ Dashboard Comparison"),
		single_column: true
	});

	new RFQDashboardComparison(page);
};

class RFQDashboardComparison {
	constructor(page) {
		this.page = page;
		this.makeBody();
		this.makeRfqField();
		this.resetSummary();
	}

	makeBody() {
		this.addStyles();
		this.$body = $(
			`<div class="rfq-comparison-dashboard">
				<div class="rfq-comparison-heading">
					<div>
						<p>${__("Compare supplier quotes and decide optimal purchase quantities")}</p>
					</div>
					<div class="rfq-comparison-actions">
						<button class="btn rfq-verdict-button" type="button">
							<span class="rfq-action-icon">✦</span>
							<span><strong>${__("Generate Verdict")}</strong><small>${__("Auto-calculate best options")}</small></span>
						</button>
						<button class="btn btn-primary rfq-purchase-button" type="button">
							<span class="rfq-action-icon">🛒</span>
							<span><strong>${__("Generate Purchase Order")}</strong><small>${__("Create PO from verdict")}</small></span>
						</button>
					</div>
				</div>
				<div class="rfq-comparison-summary-panel">
					<div class="rfq-selector-cell">
						<label>${__("Select RFQ")}</label>
						<div class="rfq-selector-control"></div>
					</div>
					<div class="rfq-summary-divider"></div>
					<div class="rfq-summary-value" data-field="rfq_date"></div>
					<div class="rfq-summary-value" data-field="required_date"></div>
					<div class="rfq-summary-value" data-field="total_items"></div>
					<div class="rfq-summary-value" data-field="total_qty_required"></div>
					<div class="rfq-summary-value" data-field="total_rate"></div>
				</div>
				<div class="rfq-item-details-section"></div>
			</div>`
		).appendTo(this.page.body);

		this.$body.find(".rfq-verdict-button").on("click", (event) => {
			event.preventDefault();
			if (!this.currentItems) {
				return;
			}
			this.verdictState = {};
			this.activeVerdictItem = null;
			this.renderItems(this.currentItems, this.currentSuppliers);
			frappe.show_alert({ message: __("Verdict recalculated."), indicator: "green" });
		});
		this.$body.find(".rfq-purchase-button").on("click", (event) => {
			event.preventDefault();
			this.confirmAndGeneratePurchaseOrders();
		});
	}

	confirmAndGeneratePurchaseOrders() {
		const rfq = this.rfqField && this.rfqField.get_value();
		if (!rfq || !this.currentItems || !this.currentSuppliers) {
			frappe.msgprint(__("Please select an RFQ first."));
			return;
		}

		const verdict = [];
		this.currentItems.forEach((item) => {
			(this.verdictState[item.name] || []).forEach((allocation) => {
				const qty = Number(allocation.qty || 0);
				if (qty > 0) {
					verdict.push({
						rfq_item: item.name,
						supplier_quotation: allocation.supplier_quotation,
						qty
					});
				}
			});
		});

		if (!verdict.length) {
			frappe.msgprint(__("The Verdict does not contain any quantities to purchase."));
			return;
		}

		frappe.confirm(
			__("Create and submit Purchase Orders from the current Verdict?"),
			() => this.generatePurchaseOrders(rfq, verdict)
		);
	}

	generatePurchaseOrders(rfq, verdict) {
		frappe.call({
			method: "nj_features.nj_features.page.rfq_dashboard_comparison.rfq_dashboard_comparison.generate_purchase_orders",
			args: {
				rfq,
				verdict: JSON.stringify(verdict)
			},
			freeze: true,
			freeze_message: __("Creating and submitting Purchase Orders..."),
			callback: (response) => {
				const result = response.message || {};
				const created = result.created || [];
				const skipped = result.skipped || [];
				const createdHtml = created.map((row) => `
					<li>
						${frappe.utils.escape_html(row.supplier)}:
						<a href="/app/purchase-order/${encodeURIComponent(row.purchase_order)}">
							${frappe.utils.escape_html(row.purchase_order)}
						</a>
					</li>
				`).join("");
				const skippedHtml = skipped.map((row) => `
					<li>
						${frappe.utils.escape_html(row.supplier)}:
						${frappe.utils.escape_html(row.purchase_order)}
						(${frappe.utils.escape_html(row.status)})
					</li>
				`).join("");
				const sections = [];
				if (createdHtml) {
					sections.push(`<p><strong>${__("Created and submitted")}</strong></p><ul>${createdHtml}</ul>`);
				}
				if (skippedHtml) {
					sections.push(`<p><strong>${__("Skipped because an active PO already exists")}</strong></p><ul>${skippedHtml}</ul>`);
				}
				frappe.msgprint({
					title: __("Purchase Order Generation"),
					indicator: created.length ? "green" : "orange",
					message: sections.join("") || __("No Purchase Orders were created.")
				});
				this.loadSummary(rfq);
			}
		});
	}

	makeRfqField() {
		this.rfqField = frappe.ui.form.make_control({
			parent: this.$body.find(".rfq-selector-control"),
			df: {
				fieldname: "rfq",
				fieldtype: "Link",
				options: "Request for Quotation",
				placeholder: __("Select RFQ"),
				get_query: () => ({ filters: { docstatus: ["<", 2] } }),
				onchange: () => {
					const rfq = this.rfqField.get_value();
					if (rfq) {
						this.loadSummary(rfq);
					} else {
						this.resetSummary();
					}
				}
			},
			render_input: true
		});
		this.rfqField.refresh();
	}

	loadSummary(rfq) {
		this.verdictState = {};
		this.activeVerdictItem = null;
		this.$body.find(".rfq-comparison-summary-panel").addClass("rfq-summary-loading");
		frappe.call({
			method: "nj_features.nj_features.page.rfq_dashboard_comparison.rfq_dashboard_comparison.get_rfq_summary",
			args: { rfq },
			callback: (response) => this.renderSummary(response.message || {}),
			always: () => {
				this.$body.find(".rfq-comparison-summary-panel").removeClass("rfq-summary-loading");
			}
		});
	}

	renderSummary(data) {
		const formatDate = (value) => value ? frappe.datetime.str_to_user(value) : "—";
		const formatNumber = (value) => format_number(value || 0, null, 2);
		const formatCurrency = (value, currency) => format_currency(value || 0, currency);

		this.setSummaryValue("rfq_date", __("RFQ Date"), formatDate(data.rfq_date));
		this.setSummaryValue("required_date", __("Required Date"), formatDate(data.required_date));
		this.setSummaryValue("total_items", __("Total Items"), format_number(data.total_items || 0));
		this.setSummaryValue(
			"total_qty_required",
			__("Total Qty Required"),
			formatNumber(data.total_qty_required)
		);
		this.setSummaryValue(
			"total_rate",
			__("Currency"),
			formatCurrency(data.total_rate, data.currency)
		);
		this.currentPurchaseOrders = data.purchase_orders || [];
		this.renderItems(data.items || [], data.suppliers || []);
	}

	resetSummary() {
		this.setSummaryValue("rfq_date", __("RFQ Date"), "—");
		this.setSummaryValue("required_date", __("Required Date"), "—");
		this.setSummaryValue("total_items", __("Total Items"), "0");
		this.setSummaryValue("total_qty_required", __("Total Qty Required"), "0.00");
		this.setSummaryValue("total_rate", __("Currency"), "—");
		this.currentPurchaseOrders = [];
		this.$body.find(".rfq-item-details-section").empty();
	}

	renderItems(items, suppliers) {
		this.currentItems = items;
		this.currentSuppliers = suppliers;
		const $section = this.$body.find(".rfq-item-details-section");
		const previousScrollLeft = $section.find(".rfq-supplier-scroll").scrollLeft() || 0;
		if (!items.length) {
			$section.html(`<div class="rfq-items-empty">${__("No RFQ items found.")}</div>`);
			return;
		}

		const getSupplierItem = (supplier, rfqItem) => {
			return supplier.items.find(
				(item) => item.request_for_quotation_item === rfqItem.name
			) || supplier.items.find((item) => item.item_code === rfqItem.item_code) || {};
		};
		const displayValue = (value, formatter) => {
			return value === undefined || value === null || value === "" ? "—" : formatter(value);
		};
		const formatCompactNumber = (value) => Number(value || 0).toLocaleString(undefined, {
			maximumFractionDigits: 2
		});
		const getCandidates = (rfqItem) => suppliers.map((supplier) => ({
			supplier,
			item: getSupplierItem(supplier, rfqItem)
		})).filter((candidate) => candidate.item.item_code);
		const buildAutoAllocations = (rfqItem) => {
			let remainingQty = Number(rfqItem.qty || 0);
			const candidates = getCandidates(rfqItem)
				.filter((candidate) =>
					String(candidate.item.availability || "").toLowerCase() === "yes" &&
					Number(candidate.item.available_qty || 0) > 0 &&
					Number(candidate.item.rate || 0) > 0
				)
				.sort((left, right) =>
					Number(left.item.rate) - Number(right.item.rate) ||
					Number(left.supplier.lead_days ?? Number.MAX_SAFE_INTEGER) -
						Number(right.supplier.lead_days ?? Number.MAX_SAFE_INTEGER) ||
					Number(right.item.available_qty) - Number(left.item.available_qty)
				);
			const allocations = [];

			for (const candidate of candidates) {
				if (remainingQty <= 0) {
					break;
				}
				const qty = Math.min(remainingQty, Number(candidate.item.available_qty));
				allocations.push({
					supplier_quotation: candidate.supplier.supplier_quotation,
					qty
				});
				remainingQty -= qty;
			}

			return allocations;
		};
		items.forEach((item) => {
			if (!this.verdictState[item.name]) {
				this.verdictState[item.name] = buildAutoAllocations(item);
			}
		});
		const supplierHeaders = suppliers.map((supplier, index) => `
			<th class="rfq-supplier-heading${index % 2 ? " rfq-supplier-alternate" : ""}" colspan="4">
				<strong>${__("Supplier {0}", [index + 1])}</strong>
				<span>${frappe.utils.escape_html(supplier.supplier || "")}</span>
			</th>
		`).join("");
		const supplierSubHeaders = suppliers.map((supplier, index) => {
			const alternateClass = index % 2 ? " class=\"rfq-supplier-alternate\"" : "";
			return `
			<th${alternateClass}>${__("Rate")}</th>
			<th${alternateClass}>${__("Qty Offered")}</th>
			<th${alternateClass}>${__("Lead Time")}</th>
			<th${alternateClass}>${__("Available")}</th>
		`;
		}).join("");
		const itemRows = items.map((rfqItem) => `
			<tr>
				<td class="rfq-item-code"><strong>${frappe.utils.escape_html(rfqItem.item_code || "")}</strong></td>
				<td class="rfq-item-qty">${formatCompactNumber(rfqItem.qty)}</td>
			</tr>
		`).join("");
		const supplierRows = items.map((rfqItem) => {
			const supplierCells = suppliers.map((supplier, supplierIndex) => {
				const item = getSupplierItem(supplier, rfqItem);
				const rate = displayValue(item.rate, (value) => format_currency(value, supplier.currency));
				const offeredQty = displayValue(item.available_qty, formatCompactNumber);
				const leadDays = item.item_code ? supplier.lead_days : null;
				const leadTime = displayValue(leadDays, (value) => `${formatCompactNumber(value)} ${__("Days")}`);
				const availability = displayValue(
					item.availability,
					(value) => frappe.utils.escape_html(value)
				);
				const availabilityValue = String(item.availability || "").toLowerCase();
				const availabilityClass = availabilityValue === "yes"
					? " is-available"
					: availabilityValue === "no" ? " is-unavailable" : "";
				const alternateClass = supplierIndex % 2 ? " rfq-supplier-alternate" : "";

				return `
					<td class="rfq-supplier-rate${alternateClass}">${rate}</td>
					<td class="${alternateClass.trim()}">${offeredQty}</td>
					<td class="rfq-lead-time${alternateClass}">${leadTime}</td>
					<td class="rfq-availability${availabilityClass}${alternateClass}">${availability}</td>
				`;
			}).join("");

			return `
				<tr>
					${supplierCells}
				</tr>
			`;
		}).join("");
		const supplierCard = suppliers.length ? `
			<div class="rfq-supplier-details-card">
				<table>
					<thead>
						<tr>${supplierHeaders}</tr>
						<tr>${supplierSubHeaders}</tr>
					</thead>
					<tbody>${supplierRows}</tbody>
				</table>
			</div>
		` : "";
		const verdictRows = items.map((rfqItem) => {
			const allocations = this.verdictState[rfqItem.name];
			const isEditing = this.activeVerdictItem === rfqItem.name;
			const disabledAttribute = isEditing ? "" : "disabled";
			const candidates = getCandidates(rfqItem);
			const supplierOptions = (selectedQuotation) => candidates.map((candidate) => `
				<option value="${frappe.utils.escape_html(candidate.supplier.supplier_quotation)}"
					${candidate.supplier.supplier_quotation === selectedQuotation ? "selected" : ""}>
					${frappe.utils.escape_html(candidate.supplier.supplier || "")}
				</option>
			`).join("");
			let totalQty = 0;
			let weightedAmount = 0;
			let verdictCurrency = suppliers[0] ? suppliers[0].currency : null;
			const supplierControls = [];
			const quantityControls = [];
			allocations.forEach((allocation, index) => {
				const supplier = suppliers.find(
					(row) => row.supplier_quotation === allocation.supplier_quotation
				);
				const supplierItem = supplier ? getSupplierItem(supplier, rfqItem) : {};
				const qty = Math.max(0, Number(allocation.qty || 0));
				totalQty += qty;
				weightedAmount += Number(supplierItem.rate || 0) * qty;
				verdictCurrency = supplier ? supplier.currency : verdictCurrency;

				supplierControls.push(`
					<select class="form-control rfq-verdict-supplier" data-item="${rfqItem.name}" data-index="${index}" ${disabledAttribute}>
							${supplierOptions(allocation.supplier_quotation)}
					</select>
				`);
				quantityControls.push(`
					<input class="form-control rfq-verdict-qty" data-item="${rfqItem.name}" data-index="${index}"
							type="number" min="0" step="any" value="${qty}" ${disabledAttribute}>
				`);
			});
			const supplierControlHtml = supplierControls.length
				? supplierControls.join("")
				: `<div class="rfq-verdict-shortage">${__("No available supplier")}</div>`;
			const quantityControlHtml = quantityControls.join("") || "—";
			const shortage = Math.max(0, Number(rfqItem.qty || 0) - totalQty);
			const estimatedRate = totalQty ? weightedAmount / totalQty : 0;

			return `
				<tr class="${isEditing ? "is-active" : ""}" data-verdict-row="${rfqItem.name}">
					<td class="rfq-verdict-buy-from">${supplierControlHtml}</td>
					<td class="rfq-verdict-qty-to-buy">
						${quantityControlHtml}
						<div class="rfq-verdict-total">
							${__("Total")}: <strong>${formatCompactNumber(totalQty)}</strong>
							${shortage ? `<span>${__("Shortage")}: ${formatCompactNumber(shortage)}</span>` : ""}
						</div>
					</td>
					<td class="rfq-verdict-est-rate">${totalQty ? format_currency(estimatedRate, verdictCurrency) : "—"}</td>
					<td class="rfq-verdict-actions">
						<button class="btn btn-xs btn-default rfq-verdict-edit ${isEditing ? "is-active" : ""}" data-item="${rfqItem.name}" title="${isEditing ? __("Lock recommendation") : __("Edit recommendation")}">✎</button>
					</td>
				</tr>
			`;
		}).join("");
		const verdictCard = suppliers.length ? `
			<div class="rfq-verdict-card">
				<table>
					<thead>
						<tr><th class="rfq-verdict-heading" colspan="4"><strong>${__("Verdict (Recommended)")}</strong><span>${__("Auto-generated")}&nbsp;&nbsp;•&nbsp;&nbsp;${__("Editable")}</span></th></tr>
						<tr><th>${__("Buy From (Multiple Allowed)")}</th><th>${__("Qty to Buy")}</th><th>${__("Est. Rate")}</th><th>${__("Actions")}</th></tr>
					</thead>
					<tbody>${verdictRows}</tbody>
				</table>
				<div class="rfq-verdict-footer">
					<button class="btn btn-xs btn-default rfq-add-supplier-split">＋ ${__("Add Supplier Split")}</button>
					<span>${__("Select an item with the pencil, then add a split")}</span>
				</div>
			</div>
		` : "";
		const estimatedTotals = items.reduce((summary, rfqItem) => {
			summary.totalRequired += Number(rfqItem.qty || 0);
			(this.verdictState[rfqItem.name] || []).forEach((allocation) => {
				const supplier = suppliers.find(
					(row) => row.supplier_quotation === allocation.supplier_quotation
				);
				const supplierItem = supplier ? getSupplierItem(supplier, rfqItem) : {};
				const qty = Math.max(0, Number(allocation.qty || 0));
				summary.totalToBuy += qty;
				summary.totalSpend += Number(supplierItem.rate || 0) * qty;
				summary.weightedLeadDays += Number(supplier?.lead_days || 0) * qty;
			});
			return summary;
		}, {
			totalRequired: 0,
			totalToBuy: 0,
			totalSpend: 0,
			weightedLeadDays: 0
		});
		const averageLeadTime = estimatedTotals.totalToBuy
			? estimatedTotals.weightedLeadDays / estimatedTotals.totalToBuy
			: 0;
		const summaryCurrency = suppliers[0] ? suppliers[0].currency : null;
		const estimatedSummary = `
			<div class="rfq-estimated-summary">
				<div class="rfq-estimated-summary-title">${__("Summary")} <span>(${__("Estimated")})</span></div>
				<div class="rfq-estimated-metric"><span>${__("Total Items")}</span><strong>${formatCompactNumber(items.length)}</strong></div>
				<div class="rfq-estimated-metric"><span>${__("Total Qty Required")}</span><strong>${formatCompactNumber(estimatedTotals.totalRequired)}</strong></div>
				<div class="rfq-estimated-metric"><span>${__("Total Qty to Buy")}</span><strong>${formatCompactNumber(estimatedTotals.totalToBuy)}</strong></div>
				<div class="rfq-estimated-metric rfq-estimated-spend"><span>${__("Estimated Total Spend")}</span><strong>${format_currency(estimatedTotals.totalSpend, summaryCurrency)}</strong></div>
				<div class="rfq-estimated-metric rfq-estimated-lead"><span>${__("Avg. Lead Time (Weighted)")}</span><strong>${formatCompactNumber(averageLeadTime)} ${__("Days")}</strong></div>
				<button class="btn btn-default btn-sm rfq-export-comparison" type="button">⇩&nbsp; ${__("Export Comparison")}</button>
			</div>
		`;
		const purchaseOrderRows = (this.currentPurchaseOrders || []).map((purchaseOrder) => {
			const poItems = purchaseOrder.items && purchaseOrder.items.length
				? purchaseOrder.items
				: [{ item_code: "—", qty: null, rate: null }];
			const rowSpan = poItems.length;
			return poItems.map((poItem, index) => `
				<tr>
					${index === 0 ? `
						<td rowspan="${rowSpan}" class="rfq-po-name"><a href="/app/purchase-order/${encodeURIComponent(purchaseOrder.name)}">${frappe.utils.escape_html(purchaseOrder.name)}</a></td>
						<td rowspan="${rowSpan}">${frappe.utils.escape_html(purchaseOrder.supplier || "—")}</td>
					` : ""}
					<td class="rfq-po-item-code">${frappe.utils.escape_html(poItem.item_code || "—")}</td>
					<td>${poItem.qty === null ? "—" : formatCompactNumber(poItem.qty)}</td>
					<td>${poItem.rate === null ? "—" : format_currency(poItem.rate, purchaseOrder.currency)}</td>
					${index === 0 ? `
						<td rowspan="${rowSpan}">${purchaseOrder.creation ? frappe.datetime.str_to_user(purchaseOrder.creation) : "—"}</td>
						<td rowspan="${rowSpan}"><span class="rfq-po-status" data-status="${frappe.utils.escape_html(String(purchaseOrder.status || "").toLowerCase())}">${frappe.utils.escape_html(purchaseOrder.status || "—")}</span></td>
					` : ""}
				</tr>
			`).join("");
		}).join("");
		const purchaseOrderSection = `
			<div class="rfq-purchase-orders-section">
				<div class="rfq-po-section-heading">
					<div><strong>${__("Purchase Orders")}</strong><span>${__("Purchase Orders created for the selected RFQ")}</span></div>
					<span class="rfq-po-count">${format_number((this.currentPurchaseOrders || []).length)} ${__("PO(s)")}</span>
				</div>
				<div class="rfq-po-table-scroll"><table>
					<thead><tr><th>${__("PO Name")}</th><th>${__("Supplier Name")}</th><th>${__("Item Code")}</th><th>${__("Qty")}</th><th>${__("Rate")}</th><th>${__("Created Date")}</th><th>${__("PO Status")}</th></tr></thead>
					<tbody>${purchaseOrderRows || `<tr><td colspan="7" class="rfq-po-empty">${__("No Purchase Orders found for this RFQ.")}</td></tr>`}</tbody>
				</table></div>
			</div>
		`;

		$section.html(`
			<div class="rfq-comparison-tables">
				<div class="rfq-item-details-card">
						<table>
							<thead>
								<tr><th class="rfq-item-details-title" colspan="2">${__("Item Details")}</th></tr>
								<tr><th>${__("Item Code")}</th><th>${__("Qty Required")}</th></tr>
							</thead>
							<tbody>${itemRows}</tbody>
						</table>
				</div>
				<div class="rfq-supplier-scroll">${supplierCard}</div>
				${verdictCard}
			</div>
			${estimatedSummary}
			${purchaseOrderSection}
		`);
		const $scrollContainer = $section.find(".rfq-supplier-scroll");
		$scrollContainer.scrollLeft(previousScrollLeft);
		window.requestAnimationFrame(() => {
			$scrollContainer.scrollLeft(previousScrollLeft);
			this.syncComparisonRowHeights();
		});
		this.bindVerdictEvents();
		this.$body.find(".rfq-export-comparison").on("click", (event) => event.preventDefault());
	}

	syncComparisonRowHeights() {
		const tableSelectors = [
			".rfq-item-details-card table",
			".rfq-supplier-details-card table",
			".rfq-verdict-card table"
		];
		["thead tr", "tbody tr"].forEach((rowSelector) => {
			const rowGroups = tableSelectors.map((selector) =>
				this.$body.find(`${selector} ${rowSelector}`)
			);
			const rowCount = Math.max(...rowGroups.map((rows) => rows.length));

			for (let index = 0; index < rowCount; index += 1) {
				const rows = rowGroups.map((group) => group.eq(index)).filter((row) => row.length);
				rows.forEach((row) => row.children("th, td").css("height", "auto"));
				const height = Math.max(...rows.map((row) => Math.ceil(row.outerHeight())));
				rows.forEach((row) => row.children("th, td").css("height", `${height}px`));
			}
		});
	}

	bindVerdictEvents() {
		this.$body.find(".rfq-verdict-supplier").on("change", (event) => {
			const $control = $(event.currentTarget);
			const itemName = $control.attr("data-item");
			const index = Number($control.attr("data-index"));
			this.verdictState[itemName][index].supplier_quotation = $control.val();
			this.renderItems(this.currentItems, this.currentSuppliers);
		});
		this.$body.find(".rfq-verdict-qty").on("change", (event) => {
			const $control = $(event.currentTarget);
			const itemName = $control.attr("data-item");
			const index = Number($control.attr("data-index"));
			this.verdictState[itemName][index].qty = Math.max(0, Number($control.val() || 0));
			this.renderItems(this.currentItems, this.currentSuppliers);
		});
		this.$body.find(".rfq-verdict-edit").on("click", (event) => {
			event.preventDefault();
			const itemName = $(event.currentTarget).attr("data-item");
			this.activeVerdictItem = this.activeVerdictItem === itemName ? null : itemName;
			this.renderItems(this.currentItems, this.currentSuppliers);
		});
		this.$body.find(".rfq-add-supplier-split").on("click", (event) => {
			event.preventDefault();
			if (!this.activeVerdictItem) {
				frappe.show_alert({ message: __("Click the pencil for the item you want to edit."), indicator: "orange" });
				return;
			}
			const itemName = this.activeVerdictItem;
			const item = this.currentItems.find((row) => row.name === itemName);
			const used = new Set(this.verdictState[itemName].map((row) => row.supplier_quotation));
			const supplier = this.currentSuppliers.find((row) =>
				!used.has(row.supplier_quotation) && row.items.some((supplierItem) =>
					supplierItem.request_for_quotation_item === item.name || supplierItem.item_code === item.item_code
				)
			);
			if (!supplier) {
				frappe.show_alert({ message: __("No additional supplier is available for this item."), indicator: "orange" });
				return;
			}
			this.verdictState[itemName].push({ supplier_quotation: supplier.supplier_quotation, qty: 0 });
			this.renderItems(this.currentItems, this.currentSuppliers);
		});
	}

	setSummaryValue(fieldname, label, value) {
		this.$body.find(`[data-field="${fieldname}"]`).html(
			`<span class="rfq-summary-label">${label}</span><strong>${value}</strong>`
		);
	}

	addStyles() {
		if (document.getElementById("rfq-dashboard-comparison-style")) {
			return;
		}

		$("<style id=\"rfq-dashboard-comparison-style\">\
			.rfq-comparison-dashboard { padding: 10px 0 24px; }\
			.rfq-comparison-heading { align-items: flex-start; display: flex; gap: 24px; justify-content: space-between; margin-bottom: 14px; }\
			.rfq-comparison-heading h2 { color: var(--heading-color); font-size: 20px; font-weight: 700; margin: 0 0 4px; }\
			.rfq-comparison-heading p { color: var(--text-muted); font-size: 12px; margin: 0; }\
			.rfq-comparison-actions { display: flex; gap: 12px; }\
			.rfq-comparison-actions .btn { align-items: center; border-radius: 6px; display: flex; gap: 9px; height: 48px; justify-content: flex-start; padding: 6px 14px; text-align: left; }\
			.rfq-comparison-actions strong, .rfq-comparison-actions small { display: block; line-height: 1.25; }\
			.rfq-comparison-actions strong { font-size: 12px; }\
			.rfq-comparison-actions small { font-size: 9px; font-weight: 400; margin-top: 3px; opacity: .85; }\
			.rfq-action-icon { font-size: 18px; }\
			.rfq-verdict-button { background: var(--card-bg); border: 1px solid var(--primary); color: var(--primary); }\
			.rfq-comparison-summary-panel { align-items: center; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 7px; display: grid; gap: 22px; grid-template-columns: minmax(190px, 1.35fr) 1px repeat(5, minmax(90px, .75fr)); min-height: 82px; padding: 12px; transition: opacity .15s; }\
			.rfq-summary-loading { opacity: .55; pointer-events: none; }\
			.rfq-selector-cell label, .rfq-summary-label { color: var(--text-muted); display: block; font-size: 10px; font-weight: 500; margin-bottom: 7px; }\
			.rfq-selector-cell > label { color: var(--text-color); }\
			.rfq-selector-control .form-group { margin: 0; }\
			.rfq-selector-control .control-label { display: none; }\
			.rfq-summary-divider { background: var(--border-color); height: 50px; width: 1px; }\
			.rfq-summary-value strong { color: var(--text-color); display: block; font-size: 12px; font-weight: 600; white-space: nowrap; }\
			.rfq-item-details-section { margin-top: 16px; width: 100%; }\
			.rfq-comparison-tables { align-items: stretch; display: grid; gap: 12px; grid-template-columns: 300px minmax(0, 1fr) 473px; width: 100%; }\
			.rfq-supplier-scroll { min-width: 0; overflow-x: auto; padding-bottom: 2px; }\
			.rfq-item-details-card, .rfq-supplier-details-card, .rfq-verdict-card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 7px; overflow: hidden; }\
			.rfq-item-details-card, .rfq-verdict-card { position: relative; z-index: 1; }\
			.rfq-supplier-details-card { min-width: max-content; }\
			.rfq-item-details-title { background: var(--control-bg); color: var(--heading-color) !important; font-size: 13px !important; font-weight: 600 !important; padding: 18px 12px !important; text-align: center !important; }\
			.rfq-item-details-card table, .rfq-supplier-details-card table, .rfq-verdict-card table { border-collapse: collapse; table-layout: fixed; }\
			.rfq-item-details-card table { width: 300px; }\
			.rfq-supplier-details-card table { width: max-content; }\
			.rfq-verdict-card table { width: 473px; }\
			.rfq-item-details-card th, .rfq-supplier-details-card th, .rfq-verdict-card th { background: var(--control-bg); color: var(--text-muted); font-size: 10px; font-weight: 500; height: 42px; padding: 8px 10px; text-align: center; }\
			.rfq-item-details-card thead tr:first-child th, .rfq-supplier-details-card thead tr:first-child th, .rfq-verdict-card thead tr:first-child th { height: 55px; }\
			.rfq-item-details-card th, .rfq-item-details-card td, .rfq-supplier-details-card th, .rfq-supplier-details-card td { border-right: 1px solid var(--border-color); }\
			.rfq-item-details-card th:last-child, .rfq-item-details-card td:last-child, .rfq-supplier-details-card th:last-child, .rfq-supplier-details-card td:last-child { border-right: 0; }\
			.rfq-item-details-card th:first-child, .rfq-item-details-card td:first-child { text-align: left; width: 205px; }\
			.rfq-item-details-card th:nth-child(2), .rfq-item-details-card td:nth-child(2) { width: 95px; }\
			.rfq-supplier-details-card th, .rfq-supplier-details-card td { min-width: 105px; }\
			.rfq-supplier-details-card .rfq-supplier-alternate { background: rgba(127, 127, 127, .09); }\
			.rfq-item-details-card td, .rfq-supplier-details-card td { border-top: 1px solid var(--border-color); color: var(--text-color); height: 64px; padding: 10px; text-align: center; vertical-align: middle; }\
			.rfq-item-details-card td strong { display: block; font-size: 12px; line-height: 1.35; }\
			.rfq-supplier-heading { color: var(--heading-color) !important; font-size: 12px !important; padding: 12px !important; }\
			.rfq-supplier-heading strong, .rfq-supplier-heading span { display: block; }\
			.rfq-supplier-heading span { color: var(--text-muted); font-size: 10px; font-weight: 400; margin-top: 3px; }\
			.rfq-item-details-card .rfq-item-qty { color: var(--primary); font-size: 13px; font-weight: 600; text-align: center; }\
			.rfq-supplier-rate { font-weight: 500; }\
			.rfq-lead-time { color: var(--green-600, #2f9e44) !important; font-weight: 500; white-space: nowrap; }\
			.rfq-availability { font-weight: 500; }\
			.rfq-availability.is-available { color: var(--green-600, #2f9e44); }\
			.rfq-availability.is-unavailable { color: var(--red-500, #e24c4c); }\
			.rfq-verdict-heading { background: rgba(72, 187, 120, .08) !important; color: var(--green-700, #237a3b) !important; }\
			.rfq-verdict-heading strong, .rfq-verdict-heading span { display: block; }\
			.rfq-verdict-heading strong { font-size: 12px; }\
			.rfq-verdict-heading span { color: var(--text-muted); font-size: 9px; font-weight: 400; margin-top: 3px; }\
			.rfq-verdict-card th, .rfq-verdict-card td { border-right: 1px solid var(--border-color); }\
			.rfq-verdict-card th:last-child, .rfq-verdict-card td:last-child { border-right: 0; }\
			.rfq-verdict-card th:nth-child(1), .rfq-verdict-card td:nth-child(1) { width: 245px; }\
			.rfq-verdict-card th:nth-child(2), .rfq-verdict-card td:nth-child(2) { width: 95px; }\
			.rfq-verdict-card th:nth-child(3), .rfq-verdict-card td:nth-child(3) { width: 91px; }\
			.rfq-verdict-card th:nth-child(4), .rfq-verdict-card td:nth-child(4) { padding-left: 4px; padding-right: 4px; width: 42px; }\
			.rfq-verdict-card td { border-top: 1px solid var(--border-color); color: var(--text-color); min-height: 76px; padding: 8px; text-align: center; vertical-align: middle; }\
			.rfq-verdict-card tbody tr.is-active td { background: rgba(72, 187, 120, .06); }\
			.rfq-verdict-supplier, .rfq-verdict-qty { font-size: 10px; height: 27px; margin-bottom: 5px; padding: 3px 6px; }\
			.rfq-verdict-supplier:disabled, .rfq-verdict-qty:disabled { cursor: not-allowed; opacity: .7; }\
			.rfq-verdict-qty { text-align: center; }\
			.rfq-verdict-total { align-items: center; display: flex; font-size: 9px; gap: 5px; justify-content: space-between; margin-top: 2px; }\
			.rfq-verdict-total span, .rfq-verdict-shortage { color: var(--orange-500, #f39c12); }\
			.rfq-verdict-est-rate { font-size: 12px; font-weight: 500; white-space: nowrap; }\
			.rfq-verdict-edit { align-items: center; color: var(--primary); display: inline-flex; font-size: 18px; height: 32px; justify-content: center; padding: 0; width: 34px; }\
			.rfq-verdict-edit.is-active { background: rgba(72, 187, 120, .12); border-color: var(--green-500, #48bb78); color: var(--green-600, #2f9e44); }\
			.rfq-verdict-footer { align-items: center; background: rgba(72, 187, 120, .04); border-top: 1px solid var(--border-color); display: flex; gap: 8px; min-height: 38px; padding: 6px 10px; }\
			.rfq-verdict-footer span { color: var(--text-muted); font-size: 9px; }\
			.rfq-add-supplier-split { color: var(--primary); white-space: nowrap; }\
			.rfq-estimated-summary { align-items: center; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 7px; display: grid; gap: 18px; grid-template-columns: minmax(150px, 1.15fr) repeat(5, minmax(115px, 1fr)) auto; margin-top: 16px; min-height: 66px; padding: 10px 18px; }\
			.rfq-estimated-summary-title { color: var(--heading-color); font-size: 11px; font-weight: 600; white-space: nowrap; }\
			.rfq-estimated-summary-title span { color: var(--text-muted); font-weight: 400; }\
			.rfq-estimated-metric { text-align: center; }\
			.rfq-estimated-metric span, .rfq-estimated-metric strong { display: block; }\
			.rfq-estimated-metric span { color: var(--text-muted); font-size: 9px; margin-bottom: 5px; white-space: nowrap; }\
			.rfq-estimated-metric strong { color: var(--text-color); font-size: 13px; font-weight: 600; white-space: nowrap; }\
			.rfq-estimated-spend strong { color: var(--primary); font-size: 15px; }\
			.rfq-estimated-lead strong { color: var(--green-600, #2f9e44); }\
			.rfq-export-comparison { white-space: nowrap; }\
			.rfq-purchase-orders-section { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 7px; margin-top: 16px; overflow: hidden; }\
			.rfq-po-section-heading { align-items: center; background: var(--control-bg); border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; min-height: 58px; padding: 10px 16px; }\
			.rfq-po-section-heading strong, .rfq-po-section-heading span { display: block; }\
			.rfq-po-section-heading strong { color: var(--heading-color); font-size: 13px; }\
			.rfq-po-section-heading div > span { color: var(--text-muted); font-size: 9px; margin-top: 3px; }\
			.rfq-po-count { border: 1px solid var(--border-color); border-radius: 12px; color: var(--text-muted); font-size: 10px; padding: 4px 9px; }\
			.rfq-po-table-scroll { overflow-x: auto; }\
			.rfq-purchase-orders-section table { border-collapse: collapse; min-width: 1000px; table-layout: fixed; width: 100%; }\
			.rfq-purchase-orders-section th { background: var(--control-bg); color: var(--text-muted); font-size: 10px; font-weight: 500; padding: 10px 12px; text-align: left; }\
			.rfq-purchase-orders-section td { border-top: 1px solid var(--border-color); color: var(--text-color); font-size: 11px; padding: 11px 12px; vertical-align: middle; }\
			.rfq-purchase-orders-section th:nth-child(1) { width: 17%; }\
			.rfq-purchase-orders-section th:nth-child(2) { width: 18%; }\
			.rfq-purchase-orders-section th:nth-child(3) { width: 23%; }\
			.rfq-purchase-orders-section th:nth-child(4) { width: 9%; }\
			.rfq-purchase-orders-section th:nth-child(5) { width: 12%; }\
			.rfq-purchase-orders-section th:nth-child(6) { width: 13%; }\
			.rfq-purchase-orders-section th:nth-child(7) { width: 8%; }\
			.rfq-po-name a { font-weight: 600; white-space: nowrap; }\
			.rfq-po-item-code { font-weight: 500; }\
			.rfq-po-status { background: var(--control-bg); border-radius: 10px; display: inline-block; font-size: 9px; font-weight: 600; padding: 4px 8px; white-space: nowrap; }\
			.rfq-po-status[data-status=completed] { background: rgba(72, 187, 120, .12); color: var(--green-600, #2f9e44); }\
			.rfq-po-status[data-status=cancelled] { background: rgba(226, 76, 76, .12); color: var(--red-500, #e24c4c); }\
			.rfq-po-status[data-status^=to] { background: rgba(66, 153, 225, .12); color: var(--blue-500, #3182ce); }\
			.rfq-po-empty { color: var(--text-muted) !important; padding: 24px !important; text-align: center !important; }\
			.rfq-items-empty { border: 1px dashed var(--border-color); border-radius: 7px; color: var(--text-muted); padding: 24px; text-align: center; }\
			@media (max-width: 1399px) { .rfq-comparison-tables { grid-template-columns: 260px minmax(0, 1fr) 440px; } .rfq-item-details-card table { width: 260px; } .rfq-item-details-card th:first-child, .rfq-item-details-card td:first-child { width: 175px; } .rfq-item-details-card th:nth-child(2), .rfq-item-details-card td:nth-child(2) { width: 85px; } .rfq-verdict-card table { width: 440px; } .rfq-verdict-card th:nth-child(1), .rfq-verdict-card td:nth-child(1) { width: 225px; } .rfq-verdict-card th:nth-child(2), .rfq-verdict-card td:nth-child(2) { width: 90px; } .rfq-verdict-card th:nth-child(3), .rfq-verdict-card td:nth-child(3) { width: 85px; } .rfq-verdict-card th:nth-child(4), .rfq-verdict-card td:nth-child(4) { width: 40px; } }\
			@media (max-width: 1199px) { .rfq-estimated-summary { grid-template-columns: repeat(3, minmax(140px, 1fr)); } }\
			@media (max-width: 991px) { .rfq-comparison-heading { flex-direction: column; } .rfq-comparison-summary-panel { grid-template-columns: repeat(2, minmax(140px, 1fr)); } .rfq-selector-cell { grid-column: 1 / -1; } .rfq-summary-divider { display: none; } }\
			@media (max-width: 575px) { .rfq-comparison-actions { align-items: stretch; flex-direction: column; width: 100%; } .rfq-comparison-actions .btn { width: 100%; } .rfq-comparison-summary-panel, .rfq-estimated-summary { grid-template-columns: 1fr; } .rfq-selector-cell { grid-column: auto; } }\
		</style>").appendTo("head");
	}
}
