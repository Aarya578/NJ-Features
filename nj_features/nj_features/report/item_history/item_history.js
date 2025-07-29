frappe.query_reports["Item History"] = {
        "filters": [
            {
                "fieldname": "barcode",
                "label": __("NJ Barcode"),
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
            {
                "fieldname": "warehouse",
                "label": __("Warehouse"),
                "fieldtype": "Link",
                "options": "Warehouse",
                "get_query": function() {
                    const company = frappe.query_report.get_filter_value('company');
                    return {
                        filters: { 'company': company }
                    };
                }
            },
            {
                "fieldname": "voucher_no",
                "label": __("Voucher #"),
                "fieldtype": "Data"
            },
            {
                "fieldname": "department",
                "label": __("Department"),
                "fieldtype": "Link",
                "hidden": 0,
                "options": "Department"
            }
        ],
    
        "formatter": function(value, row, column, data, default_formatter) {
            if (column.fieldname === "ste_number") {
                let voucher_type = data.voucher_type.toLowerCase().replace(/ /g, "-");
                let link = `/app/${voucher_type}/${value}`;
                value = `<a href="${link}" target="_blank">${value}</a>`;
                return value;
            } else {
                return default_formatter(value, row, column, data);
            }
        }
    };
    