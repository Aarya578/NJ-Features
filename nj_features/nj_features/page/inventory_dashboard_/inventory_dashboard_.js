frappe.pages["inventory_dashboard_"].on_page_load = function(wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("RFQ Quotation Workbench"), single_column: true });
	new RFQQuotationWorkbench(page);
};

class RFQQuotationWorkbench {
	constructor(page) {
		this.page = page;
		this.makeBody();
		this.makeFilters();
		this.resetWorkbench();
	}

	makeBody() {
		this.addStyles();
		this.page.main.addClass("rfq-workbench-page");
		this.$body = $(`<div class="rfq-workbench">
			<header class="rfq-workbench-topbar">
				<div class="rfq-brand">NEWJAISA</div>
				<div class="rfq-breadcrumb">${__("Buying")} › ${__("RFQ")} › <strong class="rfq-breadcrumb-name">—</strong> › ${__("Quotation Workbench")}</div>
				<div class="rfq-top-actions">
					<button class="btn rfq-create-manual-qi">${__("Create Manual QI")}</button>
					<button class="btn rfq-ui-only">${__("Recalculate from QC")}</button>
					<button class="btn rfq-ui-only">${__("Export XLSX")}</button>
					<button class="btn btn-light rfq-ui-only">${__("Generate Quotation")}</button>
				</div>
			</header>
			<div class="rfq-workbench-content">
				<section class="rfq-filter-panel">
					<div><label>${__("Supplier")}</label><div class="rfq-supplier-control"></div></div>
					<div><label>${__("Request for Quotation")}</label><div class="rfq-control"></div></div>
				</section>
				<section class="rfq-overview-card">
					<div class="rfq-overview-head">
						<div class="rfq-title-block">
							<div><h2 data-value="rfq_name">${__("Select an RFQ")}</h2><span class="rfq-status-pill" data-value="status">—</span></div>
							<p><strong data-value="supplier">—</strong> · <span data-value="company">—</span></p>
						</div>
						<div class="rfq-overview-meta">
							<div><span>${__("RFQ Date")}</span><strong data-value="rfq_date">—</strong></div>
							<div><span>${__("Required Date")}</span><strong data-value="required_date">—</strong></div>
							<div><span>${__("Total Items")}</span><strong data-value="total_items">—</strong></div>
							<div><span>${__("Currency")}</span><strong data-value="currency">—</strong></div>
						</div>
					</div>
					<div class="rfq-kpi-grid">
						<div class="rfq-kpi"><span>${__("Units in Lot")}</span><strong data-value="units_in_lot">0</strong><small data-value="models">0 ${__("models")}</small></div>
						<div class="rfq-kpi"><span>${__("Units Inspected")}</span><strong data-value="units_inspected">0</strong><small>${__("Submitted NJQCA")}</small></div>
						<div class="rfq-kpi"><span>${__("Function-Tested")}</span><strong data-value="function_tested">0</strong><small>${__("Submitted quality inspections")}</small></div>
						<div class="rfq-kpi"><span>${__("Grade A Value")}</span><strong data-value="grade_a_value">₹0.00</strong><small>${__("before deduction")}</small></div>
						<div class="rfq-kpi rfq-kpi-negative"><span>${__("Deductions")}</span><strong data-value="deductions">₹0.00</strong><small data-value="deduction_percent">0% ${__("of Grade A")}</small></div>
						<div class="rfq-kpi"><span>${__("Manual Overrides")}</span><strong>3</strong><small>${__("models edited")}</small></div>
						<div class="rfq-kpi rfq-kpi-offer"><span>${__("Net Lot Offer")}</span><strong data-value="net_lot_offer">₹0.00</strong><small data-value="net_unit_average">₹0.00 / ${__("unit avg")}</small></div>
					</div>
				</section>
				<section class="rfq-model-summary-card">
					<div class="rfq-model-summary-head">
						<span class="rfq-section-number">01</span>
						<div><h3>${__("Model summary & final rates")}</h3><p>${__("Deduction per unit is computed from the component matrix. Edit values there; this table reflects the roll-up.")}</p></div>
						<div class="rfq-read-only">🔒 ${__("Read-only roll-up")}</div>
						<button class="btn btn-default btn-sm rfq-ui-only">${__("Go to matrix")}</button>
					</div>
					<div class="rfq-model-toolbar">
						<input class="form-control rfq-model-search" placeholder="${__("Search model or processor")}">
						<button class="btn btn-xs rfq-type-filter is-active" data-type="all">${__("All types")}</button>
						<button class="btn btn-xs rfq-type-filter" data-type="laptop">${__("Laptop")}</button>
						<button class="btn btn-xs rfq-type-filter" data-type="desktop">${__("Desktop")}</button>
						<button class="btn btn-xs rfq-type-filter" data-type="mac">${__("Mac")}</button>
						<button class="btn btn-xs rfq-placeholder-filter">${__("Non-working only")}</button>
						<button class="btn btn-xs rfq-placeholder-filter">${__("Overridden only")}</button>
					</div>
					<div class="rfq-model-table-scroll"><table class="rfq-model-table">
						<thead><tr><th>${__("Type")}</th><th>${__("Model")}</th><th>${__("Processor")}</th><th>${__("RAM")}</th><th>${__("SSD")}</th><th>${__("Screen")}</th><th>${__("Segment")}</th><th>${__("Status")}</th><th>${__("Qty")}</th><th>${__("Grade A Rate")}</th><th>${__("Deduction / Unit")}</th><th>${__("Final Rate")}</th><th>${__("Line Total")}</th></tr></thead>
						<tbody></tbody>
						<tfoot></tfoot>
					</table></div>
				</section>
				<section class="rfq-qc-record-card">
					<div class="rfq-qc-record-head">
						<span class="rfq-section-number">02</span>
						<div>
							<h3>${__("Serial-level QC record")}</h3>
							<p>${__("Every inspection row from NJ Quality Inspection for this RFQ. Blank cells were not tested on that unit.")}</p>
						</div>
						<span class="rfq-qc-counter">${__("Showing 8 of 412")}</span>
						<button class="btn btn-default btn-sm rfq-ui-only">${__("Open full QC list")}</button>
					</div>
					<div class="rfq-qc-toolbar">
						<input class="form-control rfq-qc-search" placeholder="${__("Search serial number")}">
						<button class="btn btn-xs rfq-qc-filter is-active" data-qc-filter="all">${__("All models")}</button>
						<button class="btn btn-xs rfq-qc-filter" data-qc-filter="grade_c">${__("Has Grade C")}</button>
						<button class="btn btn-xs rfq-qc-filter" data-qc-filter="tested">${__("Function-tested only")}</button>
						<button class="btn btn-xs rfq-qc-filter" data-qc-filter="flagged">${__("Flagged by inspector")}</button>
					</div>
					<div class="rfq-qc-table-scroll"><table class="rfq-qc-table">
						<thead>
							<tr>
								<th>${__("Serial No.")}</th>
								<th>${__("QI Name")}</th>
								<th>${__("Model")}</th>
								<th>${__("QC Date")}</th>
								<th>${__("Inspection Type")}</th>
								<th>${__("Body A")}</th>
								<th>${__("Body D Base Cover")}</th>
								<th>${__("Camera")}</th>
								<th>${__("Speaker")}</th>
								<th>${__("Hinges")}</th>
								<th>${__("Fan")}</th>
								<th>${__("Touchpad Button")}</th>
								<th>${__("WiFi Card")}</th>
								<th>${__("Power Button")}</th>
								<th>${__("Motherboard")}</th>
								<th>${__("Software Configuration")}</th>
								<th>${__("Body B")}</th>
								<th>${__("Laptop Storage")}</th>
								<th>${__("Display")}</th>
								<th>${__("Battery")}</th>
								<th>${__("Laptop RAM")}</th>
								<th>${__("Body C Touchpad")}</th>
								<th>${__("Body D")}</th>
								<th>${__("Keyboard")}</th>
								<th>${__("Deduction")}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table></div>
					<div class="rfq-qc-legend">
						<span><span class="rfq-grade-badge grade-a">A</span> ${__("as-new")}</span>
						<span><span class="rfq-grade-badge grade-b">B</span> ${__("minor wear, no deduction")}</span>
						<span><span class="rfq-grade-badge grade-d">D</span> ${__("defective, 20% of component value")}</span>
						<span><span class="rfq-grade-badge grade-c">C</span> ${__("failed or missing, 100% of component value")}</span>
						<span><span class="rfq-grade-badge grade-dash">—</span> ${__("not tested on this unit, scaled from sample")}</span>
					</div>
				</section>
			</div>
		</div>`).appendTo(this.page.body);

		this.$body.find(".rfq-create-manual-qi").on("click", (event) => {
			event.preventDefault();
			this.openCreateManualQiDialog();
		});

		this.$body.find(".rfq-ui-only").on("click", (event) => {
			event.preventDefault();
			frappe.show_alert({ message: __("This functionality will be added in the next phase."), indicator: "blue" });
		});
		this.modelRows = [];
		this.activeType = "all";
		this.$body.find(".rfq-model-search").on("input", () => this.renderModelRows());
		this.$body.find(".rfq-type-filter").on("click", (event) => {
			event.preventDefault();
			this.activeType = $(event.currentTarget).attr("data-type");
			this.$body.find(".rfq-type-filter").removeClass("is-active");
			$(event.currentTarget).addClass("is-active");
			this.renderModelRows();
		});
		this.$body.find(".rfq-placeholder-filter").on("click", (event) => event.preventDefault());

		this.activeQcFilter = "all";
		this.$body.find(".rfq-qc-search").on("input", () => this.renderSerialQcRows());
		this.$body.find(".rfq-qc-filter").on("click", (event) => {
			event.preventDefault();
			this.activeQcFilter = $(event.currentTarget).attr("data-qc-filter");
			this.$body.find(".rfq-qc-filter").removeClass("is-active");
			$(event.currentTarget).addClass("is-active");
			this.renderSerialQcRows();
		});
	}

