// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["NJ Audit Report"] = {
	"filters": [
		{
			"fieldname":"current_date",
			"label": __("Current Date"),
			"fieldtype": "Date",
			"reqd": 0,
			"default": "Today"
		}
	],
};