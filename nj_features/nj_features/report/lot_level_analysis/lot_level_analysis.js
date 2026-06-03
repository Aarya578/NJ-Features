// Copyright (c) 2025, NewJaisa - IT Team and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Lot Level Analysis"] = {
	"filters": [
		{
			"fieldname": "model",
			"label": __("Model"),
			"fieldtype": "Link",
			"options": "Models",
			"reqd": 0
		},
		{
			"fieldname": "supplier",
			"label": __("Supplier"),
			"fieldtype": "Link",
			"options": "Supplier",
			"reqd": 0
		},
		{
			"fieldname": "purchase_order",
			"label": __("Purchase Order"),
			"fieldtype": "Link",
			"options": "Purchase Order",
			"reqd": 0
		}
	]
};




