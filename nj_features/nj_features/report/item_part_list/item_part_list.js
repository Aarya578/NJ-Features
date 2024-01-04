// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Item Part List"] = {
	"filters": [
		{
			"fieldname":"serial_no",
			"label": __("Serial No"),
			"fieldtype": "Data",
			"reqd": 1
		}
	]
};
