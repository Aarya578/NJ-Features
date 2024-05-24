// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Stock in Work Warehouse"] = {
	"filters": [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"hidden": 1,
			"reqd": 0
		},
		{
			"fieldname":"warehouse",
			"label": __("Work Warehouse"),
			"fieldtype": "Link",
			"options": "Warehouse",
			"reqd": 1,
			"get_query": function() {
					const company = frappe.query_report.get_filter_value('company');
					return {
							filters: { 'company': company }
					}
			}
		}
	]
};
