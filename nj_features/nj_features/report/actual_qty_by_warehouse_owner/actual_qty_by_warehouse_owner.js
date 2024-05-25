// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Actual Qty by Warehouse Owner"] = {
	"filters": [
		{
			"fieldname":"warehouse_owner",
			"label": __("Warehouse Owner"),
			"fieldtype": "Link",
			"options": "User",
			"reqd": 1,
		}
	]
};
