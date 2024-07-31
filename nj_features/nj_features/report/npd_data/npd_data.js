// Copyright (c) 2024, NewJaisa - IT Team and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["NPD Data"] = {
	"filters": [
		{
			"fieldname":"sheet_no",
			"label": __("Sheet No."),
			"fieldtype": "Select",
			"options": "\n1\n2\n3\n4\n5",
			"reqd": 1
		}
	],
	onload: function(report) {
        const messageHtml = `
            <div style="border-bottom: 1px solid var(--border-color); padding: 20px;">
                <strong>Information:</strong><br>
                Sheet No. '<b>1</b>' -- Brand, Model, Item Group not filled in variant</span><br>
                Sheet No. '<b>2</b>' -- Item Group present in Item Wizard, but not available in main Item Group like 'Laptops'</span><br>
                Sheet No. '<b>3</b>' -- Model is not matching with item template and selected model in item wizard</span><br>
                Sheet No. '<b>4</b>' -- Attribute and attribute value not matching need to add in 'Item Attribute Value'</span><br>
                Sheet No. '<b>5</b>' -- Serial No that doesn't have Item Wizard</span>
            </div>
        `;

        $(report.page.wrapper).find('.frappe-card').prepend(messageHtml);
    }
};