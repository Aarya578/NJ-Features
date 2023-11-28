// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Item History"] = {
	"filters": [
                {
                        "fieldname":"serial_no",
                        "label": __("Serial No"),
                        "fieldtype": "Data",
                        "reqd": 1
                },
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
                        "fieldname":"from_date",
                        "label": __("From Date"),
                        "fieldtype": "Date",
                        "default": frappe.datetime.add_months(frappe.datetime.get_today(), -6),
			"hidden": 1
                },
                {
                        "fieldname":"to_date",
                        "label": __("To Date"),
                        "fieldtype": "Date",
                        "default": frappe.datetime.get_today(),
			"hidden": 1
                },
                {
                        "fieldname":"warehouse",
                        "label": __("Warehouse"),
                        "fieldtype": "Link",
                        "options": "Warehouse",
                        "get_query": function() {
                                const company = frappe.query_report.get_filter_value('company');
                                return {
                                        filters: { 'company': company }
                                }
                        }
                },
                {
                        "fieldname":"voucher_no",
                        "label": __("Voucher #"),
                        "fieldtype": "Data"
                },
                {
                        "fieldname":"department",
                        "label": __("Department"),
                        "fieldtype": "Link",
                        "hidden": 1,
                        "options": "Department"
                }
        ]
};