// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Item Part History"] = {
	"filters": [
		{
			"fieldname":"barcode",
			"label": __("NJ Barcode"),
			"fieldtype": "Data",
			"reqd": 1
		}
	]
};
