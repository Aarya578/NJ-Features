(() => {
	const methodPath =
		"nj_features.nj_features.doctype.rfq_customer_quotation_access.rfq_customer_quotation_access";
	const token = new URLSearchParams(window.location.search).get("token");
	const info = document.getElementById("quotation-info");
	const rfqName = document.getElementById("quotation-rfq");
	const supplierName = document.getElementById("quotation-supplier");
	const message = document.getElementById("quotation-message");
	const form = document.getElementById("quotation-form");
	const itemBody = document.getElementById("quotation-items");
	const submitButton = document.getElementById("submit-quotation");
	let quotationItems = [];

	const escapeHtml = (value) => {
		const element = document.createElement("div");
		element.textContent = value == null ? "" : String(value);
		return element.innerHTML;
	};

	const showMessage = (text, type) => {
		message.textContent = text;
		message.classList.remove("d-none", "success", "error");
		if (type) {
			message.classList.add(type);
		}
	};

	const getQuotation = async () => {
		const url = new URL(
			`/api/method/${methodPath}.get_customer_quotation`,
			window.location.origin
		);
		url.searchParams.set("token", token);

		const response = await fetch(url.toString(), {
			credentials: "same-origin",
			headers: { Accept: "application/json" }
		});
		const body = await response.json();

		if (!response.ok || body.exc) {
			throw new Error("Invalid or expired quotation link.");
		}

		return body.message || {};
	};

	const submitQuotation = async (items) => {
		const url = `/api/method/${methodPath}.submit_customer_quotation`;
		const requestBody = new URLSearchParams({
			token,
			items: JSON.stringify(items)
		});
		const headers = {
			Accept: "application/json",
			"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
		};

		if (window.frappe && frappe.csrf_token) {
			headers["X-Frappe-CSRF-Token"] = frappe.csrf_token;
		}

		const response = await fetch(url, {
			method: "POST",
			credentials: "same-origin",
			headers,
			body: requestBody.toString()
		});
		const body = await response.json();

		if (!response.ok || body.exc) {
			throw new Error(body._server_messages || body.exception || "Unable to create Supplier Quotation.");
		}

		return body.message || {};
	};

	const renderItems = (items) => {
		itemBody.innerHTML = items
			.map(
				(row, index) => {
					const availability = Number(row.available_qty) > 0 ? "Yes" : "No";

					return `
					<tr>
						<td>${escapeHtml(row.item_code)}</td>
						<td>${escapeHtml(row.schedule_date)}</td>
						<td>
							<input
								class="form-control quotation-item-lead-date"
								data-index="${String(index)}"
								type="date"
								value="${escapeHtml(row.lead_date || "")}"
								required
							>
						</td>
						<td class="text-right">${escapeHtml(row.qty)}</td>
						<td>
							<select
								class="form-control quotation-availability"
								data-index="${String(index)}"
								required
							>
								<option value="Yes" ${availability === "Yes" ? "selected" : ""}>Yes</option>
								<option value="No" ${availability === "No" ? "selected" : ""}>No</option>
							</select>
						</td>
						<td>
							<input
								class="form-control quotation-available-qty"
								data-index="${String(index)}"
								min="0"
								step="1"
								type="number"
								value="${escapeHtml(row.available_qty || 0)}"
								required
							>
						</td>
						<td>
							<input
								class="form-control quotation-rate"
								data-index="${String(index)}"
								min="0"
								step="0.01"
								type="number"
								value="${escapeHtml(row.rate || 0)}"
								required
							>
						</td>
					</tr>
				`;
				}
			)
			.join("");
	};

	itemBody.addEventListener("input", (event) => {
		if (!event.target.matches(".quotation-available-qty")) {
			return;
		}

		const index = event.target.dataset.index;
		const availabilityField = itemBody.querySelector(
			`.quotation-availability[data-index="${String(index)}"]`
		);

		if (availabilityField && Number(event.target.value) > 0) {
			availabilityField.value = "Yes";
		}
	});

	itemBody.addEventListener("change", (event) => {
		if (!event.target.matches(".quotation-availability") || event.target.value !== "No") {
			return;
		}

		const index = event.target.dataset.index;
		const availableQtyField = itemBody.querySelector(
			`.quotation-available-qty[data-index="${String(index)}"]`
		);

		if (availableQtyField) {
			availableQtyField.value = 0;
		}
	});

	const initialize = async () => {
		if (!token) {
			showMessage("Quotation token is missing.", "error");
			return;
		}

		try {
			const data = await getQuotation();
			quotationItems = data.items || [];
			rfqName.textContent = data.rfq || "";
			supplierName.textContent = data.supplier || "";
			renderItems(quotationItems);
			info.classList.remove("d-none");
			message.classList.add("d-none");
			form.classList.remove("d-none");
		} catch (error) {
			showMessage("Invalid or expired quotation link.", "error");
		}
	};

	form.addEventListener("submit", async (event) => {
		event.preventDefault();
		submitButton.disabled = true;

		try {
			const items = quotationItems.map((row, index) => {
				const rateField = document.querySelector(
					`.quotation-rate[data-index="${String(index)}"]`
				);
				const availabilityField = document.querySelector(
					`.quotation-availability[data-index="${String(index)}"]`
				);
				const availableQtyField = document.querySelector(
					`.quotation-available-qty[data-index="${String(index)}"]`
				);
				const leadDateField = document.querySelector(
					`.quotation-item-lead-date[data-index="${String(index)}"]`
				);

				if (!rateField || !availabilityField || !availableQtyField || !leadDateField) {
					throw new Error(`Quotation fields were not found for item ${row.item_code}.`);
				}

				return {
					row_name: row.row_name,
					item_code: row.item_code,
					rate: rateField.value,
					availability: availabilityField.value,
					available_qty: availableQtyField.value,
					lead_date: leadDateField.value
				};
			});
			const data = await submitQuotation(items);
			form.classList.add("d-none");
			showMessage(data.message || "Supplier Quotation created successfully", "success");
		} catch (error) {
			submitButton.disabled = false;
			showMessage(
				error.message || "Unable to create Supplier Quotation. Please verify the entered values.",
				"error"
			);
		}
	});

	initialize();
})();