	openCreateManualQiDialog() {
		const rfq = this.rfqField ? this.rfqField.get_value() : "";
		if (!rfq) {
			frappe.msgprint(__("Please select a Request for Quotation (RFQ) first."));
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Create Manual QI"),
			fields: [
				{
					fieldname: "ext_serial_no",
					label: __("EXT Serial No"),
					fieldtype: "Data",
					read_only: 1
				},
				{
					fieldname: "item_code",
					label: __("Item Code"),
					fieldtype: "Link",
					options: "Item",
					reqd: 1,
					onchange: () => {
						const item_code = dialog.get_value("item_code");
						if (!item_code) {
							dialog.set_value("item_wizard", "");
							dialog._item_wizard_data = null;
							return;
						}
						frappe.call({
							method: "nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_.get_item_wizard_for_item",
							args: { item_code: item_code },
							callback: (r) => {
								if (r.message && r.message.name) {
									dialog.set_value("item_wizard", r.message.name);
									dialog._item_wizard_data = r.message;
								} else {
									dialog.set_value("item_wizard", "");
									dialog._item_wizard_data = null;
									frappe.msgprint(__("Item Wizard not found for Item Code: {0}", [item_code]));
								}
							},
							error: () => {
								dialog.set_value("item_wizard", "");
								dialog._item_wizard_data = null;
							}
						});
					}
				},
				{
					fieldname: "item_wizard",
					label: __("Item Wizard"),
					fieldtype: "Link",
					options: "Item Wizards",
					read_only: 1
				}
			],
			primary_action_label: __("Create QI"),
			primary_action: (values) => {
				if (!values.ext_serial_no) {
					frappe.msgprint(__("First generate EXT Serial No"));
					return;
				}
				if (!values.item_code) {
					frappe.msgprint(__("Please select Item Code"));
					return;
				}
				if (!values.item_wizard) {
					frappe.msgprint(__("Item Wizard not found for the selected Item Code"));
					return;
				}

				frappe.call({
					method: "nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_.get_manual_qi_context",
					args: {
						item_code: values.item_code,
						item_wizard: values.item_wizard,
						ext_serial_no: values.ext_serial_no,
						rfq: rfq
					},
					callback: (r) => {
						const ctx = r.message || {};
						dialog.hide();
						frappe.route_options = {
							barcode: values.ext_serial_no,
							item_code: values.item_code,
							item_wizard: values.item_wizard,
							item_group: ctx.item_group || "",
							brand: ctx.brand || "",
							model: ctx.model || "",
							department: ctx.department || "",
							warehouse: ctx.work_warehouse || "",
							rfq_id: rfq
						};
						frappe.model.with_doctype("NJ Quality Inspection", () => {
							const new_name = frappe.model.make_new_doc_and_get_name("NJ Quality Inspection");
							const new_doc = locals["NJ Quality Inspection"] && locals["NJ Quality Inspection"][new_name];
							if (new_doc) {
								new_doc.barcode = values.ext_serial_no;
								new_doc.item_code = values.item_code;
								new_doc.item_wizard = values.item_wizard;
								new_doc.item_group = ctx.item_group || "";
								new_doc.brand = ctx.brand || "";
								new_doc.model = ctx.model || "";
								new_doc.department = ctx.department || "";
								new_doc.warehouse = ctx.work_warehouse || "";
								new_doc.rfq_id = rfq;
							}
							frappe.set_route("Form", "NJ Quality Inspection", new_name);
						});
					}
				});
			}
		});

