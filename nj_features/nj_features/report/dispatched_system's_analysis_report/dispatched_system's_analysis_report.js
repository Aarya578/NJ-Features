// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Dispatched System's analysis Report"] = {
	"filters": [
		{
			"fieldname": "serial_no",
			"label": __("Serial No"),
			"fieldtype": "Data",
			"reqd": 1
		},
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"hidden": 1,
			"reqd": 0
		},
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), -6),
			"hidden": 1
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"hidden": 1
		},
		// {
		// 	"fieldname": "warehouse",
		// 	"label": __("Warehouse"),
		// 	"fieldtype": "Link",
		// 	"options": "Warehouse",
		// 	"get_query": function() {
		// 		const company = frappe.query_report.get_filter_value('company');
		// 		return {
		// 			filters: { 'company': company }
		// 		};
		// 	}
		// },
		// {
		// 	"fieldname": "voucher_no",
		// 	"label": __("Voucher #"),
		// 	"fieldtype": "Data"
		// },
		// {
		// 	"fieldname": "parent",
		// 	"label": __("Parent"),
		// 	"fieldtype": "Link",
		// 	"hidden": 0,
		// 	"options": "parent"
		// }
	],

	"formatter": function(value, row, column, data, default_formatter) {
    if (column.fieldname === "parent") {
        let parent = data.parenttype.toLowerCase().replace(/ /g, "-");
        let link = `/app/${parent}/${value}`;
        value = `<a href="${link}" target="_blank">${value}</a>`;
    } else if (column.fieldname === "status") {
		if (data.s_warehouse && data.item_group !== "Laptops"){
			value = `Added`;
			data.part_current_warehouse = 'Delivered';
			data.part_item_code = '';
		} else if (data.t_warehouse && data.item_group !== "Laptops"){
			value = `Removed`;
			if(data.part_current_warehouse == '' || data.part_current_warehouse == null){
				data.part_item_code = '';
			}
		}else{
			value = '';
		}
    } else if (column.fieldname === "part_current_warehouse"){
		if(data.part_current_warehouse && data.item_group !== "Laptops"){
			value = data.part_current_warehouse;
		}else{
			value = '';
		}
	}else if (column.fieldname === "part_item_code"){
		if(data.part_item_code && data.item_group !== "Laptops"){
			value = data.part_item_code;
		}else{
			value = '';
		}
	}
	else {
        value = default_formatter(value, row, column, data);
    }
    return value;
}
};
