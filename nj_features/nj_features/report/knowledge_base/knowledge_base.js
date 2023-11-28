// Copyright (c) 2023, NewJaisa - IT Team
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Knowledge Base"] = {
	"filters": [
		{
			"fieldname":"brand",
			"label": __("Brand"),
			"fieldtype": "Link",
			"options": "Brand",
			"reqd": 0
		},
		{
			"fieldname":"model",
			"label": __("Model"),
			"fieldtype": "Link",
			"options": "Models",
			"reqd": 0
		},
		{
			"fieldname":"part",
			"label": __("Part"),
			"fieldtype": "Link",
			"options": "Item Group",
			"reqd": 0
		},
		{
			"fieldname":"department",
			"label": __("Department"),
			"fieldtype": "Link",
			"options": "Department",
			"reqd": 0
		},
		{
			"fieldname":"name",
			"label": __("Name"),
			"fieldtype": "Data",
			"reqd": 0
		}
	]
};