		dialog.set_secondary_action_label(__("Generate EXT SN"));
		dialog.set_secondary_action(() => {
			const existing_sn = dialog.get_value("ext_serial_no");
			if (existing_sn) {
				frappe.msgprint(__("Already serial no generated: {0}", [existing_sn]));
				return;
			}

			const item_code = dialog.get_value("item_code");
			if (!item_code) {
				frappe.msgprint(__("Please select Item Code first."));
				return;
			}

			frappe.call({
				method: "nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_.generate_ext_serial_no",
				args: {
					rfq: rfq,
					item_code: item_code
				},
				callback: (r) => {
					if (r.message) {
						const serial_no = typeof r.message === "object" ? r.message.serial_no : r.message;
						const returned_item_code = typeof r.message === "object" ? r.message.item_code : null;
						dialog.set_value("ext_serial_no", serial_no);
						if (!dialog.get_value("item_code") && returned_item_code) {
							dialog.set_value("item_code", returned_item_code);
						}
						frappe.show_alert({
							message: __("Generated EXT Serial No: {0}", [serial_no]),
							indicator: "green"
						});
					}
				}
			});
		});

		// Filter item_code to items associated with this RFQ
		frappe.call({
			method: "nj_features.nj_features.doctype.njqca.njqca.get_item_code_from_rfq_id",
			args: { rfq_id: rfq },
			callback: (r) => {
				const items = (r.message || []).map((x) => x.item_code).filter(Boolean);
				if (items.length) {
					dialog.get_field("item_code").get_query = () => ({
						filters: { name: ["in", items] }
					});
					if (items.length === 1) {
						dialog.set_value("item_code", items[0]);
					}
				}
			}
		});

