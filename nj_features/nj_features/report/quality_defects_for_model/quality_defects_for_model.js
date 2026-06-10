// Copyright (c) 2025, NewJaisa - IT Team and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Quality Defects For Model"] = {
    "filters": [
        {
            "fieldname": "model",
            "label": "Model",
            "fieldtype": "Link",
            "options": "Models",
            "reqd": 1
        },
        {
            "fieldname": "item_code",
            "label": "Item Code",
            "fieldtype": "Link",
            "options": "Item"
        },
        {
            "fieldname": "from_date",
            "label": "From Date",
            "fieldtype": "Date",
            "default": "2020-01-01",
            "reqd": 1
        },
        {
            "fieldname": "to_date",
            "label": "To Date",
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "reqd": 1
        }
    ],

    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (data && data.item_group === "TOTAL") {
            return `<b style="color: green;">${value}</b>`;
        }
        return value;
    }
};