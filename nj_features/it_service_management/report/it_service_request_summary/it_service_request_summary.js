frappe.query_reports["IT Service Request Summary"] = {
    "filters": [
        {
            "fieldname": "priority",
            "label": __("Priority"),
            "fieldtype": "Select",
            "options": "\nUrgent\nHigh\nMedium\nLow"
        },
        {
            "fieldname": "status",
            "label": __("Status"),
            "fieldtype": "Select",
            "options": "\nDraft\nOpen\nIn Progress\nPending Review\nResolved\nClosed\nRejected"
        },
        {
            "fieldname": "department",
            "label": __("Department"),
            "fieldtype": "Link",
            "options": "Department"
        }
    ],
    "formatter": function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (column.fieldname === "sla_status") {
            if (data.sla_status === "Breached") {
                value = `<span class="indicator-pill red">${data.sla_status}</span>`;
            } else if (data.sla_status === "Near Breach") {
                value = `<span class="indicator-pill orange">${data.sla_status}</span>`;
            } else if (data.sla_status === "Within SLA") {
                value = `<span class="indicator-pill green">${data.sla_status}</span>`;
            } else if (data.sla_status === "Completed") {
                value = `<span class="indicator-pill blue">${data.sla_status}</span>`;
            }
        }
        return value;
    }
};
