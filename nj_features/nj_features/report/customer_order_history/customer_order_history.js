// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Customer Order History"] = {
    "filters": [
        {
            "fieldname": "order_id",
            "label": __("Order ID"),
            "fieldtype": "Data"
        },
        {
            "fieldname": "sales_order",
            "label": __("Sales Order"),
            "fieldtype": "Link",
            "options": "Sales Order"
        },
        {
            "fieldname": "serial_no",
            "label": __("Serial No"),
            "fieldtype": "Data"
        },
        {
            "fieldname": "delivery_note",
            "label": __("Delivery Note"),
            "fieldtype": "Link",
            "options": "Delivery Note"
        }
    ],
    onload: function(report) {
        $(document).ready(function() {
            var reportTitle = $(".page-title");
            var requiredFilters = ["serial_no", "delivery_note", "sales_order", "order_id"];
            var hasFilter = requiredFilters.some(filter => report.get_filter(filter).get_value());
            
            if (!hasFilter) {
                var additionalContent = $("<p style='color:#975a16;'><br>At least one of the following filters must be provided: Serial No, Delivery Note, Sales Order, Order ID</p>");
                reportTitle.after(additionalContent);
            }
        });
    }
};
