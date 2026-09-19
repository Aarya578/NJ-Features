(() => {
	const methodPath =
		"nj_features.nj_features.doctype.quotation_customer_access.quotation_customer_access";
	const token = new URLSearchParams(window.location.search).get("token");
	const summary = document.getElementById("response-summary");
	const message = document.getElementById("response-message");
	const form = document.getElementById("response-form");
	const responseField = document.getElementById("customer-replay");
	const submitButton = document.getElementById("submit-response");
	const choiceButtons = document.querySelectorAll(".response-choice-btn");
	const choiceText = document.getElementById("response-choice-text");

	const CHOICE_TEXT = {
		Agree: "You have agreed to this quotation.",
		"Dis Agree": "You have disagreed with this quotation."
	};

	const applyChoice = (value) => {
		responseField.value = value || "";
		choiceButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.value === value));
		if (value && CHOICE_TEXT[value]) {
			choiceText.textContent = CHOICE_TEXT[value];
			choiceText.classList.remove("d-none");
			choiceText.classList.toggle("text-success", value === "Agree");
			choiceText.classList.toggle("text-danger", value === "Dis Agree");
		} else {
			choiceText.classList.add("d-none");
			choiceText.classList.remove("text-success", "text-danger");
		}
		submitButton.disabled = !value;
	};

	choiceButtons.forEach((btn) => {
		btn.addEventListener("click", () => applyChoice(btn.dataset.value));
	});

	const escapeHtml = (value) => {
		const element = document.createElement("div");
		element.textContent = value == null ? "" : String(value);
		return element.innerHTML;
	};

	const formatNumber = (value, maximumFractionDigits = 2) =>
		new Intl.NumberFormat(undefined, { maximumFractionDigits }).format(Number(value) || 0);

	const formatCurrency = (value, currency) => {
		try {
			return new Intl.NumberFormat(undefined, {
				style: "currency",
				currency: currency || "INR"
			}).format(Number(value) || 0);
		} catch (error) {
			return `${escapeHtml(currency || "")} ${formatNumber(value)}`.trim();
		}
	};

	const showMessage = (text, type) => {
		message.textContent = text;
		message.classList.remove("d-none", "success", "error");
		if (type) message.classList.add(type);
	};

	const apiCall = async (method, values, post = false) => {
		const url = new URL(`/api/method/${methodPath}.${method}`, window.location.origin);
		const options = { credentials: "same-origin", headers: { Accept: "application/json" } };
		if (post) {
			options.method = "POST";
			options.headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8";
			if (window.frappe && frappe.csrf_token) {
				options.headers["X-Frappe-CSRF-Token"] = frappe.csrf_token;
			}
			options.body = new URLSearchParams(values).toString();
		} else {
			Object.entries(values).forEach(([key, value]) => url.searchParams.set(key, value));
		}

		const response = await fetch(url.toString(), options);
		const body = await response.json();
		if (!response.ok || body.exc) throw new Error("Invalid, expired, or unavailable quotation link.");
		return body.message || {};
	};

	const render = (data) => {
		document.getElementById("response-quotation").textContent = data.quotation || "";
		document.getElementById("response-customer").textContent = data.customer || "";
		document.getElementById("response-items-total").textContent = formatCurrency(
			data.total,
			data.currency
		);
		document.getElementById("response-grand-total").textContent = formatCurrency(
			data.grand_total,
			data.currency
		);
		document.getElementById("response-total-taxes").textContent = formatCurrency(
			data.total_taxes_and_charges,
			data.currency
		);
		document.getElementById("response-terms-name").textContent = data.tc_name || "-";
		document.getElementById("response-terms-details").innerHTML = data.terms || "-";
		applyChoice(data.customer_replay || "");

		document.getElementById("response-items").innerHTML = (data.items || [])
			.map(
				(row) => `<tr>
					<td>${escapeHtml(row.item_code)}</td>
					<td class="text-right">${formatNumber(row.qty)}</td>
					<td class="text-right">${formatCurrency(row.rate, data.currency)}</td>
					<td class="text-right">${formatCurrency(row.amount, data.currency)}</td>
					<td>${escapeHtml(row.hsn_sac)}</td>
				</tr>`
			)
			.join("");

		const taxes = data.taxes || [];
		document.getElementById("taxes-section").classList.toggle("d-none", !taxes.length);
		document.getElementById("response-taxes").innerHTML = taxes
			.map(
				(row) => `<tr>
					<td>${escapeHtml(row.type)}</td>
					<td>${escapeHtml(row.account_head)}</td>
					<td class="text-right">${formatNumber(row.rate)}%</td>
					<td class="text-right">${formatCurrency(row.amount, data.currency)}</td>
					<td class="text-right">${formatCurrency(row.total, data.currency)}</td>
				</tr>`
			)
			.join("");

		const payments = data.payment_schedule || [];
		document.getElementById("payment-section").classList.toggle("d-none", !payments.length);
		document.getElementById("response-payments").innerHTML = payments
			.map(
				(row) => `<tr>
					<td>${escapeHtml(row.payment_term)}</td>
					<td>${escapeHtml(row.description)}</td>
					<td class="text-right">${formatNumber(row.invoice_portion)}%</td>
					<td class="text-right">${formatCurrency(row.payment_amount, data.currency)}</td>
				</tr>`
			)
			.join("");
	};

	const initialize = async () => {
		if (!token) return showMessage("Quotation token is missing.", "error");
		try {
			const data = await apiCall("get_quotation_response", { token });
			render(data);
			summary.classList.remove("d-none");
			message.classList.add("d-none");
			form.classList.remove("d-none");
		} catch (error) {
			showMessage(error.message, "error");
		}
	};

	form.addEventListener("submit", async (event) => {
		event.preventDefault();
		if (!responseField.value) {
			showMessage("Please choose Agree or Disagree before submitting.", "error");
			return;
		}
		submitButton.disabled = true;
		try {
			const data = await apiCall(
				"submit_quotation_response",
				{ token, customer_replay: responseField.value },
				true
			);
			form.classList.add("d-none");
			showMessage(data.message || "Your response was submitted successfully.", "success");
		} catch (error) {
			submitButton.disabled = false;
			showMessage(error.message || "Unable to submit your response.", "error");
		}
	});

	initialize();
})();
