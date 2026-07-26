(() => {
	const methodPath =
		"nj_features.nj_features.doctype.rfq_dashboard_access.rfq_dashboard_access";
	const token = new URLSearchParams(window.location.search).get("token");
	const supplierSelect = document.getElementById("dashboard-supplier");
	const rfqSelect = document.getElementById("dashboard-rfq");
	const refreshButton = document.getElementById("refresh-dashboard");
	const message = document.getElementById("dashboard-message");
	const content = document.getElementById("dashboard-content");
	const renderer = new RFQDashboardRenderer(content);

	const escapeHtml = (value) => {
		const element = document.createElement("div");
		element.textContent = value == null ? "" : String(value);
		return element.innerHTML;
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
		message.classList.remove("d-none");
		message.style.color = isError ? "#e24c4c" : "";
		content.classList.add("d-none");
	};

	const loadDashboard = async () => {
		if (!rfqSelect.value) {
			showMessage("Please select an RFQ.");
			return;
		}

		showMessage("Loading dashboard...");

		try {
			const data = await call("get_public_dashboard", {
				token,
				rfq: rfqSelect.value
			});
			renderer.render(data);
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
			supplierSelect.innerHTML = `<option value="${escapeHtml(options.supplier)}">${escapeHtml(
				options.supplier
			)}</option>`;
			rfqSelect.innerHTML =
				'<option value="">Select RFQ</option>' +
				(options.rfqs || [])
					.map(
						(row) =>
							`<option value="${escapeHtml(row.name)}">${escapeHtml(row.name)}</option>`
					)
					.join("");
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
	refreshButton.addEventListener("click", loadDashboard);
	initialize();
})();