		dialog.show();
	}

	makeFilters() {
		this.supplierField = frappe.ui.form.make_control({
			parent: this.$body.find(".rfq-supplier-control"),
			df: { fieldname: "supplier", fieldtype: "Link", options: "Supplier", placeholder: __("Select Supplier"), onchange: () => {
				this.clearRfqOptions();
				this.resetWorkbench();
				const supplier = this.supplierField.get_value();
				if (supplier) this.loadSupplierRfqs(supplier);
			}}, render_input: true
		});
		this.supplierField.refresh();

		this.rfqField = frappe.ui.form.make_control({
			parent: this.$body.find(".rfq-control"),
			df: { fieldname: "rfq", fieldtype: "Select", options: "", placeholder: __("Select RFQ"), onchange: () => {
				const supplier = this.supplierField.get_value();
				const rfq = this.rfqField.get_value();
				supplier && rfq ? this.loadWorkbench(supplier, rfq) : this.resetWorkbench();
			}}, render_input: true
		});
		this.rfqField.refresh();
	}

	loadSupplierRfqs(supplier) {
		frappe.call({
			method: "nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_.get_supplier_rfqs",
			args: { supplier },
			callback: (response) => {
				const rows = response.message || [];
				this.rfqField.df.options = ["", ...rows.map((row) => row.name)].join("\n");
				this.rfqField.refresh();
				if (!rows.length) frappe.show_alert({ message: __("No RFQs found for this supplier."), indicator: "orange" });
			}
		});
	}

	clearRfqOptions() {
		if (!this.rfqField) return;
		this.rfqField.df.options = "";
		this.rfqField.refresh();
		this.rfqField.set_value("");
	}

	loadWorkbench(supplier, rfq) {
		this.$body.find(".rfq-overview-card").addClass("is-loading");
		frappe.call({
			method: "nj_features.nj_features.page.inventory_dashboard_.inventory_dashboard_.get_supplier_rfq_dashboard",
			args: { supplier, rfq },
			callback: (response) => this.renderWorkbench(response.message || {}),
			always: () => this.$body.find(".rfq-overview-card").removeClass("is-loading")
		});
	}

	renderWorkbench(data) {
		const date = (value) => value ? frappe.datetime.str_to_user(value) : "—";
		const number = (value) => format_number(value || 0, null, 2);
		this.setValue("rfq_name", data.rfq || "—");
		this.setValue("status", String(data.status || "Draft").toUpperCase());
		this.setValue("supplier", data.supplier || "—");
		this.setValue("company", data.company || "—");
		this.setValue("rfq_date", date(data.rfq_date));
		this.setValue("required_date", date(data.required_date));
		this.setValue("total_items", format_number(data.total_items || 0));
		this.setValue("currency", data.currency || "—");
		this.currency = data.currency || "INR";
		this.setValue("units_in_lot", number(data.total_qty));
		this.setValue("models", `${format_number(data.total_items || 0)} ${__("models")}`);
		this.setValue("units_inspected", format_number(data.total_submitted || 0));
		this.setValue("function_tested", format_number(data.function_tested || 0));
		this.$body.find(".rfq-breadcrumb-name").text(data.rfq || "—");
		this.modelRows = data.model_rows || [];
		const gradeAValue = this.modelRows.reduce((total, row) => total + Number(row.qty || 0) * Number(row.grade_a_rate || 0), 0);
		const deductions = this.modelRows.reduce((total, row) => total + Number(row.qty || 0) * Number(row.deduction_per_unit || 0), 0);
		const netLotOffer = this.modelRows.reduce((total, row) => total + Number(row.line_total || 0), 0);
		const pricedQty = this.modelRows.reduce((total, row) => row.final_rate === null || row.final_rate === undefined ? total : total + Number(row.qty || 0), 0);
		const deductionPercent = gradeAValue ? deductions / gradeAValue * 100 : 0;
		this.setValue("grade_a_value", format_currency(gradeAValue, this.currency));
		this.setValue("deductions", format_currency(-deductions, this.currency));
		this.setValue("deduction_percent", `${format_number(deductionPercent, null, 2)}% ${__("of Grade A")}`);
		this.setValue("net_lot_offer", format_currency(netLotOffer, this.currency));
		this.setValue("net_unit_average", `${format_currency(pricedQty ? netLotOffer / pricedQty : 0, this.currency)} / ${__("unit avg")}`);
		this.activeType = "all";
		this.$body.find(".rfq-model-search").val("");
		this.$body.find(".rfq-type-filter").removeClass("is-active").filter('[data-type="all"]').addClass("is-active");
		this.renderModelRows();
		this.serialQcRows = data.serial_qc_rows || [];
		this.renderSerialQcRows();
	}

	resetWorkbench() {
		["supplier", "company", "rfq_date", "required_date", "total_items", "currency"].forEach((field) => this.setValue(field, "—"));
		this.setValue("rfq_name", __("Select an RFQ"));
		this.setValue("status", "—");
		this.setValue("units_in_lot", "0");
		this.setValue("models", `0 ${__("models")}`);
		this.setValue("units_inspected", "0");
		this.setValue("function_tested", "0");
		this.setValue("grade_a_value", format_currency(0, this.currency || "INR"));
		this.setValue("deductions", format_currency(0, this.currency || "INR"));
		this.setValue("deduction_percent", `0% ${__("of Grade A")}`);
		this.setValue("net_lot_offer", format_currency(0, this.currency || "INR"));
		this.setValue("net_unit_average", `${format_currency(0, this.currency || "INR")} / ${__("unit avg")}`);
		this.$body.find(".rfq-breadcrumb-name").text("—");
		this.modelRows = [];
		this.renderModelRows();
		this.serialQcRows = [];
		this.renderSerialQcRows();
	}

	normalizeType(value) {
		const type = String(value || "").toLowerCase();
		if (type.includes("laptop")) return "laptop";
		if (type.includes("desktop")) return "desktop";
		if (type.includes("mac")) return "mac";
		return type;
	}

	renderModelRows() {
		const escape = frappe.utils.escape_html;
		const search = String(this.$body.find(".rfq-model-search").val() || "").trim().toLowerCase();
		const rows = (this.modelRows || []).filter((row) => {
			const matchesType = this.activeType === "all" || this.normalizeType(row.type) === this.activeType;
			const matchesSearch = !search || `${row.model || ""} ${row.processor || ""}`.toLowerCase().includes(search);
			return matchesType && matchesSearch;
		});
		const body = rows.map((row) => `<tr>
			<td><span class="rfq-type-pill rfq-type-${this.normalizeType(row.type)}">${escape(row.type || "")}</span></td>
			<td class="rfq-model-name">${escape(row.model || "")}</td>
			<td>${escape(row.processor || "")}</td><td>${escape(row.ram || "")}</td><td>${escape(row.ssd || "")}</td><td>${escape(row.screen || "")}</td>
			<td>${escape(row.segment || "")}</td><td><span class="rfq-status-badge ${row.status === "Working" ? "is-working" : "is-not-working"}">${escape(row.status || "")}</span></td><td class="rfq-model-qty">${format_number(row.qty || 0, null, 2)}</td><td class="rfq-grade-a-rate">${row.grade_a_rate === null || row.grade_a_rate === undefined ? "" : format_currency(row.grade_a_rate, this.currency)}</td><td class="rfq-deduction-rate">${format_currency(row.deduction_per_unit || 0, this.currency)}</td><td class="rfq-final-rate">${row.final_rate === null || row.final_rate === undefined ? "" : format_currency(row.final_rate, this.currency)}</td><td class="rfq-line-total">${row.line_total === null || row.line_total === undefined ? "" : format_currency(row.line_total, this.currency)}</td>
		</tr>`).join("");
		this.$body.find(".rfq-model-table tbody").html(body || `<tr><td colspan="13" class="rfq-model-empty">${__("No matching RFQ items found.")}</td></tr>`);
		const totalQty = rows.reduce((total, row) => total + Number(row.qty || 0), 0);
		const pricedQty = rows.reduce((total, row) => row.final_rate === null || row.final_rate === undefined ? total : total + Number(row.qty || 0), 0);
		const gradeATotal = rows.reduce((total, row) => total + Number(row.qty || 0) * Number(row.grade_a_rate || 0), 0);
		const deductionTotal = rows.reduce((total, row) => total + Number(row.qty || 0) * Number(row.deduction_per_unit || 0), 0);
		const lineTotal = rows.reduce((total, row) => total + Number(row.line_total || 0), 0);
		const averageFinalRate = pricedQty ? lineTotal / pricedQty : 0;
		this.$body.find(".rfq-model-table tfoot").html(`<tr>
			<td colspan="8"><strong>${__("Total — {0} models", [rows.length])}</strong></td>
			<td><strong>${format_number(totalQty, null, 2)}</strong></td>
			<td><strong>${format_currency(gradeATotal, this.currency)}</strong></td>
			<td class="rfq-total-deduction"><strong>${format_currency(-deductionTotal, this.currency)}</strong></td>
			<td><strong>${format_currency(averageFinalRate, this.currency)}</strong> <small>${__("avg")}</small></td>
			<td><strong>${format_currency(lineTotal, this.currency)}</strong></td>
		</tr>`);
	}

	renderSerialQcRows() {
		const escape = frappe.utils.escape_html;
		const search = String(this.$body.find(".rfq-qc-search").val() || "").trim().toLowerCase();
		const rows = this.serialQcRows || [];

		const gradeBadge = (grade) => {
			const g = String(grade || "").trim().toUpperCase();
			if (g === "A") return `<span class="rfq-grade-badge grade-a">A</span>`;
			if (g === "B") return `<span class="rfq-grade-badge grade-b">B</span>`;
			if (g === "C") return `<span class="rfq-grade-badge grade-c">C</span>`;
			if (g === "D") return `<span class="rfq-grade-badge grade-d">D</span>`;
			return `<span class="rfq-grade-badge grade-dash">—</span>`;
		};

		const filtered = rows.filter((row) => {
			const matchesSearch = !search || `${row.serial_no || ""} ${row.qi_name || ""} ${row.model || ""}`.toLowerCase().includes(search);
			if (!matchesSearch) return false;
			if (this.activeQcFilter === "grade_c") {
				return Object.values(row).includes("C");
			}
			if (this.activeQcFilter === "tested") {
				return String(row.inspection_type || "").toLowerCase().includes("full");
			}
			if (this.activeQcFilter === "flagged") {
				return Number(row.deduction || 0) > 0;
			}
			return true;
		});

		const body = filtered.map((row) => `<tr>
			<td class="rfq-qc-serial">${escape(row.serial_no || "")}</td>
			<td><a href="/app/nj-quality-inspection/${encodeURIComponent(row.qi_name || "")}" target="_blank" class="rfq-qc-name" title="${escape(row.qi_name || "")}">${escape(row.qi_name || "")}</a></td>
			<td><span class="rfq-qc-model" title="${escape(row.model || "")}">${escape(row.model || "")}</span></td>
			<td>${escape(row.qc_date || "")}</td>
			<td><span class="rfq-depth-pill ${String(row.inspection_type || "").toLowerCase().includes("full") ? "is-full" : "is-spec"}">${escape(row.inspection_type || "—")}</span></td>
			<td>${gradeBadge(row.body_a)}</td>
			<td>${gradeBadge(row.body_d_base_cover)}</td>
			<td>${gradeBadge(row.camera)}</td>
			<td>${gradeBadge(row.speaker)}</td>
			<td>${gradeBadge(row.hinges)}</td>
			<td>${gradeBadge(row.fan)}</td>
			<td>${gradeBadge(row.touchpad_button)}</td>
			<td>${gradeBadge(row.wifi_card)}</td>
			<td>${gradeBadge(row.power_button)}</td>
			<td>${gradeBadge(row.motherboard)}</td>
			<td>${gradeBadge(row.software_configuration)}</td>
			<td>${gradeBadge(row.body_b)}</td>
			<td>${gradeBadge(row.laptop_storage)}</td>
			<td>${gradeBadge(row.display)}</td>
			<td>${gradeBadge(row.battery)}</td>
			<td>${gradeBadge(row.laptop_ram)}</td>
			<td>${gradeBadge(row.body_c_touchpad)}</td>
			<td>${gradeBadge(row.body_d)}</td>
			<td>${gradeBadge(row.keyboard)}</td>
			<td class="rfq-qc-deduction">${row.deduction ? format_currency(row.deduction, this.currency) : (row.deduction === 0 ? format_currency(0, this.currency) : "—")}</td>
		</tr>`).join("");

		this.$body.find(".rfq-qc-table tbody").html(body || `<tr><td colspan="25" class="rfq-model-empty">${__("No inspection records found for this RFQ.")}</td></tr>`);
		this.$body.find(".rfq-qc-counter").text(`${__("Showing {0} of {1}", [filtered.length, rows.length])}`);
	}

	setValue(field, value) { this.$body.find(`[data-value="${field}"]`).text(value); }

	addStyles() {
		if (document.getElementById("rfq-quotation-workbench-style")) return;
		$("<style id=\"rfq-quotation-workbench-style\">\
			.rfq-workbench-page .page-body .container, .rfq-workbench-page .page-body .container-fluid { max-width:none; width:100%; }\
			.rfq-workbench-page .layout-main-section-wrapper, .rfq-workbench-page .layout-main-section { width:100%; }\
			.rfq-workbench-page .layout-main-section { background:var(--bg-color); padding:0 !important; }\
			.rfq-workbench { background:var(--bg-color); color:var(--text-color); min-height:calc(100vh - 150px); width:100%; }\
			.rfq-workbench-topbar { align-items:center; background:#087db9; color:#fff; display:flex; gap:18px; min-height:48px; padding:7px 24px; }\
			.rfq-brand { font-size:13px; font-weight:800; letter-spacing:2px; } .rfq-breadcrumb { font-size:11px; opacity:.9; }\
			.rfq-top-actions { display:flex; gap:12px; margin-left:auto; } .rfq-top-actions .btn { background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.45); color:#fff; font-size:11px; min-height:30px; padding:5px 15px; }\
			.rfq-top-actions .btn-light { background:var(--card-bg); color:var(--primary); font-weight:600; }\
			.rfq-workbench-content { padding:16px 0 24px; width:100%; }\
			.rfq-filter-panel { background:var(--card-bg); border:1px solid var(--border-color); border-radius:4px; display:grid; gap:16px; grid-template-columns:minmax(240px,.8fr) minmax(280px,1.2fr); margin-bottom:14px; padding:12px 18px; }\
			.rfq-filter-panel label { color:var(--text-muted); display:block; font-size:9px; font-weight:700; letter-spacing:.6px; margin-bottom:5px; text-transform:uppercase; } .rfq-filter-panel .form-group { margin:0; } .rfq-filter-panel .control-label { display:none; }\
			.rfq-filter-panel .form-control { background:var(--control-bg); border-color:var(--border-color); color:var(--text-color); }\
			.rfq-overview-card { background:var(--card-bg); border:1px solid var(--border-color); border-radius:4px; border-top:3px solid var(--primary); padding:16px 20px; transition:opacity .15s; } .rfq-overview-card.is-loading { opacity:.55; pointer-events:none; }\
			.rfq-overview-head { align-items:flex-start; display:flex; gap:30px; justify-content:space-between; margin-bottom:16px; } .rfq-title-block > div { align-items:center; display:flex; gap:12px; }\
			.rfq-title-block h2 { color:var(--heading-color); font-size:22px; font-weight:750; margin:0; } .rfq-title-block p { color:var(--text-muted); font-size:11px; margin:4px 0 0; }\
			.rfq-status-pill { background:var(--orange-100,rgba(245,158,11,.14)); border-radius:3px; color:var(--orange-600,#b46b08); font-size:9px; font-weight:700; letter-spacing:.7px; padding:4px 10px; }\
			.rfq-overview-meta { display:flex; gap:30px; } .rfq-overview-meta div { min-width:90px; } .rfq-overview-meta span, .rfq-overview-meta strong { display:block; }\
			.rfq-overview-meta span, .rfq-kpi > span { color:var(--text-muted); font-size:9px; font-weight:700; letter-spacing:.8px; text-transform:uppercase; } .rfq-overview-meta strong { color:var(--text-color); font-size:11px; margin-top:3px; }\
			.rfq-kpi-grid { border:1px solid var(--border-color); border-radius:3px; display:grid; grid-template-columns:repeat(7,minmax(130px,1fr)); overflow:hidden; } .rfq-kpi { background:var(--card-bg); border-right:1px solid var(--border-color); min-height:82px; padding:12px 14px; } .rfq-kpi:last-child { border-right:0; }\
			.rfq-kpi span, .rfq-kpi strong, .rfq-kpi small { display:block; } .rfq-kpi strong { color:var(--text-color); font-size:18px; margin:6px 0 4px; white-space:nowrap; } .rfq-kpi small { color:var(--text-muted); font-size:9px; }\
			.rfq-kpi-negative strong { color:var(--red-500,#d12d22); } .rfq-kpi-offer { background:var(--control-bg); } .rfq-kpi-offer strong { color:var(--primary); }\
			.rfq-model-summary-card { background:var(--card-bg); border:1px solid var(--border-color); border-radius:4px; margin-top:14px; overflow:hidden; }\
			.rfq-model-summary-head { align-items:center; border-bottom:1px solid var(--border-color); display:flex; gap:12px; min-height:62px; padding:10px 16px; }\
			.rfq-section-number { border:1px solid var(--primary); border-radius:3px; color:var(--primary); font-size:10px; font-weight:700; padding:3px 6px; }\
			.rfq-model-summary-head h3 { color:var(--heading-color); font-size:14px; font-weight:700; margin:0; } .rfq-model-summary-head p { color:var(--text-muted); font-size:9px; margin:3px 0 0; }\
			.rfq-read-only { color:var(--text-muted); font-size:9px; margin-left:auto; white-space:nowrap; }\
			.rfq-model-toolbar { align-items:center; display:flex; flex-wrap:wrap; gap:8px; padding:9px 16px; } .rfq-model-search { background:var(--control-bg); border-color:var(--border-color); color:var(--text-color); font-size:10px; height:29px; width:210px; }\
			.rfq-type-filter, .rfq-placeholder-filter { background:var(--card-bg); border:1px solid var(--border-color); border-radius:15px; color:var(--text-color); font-size:9px; padding:4px 11px; } .rfq-type-filter.is-active { background:var(--primary); border-color:var(--primary); color:#fff; }\
			.rfq-model-table-scroll { overflow-x:auto; } .rfq-model-table { border-collapse:collapse; min-width:1500px; table-layout:fixed; width:100%; }\
			.rfq-model-table th { background:var(--primary); color:#fff; font-size:9px; font-weight:700; letter-spacing:.5px; padding:9px 10px; text-align:left; text-transform:uppercase; white-space:nowrap; }\
			.rfq-model-table td { border-bottom:1px solid var(--border-color); color:var(--text-color); font-size:10px; height:41px; padding:8px 10px; vertical-align:middle; } .rfq-model-table tbody tr:nth-child(even) td { background:var(--control-bg); }\
			.rfq-model-table th:nth-child(1) { width:85px; } .rfq-model-table th:nth-child(2) { width:205px; } .rfq-model-table th:nth-child(3) { width:140px; } .rfq-model-table th:nth-child(4), .rfq-model-table th:nth-child(5), .rfq-model-table th:nth-child(6) { width:80px; } .rfq-model-table th:nth-child(7), .rfq-model-table th:nth-child(8) { width:90px; } .rfq-model-table th:nth-child(9) { width:70px; }\
			.rfq-model-name { font-weight:600; } .rfq-model-qty { font-weight:600; } .rfq-type-pill { background:var(--control-bg); border-radius:3px; color:var(--primary); display:inline-block; font-size:9px; font-weight:600; padding:2px 5px; } .rfq-status-badge { border-radius:3px; display:inline-block; font-size:9px; font-weight:600; padding:2px 6px; white-space:nowrap; } .rfq-status-badge.is-working { background:var(--green-100,rgba(34,197,94,.12)); color:var(--green-600,#16823b); } .rfq-status-badge.is-not-working { background:var(--red-100,rgba(239,68,68,.12)); color:var(--red-500,#d12d22); }\
			.rfq-model-table tfoot td { background:var(--control-bg); border-bottom:0; border-top:2px solid var(--primary); white-space:nowrap; } .rfq-model-table tfoot small { color:var(--text-muted); font-size:8px; margin-left:3px; } .rfq-model-table tfoot .rfq-total-deduction strong { color:var(--red-500,#d12d22); } .rfq-model-empty { color:var(--text-muted) !important; padding:22px !important; text-align:center; }\
			.rfq-qc-record-card { background:var(--card-bg); border:1px solid var(--border-color); border-radius:4px; margin-top:14px; overflow:hidden; }\
			.rfq-qc-record-head { align-items:center; border-bottom:1px solid var(--border-color); display:flex; gap:12px; min-height:62px; padding:10px 16px; }\
			.rfq-qc-record-head h3 { color:var(--heading-color); font-size:14px; font-weight:700; margin:0; } .rfq-qc-record-head p { color:var(--text-muted); font-size:9px; margin:3px 0 0; }\
			.rfq-qc-counter { color:var(--text-muted); font-size:10px; margin-left:auto; }\
			.rfq-qc-toolbar { align-items:center; display:flex; flex-wrap:wrap; gap:8px; padding:9px 16px; }\
			.rfq-qc-search { background:var(--control-bg); border-color:var(--border-color); color:var(--text-color); font-size:10px; height:29px; width:210px; }\
			.rfq-qc-filter { background:var(--card-bg); border:1px solid var(--border-color); border-radius:15px; color:var(--text-color); font-size:9px; padding:4px 11px; }\
			.rfq-qc-filter.is-active { background:var(--primary); border-color:var(--primary); color:#fff; }\
			.rfq-qc-table-scroll { overflow-x:auto; }\
			.rfq-qc-table { border-collapse:collapse; min-width:2600px; table-layout:fixed; width:100%; }\
			.rfq-qc-table th { background:var(--primary); color:#fff; font-size:9px; font-weight:700; letter-spacing:.5px; padding:9px 10px; text-align:center; text-transform:uppercase; white-space:nowrap; min-width:85px; }\
			.rfq-qc-table th:nth-child(1) { width: 140px; min-width: 140px; text-align:left; }\
			.rfq-qc-table th:nth-child(2) { width: 250px; min-width: 250px; text-align:left; }\
			.rfq-qc-table th:nth-child(3) { width: 180px; min-width: 180px; text-align:left; }\
			.rfq-qc-table th:nth-child(4) { width: 90px; min-width: 90px; text-align:left; }\
			.rfq-qc-table th:nth-child(5) { width: 120px; min-width: 120px; text-align:left; }\
			.rfq-qc-table th:nth-child(7) { width: 145px; min-width: 145px; }\
			.rfq-qc-table th:nth-child(12) { width: 130px; min-width: 130px; }\
			.rfq-qc-table th:nth-child(14) { width: 115px; min-width: 115px; }\
			.rfq-qc-table th:nth-child(16) { width: 165px; min-width: 165px; }\
			.rfq-qc-table th:nth-child(18) { width: 125px; min-width: 125px; }\
			.rfq-qc-table th:nth-child(22) { width: 140px; min-width: 140px; }\
			.rfq-qc-table th:nth-child(25) { width: 110px; min-width: 110px; text-align:right; }\
			.rfq-qc-table td { border-bottom:1px solid var(--border-color); color:var(--text-color); font-size:10px; height:38px; padding:6px 10px; text-align:center; vertical-align:middle; white-space:nowrap; }\
			.rfq-qc-table td:nth-child(1) { text-align:left; }\
			.rfq-qc-table td:nth-child(2) { text-align:left; }\
			.rfq-qc-table td:nth-child(3) { text-align:left; }\
			.rfq-qc-table td:nth-child(4) { text-align:left; }\
			.rfq-qc-table td:nth-child(5) { text-align:left; }\
			.rfq-qc-table tbody tr:nth-child(even) td { background:var(--control-bg); }\
			.rfq-qc-serial { font-weight:600; }\
			.rfq-qc-name { color:var(--primary); font-weight:500; display:inline-block; max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; vertical-align:middle; text-decoration:none; }\
			.rfq-qc-name:hover { text-decoration:underline; }\
			.rfq-qc-model { display:inline-block; max-width:170px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; vertical-align:middle; }\
			.rfq-qc-deduction { font-weight:600; color:var(--red-500,#d12d22); text-align:right !important; }\
			.rfq-grade-badge { border-radius:3px; display:inline-block; font-size:9px; font-weight:700; height:18px; line-height:18px; text-align:center; width:18px; }\
			.rfq-grade-badge.grade-a { background:rgba(34,197,94,.15); color:#16a34a; }\
			.rfq-grade-badge.grade-b { background:rgba(59,130,246,.15); color:#2563eb; }\
			.rfq-grade-badge.grade-c { background:rgba(239,68,68,.15); color:#dc2626; }\
			.rfq-grade-badge.grade-d { background:rgba(245,158,11,.15); color:#d97706; }\
			.rfq-grade-badge.grade-dash { color:var(--text-muted); }\
			.rfq-depth-pill { background:rgba(34,197,94,.12); border-radius:3px; color:#16a34a; display:inline-block; font-size:9px; font-weight:600; padding:2px 6px; }\
			.rfq-depth-pill.is-spec { background:rgba(59,130,246,.12); color:#2563eb; }\
			.rfq-qc-legend { align-items:center; background:var(--card-bg); border-top:1px solid var(--border-color); color:var(--text-muted); display:flex; flex-wrap:wrap; gap:20px; font-size:10px; padding:10px 16px; }\
			.rfq-qc-legend > span { align-items:center; display:inline-flex; gap:6px; }\
			@media (max-width:1200px) { .rfq-kpi-grid { grid-template-columns:repeat(4,1fr); } .rfq-kpi { border-bottom:1px solid var(--border-color); } .rfq-overview-head { flex-direction:column; } }\
			@media (max-width:767px) { .rfq-workbench-topbar { align-items:flex-start; flex-wrap:wrap; } .rfq-top-actions { margin-left:0; width:100%; } .rfq-filter-panel { grid-template-columns:1fr; } .rfq-kpi-grid { grid-template-columns:repeat(2,1fr); } .rfq-overview-meta { flex-wrap:wrap; gap:14px; } }\
		</style>").appendTo("head");
	}
}
