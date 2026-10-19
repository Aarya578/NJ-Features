(() => {
	const methodPath = "nj_features.nj_features.doctype.rfq_dashboard_access.rfq_dashboard_access";
	const token = new URLSearchParams(window.location.search).get("token");
	const supplierSelect = document.getElementById("dashboard-supplier");
	const rfqSelect = document.getElementById("dashboard-rfq");
	const message = document.getElementById("dashboard-message");
	const content = document.getElementById("dashboard-content");
	const searchInput = document.querySelector(".rfq-model-search");
	const createQiButton = document.querySelector(".rfq-create-qi");
	let currency = "INR";
	let modelRows = [];
	let activeType = "all";
	let njpulseUrl = "";

	const escapeHtml = (value) => {
		const element = document.createElement("div");
		element.textContent = value == null ? "" : String(value);
		return element.innerHTML;
	};

	const number = (value, decimals = 2) => Number(value || 0).toLocaleString("en-IN", {
		minimumFractionDigits: decimals,
		maximumFractionDigits: decimals
	});

	const money = (value) => {
		try {
			return new Intl.NumberFormat("en-IN", {
				style: "currency",
				currency: currency || "INR",
				minimumFractionDigits: 2,
				maximumFractionDigits: 2
			}).format(Number(value || 0));
		} catch (error) {
			return `${currency || ""} ${number(value, 2)}`.trim();
		}
	};

	const date = (value) => value ? String(value) : "—";
	const setValue = (field, value) => {
		content.querySelectorAll(`[data-value="${field}"]`).forEach((node) => {
			node.textContent = value;
		});
	};

	const call = async (method, args) => {
		const url = new URL(`/api/method/${methodPath}.${method}`, window.location.origin);
		Object.entries(args).forEach(([key, value]) => url.searchParams.set(key, value));
		const response = await fetch(url.toString(), {
			credentials: "same-origin",
			headers: { Accept: "application/json" }
		});
		const body = await response.json();
		if (!response.ok || body.exc) {
			throw new Error(body._server_messages || "Unable to load dashboard data.");
		}
		return body.message || {};
	};

	const showMessage = (text, isError = false) => {
		message.textContent = text;
		message.classList.remove("d-none", "is-error");
		if (isError) message.classList.add("is-error");
		content.classList.add("d-none");
	};

	const normalizeType = (value) => {
		const type = String(value || "").toLowerCase();
		if (type.includes("laptop")) return "laptop";
		if (type.includes("desktop")) return "desktop";
		if (type.includes("mac")) return "mac";
		return type;
	};

	const renderModelRows = () => {
		const search = String(searchInput.value || "").trim().toLowerCase();
		const rows = modelRows.filter((row) => {
			const matchesType = activeType === "all" || normalizeType(row.type) === activeType;
			const matchesSearch = !search || `${row.model || ""} ${row.processor || ""}`.toLowerCase().includes(search);
			return matchesType && matchesSearch;
		});

		const tbody = document.querySelector(".rfq-model-table tbody");
		tbody.innerHTML = rows.map((row) => `<tr>
			<td><span class="rfq-type-pill rfq-type-${normalizeType(row.type)}">${escapeHtml(row.type || "")}</span></td>
			<td class="rfq-model-name">${escapeHtml(row.model || "")}</td>
			<td>${escapeHtml(row.processor || "")}</td><td>${escapeHtml(row.ram || "")}</td><td>${escapeHtml(row.ssd || "")}</td><td>${escapeHtml(row.screen || "")}</td>
			<td></td><td><span class="rfq-status-badge ${row.status === "Working" ? "is-working" : "is-not-working"}">${escapeHtml(row.status || "")}</span></td>
			<td class="rfq-model-qty">${number(row.qty, 2)}</td>
			<td>${row.grade_a_rate == null ? "" : money(row.grade_a_rate)}</td>
			<td>${money(row.deduction_per_unit || 0)}</td>
			<td>${row.final_rate == null ? "" : money(row.final_rate)}</td>
			<td>${row.line_total == null ? "" : money(row.line_total)}</td>
		</tr>`).join("") || `<tr><td colspan="13" class="rfq-model-empty">No matching RFQ items found.</td></tr>`;

		const totalQty = rows.reduce((total, row) => total + Number(row.qty || 0), 0);
		const pricedQty = rows.reduce((total, row) => row.final_rate == null ? total : total + Number(row.qty || 0), 0);
		const gradeATotal = rows.reduce((total, row) => total + Number(row.qty || 0) * Number(row.grade_a_rate || 0), 0);
		const deductionTotal = rows.reduce((total, row) => total + Number(row.qty || 0) * Number(row.deduction_per_unit || 0), 0);
		const lineTotal = rows.reduce((total, row) => total + Number(row.line_total || 0), 0);
		const averageFinalRate = pricedQty ? lineTotal / pricedQty : 0;
		document.querySelector(".rfq-model-table tfoot").innerHTML = `<tr>
			<td colspan="8"><strong>Total — ${rows.length} models</strong></td>
			<td><strong>${number(totalQty, 2)}</strong></td>
			<td><strong>${money(gradeATotal)}</strong></td>
			<td class="rfq-total-deduction"><strong>${money(-deductionTotal)}</strong></td>
			<td><strong>${money(averageFinalRate)}</strong> <small>avg</small></td>
			<td><strong>${money(lineTotal)}</strong></td>
		</tr>`;
	};

	const renderWorkbench = (data) => {
		currency = data.currency || "INR";
		modelRows = data.model_rows || [];
		njpulseUrl = String(data.njpulse_url || "").trim();
		createQiButton.disabled = !njpulseUrl;
		setValue("rfq_name", data.rfq || "—");
		setValue("status", String(data.status || "Draft").toUpperCase());
		setValue("supplier", data.supplier || "—");
		setValue("company", data.company || "—");
		setValue("rfq_date", date(data.rfq_date));
		setValue("required_date", date(data.required_date));
		setValue("total_items", number(data.total_items, 2));
		setValue("currency", currency);
		setValue("units_in_lot", number(data.total_qty, 2));
		setValue("models", `${number(data.total_items, 2)} models`);
		setValue("units_inspected", number(data.total_submitted, 2));
		setValue("function_tested", number(data.function_tested, 2));
		document.getElementById("breadcrumb-rfq").textContent = data.rfq || "—";

		const gradeAValue = modelRows.reduce((total, row) => total + Number(row.qty || 0) * Number(row.grade_a_rate || 0), 0);
		const deductions = modelRows.reduce((total, row) => total + Number(row.qty || 0) * Number(row.deduction_per_unit || 0), 0);
		const netLotOffer = modelRows.reduce((total, row) => total + Number(row.line_total || 0), 0);
		const pricedQty = modelRows.reduce((total, row) => row.final_rate == null ? total : total + Number(row.qty || 0), 0);
		setValue("grade_a_value", money(gradeAValue));
		setValue("deductions", money(-deductions));
		setValue("deduction_percent", `${number(gradeAValue ? deductions / gradeAValue * 100 : 0, 2)}% of Grade A`);
		setValue("net_lot_offer", money(netLotOffer));
		setValue("net_unit_average", `${money(pricedQty ? netLotOffer / pricedQty : 0)} / unit avg`);

		activeType = "all";
		searchInput.value = "";
		document.querySelectorAll(".rfq-type-filter").forEach((button) => button.classList.toggle("is-active", button.dataset.type === "all"));
		renderModelRows();
	};

	const loadDashboard = async () => {
		if (!rfqSelect.value) {
			showMessage("Please select an RFQ.");
			return;
		}
		showMessage("Loading dashboard...");
		try {
			const data = await call("get_public_dashboard", { token, rfq: rfqSelect.value });
			renderWorkbench(data);
			message.classList.add("d-none");
			content.classList.remove("d-none");
		} catch (error) {
			showMessage("Invalid, expired, or unauthorized dashboard link.", true);
		}
	};

	const initialize = async () => {
		if (!token) {
			showMessage("Dashboard token is missing.", true);
			return;
		}
		try {
			const options = await call("get_public_dashboard_options", { token });
			supplierSelect.innerHTML = `<option value="${escapeHtml(options.supplier)}">${escapeHtml(options.supplier)}</option>`;
			rfqSelect.innerHTML = '<option value="">Select RFQ</option>' + (options.rfqs || []).map((row) => `<option value="${escapeHtml(row.name)}">${escapeHtml(row.name)}</option>`).join("");
			rfqSelect.disabled = false;
			showMessage("Please select an RFQ to view the dashboard.");
			if ((options.rfqs || []).length === 1) {
				rfqSelect.value = options.rfqs[0].name;
				loadDashboard();
			}
		} catch (error) {
			showMessage("Invalid or expired dashboard link.", true);
		}
	};

	rfqSelect.addEventListener("change", loadDashboard);
	createQiButton.addEventListener("click", () => {
		if (!njpulseUrl) {
			window.alert("NJPulse URL is not configured.");
			return;
		}
		window.open(njpulseUrl, "_blank", "noopener,noreferrer");
	});
	searchInput.addEventListener("input", renderModelRows);
	document.querySelectorAll(".rfq-type-filter").forEach((button) => button.addEventListener("click", () => {
		activeType = button.dataset.type;
		document.querySelectorAll(".rfq-type-filter").forEach((item) => item.classList.remove("is-active"));
		button.classList.add("is-active");
		renderModelRows();
	}));
	document.querySelectorAll(".rfq-ui-only").forEach((button) => button.addEventListener("click", () => window.alert("This functionality will be added in the next phase.")));
	document.querySelectorAll(".rfq-placeholder-filter").forEach((button) => button.addEventListener("click", (event) => event.preventDefault()));
	initialize();
})();
